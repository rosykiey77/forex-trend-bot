from datetime import timezone

from src.data.mt5_feed import Mt5Feed


def test_poll_returns_closed_bars_only(gw, eurusd):
    feed = Mt5Feed(gw.client, {"EURUSD": eurusd}, "M15", count=500)
    bars = feed.poll({})
    assert len(bars) == 99  # 100 bars on the server, the forming one excluded
    assert bars[0].time.tzinfo == timezone.utc and bars == sorted(bars, key=lambda b: b.time)
    assert bars[-1].time.timestamp() == gw.fake.rates["EURUSD"][-2]["time"]
    assert (bars[-1].spread_points, bars[-1].volume) == (10, 100)


def test_poll_after_only_new_bars(gw, eurusd):
    feed = Mt5Feed(gw.client, {"EURUSD": eurusd}, "M15", count=50)
    last = feed.poll({})[-1].time
    assert feed.poll({"EURUSD": last}) == []
    gw.fake.add_bar(1.1012)
    [new] = feed.poll({"EURUSD": last})
    assert (new.time - last).total_seconds() == 900


def test_specs_take_broker_contract_data(gw, eurusd):
    gw.fake.symbols["EURUSD"].trade_contract_size = 10000.0
    gw.fake.symbols["EURUSD"].volume_step = 0.1
    spec = Mt5Feed(gw.client, {"EURUSD": eurusd}, "M15").specs()["EURUSD"]
    assert (spec.contract_size, spec.volume_step) == (10000.0, 0.1)
    assert spec.pip_size == eurusd.pip_size and spec.max_spread_points == eurusd.max_spread_points  # config kept
