import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import settings  # noqa: E402


@pytest.fixture
def cfg():
    return settings.load(ROOT / "config" / "config.yaml")


@pytest.fixture
def eurusd(cfg):
    return cfg.symbols["EURUSD"]


@pytest.fixture
def xauusd(cfg):
    return cfg.symbols["XAUUSD"]
