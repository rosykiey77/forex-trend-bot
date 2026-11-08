import io
import json
import urllib.error
from datetime import datetime, timezone

import pytest

from src.models import Position, Trade
from src.notify import telegram
from src.notify.telegram import TelegramNotifier

T = datetime(2025, 1, 6, tzinfo=timezone.utc)
POS = Position("1", "EURUSD", "BUY", 0.02, 1.1001, 1.0950, 1.1100, T, 10.2, "EMA20>EMA50 cross")


@pytest.fixture
def sent(monkeypatch):
    calls = []

    class Resp:
        def close(self):
            pass

    def fake_urlopen(req, timeout):
        calls.append((req.full_url, json.loads(req.data), timeout))
        return Resp()

    monkeypatch.setattr(telegram.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_payload_and_url(sent):
    n = TelegramNotifier("TOKEN123", "42")
    assert n.entry(POS) is True
    [(url, payload, timeout)] = sent
    assert url == "https://api.telegram.org/botTOKEN123/sendMessage"
    assert payload["chat_id"] == "42" and payload["parse_mode"] == "Markdown"
    assert "*BUY EURUSD*" in payload["text"] and "1.095" in payload["text"] and "1.11" in payload["text"]
    assert timeout == 5.0


@pytest.mark.parametrize("call", [
    lambda n: n.startup("paper", 1000.0, 0),
    lambda n: n.exit(Trade(POS, 1.1100, T, "TP", 19.8, 18.4, 1.8)),
    lambda n: n.daily_lock(969.0, 1000.0),
    lambda n: n.kill("stop_file"),
    lambda n: n.error("boom"),
])
def test_every_alert_kind_sends(sent, call):
    assert call(TelegramNotifier("t", "c")) is True and len(sent) == 1


def test_exit_message_has_reason_pnl_r(sent):
    TelegramNotifier("t", "c").exit(Trade(POS, 1.0950, T, "SL", -10.2, -11.6, -1.14))
    text = sent[0][1]["text"]
    assert "(SL)" in text and "-11.60" in text and "-1.14" in text


@pytest.mark.parametrize("token,chat", [("", "42"), ("t", ""), (None, None)])
def test_disabled_without_credentials(sent, token, chat):
    n = TelegramNotifier(token, chat)
    assert not n.enabled and n.error("x") is False and sent == []


def test_failure_never_raises_and_reports(monkeypatch):
    def boom(req, timeout):
        raise urllib.error.URLError("network down")
    monkeypatch.setattr(telegram.urllib.request, "urlopen", boom)
    failures = []
    n = TelegramNotifier("SECRET", "42", on_fail=failures.append)
    assert n.error("x") is False
    assert len(failures) == 1 and "network down" in failures[0] and "SECRET" not in failures[0]


def test_markdown_rejected_resends_plain(monkeypatch):
    payloads = []

    def urlopen(req, timeout):
        payloads.append(json.loads(req.data))
        if len(payloads) == 1:
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO())
        return io.BytesIO()
    monkeypatch.setattr(telegram.urllib.request, "urlopen", urlopen)
    assert TelegramNotifier("t", "c").error("bad_name_with_underscores") is True
    assert "parse_mode" in payloads[0] and "parse_mode" not in payloads[1]


def test_from_env_reads_dotenv_env_wins(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("# comment\nTELEGRAM_BOT_TOKEN='abc'\nTELEGRAM_CHAT_ID=99\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "7")
    n = TelegramNotifier.from_env()
    assert (n.token, n.chat_id) == ("abc", "7")
