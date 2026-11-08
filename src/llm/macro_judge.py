"""Lapisan B: daily macro bias from an LLM (analyst -> bull -> bear -> judge, 4 calls), merged with Lapisan A.

The LLM is any callable prompt -> text, so the provider stays out of this module. Off by default
(strategy param llm_bias_enabled: false). Never backtest this layer: the model already knows the past."""
import json
import logging
from datetime import date
from typing import Callable

from src.strategy.daily_bias import RATINGS, direction

log = logging.getLogger(__name__)
HOLD = {"rating": "Hold", "alasan": "", "risiko_utama": ""}


def combine(tech: str, llm: str) -> str:
    """Same direction -> stronger rating; one Hold -> other one step weaker; opposite -> Hold."""
    t, m = RATINGS.index(tech) - 2, RATINGS.index(llm) - 2  # -2..+2, ValueError if unknown
    dt, dm = direction(tech), direction(llm)
    if dt == dm:
        return RATINGS[2 + (t if abs(t) >= abs(m) else m)]
    if dt == 0 or dm == 0:
        x = t or m
        return RATINGS[2 + x - (1 if x > 0 else -1)]
    return "Hold"


def parse_verdict(raw: str) -> dict:
    """Validate the judge's JSON {"rating", "alasan", "risiko_utama"}; raises ValueError on anything else."""
    text = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        v = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"judge output is not JSON: {e}") from None
    if not isinstance(v, dict) or v.get("rating") not in RATINGS:
        raise ValueError(f"invalid rating in {text[:100]!r}")
    if not all(isinstance(v.get(k), str) for k in ("alasan", "risiko_utama")):
        raise ValueError("alasan / risiko_utama must be strings")
    return {k: v[k] for k in ("rating", "alasan", "risiko_utama")}


class MacroJudge:
    def __init__(self, llm: Callable[[str], str], news: Callable[[str, date], str] | None = None,
                 probs: Callable[[], dict] | None = None, lessons: Callable[[str], list[str]] | None = None):
        self.llm, self.news, self.probs, self.lessons = llm, news, probs, lessons

    def rate(self, symbol: str, day: date) -> dict:
        """Never raises: a failed source or bad LLM output yields Hold (logged), as the strategy doc requires."""
        try:
            news = self.news(symbol, day) if self.news else "(no news source)"
            probs = self.probs() if self.probs else {}
            lessons = self.lessons(symbol)[:5] if self.lessons else []
        except Exception as e:  # noqa: BLE001 - any source failure -> Hold, don't guess
            log.warning("macro inputs failed for %s: %s", symbol, e)
            return {**HOLD, "alasan": f"input gagal: {e}"}
        ctx = f"Pair {symbol}, tanggal {day}.\nBerita & kalender:\n{news}\nProbabilitas Polymarket bank sentral: {probs}"
        try:
            analysis = self.llm(f"Kamu analis makro forex. Ringkas faktor yang menggerakkan {symbol}.\n{ctx}")
            bull = self.llm(f"Beri satu argumen singkat BULLISH untuk {symbol}.\n{analysis}")
            bear = self.llm(f"Beri satu argumen singkat BEARISH untuk {symbol}.\n{analysis}")
            verdict = self.llm(
                "Kamu hakim. Konflik pendapat bukan alasan untuk Hold; Hold hanya jika bukti seimbang atau terlalu tipis.\n"
                f"Analisis: {analysis}\nBull: {bull}\nBear: {bear}\nPelajaran terbaru: {lessons}\n"
                'Jawab HANYA JSON: {"rating": "Buy|Overweight|Hold|Underweight|Sell", "alasan": "...", "risiko_utama": "..."}')
            return parse_verdict(verdict)
        except Exception as e:  # noqa: BLE001
            log.warning("macro judge failed for %s: %s", symbol, e)
            return {**HOLD, "alasan": f"llm gagal: {e}"}
