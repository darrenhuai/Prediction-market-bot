"""Tests for the live scanner: market normalization, signals, the service, and the web API."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from src.common.util import ev_yes, remove_vig
from src.scanner.alerts import Alerter
from src.scanner.demo import DemoSource
from src.scanner.markets import flatten_events, normalize_market, normalize_trade
from src.scanner.service import Scanner
from src.scanner.signals import evaluate_pick, find_arbitrage, find_pick_opportunities, flow_signal, taker_fee


def market(ticker="T", yes_bid=40, yes_ask=42, **extra):
    return normalize_market({"ticker": ticker, "status": "active", "yes_bid": yes_bid, "yes_ask": yes_ask, **extra})


class TestNormalizeMarket:
    def test_reads_dollar_string_fields(self):
        m = normalize_market({"ticker": "A", "status": "active", "yes_bid_dollars": "0.4100",
                              "yes_ask_dollars": "0.4300", "volume_fp": "1234.00"})
        assert (m["yes_bid"], m["yes_ask"], m["volume"]) == (41, 43, 1234)

    def test_derives_no_side_from_single_book(self):
        m = market(yes_bid=41, yes_ask=43)
        assert m["no_bid"] == 57 and m["no_ask"] == 59

    def test_active_status_counts_as_open(self):
        assert market()["status"] == "open"

    def test_chance_is_mid_price(self):
        assert market(yes_bid=40, yes_ask=44)["chance"] == 42

    def test_multi_outcome_title_includes_outcome(self):
        event = {"title": "Fed decision", "markets": [{}, {}]}
        m = normalize_market({"ticker": "F", "title": "x", "yes_sub_title": "Hold"}, event)
        assert m["title"] == "Fed decision: Hold"

    def test_trade_reads_fixed_point_count(self):
        t = normalize_trade({"ticker": "A", "count_fp": "12.00", "taker_side": "YES"})
        assert t["count"] == 12 and t["taker_side"] == "yes"


class TestOldEvMathNeverFires:
    """The original bot compared a market's vig-free bids to its own asks, which can never be positive."""

    @pytest.mark.parametrize("yes_bid,no_bid", [(40, 40), (1, 98), (49, 50), (90, 5)])
    def test_self_referential_ev_is_never_positive(self, yes_bid, no_bid):
        fair_yes, _ = remove_vig(yes_bid, no_bid)
        assert ev_yes(fair_yes, 100 - no_bid) <= 1e-12


class TestSignals:
    def test_fee_peaks_at_fifty_cents(self):
        assert taker_fee(50) == pytest.approx(1.75)
        assert taker_fee(10) < taker_fee(50)

    def test_pick_ev_includes_fee(self):
        r = evaluate_pick(0.75, market(yes_bid=56, yes_ask=57))
        assert r["best_side"] == "YES"
        assert r["best"]["ev_cents"] == pytest.approx(75 - 57 - taker_fee(57), abs=0.01)

    def test_pick_prefers_no_when_you_think_yes_is_overpriced(self):
        assert evaluate_pick(0.2, market(yes_bid=50, yes_ask=52))["best_side"] == "NO"

    def test_pick_opportunities_respect_min_edge_and_stake(self):
        m = market("A", 56, 57)
        opps = find_pick_opportunities({"A": m}, {"A": 0.75}, min_edge_cents=2, bankroll=1000)
        assert len(opps) == 1 and opps[0]["suggested_stake"] > 0
        assert find_pick_opportunities({"A": m}, {"A": 0.58}, min_edge_cents=2) == []

    def _event(self, prices, exclusive=True):
        raw = {"event_ticker": "E", "title": "E", "mutually_exclusive": exclusive,
               "markets": [{"ticker": f"E{i}", "status": "active", "yes_bid": b, "yes_ask": a}
                           for i, (b, a) in enumerate(prices)]}
        events, markets = flatten_events([raw])
        return events, {m["ticker"]: m for m in markets}

    def test_arbitrage_when_yes_bids_overlap(self):
        # YES bids sum to 116: NO on every bracket costs 384 + fees, but pays 400.
        events, by_ticker = self._event([(15, 17), (30, 32), (35, 37), (22, 24), (14, 16)])
        opps = find_arbitrage(events, by_ticker)
        assert opps[0]["side"] == "NO" and opps[0]["guaranteed"]
        assert opps[0]["profit_cents"] == pytest.approx(400 - sum(n + taker_fee(n) for n in (85, 70, 65, 78, 86)), abs=0.01)

    def test_no_arbitrage_in_fairly_priced_event(self):
        events, by_ticker = self._event([(30, 32), (30, 32), (36, 38)])
        assert find_arbitrage(events, by_ticker) == []

    def test_no_arbitrage_when_outcomes_can_overlap(self):
        events, by_ticker = self._event([(15, 17), (30, 32), (35, 37), (22, 24), (14, 16)], exclusive=False)
        assert find_arbitrage(events, by_ticker) == []

    def test_flow_flags_one_sided_buying_and_large_trades(self):
        trades = [{"count": 5, "taker_side": "yes"}] * 12
        assert "YES" in flow_signal("A", trades)["reason"]
        mixed = [{"count": 5, "taker_side": s} for s in ["yes", "no"] * 6]
        assert flow_signal("A", mixed) is None
        assert "Large trade" in flow_signal("A", [*mixed, {"count": 500, "taker_side": "no"}])["reason"]


class TestScanner:
    @pytest.fixture
    def scanner(self, tmp_path):
        s = Scanner(DemoSource(), data_dir=tmp_path, mode="demo")
        assert s.refresh()
        return s

    def test_demo_refresh_finds_arbitrage_and_flow(self, scanner):
        opps = scanner.opportunities()
        assert scanner.snapshot["markets"]
        assert any(o["event_ticker"] == "DEMO-NYCTEMP" for o in opps["arbitrage"])
        assert opps["flow"]

    def test_estimates_persist_and_create_picks(self, scanner, tmp_path):
        scanner.set_estimate("DEMO-GDP-Q3-YES", 90)
        assert scanner.opportunities()["picks"][0]["ticker"] == "DEMO-GDP-Q3-YES"
        assert Scanner(DemoSource(), data_dir=tmp_path, mode="demo").estimates == {"DEMO-GDP-Q3-YES": 0.9}
        scanner.set_estimate("DEMO-GDP-Q3-YES", None)
        assert scanner.estimates == {}

    def test_rejects_bad_input(self, scanner):
        with pytest.raises(ValueError):
            scanner.set_estimate("X", 100)
        with pytest.raises(ValueError):
            scanner.update_settings({"nope": 1})

    def test_failed_refresh_keeps_last_data(self, scanner):
        before = len(scanner.snapshot["markets"])

        class Broken:
            def get_all_events(self, **_):
                raise RuntimeError("403 Forbidden")

        scanner.source = Broken()
        scanner.refresh()
        assert "403" in scanner.snapshot["error"]
        assert len(scanner.snapshot["markets"]) == before

    def test_watch_series_filters_markets(self, scanner):
        scanner.update_settings({"watch_series": "DEMO-FED"})
        scanner.refresh()
        assert {m["event_ticker"] for m in scanner.snapshot["markets"]} == {"DEMO-FED-DEC"}


class TestAlerter:
    def test_does_not_repeat_until_edge_improves(self, tmp_path):
        a = Alerter(tmp_path / "alerts.json")
        opp = {"key": "k", "kind": "pick", "ev_cents": 3.0}
        assert a.new_alerts([opp]) == [opp]
        assert a.new_alerts([opp]) == []
        better = {**opp, "ev_cents": 4.5}
        assert a.new_alerts([better]) == [better]


class TestWebApi:
    @pytest.fixture
    def base_url(self, tmp_path):
        from app import make_handler

        scanner = Scanner(DemoSource(), data_dir=tmp_path, mode="demo")
        scanner.refresh()
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(scanner))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        yield f"http://127.0.0.1:{server.server_address[1]}"
        server.shutdown()

    def _post(self, url, body):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
        return json.load(urllib.request.urlopen(req))

    def test_serves_page_and_state(self, base_url):
        assert b"Prediction Market Bot" in urllib.request.urlopen(base_url + "/").read()
        state = json.load(urllib.request.urlopen(base_url + "/api/state"))
        assert state["mode"] == "demo" and state["markets"]

    def test_saving_an_estimate_shows_up_in_state(self, base_url):
        assert self._post(base_url + "/api/estimate", {"ticker": "DEMO-GDP-Q3-YES", "chance": 90})["ok"]
        state = json.load(urllib.request.urlopen(base_url + "/api/state"))
        assert state["estimates"] == {"DEMO-GDP-Q3-YES": 90.0}
        assert state["opportunities"]["picks"]

    def test_bad_input_returns_400(self, base_url):
        with pytest.raises(urllib.error.HTTPError) as e:
            self._post(base_url + "/api/estimate", {"ticker": "X", "chance": 150})
        assert e.value.code == 400

    def test_does_not_serve_files_outside_web_dir(self, base_url):
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base_url + "/%2e%2e/pyproject.toml")
        assert e.value.code == 404
