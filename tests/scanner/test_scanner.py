"""Tests for the live scanner: market normalization, signals, the service, and the web API."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import httpx
import pytest

from src.common.util import ev_yes, remove_vig
from src.scanner.alerts import Alerter
from src.scanner.demo import DemoSource
from src.scanner.markets import flatten_events, normalize_market, normalize_trade
from src.scanner.service import Scanner
from src.scanner.signals import (
    evaluate_pick,
    find_arbitrage,
    find_pick_opportunities,
    flow_signal,
    single_contract_fee,
    taker_fee,
)


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
        question = normalize_market({"ticker": "W", "yes_sub_title": "Bills"}, {**event, "title": "Who wins?"})
        assert question["title"] == "Who wins? — Bills"

    def test_trade_reads_fixed_point_count(self):
        t = normalize_trade({"ticker": "A", "count_fp": "12.00", "taker_side": "YES"})
        assert t["count"] == 12 and t["taker_side"] == "yes"

    def test_trade_side_from_current_fields(self):
        assert normalize_trade({"taker_outcome_side": "no"})["taker_side"] == "no"
        assert normalize_trade({"taker_book_side": "bid"})["taker_side"] == "yes"
        assert normalize_trade({"taker_book_side": "ask"})["taker_side"] == "no"

    def test_null_series_ticker_does_not_crash(self):
        events, markets = flatten_events([{"event_ticker": "E", "series_ticker": None,
                                           "markets": [{"ticker": "M", "status": "active"}]}])
        assert events[0]["series_ticker"] == "" and markets[0]["series_ticker"] == ""


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

    def test_single_contract_fee_rounds_up_to_whole_cent(self):
        assert single_contract_fee(85) == 1  # 0.89c -> 1c
        assert single_contract_fee(50) == 2  # 1.75c -> 2c
        assert single_contract_fee(99) == 1

    def test_arbitrage_when_yes_bids_overlap(self):
        # YES bids sum to 116: NO on every bracket costs 384 + 8c of fees, but pays 400.
        events, by_ticker = self._event([(15, 17), (30, 32), (35, 37), (22, 24), (14, 16)])
        opps = find_arbitrage(events, by_ticker)
        assert opps[0]["side"] == "NO" and opps[0]["guaranteed"]
        assert opps[0]["profit_cents"] == pytest.approx(400 - 384 - 8)

    def test_fee_rounding_rules_out_sub_cent_arbitrage(self):
        # Unrounded fees would show +0.7c, but one-contract orders pay 2c each: a real loss.
        events, by_ticker = self._event([(35, 36), (35, 36), (35.5, 36.5)])
        assert find_arbitrage(events, by_ticker) == []

    def test_yes_bundle_is_never_guaranteed(self):
        # Asks sum to 93c: cheap, but an unlisted outcome could still win.
        events, by_ticker = self._event([(30, 31), (30, 31), (30, 31)])
        opps = find_arbitrage(events, by_ticker)
        assert [o["side"] for o in opps] == ["YES"] and not opps[0]["guaranteed"]

    def test_no_arbitrage_in_fairly_priced_event(self):
        events, by_ticker = self._event([(30, 32), (30, 32), (36, 38)])
        assert find_arbitrage(events, by_ticker) == []

    def test_no_arbitrage_when_outcomes_can_overlap(self):
        events, by_ticker = self._event([(15, 17), (30, 32), (35, 37), (22, 24), (14, 16)], exclusive=False)
        assert find_arbitrage(events, by_ticker) == []

    def test_flow_flags_one_sided_buying_and_large_trades(self):
        trades = [{"count": 5, "taker_side": "yes"}] * 12
        assert "YES" in flow_signal("A", trades)["reason"]
        mixed = [{"count": 10, "taker_side": s} for s in ["yes", "no"] * 20]
        assert flow_signal("A", mixed) is None
        assert "Large trade" in flow_signal("A", [*mixed, {"count": 300, "taker_side": "yes"}])["reason"]

    def test_routine_size_trades_are_not_large(self):
        # In a busy market where 60-lots are normal, a 100-lot is not news.
        busy = [{"count": 60, "taker_side": s} for s in ["yes", "no"] * 20]
        assert flow_signal("A", [*busy, {"count": 100, "taker_side": "yes"}]) is None

    def test_one_sided_flow_is_not_masked_by_a_modest_big_trade(self):
        trades = [{"count": 10, "taker_side": "yes"}] * 19 + [{"count": 50, "taker_side": "yes"}]
        assert flow_signal("A", trades)["key"] == "flow:A:yes"


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
            scanner.set_estimate("NOT-A-MARKET", 50)
        for bad in ({"nope": 1}, {"bankroll": float("nan")}, {"refresh_minutes": 1e300},
                    {"flow_markets": -5}, {"max_event_pages": 0}, {"fee_rate": 7}, {"large_trade": 0}):
            with pytest.raises(ValueError):
                scanner.update_settings(bad)
        assert scanner.settings["bankroll"] == 0

    def test_only_changed_settings_are_saved_so_env_still_applies(self, scanner, tmp_path, monkeypatch):
        scanner.update_settings({"bankroll": 500, "min_edge_cents": 2.0})  # 2.0 is the default
        assert json.loads((tmp_path / "demo_settings.json").read_text()) == {"bankroll": 500.0}
        monkeypatch.setenv("LARGE_TRADE_THRESHOLD", "75")
        scanner.reload()
        assert scanner.settings["large_trade"] == 75 and scanner.settings["bankroll"] == 500

    def test_bad_saved_settings_fall_back_to_defaults(self, tmp_path):
        (tmp_path / "demo_settings.json").write_text('{"refresh_minutes": Infinity, "bankroll": 250}')
        s = Scanner(DemoSource(), data_dir=tmp_path, mode="demo")
        assert s.settings["refresh_minutes"] == 5 and s.settings["bankroll"] == 250

    def test_picks_saved_by_another_process_are_picked_up(self, scanner, tmp_path):
        web = Scanner(DemoSource(), data_dir=tmp_path, mode="demo")
        web.refresh()
        web.set_estimate("DEMO-GDP-Q3-YES", 90)
        scanner.refresh()
        assert [p["ticker"] for p in scanner.opportunities()["picks"]] == ["DEMO-GDP-Q3-YES"]

    def test_runtime_overrides_survive_reload(self, scanner):
        scanner.overrides["min_edge_cents"] = 50.0
        scanner.reload()
        assert scanner.settings["min_edge_cents"] == 50.0

    def test_watch_filter_keeps_markets_you_have_picks_on(self, scanner):
        scanner.set_estimate("DEMO-GDP-Q3-YES", 90)
        scanner.update_settings({"watch_series": "DEMO-FED"})
        scanner.refresh()
        assert "DEMO-GDP-Q3-YES" in scanner.by_ticker

    def test_failed_refresh_keeps_last_data(self, scanner):
        before = len(scanner.snapshot["markets"])

        class Offline:
            def get_all_events(self, **_):
                raise httpx.ConnectError("no route to host")

        scanner.source = Offline()
        scanner.refresh()
        assert scanner.snapshot["error"].startswith("Couldn't reach Kalshi") and scanner.snapshot["offline"]
        assert len(scanner.snapshot["markets"]) == before

    def test_http_errors_are_described_plainly(self):
        from src.scanner.service import friendly_error

        request = httpx.Request("GET", "https://example.test/events?secret=1")
        err = httpx.HTTPStatusError("boom", request=request, response=httpx.Response(429, request=request))
        assert friendly_error(err) == "Kalshi answered 429 (too many requests)"

    def test_balance_errors_are_reported_not_hidden(self, tmp_path):
        class NoBalance(DemoSource):
            def get_balance(self):
                return {}

        s = Scanner(NoBalance(), data_dir=tmp_path, mode="demo")
        s.refresh()
        assert s.snapshot["balance"] is None and s.snapshot["balance_error"]

    def test_balance_skipped_quietly_without_api_key(self, tmp_path):
        class NoKey(DemoSource):
            has_auth = False

        s = Scanner(NoKey(), data_dir=tmp_path, mode="demo")
        s.refresh()
        assert s.snapshot["balance"] is None and s.snapshot["balance_error"] is None

    def test_categories_come_from_series_list(self, tmp_path):
        class WithSeries(DemoSource):
            def get_series_list(self):
                return [{"ticker": "DEMO-FED", "category": "Rates"}]

        s = Scanner(WithSeries(), data_dir=tmp_path, mode="demo")
        s.refresh()
        assert s.by_ticker["DEMO-FED-DEC-HOLDRATES"]["category"] == "Rates"

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

    def _post(self, url, body, headers=None, raw=None):
        data = raw if raw is not None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
        return json.load(urllib.request.urlopen(req))

    def _get(self, url):
        return json.load(urllib.request.urlopen(url))

    def _status(self, fn):
        with pytest.raises(urllib.error.HTTPError) as e:
            fn()
        return e.value.code

    def test_serves_page_state_and_markets(self, base_url):
        assert b"Prediction Market Bot" in urllib.request.urlopen(base_url + "/").read()
        state = self._get(base_url + "/api/state")
        assert state["mode"] == "demo" and state["market_count"] > 0 and "markets" not in state
        markets = self._get(base_url + "/api/markets")["markets"]
        assert len(markets) == state["market_count"] and "rules" not in markets[0]
        detail = self._get(base_url + "/api/market?ticker=" + markets[0]["ticker"])
        assert detail["rules"]

    def test_saving_an_estimate_shows_up_in_state(self, base_url):
        assert self._post(base_url + "/api/estimate", {"ticker": "DEMO-GDP-Q3-YES", "chance": 90})["ok"]
        state = self._get(base_url + "/api/state")
        assert state["estimates"] == {"DEMO-GDP-Q3-YES": 90.0}
        assert state["opportunities"]["picks"]

    def test_bad_input_returns_400(self, base_url):
        assert self._status(lambda: self._post(base_url + "/api/estimate", {"ticker": "X", "chance": 150})) == 400
        assert self._status(lambda: self._post(base_url + "/api/settings", None, raw=b'{"bankroll": NaN}')) == 400
        assert self._status(lambda: self._post(base_url + "/api/settings", {"max_event_pages": 1e400})) == 400

    def test_rejects_cross_site_writes(self, base_url):
        evil = {"Origin": "http://evil.example"}
        assert self._status(lambda: self._post(base_url + "/api/settings", {"bankroll": 5}, evil)) == 403
        assert self._status(lambda: self._post(base_url + "/api/settings", {"bankroll": 5},
                                               {"Sec-Fetch-Site": "cross-site"})) == 403
        plain = {"Content-Type": "text/plain"}  # what an HTML form can send without a preflight
        assert self._status(lambda: self._post(base_url + "/api/settings", {"bankroll": 5}, plain)) == 415
        assert self._get(base_url + "/api/state")["settings"]["bankroll"] == 0

    def test_rejects_unknown_host_header(self, base_url):
        req = urllib.request.Request(base_url + "/api/state", headers={"Host": "rebind.evil.example"})
        assert self._status(lambda: urllib.request.urlopen(req)) == 403

    def test_negative_content_length_is_rejected(self, base_url):
        import http.client
        from urllib.parse import urlsplit

        conn = http.client.HTTPConnection(urlsplit(base_url).netloc, timeout=5)
        conn.putrequest("POST", "/api/settings")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", "-1")
        conn.endheaders()
        conn.send(b'{"watch_series": "x"}')
        assert conn.getresponse().status == 400

    def test_does_not_serve_files_outside_web_dir(self, base_url):
        assert self._status(lambda: urllib.request.urlopen(base_url + "/%2e%2e/pyproject.toml")) == 404
        assert self._status(lambda: urllib.request.urlopen(base_url + "/" + "a" * 300)) == 404
