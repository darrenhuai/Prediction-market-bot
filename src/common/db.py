from __future__ import annotations
import json
from pathlib import Path
import duckdb

DB_PATH = Path("data/kalshi.duckdb")

def get_conn(path=DB_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    _init_schema(conn)
    return conn

def _init_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS markets (
            ticker VARCHAR PRIMARY KEY,
            event_ticker VARCHAR,
            series_ticker VARCHAR,
            title VARCHAR,
            status VARCHAR,
            yes_bid INTEGER,
            yes_ask INTEGER,
            no_bid INTEGER,
            no_ask INTEGER,
            last_price INTEGER,
            volume INTEGER,
            open_interest INTEGER,
            close_time VARCHAR,
            result VARCHAR,
            raw JSON,
            indexed_at TIMESTAMP DEFAULT current_timestamp
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            ticker VARCHAR PRIMARY KEY,
            yes_position INTEGER,
            no_position INTEGER,
            total_cost INTEGER,
            market_exposure INTEGER,
            realized_pnl INTEGER,
            unrealized_pnl INTEGER,
            raw JSON,
            indexed_at TIMESTAMP DEFAULT current_timestamp
        )
    """)

def upsert_markets(conn, markets):
    count = 0
    for m in markets:
        conn.execute(
            "INSERT OR REPLACE INTO markets (ticker,event_ticker,series_ticker,title,status,yes_bid,yes_ask,no_bid,no_ask,last_price,volume,open_interest,close_time,result,raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [m.get("ticker"),m.get("event_ticker"),m.get("series_ticker"),m.get("title") or m.get("subtitle"),m.get("status"),m.get("yes_bid"),m.get("yes_ask"),m.get("no_bid"),m.get("no_ask"),m.get("last_price"),m.get("volume"),m.get("open_interest"),m.get("close_time"),m.get("result"),json.dumps(m)]
        )
        count += 1
    return count

def upsert_positions(conn, positions):
    count = 0
    for p in positions:
        conn.execute(
            "INSERT OR REPLACE INTO positions (ticker,yes_position,no_position,total_cost,market_exposure,realized_pnl,unrealized_pnl,raw) VALUES (?,?,?,?,?,?,?,?)",
            [p.get("ticker"),p.get("position",0) if p.get("position",0)>0 else 0,abs(p.get("position",0)) if p.get("position",0)<0 else 0,p.get("total_traded"),p.get("market_exposure"),p.get("realized_pnl"),p.get("unrealized_pnl"),json.dumps(p)]
        )
        count += 1
    return count
