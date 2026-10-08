r"""Every line of a .env is read, whether or not the file starts with a BOM.

    .venv\Scripts\python.exe scripts\test_env_encoding.py

The VPS .env is saved "UTF-8 with BOM". Before engine/config.py read env files as
utf-8-sig, the BOM became part of the first variable's name, so the first line
was ignored without any error and its setting fell back to the default. The
first line there is TEST_MODE=true, equal to its default, so nothing showed.
In .env.live, whose job is TEST_MODE=false and the live account key, the same
quirk would quietly undo whichever setting came first.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings  # noqa: E402

BOM = b"\xef\xbb\xbf"
NAMES = ("TEST_MODE", "ACCOUNT_KEY", "AI_REVIEW_SAMPLE_PCT", "LIVE_TRADING_ENABLED")


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want}\n         actual  : {got}")
    return ok


def load(*files: bytes) -> Settings:
    """Settings from these file contents, layered in order like run_engine's
    --env-file chain, with nothing leaking in from the real environment."""
    for name in NAMES:
        os.environ.pop(name, None)
    folder = Path(tempfile.mkdtemp())
    paths = []
    for i, content in enumerate(files):
        path = folder / f"{i}.env"
        path.write_bytes(content)
        paths.append(str(path))
    return Settings(_env_file=tuple(paths))


def main() -> int:
    passed = []
    body = b"TEST_MODE=false\r\nAI_REVIEW_SAMPLE_PCT=100\r\n"

    print("a non-default value on the FIRST line is read")
    passed.append(check("plain UTF-8", load(body).test_mode, False))
    passed.append(check("UTF-8 with BOM", load(BOM + body).test_mode, False))
    passed.append(check("later lines unaffected by the BOM", load(BOM + body).ai_review_sample_pct, 100.0))

    print("\nlayered like the live engine: .env, then .env.live on top")
    base = BOM + b"TEST_MODE=true\r\nACCOUNT_KEY=icmarkets-demo\r\n"
    live = BOM + b"ACCOUNT_KEY=icmarkets-live\r\nTEST_MODE=false\r\nLIVE_TRADING_ENABLED=true\r\n"
    s = load(base, live)
    passed.append(check("the live file's first line wins (account key)", s.account_key, "icmarkets-live"))
    passed.append(check("TEST_MODE=false reaches the live engine", s.test_mode, False))
    passed.append(check("guard 1 read", s.live_trading_enabled, True))

    print("\nnothing else about reading changed")
    passed.append(check("no BOM, CRLF: values exact", (load(b"ACCOUNT_KEY=icmarkets-live\r\n").account_key), "icmarkets-live"))
    passed.append(check("no BOM, LF only", load(b"TEST_MODE=false\n").test_mode, False))

    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
