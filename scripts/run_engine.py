"""The engine's entrypoint - full pipeline (data feed, strategy, risk,
execution, AI review, command handling).

    python scripts/run_engine.py                        # the demo lab, from .env
    python scripts/run_engine.py --env-file .env.live   # the live engine

Runs standalone during local development (Ctrl+C to stop) and, on the VPS,
via a Task Scheduler "at logon" trigger (see infra/setup-scheduled-tasks.ps1)
rather than a Windows service - MT5's Python bridge needs an interactive
desktop session, which a Session-0 service doesn't have.

WHY --env-file EXISTS. One repo runs two engines against two accounts, and the
second one needs different settings. That used to be done by a PowerShell
wrapper (infra/run-live-engine.ps1) that exported the values and then launched
python - which meant Task Scheduler owned the WRAPPER, not the engine. Stopping
the task killed the wrapper and left the engine running, reparented, still
holding its MT5 connection; starting the task again produced two live engines on
one account. Loading the file here instead lets the task execute python
directly, exactly as the demo task does, so Stop-ScheduledTask stops the actual
engine and a restart is one command for both.
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


def _require_pinned(settings: Settings) -> None:
    """A non-default engine must be pinned to its own terminal and account.

    mt5.initialize() attaches to whatever terminal it is pointed at, and logs in
    only if credentials are supplied. An unpinned second engine therefore trades
    whatever account its terminal happens to be showing, labels everything with
    its own ACCOUNT_KEY regardless, and cannot log back in when the terminal is
    switched. The live engine writing demo trades tagged 'icmarkets-live' is the
    specific disaster this prevents.

    infra/run-live-engine.ps1 used to enforce this before launching python. That
    check has to live here now that Task Scheduler starts python directly - a
    guard that only exists in a launcher you have stopped using is not a guard.

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

    Restarting the live engine used to mean identifying it by walking the
    Windows process tree over WMI - the only way to tell it from the demo lab,
    which runs the identical command line. That worked, but `Win32_Process` can
    hang for minutes on a loaded box, and a restart script that hangs before it
    stops anything is a restart script that does not restart anything. It
    happened twice on 2026-09-05.

    A process that knows its own PID has no reason to make anything guess. The
    file also gives the restart script a clean success signal: it deletes this
    file, starts the task, and waits for a NEW pid to appear. That is proof the
    engine came back, not an inference from a log line that may predate it.

    The timestamp is there to survive PID recycling - Windows reuses PIDs, and a
    stale file must never point the killer at an unrelated process. A reader
    checks that the PID is alive, is a python, and started around this time.

    Best-effort by design: a failure to write it must never stop the engine, and
    a hard kill leaves the file stale, which readers already have to handle.
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
        settings = Settings(_env_file=str(env_path))
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
    _require_pinned(settings)
    _publish_pid(log_dir, settings.account_key)

    engine = build_engine(settings=settings)
    supabase = SupabaseClient(settings)

    if engine.broker is None or engine.market_data is None:
        raise SystemExit("broker and market_data must both be configured in config/plugins.yaml")

    EngineLoop(engine, supabase, settings).run_forever()


if __name__ == "__main__":
    main()
