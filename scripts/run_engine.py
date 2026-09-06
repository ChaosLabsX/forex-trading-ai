"""The engine's entrypoint - full pipeline (data feed, strategy, risk,
execution, AI review, command handling).

    python scripts/run_engine.py                        # the demo lab, from .env
    python scripts/run_engine.py --env-file .env.live   # the live engine

Runs standalone during local development (Ctrl+C to stop) and, on the VPS,
via a Task Scheduler "at logon" trigger (see infra/setup-scheduled-tasks.ps1)
rather than a Windows service - MT5's Python bridge needs an interactive
desktop session, which a Session-0 service doesn't have.

--env-file lets one repo run two engines against two accounts. It layers over
.env rather than replacing it, so .env.live holds only what differs (account,
terminal, credentials, sizing) while Supabase/Telegram/Anthropic keep coming
from .env. Both scheduled tasks therefore execute python directly, which is why
Stop-ScheduledTask stops the real engine and restarting either is one command.
"""

from __future__ import annotations

import argparse
import atexit
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings
from engine.loop import EngineLoop
from engine.registry import build_engine
from engine.supabase_client import SupabaseClient


def _set_console_title(settings: Settings) -> None:
    r"""Name this engine's console window after the account it is trading.

    Both engines run the identical command line, and MainWindowTitle is empty
    under Windows Terminal's ConPTY, so without this there is no way to tell at
    a glance which window is about to trade real money. The live title is loud
    on purpose: closing a console kills the process attached to it.

    Best effort - failing to set a title must never stop an engine.
    """
    try:
        import ctypes

        if settings.account_key == Settings.model_fields["account_key"].default:
            title = f"ForexAI  -  DEMO LAB  ({settings.account_key})"
        elif settings.live_trading_enabled:
            title = f"*** ForexAI  -  LIVE / REAL MONEY ARMED  ({settings.account_key}) ***"
        else:
            title = f"ForexAI  -  LIVE account, trading OFF  ({settings.account_key})"
        ctypes.windll.kernel32.SetConsoleTitleW(title)
    except Exception:
        logging.getLogger("engine").debug("could not set console title", exc_info=True)


def _require_pinned(settings: Settings) -> None:
    """A non-default engine must be pinned to its own terminal and account.

    mt5.initialize() attaches to whatever terminal it is pointed at, and logs in
    only if credentials are supplied. An unpinned second engine therefore trades
    whatever account its terminal happens to be showing while labelling
    everything with its own ACCOUNT_KEY - the live engine writing demo trades
    tagged 'icmarkets-live' is the disaster this prevents.

    The demo lab is exempt on purpose: it attaches to whatever terminal is open
    and logged in, which is how local development works.
    """
    if settings.account_key == Settings.model_fields["account_key"].default:
        return

    missing = [
        name.upper()
        for name in ("mt5_terminal_path", "mt5_login", "mt5_password", "mt5_server")
        if not getattr(settings, name)
    ]
    if missing:
        raise SystemExit(
            f"Refusing to start: account_key is '{settings.account_key}' (not the default lab), "
            f"but {', '.join(missing)} {'is' if len(missing) == 1 else 'are'} empty. "
            "An engine with no account pinned trades whatever account its terminal happens "
            "to be on. Fill these in the env file this process was started with "
            "(see .env.live.example)."
        )

    terminal = Path(settings.mt5_terminal_path)
    # is_file(), not exists(): on Windows a truncated path like "C:" exists (it
    # resolves to the current directory of that drive), so exists() would wave
    # through a mangled MT5_TERMINAL_PATH and let the engine attach to whatever
    # terminal was already open. A terminal64.exe is a file or it is nothing.
    if not terminal.is_file():
        raise SystemExit(
            f"Refusing to start: MT5_TERMINAL_PATH '{terminal}' is not a file. "
            "The live engine needs its OWN MT5 installation - sharing the demo terminal "
            "would attach both engines to one account."
        )


def _publish_pid(log_dir: Path, account_key: str) -> None:
    """Write this process's PID next to its log, and remove it on a clean exit.

    The two engines share a command line, so this file is the only reliable way
    to tell them apart - see infra/restart-live-engine.ps1, which uses it both
    to find the right process and as proof that a restart really happened.

    The timestamp survives PID recycling: a reader checks that the pid is alive,
    is a python, and started around this time.

    Best effort - a hard kill leaves the file stale, which readers must handle
    anyway, and failing to write it must never stop the engine.
    """
    try:
        pid_file = log_dir / f"engine-{account_key}.pid"
        pid_file.write_text(
            f"{os.getpid()}\n{datetime.now(timezone.utc).isoformat()}\n",
            encoding="utf-8",
        )
        atexit.register(lambda: pid_file.unlink(missing_ok=True))
        logging.getLogger("engine").info("pid %s published to %s", os.getpid(), pid_file)
    except Exception:
        logging.getLogger("engine").warning("could not write pid file", exc_info=True)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument(
        "--env-file",
        default=None,
        help=(
            "Env file to load instead of .env. Use for a second engine on another "
            "account (e.g. --env-file .env.live). Real environment variables still "
            "win over the file, as pydantic-settings always has it."
        ),
    )
    return parser.parse_args(argv)


def main() -> None:
    # Verify TLS against the OS trust store, not OpenSSL's bundled CAs, and do
    # it before anything opens a connection. On the VPS, api.telegram.org's
    # certificate chain validates under Windows' own verifier (confirmed via
    # .NET SslStream: zero policy errors) but not under Python's OpenSSL
    # default context, which can't build the same path and reports
    # "self-signed certificate in certificate chain". truststore delegates
    # verification to Windows' verifier - the one that already trusts this
    # chain - so verification stays fully on, just sourced from the store that
    # works. No-op where OpenSSL already succeeds (e.g. Supabase, Anthropic).
    import truststore

    truststore.inject_into_ssl()

    # Make console logging tolerant of non-ASCII (emoji in trade alerts) so a
    # legacy code-page console can never turn a notification into an encoding
    # error. The rotating file handler is already UTF-8.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = _parse_args()
    # An explicit path is resolved against the repo root, not the working
    # directory: Task Scheduler's working directory is not guaranteed, and a
    # silently-missing env file would start the LIVE engine on the demo
    # account's defaults.
    if args.env_file:
        env_path = Path(args.env_file)
        if not env_path.is_absolute():
            env_path = Path(__file__).resolve().parent.parent / env_path
        if not env_path.exists():
            raise SystemExit(f"--env-file '{env_path}' does not exist")
        # BOTH files, override LAST - pydantic-settings gives later entries
        # priority, making this a DELTA over .env rather than a replacement.
        # The override alone would start the engine with no SUPABASE_URL, no
        # service-role key and no Telegram token: all of those live in .env and
        # none of them in .env.live.
        base_env = Path(__file__).resolve().parent.parent / ".env"
        chain = [str(base_env), str(env_path)] if base_env.exists() else [str(env_path)]
        settings = Settings(_env_file=tuple(chain))
        # You do not pass --env-file to run the default lab. If the file leaves
        # ACCOUNT_KEY out, account_key silently falls back to the demo default
        # and this process becomes a SECOND engine on the demo account - two
        # engines reconciling each other's trades, which is the data-destroying
        # failure migration 0013 had to repair by hand. Refuse instead.
        if settings.account_key == Settings.model_fields["account_key"].default:
            raise SystemExit(
                f"Refusing to start: --env-file '{env_path}' does not set ACCOUNT_KEY, "
                f"so this process would run as '{settings.account_key}' - a second engine "
                "on the demo account. Add ACCOUNT_KEY (see .env.live.example)."
            )
    else:
        settings = Settings()

    # File handler is what makes this work under Task Scheduler, which
    # doesn't capture stdout/stderr the way a manually-redirected console
    # process does - console handler stays too, for local interactive runs.
    #
    # One log file PER ACCOUNT: the demo and live engines are separate processes
    # on the same box, and RotatingFileHandler is not safe across processes -
    # sharing one file would interleave writes and corrupt on rotation.
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.handlers.RotatingFileHandler(
                log_dir / f"engine-{settings.account_key}.log",
                maxBytes=10_000_000,
                backupCount=5,
                encoding="utf-8",
            ),
            logging.StreamHandler(),
        ],
    )
    if args.env_file:
        logging.getLogger("engine").info("settings loaded from %s", args.env_file)
    _set_console_title(settings)
    _require_pinned(settings)
    _publish_pid(log_dir, settings.account_key)

    engine = build_engine(settings=settings)
    supabase = SupabaseClient(settings)

    if engine.broker is None or engine.market_data is None:
        raise SystemExit("broker and market_data must both be configured in config/plugins.yaml")

    EngineLoop(engine, supabase, settings).run_forever()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        # A deliberate refusal from one of the guards. It has already said why,
        # in its own words, and a traceback would only bury it.
        raise
    except BaseException:
        # Anything else has to reach the log file, because under Task Scheduler
        # there is no console and stderr goes nowhere. Without this the engine
        # dies leaving a log that simply stops mid-sentence and a task whose only
        # evidence is "Last run result: 1" - which is exactly how the missing
        # Supabase credentials above stayed invisible.
        logging.getLogger("engine").exception("engine exited on an unhandled exception")
        raise
