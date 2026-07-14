from __future__ import annotations

from abc import ABC, abstractmethod

from engine.core.interfaces.strategy import StrategyContext
from engine.core.models import AIVerdict, Signal


class AIProvider(ABC):
    """Optional pre-execution reviewer for a candidate signal (Phase 5, Claude first).

    Never required for the engine to run - a deployment with no AIProvider
    configured just skips this review step entirely.
    """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Identifier of the model behind the verdicts, so callers persist what
        actually ran instead of a second hardcoded copy that can drift."""
        ...

    @abstractmethod
    def review_signal(self, signal: Signal, context: StrategyContext) -> AIVerdict: ...
