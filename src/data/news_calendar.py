"""Economic calendar input: high-impact blackout filter for entries and a text summary for Lapisan B.
shortcut: reads a JSON file [{time, currency, impact, title}]; plug a live calendar feed in when going forward-test."""
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class CalendarEvent:
    time: datetime   # tz-aware UTC
    currency: str
    impact: str      # low | medium | high
    title: str


def load_calendar(path: str | Path) -> list[CalendarEvent]:
    return [CalendarEvent(datetime.fromisoformat(e["time"]), e["currency"], e["impact"], e["title"])
            for e in json.loads(Path(path).read_text())]


def currencies(symbol: str) -> tuple[str, str]:
    return symbol[:3], symbol[3:6]


def in_blackout(events: list[CalendarEvent], symbol: str, now: datetime, minutes: int = 30) -> bool:
    """True within +-minutes of a high-impact release for either currency of the pair."""
    w, ccys = timedelta(minutes=minutes), currencies(symbol)
    return any(e.impact == "high" and e.currency in ccys and abs(e.time - now) <= w for e in events)


def summarize(events: list[CalendarEvent], symbol: str, day: date) -> str:
    ccys = currencies(symbol)
    rows = [f"{e.time:%H:%M} {e.currency} [{e.impact}] {e.title}" for e in events
            if e.time.date() == day and e.currency in ccys]
    return "\n".join(rows) or "(tidak ada rilis terjadwal)"
