"""Which strategies may trade on THIS account, right now.

The engine never decides this from code or config alone - it reads the
registries in Supabase (accounts / strategies / strategy_accounts) so the
dashboard's toggles and the evaluator's verdicts take effect on a running
engine without a redeploy.

Safety model, in order of authority:
  1. an account-wide block beats everything (see LIVE_SIZING_IMPLEMENTED);
  2. a live account additionally requires readiness == 'ready', unless you have
     deliberately set live_override on that strategy/account pair;
  3. only then does the manual `enabled` toggle let it through.
There is deliberately no fallback path: if nothing is eligible, nothing trades.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from engine.config import Settings
from engine.supabase_client import SupabaseClient

logger = logging.getLogger("engine.gating")

CACHE_TTL_SECONDS = 30  # dashboard toggles land within this; not per-2s-tick load

# Real-money position sizing does not exist yet: DefaultRiskEngine implements
# only the TEST_MODE fixed micro-lot and refuses everything else. A micro-lot
# that "works on demo" must never be pointed at a real account by accident, so
# live execution is blocked at the source until sizing is built and tested.
# Flipping this to True without implementing sizing is a live-money incident.
LIVE_SIZING_IMPLEMENTED = False


@dataclass(frozen=True)
class AccountInfo:
    key: str
    label: str
    account_type: str  # 'demo' | 'live'
    enabled: bool

    @property
    def is_live(self) -> bool:
        return self.account_type == "live"


@dataclass(frozen=True)
class Gate:
    eligible: frozenset[str]
    blocked: dict[str, str]  # strategy name -> plain-English reason
    account_block: str | None  # non-None means nothing trades on this account


class StrategyGate:
    def __init__(self, supabase: SupabaseClient, settings: Settings) -> None:
        self._supabase = supabase
        self._settings = settings
        self._account_key = settings.account_key
        self._account: AccountInfo | None = None
        self._cache: Gate | None = None
        self._fetched_at = 0.0

    # ---------------------------------------------------------------- account

    def account(self) -> AccountInfo | None:
        """This engine's account row. Cached for the process lifetime - an
        account's identity/type doesn't change under a running engine."""
        if self._account is None:
            try:
                rows = self._supabase.select("accounts", {"key": f"eq.{self._account_key}"})
            except Exception:
                logger.exception("failed to read account %s", self._account_key)
                return None
            if rows:
                row = rows[0]
                self._account = AccountInfo(
                    key=row["key"],
                    label=row["label"],
                    account_type=row["account_type"],
                    enabled=row["enabled"],
                )
        return self._account

    # ----------------------------------------------------------- registration

    def sync_strategies(self, known: list[str]) -> None:
        """Make every strategy this process can run appear in the registries.

        Insert-missing-only (never upsert): a blind upsert would clobber the
        evaluator's readiness verdict and your manual toggles on every restart.
        This is what makes a new strategy show up on the dashboard by itself -
        drop in the plugin, name it in plugins.yaml, done."""
        account = self.account()
        if account is None:
            return
        try:
            existing = {r["name"] for r in self._supabase.select("strategies", {})}
            for name in known:
                if name not in existing:
                    self._supabase.insert(
                        "strategies", [{"name": name, "display_name": name}]
                    )
                    logger.info("registered new strategy: %s", name)

            pairs = self._supabase.select(
                "strategy_accounts", {"account_key": f"eq.{self._account_key}"}
            )
            have = {r["strategy_name"] for r in pairs}
            for name in known:
                if name not in have:
                    # The lab tests everything by default; live starts off.
                    self._supabase.insert(
                        "strategy_accounts",
                        [
                            {
                                "strategy_name": name,
                                "account_key": self._account_key,
                                "enabled": not account.is_live,
                            }
                        ],
                    )
                    logger.info(
                        "linked strategy %s to account %s (enabled=%s)",
                        name, self._account_key, not account.is_live,
                    )
        except Exception:
            logger.exception("failed to sync strategy registries")

    # ------------------------------------------------------------------ gate

    def gate(self, known: list[str], force: bool = False) -> Gate:
        if not force and self._cache is not None and (time.monotonic() - self._fetched_at) < CACHE_TTL_SECONDS:
            return self._cache
        gate = self._compute(known)
        self._cache = gate
        self._fetched_at = time.monotonic()
        return gate

    def _compute(self, known: list[str]) -> Gate:
        account = self.account()
        if account is None:
            return self._all_blocked(
                known, f"account '{self._account_key}' is not registered in the accounts table"
            )
        if not account.enabled:
            return self._all_blocked(known, f"account '{account.key}' is disabled")
        if account.is_live and not LIVE_SIZING_IMPLEMENTED:
            return self._all_blocked(
                known,
                "live trading is blocked: risk-based position sizing is not implemented yet",
            )

        try:
            strategies = {r["name"]: r for r in self._supabase.select("strategies", {})}
            pairs = {
                r["strategy_name"]: r
                for r in self._supabase.select(
                    "strategy_accounts", {"account_key": f"eq.{self._account_key}"}
                )
            }
        except Exception:
            logger.exception("failed to read strategy registries - blocking to stay safe")
            return self._all_blocked(known, "strategy registry unreadable - refusing to trade blind")

        eligible: set[str] = set()
        blocked: dict[str, str] = {}
        for name in known:
            strategy = strategies.get(name)
            pair = pairs.get(name)
            if strategy is None:
                blocked[name] = "not registered in the strategies table"
            elif strategy.get("retired"):
                blocked[name] = "retired"
            elif pair is None:
                blocked[name] = f"not linked to account {self._account_key}"
            elif not pair.get("enabled"):
                blocked[name] = "disabled (manual toggle off)"
            elif account.is_live and strategy.get("readiness") != "ready" and not pair.get("live_override"):
                blocked[name] = (
                    f"readiness is '{strategy.get('readiness')}' - live requires 'ready' "
                    f"(or an explicit live_override)"
                )
            else:
                eligible.add(name)
        return Gate(frozenset(eligible), blocked, None)

    @staticmethod
    def _all_blocked(known: list[str], reason: str) -> Gate:
        return Gate(frozenset(), {name: reason for name in known}, reason)
