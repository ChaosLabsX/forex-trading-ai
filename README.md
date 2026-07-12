# MT5 + IC Markets Automated Trading

A strategy-agnostic automated trading engine for MetaTrader 5 / IC Markets, plus a
browser dashboard for monitoring and control. Personal use, self-hosted on a
Windows VPS. Independent of, and unrelated to, any other trading project.

- [`APP-CREATION-PLANNING.md`](APP-CREATION-PLANNING.md) - phased build plan and
  the reasoning behind every major architecture decision. Start here.
- [`docs/architecture.md`](docs/architecture.md) - current-state architecture map.
- [`docs/plugin-system.md`](docs/plugin-system.md) - how the plugin/interface
  system works and how to add a new broker/strategy/provider.
- [`infra/vps-setup.md`](infra/vps-setup.md) - VPS and demo account setup guidance.

## Status

Phase 0 (Foundations) in progress. See `APP-CREATION-PLANNING.md` for what's
built vs. pending.

## Local setup

```
python -m venv .venv
.venv/Scripts/activate     # Windows
pip install -e .
cp .env.example .env       # fill in values as they become available
python scripts/smoke_test_registry.py
```
