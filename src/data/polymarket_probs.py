"""Central-bank decision probabilities from Polymarket's public Gamma API (input for Lapisan B)."""
import json
import urllib.request

GAMMA = "https://gamma-api.polymarket.com"


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "forex-trend-bot"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def fed_decision_probs(event_slug: str, get=_get_json) -> dict[str, float]:
    """{outcome title: P(Yes)} for a multi-outcome event such as 'fed-decision-in-december'. Raises on bad data."""
    events = get(f"{GAMMA}/events?slug={event_slug}")
    if not events or not events[0].get("markets"):
        raise ValueError(f"polymarket event {event_slug!r} not found")
    out = {}
    for m in events[0]["markets"]:
        outcomes, prices = json.loads(m["outcomes"]), [float(p) for p in json.loads(m["outcomePrices"])]
        p = prices[outcomes.index("Yes")]
        if not 0 <= p <= 1:
            raise ValueError(f"probability out of range: {p}")
        out[m.get("groupItemTitle") or m.get("question", "?")] = p
    return out
