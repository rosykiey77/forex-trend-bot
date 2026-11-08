"""Telegram alerts. Never raises: a failed alert must not stop trading (FR-029).
Credentials come only from env / .env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID); empty token = disabled."""
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path

from src.models import Position, Trade

log = logging.getLogger("telegram")


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal KEY=VALUE loader; real env vars win."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


class TelegramNotifier:
    def __init__(self, token: str | None, chat_id: str | None, timeout: float = 5.0, on_fail=None):
        self.token, self.chat_id, self.timeout = token or "", chat_id or "", timeout
        self.on_fail = on_fail  # callback(str) e.g. storage event "notify_failed"

    @classmethod
    def from_env(cls, **kw) -> "TelegramNotifier":
        load_dotenv()
        return cls(os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID"), **kw)

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def _post(self, text: str, markdown: bool) -> None:
        payload = {"chat_id": self.chat_id, "text": text}
        if markdown:
            payload["parse_mode"] = "Markdown"
        req = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/sendMessage",
                                     data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=self.timeout).close()

    def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        try:
            try:
                self._post(text, markdown=True)
            except urllib.error.HTTPError as e:
                if e.code != 400:  # 400 = Markdown parse error (e.g. stray "_" in an error text): resend as plain
                    raise
                self._post(text, markdown=False)
            return True
        except Exception as e:  # network, timeout, HTTP: log and carry on
            msg = f"telegram send failed: {type(e).__name__}: {e}".replace(self.token, "***")
            log.warning(msg)
            if self.on_fail:
                try:
                    self.on_fail(msg)
                except Exception:
                    pass
            return False

    # --- formatters ---------------------------------------------------------------
    def startup(self, mode: str, balance: float, positions: int) -> bool:
        return self.send(f"🟢 *Bot started* ({mode})\nBalance: `{balance:.2f}`\nOpen positions: `{positions}`")

    def entry(self, p: Position) -> bool:
        icon = "📈" if p.side == "BUY" else "📉"
        return self.send(f"{icon} *{p.side} {p.symbol}* `{p.lots}` lots @ `{p.entry_price}`\n"
                         f"SL: `{p.sl}`  TP: `{p.tp}`\nReason: {p.entry_reason}")

    def exit(self, t: Trade) -> bool:
        p, icon = t.position, "✅" if t.net_pnl >= 0 else "❌"
        return self.send(f"{icon} *Exit {p.symbol} {p.side}* ({t.exit_reason}) @ `{t.exit_price}`\n"
                         f"Net PnL: `{t.net_pnl:.2f}`  R: `{t.r_multiple:.2f}`")

    def daily_lock(self, equity: float, day_start_equity: float) -> bool:
        return self.send(f"⛔ *Daily loss limit reached*\nEquity `{equity:.2f}` (day start `{day_start_equity:.2f}`)"
                         "\nNo new positions until next trading day.")

    def kill(self, reason: str) -> bool:
        return self.send(f"🛑 *KILL SWITCH* ({reason})\nAll positions closed, bot stopped.")

    def error(self, msg: str) -> bool:
        return self.send(f"⚠️ *Error*\n{msg}")

    def stopped(self, reason: str) -> bool:
        return self.send(f"⚪ *Bot stopped* ({reason})")
