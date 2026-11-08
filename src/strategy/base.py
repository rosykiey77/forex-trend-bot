from abc import ABC, abstractmethod

from src.models import Bar, Position, Signal


class Strategy(ABC):
    """Mode-agnostic: sees only closed bars, never calls the broker. Must be deterministic."""
    name: str
    warmup_bars: int = 0

    def __init__(self, params: dict):
        self.params = params

    @abstractmethod
    def on_bar(self, symbol: str, bars: list[Bar], position: Position | None) -> Signal | None:
        """Called once per closed bar, in time order; bars[-1] is the bar that just closed."""
