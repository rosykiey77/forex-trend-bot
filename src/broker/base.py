from abc import ABC, abstractmethod

from src.models import AccountInfo, Bar, Order, Position, Trade


class OrderRejected(Exception):
    pass


class Broker(ABC):
    @abstractmethod
    def account(self) -> AccountInfo: ...

    @abstractmethod
    def positions(self) -> list[Position]: ...

    @abstractmethod
    def open(self, order: Order) -> Position:
        """Raise OrderRejected if the order cannot be filled."""

    @abstractmethod
    def close(self, position_id: str, reason: str) -> Trade: ...

    @abstractmethod
    def modify(self, position_id: str, sl: float | None, tp: float | None) -> None: ...

    @abstractmethod
    def on_price(self, bar: Bar) -> list[Trade]:
        """Paper: SL/TP/gap check and mark-to-market. Live: sync with server."""
