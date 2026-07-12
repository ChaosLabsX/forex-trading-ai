# MT5 + IC Markets Automated Trading

A strategy-agnostic automated trading engine for MetaTrader 5 / IC Markets, plus
a browser dashboard for monitoring and control. Personal use, self-hosted (a
local Windows machine today; a VPS eventually). Independent of, and unrelated
to, any other trading project.

**Start here:** [`CLAUDE.md`](CLAUDE.md) - orientation for both AI assistants
and humans: what's built, how it fits together, conventions, how to run it.

## Docs

- [`APP-CREATION-PLANNING.md`](APP-CREATION-PLANNING.md) - phased build plan,
  current status, and the reasoning behind every major decision
- [`docs/architecture.md`](docs/architecture.md) - system layout, data flow,
  security model
- [`docs/plugin-system.md`](docs/plugin-system.md) - the interface/plugin
  pattern, how to add a new broker/strategy/provider
- [`docs/engine.md`](docs/engine.md) - the Python engine in depth
- [`docs/dashboard.md`](docs/dashboard.md) - the React dashboard in depth
- [`docs/safety-rails.md`](docs/safety-rails.md) - `TEST_MODE`, circuit
  breakers, RLS security model
- [`infra/vps-setup.md`](infra/vps-setup.md) - VPS setup guidance (Phase 6,
  not started yet)

## Status

Phases 0-5 built and running; see the status line at the bottom of
`APP-CREATION-PLANNING.md` for exact current state. Phase 6 (VPS deployment)
is intentionally not started.

## Local setup

```
python -m venv .venv
.venv/Scripts/activate     # Windows
pip install -e .
cp .env.example .env       # fill in values - see docs/safety-rails.md
python scripts/smoke_test_registry.py
```

Dashboard: see [`dashboard/README.md`](dashboard/README.md).
