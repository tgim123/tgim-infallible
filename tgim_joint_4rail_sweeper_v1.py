#!/usr/bin/env python3
"""
TGIM REDLINE 5-R SWEEPER v2.1 — DEPLOY BUILD
=============================================

BUILD ID: REDLINE-5R-V2.1-20260826-A

Five fixed timeframe bays:
    R1  = 1W
    R2  = 1D
    R8  = 15m
    R9  = 5m
    R10 = 1m

Baseline:
    R1  = HMA5 RAW
    R2  = EMA5 RAW  Guardian + Trigger
    R8  = HMA27 RAW
    R9  = KS27 RAW
    R10 = KS27 RAW

Search:
    EMA / HMA / KS / WMA
    lengths 3 / 5 / 8 / 13 / 21 / 27 / 34
    Guardian = any of the five R bays
    Trigger  = any of the five R bays
    Guardian and Trigger may be the SAME R.

Adaptive REDLINE behavior:
    baseline certification
    candidate prescreen
    diversity-preserving shortlist
    actual Render throughput benchmark
    largest safe K^5 x 25 joint search inside runtime budget
    streaming result retention
    exact-length local refinement

EURUSD current control:
    36/36 total
    11/11 latest 30d

RAW fixed. ADX off for this phase.
Registry defaults to 27 and may be switched to 20 for a control run.

This Python program is research-only and cannot place orders.
TradingView remains the final verifier.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import requests

BUILD_ID = "REDLINE-5R-V2.1-20260826-A"

try:
    from numba import njit, prange
except Exception as exc:
    raise SystemExit(
        "numba is required. Install requirements.txt first. "
        f"Import error: {exc}"
    )

FAMILIES = ("EMA", "HMA", "KS", "WMA")
DEFAULT_LENGTHS = (3, 5, 8, 13, 21, 27, 34)

BASELINE = {
    "R1": ("HMA", 5),
    "R2": ("EMA", 5),
    "R8": ("HMA", 27),
    "R9": ("KS", 27),
    "R10": ("KS", 27),
}
SLOT_TF = {"R1": "W", "R2": "D", "R8": "M15", "R9": "M5", "R10": "M1"}
SLOT_ORDER = ("R1", "R2", "R8", "R9", "R10")
ROLE_INDEX = {slot: i for i, slot in enumerate(SLOT_ORDER)}

BASE_GUARDIAN = "R2"
BASE_TRIGGER = "R2"

# Current EURUSD control from the supplied TradingView screenshot/export.
EXPECTED_TOTAL = {"EUR_USD": 36}
EXPECTED_FORWARD = {"EUR_USD": 11}

MAX_REGISTRY_LIMIT = 64


def instrument_norm(raw: str) -> str:
    s = raw.upper().replace("OANDA:", "").replace("/", "_").replace("-", "_")
    if "_" not in s and len(s) == 6:
        s = s[:3] + "_" + s[3:]
    if len(s) != 7 or s[3] != "_":
        raise ValueError(f"Bad instrument: {raw!r}")
    return s


def pip_size(instrument: str) -> float:
    return 0.01 if instrument.endswith("_JPY") else 0.0001


@dataclass(frozen=True)
class RailCfg:
    family: str
    length: int

    def label(self) -> str:
        return f"{self.family}{self.length}"


class OandaHistory:
    def __init__(self, token: str, env: str, cache_dir: Path, timeout: float = 20.0):
        if not token:
            raise ValueError(
                "OANDA_TOKEN is empty. Set it in the environment or pass --token."
            )
        self.base = (
            "https://api-fxpractice.oanda.com"
            if env == "practice"
            else "https://api-fxtrade.oanda.com"
        )
        self.timeout = timeout
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept-Datetime-Format": "RFC3339",
        })

    def _request(self, path: str, params: dict) -> dict:
        last_err = None
        for attempt in range(6):
            try:
                r = self.s.get(self.base + path, params=params, timeout=self.timeout)
                if r.status_code == 429:
                    time.sleep(min(8.0, 0.75 * (2 ** attempt)))
                    continue
                if r.status_code >= 400:
                    body = (r.text or "")[:800]
                    raise RuntimeError(
                        f"OANDA HTTP {r.status_code}: {body} | url={r.url}"
                    )
                return r.json()
            except Exception as exc:
                last_err = exc
                time.sleep(min(5.0, 0.5 * (2 ** attempt)))
        raise RuntimeError(f"OANDA request failed after retries: {last_err}")

    def candles(
        self,
        instrument: str,
        granularity: str,
        start: datetime,
        end: datetime,
        refresh: bool = False,
    ) -> pd.DataFrame:
        key = (
            f"{instrument}_{granularity}_"
            f"{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv.gz"
        )
        cache = self.cache_dir / key
        if cache.exists() and not refresh:
            df = pd.read_csv(cache, compression="gzip")
            df["time"] = pd.to_datetime(df["time"], utc=True)
            return df

        rows = []
        cursor = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)
        path = f"/v3/instruments/{instrument}/candles"

        # Approximate candle durations for pagination cursor advancement.
        sec_map = {"M1": 60, "M5": 300, "M15": 900, "D": 86400, "W": 604800}
        step_sec = sec_map[granularity]

        while cursor < end:
            params = {
                "price": "M",
                "granularity": granularity,
                "from": cursor.isoformat().replace("+00:00", "Z"),
                "count": 5000,
                "includeFirst": "true",
                "smooth": "false",
            }
            if granularity == "D":
                params["dailyAlignment"] = 17
                params["alignmentTimezone"] = "America/New_York"
            elif granularity == "W":
                params["weeklyAlignment"] = "Friday"
                params["alignmentTimezone"] = "America/New_York"
            data = self._request(path, params)
            candles = data.get("candles", [])
            if not candles:
                break

            last_time = None
            for c in candles:
                t = pd.Timestamp(c["time"])
                if t.tzinfo is None:
                    t = t.tz_localize("UTC")
                else:
                    t = t.tz_convert("UTC")
                if t.to_pydatetime() > end:
                    continue
                m = c.get("mid") or {}
                rows.append({
                    "time": t,
                    "open": float(m.get("o", "nan")),
                    "high": float(m.get("h", "nan")),
                    "low": float(m.get("l", "nan")),
                    "close": float(m.get("c", "nan")),
                    "volume": int(c.get("volume", 0) or 0),
                    "complete": bool(c.get("complete", False)),
                })
                last_time = t

            if last_time is None:
                break
            nxt = last_time.to_pydatetime() + timedelta(seconds=step_sec)
            if nxt <= cursor:
                break
            cursor = nxt

            # v1.1: A page shorter than the requested 5000 candles is the final
            # available page. Stop immediately instead of advancing the cursor
            # beyond OANDA's newest candle and issuing a future-dated request.
            if len(candles) < 5000:
                break

            if last_time.to_pydatetime() >= end - timedelta(seconds=step_sec):
                break

        if not rows:
            raise RuntimeError(f"No {granularity} candles returned for {instrument}")

        df = (
            pd.DataFrame(rows)
            .drop_duplicates("time", keep="last")
            .sort_values("time")
            .reset_index(drop=True)
        )
        df.to_csv(cache, index=False, compression="gzip")
        return df


# ─────────────────────────────────────────────────────────────────────────────
# Pine rail math
# ─────────────────────────────────────────────────────────────────────────────

def ema_np(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if len(x) == 0:
        return out
    alpha = 2.0 / (n + 1.0)
    # Warm seed. With the large historical warmup this converges before evaluation.
    seed = np.nan
    for i in range(len(x)):
        v = x[i]
        if not np.isfinite(v):
            continue
        if not np.isfinite(seed):
            seed = v
        else:
            seed = alpha * v + (1.0 - alpha) * seed
        out[i] = seed
    return out


def wma_np(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if n <= 0:
        return out
    w = np.arange(1.0, n + 1.0, dtype=np.float64)
    den = w.sum()
    for i in range(n - 1, len(x)):
        win = x[i - n + 1 : i + 1]
        if np.all(np.isfinite(win)):
            out[i] = np.dot(win, w) / den
    return out


def linreg_np(x: np.ndarray, n: int) -> np.ndarray:
    """Pine ta.linreg(source, length, 0): fitted value at x=n-1."""
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if n <= 1:
        out[:] = x
        return out
    xs = np.arange(n, dtype=np.float64)
    sx = xs.sum()
    sxx = np.dot(xs, xs)
    den = n * sxx - sx * sx
    for i in range(n - 1, len(x)):
        y = x[i - n + 1 : i + 1]
        if not np.all(np.isfinite(y)):
            continue
        sy = y.sum()
        sxy = np.dot(xs, y)
        slope = (n * sxy - sx * sy) / den
        intercept = (sy - slope * sx) / n
        out[i] = intercept + slope * (n - 1)
    return out


def hma_np(x: np.ndarray, n: int) -> np.ndarray:
    half = max(1, int(math.floor(n / 2.0 + 0.5)))
    root = max(1, int(math.floor(math.sqrt(n) + 0.5)))
    a = wma_np(x, half)
    b = wma_np(x, n)
    raw = 2.0 * a - b
    return wma_np(raw, root)


def rail_np(close: np.ndarray, family: str, length: int) -> np.ndarray:
    if family == "EMA":
        return ema_np(close, length)
    if family == "HMA":
        return hma_np(close, length)
    if family == "KS":
        return linreg_np(close, length)
    if family == "WMA":
        return wma_np(close, length)
    raise ValueError(f"Unknown rail family {family}")


def daily_execution_frame(d_all: pd.DataFrame) -> pd.DataFrame:
    """
    Keep complete Daily candles that have a following Daily timestamp.
    The following timestamp is the current candle's close boundary.
    """
    d = d_all.sort_values("time").reset_index(drop=True).copy()
    d["next_time"] = d["time"].shift(-1)
    mask = d["complete"].astype(bool) & d["next_time"].notna()
    d = d.loc[mask].copy().reset_index(drop=True)
    d["bar_open_ns"] = d["time"].astype("int64")
    d["bar_close_ns"] = d["next_time"].astype("int64")
    return d


def sample_source_to_daily(
    source: pd.DataFrame,
    rail: np.ndarray,
    daily: pd.DataFrame,
    granularity: str,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Emulate request.security(..., lookahead_off) on a Daily chart.

    For D, current source rail is the same Daily candle; inverse is previous D rail.
    For M15/M5/M1, use the final completed source candle inside each Daily candle;
    inverse is the source rail one source bar earlier.
    """
    n = len(daily)
    cur = np.full(n, np.nan, dtype=np.float64)
    inv = np.full(n, np.nan, dtype=np.float64)

    if granularity == "D":
        src = source.sort_values("time").reset_index(drop=True)
        time_to_idx = {int(t.value): i for i, t in enumerate(pd.to_datetime(src["time"], utc=True))}
        for j in range(n):
            k = time_to_idx.get(int(pd.Timestamp(daily.loc[j, "time"]).value), -1)
            if k >= 0:
                cur[j] = rail[k]
                if k > 0:
                    inv[j] = rail[k - 1]
        return cur, inv

    sec_map = {"M1": 60, "M5": 300, "M15": 900, "W": 604800}
    dur_ns = sec_map[granularity] * 1_000_000_000

    src = source.sort_values("time").reset_index(drop=True)
    src_start = pd.to_datetime(src["time"], utc=True).astype("int64").to_numpy()
    # Complete source candles only.
    complete = src["complete"].astype(bool).to_numpy()
    valid_idx = np.flatnonzero(complete)
    valid_start = src_start[valid_idx]

    for j in range(n):
        boundary = int(daily.loc[j, "bar_close_ns"])
        latest_start = boundary - dur_ns
        pos = np.searchsorted(valid_start, latest_start, side="right") - 1
        if pos >= 0:
            k = int(valid_idx[pos])
            cur[j] = rail[k]
            if k > 0:
                inv[j] = rail[k - 1]
    return cur, inv


def candidate_daily_arrays(
    source: pd.DataFrame,
    daily: pd.DataFrame,
    granularity: str,
    cfgs: List[RailCfg],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Return candidate x day:
      event_type: +1 valley / -1 peak / 0
      turn_price: inverse rail at event
      raw_dir:    +1 / -1 / 0
    """
    close = source["close"].to_numpy(dtype=np.float64)
    nc, nd = len(cfgs), len(daily)
    evt = np.zeros((nc, nd), dtype=np.int8)
    price = np.full((nc, nd), np.nan, dtype=np.float64)
    direction = np.zeros((nc, nd), dtype=np.int8)

    for ci, cfg in enumerate(cfgs):
        r = rail_np(close, cfg.family, cfg.length)
        cur, inv = sample_source_to_daily(source, r, daily, granularity)
        d = np.where(np.isfinite(cur) & np.isfinite(inv),
                     np.where(cur > inv, 1, np.where(cur < inv, -1, 0)), 0).astype(np.int8)
        direction[ci] = d

        for t in range(1, nd):
            if not (np.isfinite(cur[t]) and np.isfinite(inv[t]) and
                    np.isfinite(cur[t-1]) and np.isfinite(inv[t-1])):
                continue
            up = cur[t] > inv[t] and cur[t-1] <= inv[t-1]
            dn = cur[t] < inv[t] and cur[t-1] >= inv[t-1]
            if up:
                evt[ci, t] = 1
                price[ci, t] = inv[t]
            elif dn:
                evt[ci, t] = -1
                price[ci, t] = inv[t]
    return evt, price, direction



# ─────────────────────────────────────────────────────────────────────────────
# Redline joint simulator — five R bays / dynamic Guardian + Trigger
# ─────────────────────────────────────────────────────────────────────────────

@njit(cache=True)
def _find_target(reg_price, reg_type, reg_bar, reg_count, wanted_type, current_event_bar):
    for k in range(reg_count - 1, -1, -1):
        if reg_bar[k] < current_event_bar and reg_type[k] == wanted_type:
            return reg_price[k]
    return np.nan


@njit(cache=True)
def _push_turn(reg_price, reg_type, reg_bar, reg_count, price, typ, event_bar, registry_limit):
    if reg_count < registry_limit:
        reg_price[reg_count] = price
        reg_type[reg_count] = typ
        reg_bar[reg_count] = event_bar
        return reg_count + 1

    for k in range(registry_limit - 1):
        reg_price[k] = reg_price[k + 1]
        reg_type[k] = reg_type[k + 1]
        reg_bar[k] = reg_bar[k + 1]
    reg_price[registry_limit - 1] = price
    reg_type[registry_limit - 1] = typ
    reg_bar[registry_limit - 1] = event_bar
    return registry_limit


@njit(cache=True)
def _tv_tick_path(o, h, l, c):
    out = np.empty(4, dtype=np.float64)
    out[0] = o
    if abs(o - h) <= abs(o - l):
        out[1] = h
        out[2] = l
    else:
        out[1] = l
        out[2] = h
    out[3] = c
    return out


@njit(cache=True)
def _selected_dir(role_idx, c0, c1, c2, c3, c4, d0, d1, d2, d3, d4, t):
    if role_idx == 0:
        return int(d0[c0, t])
    if role_idx == 1:
        return int(d1[c1, t])
    if role_idx == 2:
        return int(d2[c2, t])
    if role_idx == 3:
        return int(d3[c3, t])
    return int(d4[c4, t])


@njit(cache=True)
def _simulate_one(
    c0, c1, c2, c3, c4,
    guardian_role, trigger_role,
    e0, p0, d0,
    e1, p1, d1,
    e2, p2, d2,
    e3, p3, d3,
    e4, p4, d4,
    o, h, l, c,
    open_ns, close_ns,
    eval_start_ns, fwd_start_ns,
    pip, registry_limit,
):
    nd = len(c)

    reg_price = np.empty(MAX_REGISTRY_LIMIT, dtype=np.float64)
    reg_type = np.empty(MAX_REGISTRY_LIMIT, dtype=np.int8)
    reg_bar = np.empty(MAX_REGISTRY_LIMIT, dtype=np.int32)
    reg_count = 0

    position = 0
    entry_price = 0.0
    target = np.nan
    entry_time_ns = 0
    mae_pips = 0.0

    order_pending = 0
    order_target = np.nan
    order_signal_day = -1
    order_signal_tick = -1

    # Meaningful Guardian direction is persistent; a flat reading does not erase it.
    guard_meaningful = 0
    exit_day = -1

    entries_total = 0
    closed_total = 0
    wins_total = 0
    net_total = 0.0
    max_mae_total = 0.0
    longest_total = 0.0
    hold_sum_total = 0.0

    entries_fwd = 0
    closed_fwd = 0
    wins_fwd = 0
    net_fwd = 0.0

    day_ns = 86_400_000_000_000

    for t in range(nd):
        trigger_dir = _selected_dir(trigger_role, c0,c1,c2,c3,c4, d0,d1,d2,d3,d4, t)
        g_now = _selected_dir(guardian_role, c0,c1,c2,c3,c4, d0,d1,d2,d3,d4, t)
        if g_now != 0:
            guard_meaningful = g_now
        guardian_dir = guard_meaningful

        event_types = np.empty(5, dtype=np.int8)
        event_prices = np.empty(5, dtype=np.float64)
        event_count = 0

        typ = int(e0[c0, t])
        if typ != 0:
            pr = p0[c0, t]
            reg_count = _push_turn(reg_price, reg_type, reg_bar, reg_count, pr, typ, t - 1, registry_limit)
            event_types[event_count] = typ
            event_prices[event_count] = pr
            event_count += 1

        typ = int(e1[c1, t])
        if typ != 0:
            pr = p1[c1, t]
            reg_count = _push_turn(reg_price, reg_type, reg_bar, reg_count, pr, typ, t - 1, registry_limit)
            event_types[event_count] = typ
            event_prices[event_count] = pr
            event_count += 1

        typ = int(e2[c2, t])
        if typ != 0:
            pr = p2[c2, t]
            reg_count = _push_turn(reg_price, reg_type, reg_bar, reg_count, pr, typ, t - 1, registry_limit)
            event_types[event_count] = typ
            event_prices[event_count] = pr
            event_count += 1

        typ = int(e3[c3, t])
        if typ != 0:
            pr = p3[c3, t]
            reg_count = _push_turn(reg_price, reg_type, reg_bar, reg_count, pr, typ, t - 1, registry_limit)
            event_types[event_count] = typ
            event_prices[event_count] = pr
            event_count += 1

        typ = int(e4[c4, t])
        if typ != 0:
            pr = p4[c4, t]
            reg_count = _push_turn(reg_price, reg_type, reg_bar, reg_count, pr, typ, t - 1, registry_limit)
            event_types[event_count] = typ
            event_prices[event_count] = pr
            event_count += 1

        ticks = _tv_tick_path(o[t], h[t], l[t], c[t])
        span = close_ns[t] - open_ns[t]
        if span <= 0:
            span = day_ns

        for q in range(4):
            px = ticks[q]
            tick_ns = open_ns[t] + (span * q) // 3

            if order_pending != 0:
                later_tick = (t > order_signal_day) or (t == order_signal_day and q > order_signal_tick)
                if later_tick and position == 0:
                    position = order_pending
                    entry_price = px
                    target = order_target
                    entry_time_ns = tick_ns
                    mae_pips = 0.0

                    if tick_ns >= eval_start_ns:
                        entries_total += 1
                    if tick_ns >= fwd_start_ns:
                        entries_fwd += 1

                    order_pending = 0
                    order_target = np.nan
                    order_signal_day = -1
                    order_signal_tick = -1

            if position != 0:
                adverse = ((entry_price - px) / pip) if position == 1 else ((px - entry_price) / pip)
                if adverse > mae_pips:
                    mae_pips = adverse

                reached = (px >= target) if position == 1 else (px <= target)
                if reached:
                    exit_price = px
                    pnl_pips = ((exit_price - entry_price) / pip) if position == 1 else ((entry_price - exit_price) / pip)
                    hold_days = max(0.0, (tick_ns - entry_time_ns) / float(day_ns))

                    if tick_ns >= eval_start_ns:
                        closed_total += 1
                        if pnl_pips > 0:
                            wins_total += 1
                        net_total += pnl_pips
                        if mae_pips > max_mae_total:
                            max_mae_total = mae_pips
                        if hold_days > longest_total:
                            longest_total = hold_days
                        hold_sum_total += hold_days

                    if tick_ns >= fwd_start_ns:
                        closed_fwd += 1
                        if pnl_pips > 0:
                            wins_fwd += 1
                        net_fwd += pnl_pips

                    position = 0
                    entry_price = 0.0
                    target = np.nan
                    entry_time_ns = 0
                    mae_pips = 0.0
                    exit_day = t
                    continue

            if tick_ns < eval_start_ns:
                continue
            if position != 0 or order_pending != 0:
                continue
            if exit_day == t or event_count == 0:
                continue

            for ei in range(event_count):
                et = int(event_types[ei])
                candidate_dir = 1 if et == 1 else -1

                if candidate_dir != guardian_dir or candidate_dir != trigger_dir:
                    continue

                tgt = _find_target(reg_price, reg_type, reg_bar, reg_count, -et, t - 1)
                if not np.isfinite(tgt):
                    continue

                target_valid = (tgt > px) if candidate_dir == 1 else (tgt < px)
                if not target_valid:
                    continue

                order_pending = candidate_dir
                order_target = tgt
                order_signal_day = t
                order_signal_tick = q
                break

    open_end = 1 if (position != 0 or order_pending != 0) else 0
    avg_hold = hold_sum_total / closed_total if closed_total > 0 else 9999.0

    out = np.empty(13, dtype=np.float64)
    out[0] = entries_total
    out[1] = closed_total
    out[2] = wins_total
    out[3] = net_total
    out[4] = max_mae_total
    out[5] = longest_total
    out[6] = avg_hold
    out[7] = entries_fwd
    out[8] = closed_fwd
    out[9] = wins_fwd
    out[10] = net_fwd
    out[11] = open_end
    out[12] = (closed_total / entries_total * 100.0) if entries_total > 0 else 0.0
    return out


@njit(parallel=True, cache=True)
def simulate_many(
    combos,
    e0, p0, d0,
    e1, p1, d1,
    e2, p2, d2,
    e3, p3, d3,
    e4, p4, d4,
    o, h, l, c,
    open_ns, close_ns,
    eval_start_ns, fwd_start_ns,
    pip, registry_limit,
):
    n = combos.shape[0]
    out = np.empty((n, 13), dtype=np.float64)
    for i in prange(n):
        out[i] = _simulate_one(
            combos[i,0], combos[i,1], combos[i,2], combos[i,3], combos[i,4],
            combos[i,5], combos[i,6],
            e0,p0,d0,e1,p1,d1,e2,p2,d2,e3,p3,d3,e4,p4,d4,
            o,h,l,c,open_ns,close_ns,eval_start_ns,fwd_start_ns,pip,registry_limit
        )
    return out


def coarse_cfgs(lengths: Tuple[int, ...]) -> Dict[str, List[RailCfg]]:
    bank = [RailCfg(f, n) for f in FAMILIES for n in lengths]
    return {slot: list(bank) for slot in SLOT_ORDER}


def cfg_index(cfgs: List[RailCfg], wanted: Tuple[str,int]) -> int:
    for i, c in enumerate(cfgs):
        if c.family == wanted[0] and c.length == wanted[1]:
            return i
    raise ValueError(f"Baseline {wanted} not found in candidate bank")


def metric_dict(row: np.ndarray) -> dict:
    return {
        "entries_120d": int(row[0]),
        "closed_120d": int(row[1]),
        "wins_120d": int(row[2]),
        "win_pct_120d": (row[2] / row[1] * 100.0) if row[1] > 0 else 0.0,
        "net_pips_120d": float(row[3]),
        "max_mae_pips_120d": float(row[4]),
        "longest_days_120d": float(row[5]),
        "avg_hold_days_120d": float(row[6]),
        "entries_30d": int(row[7]),
        "closed_30d": int(row[8]),
        "wins_30d": int(row[9]),
        "win_pct_30d": (row[9] / row[8] * 100.0) if row[8] > 0 else 0.0,
        "net_pips_30d": float(row[10]),
        "open_or_pending_end": int(row[11]),
        "completion_pct_120d": float(row[12]),
    }


def _quality_tier(metrics: np.ndarray) -> np.ndarray:
    closed = metrics[:,1]
    wins = metrics[:,2]
    fclosed = metrics[:,8]
    fwins = metrics[:,9]

    wr = np.divide(wins, np.maximum(closed,1), dtype=np.float64) * 100.0
    fwr = np.divide(fwins, np.maximum(fclosed,1), dtype=np.float64) * 100.0

    q = np.zeros(len(metrics), dtype=np.int16)
    q[(wr >= 90.0) & (fwr >= 90.0)] = 1
    q[(wr >= 95.0) & (fwr >= 95.0)] = 2
    q[(wr >= 97.5) & (fwr >= 97.5)] = 3
    q[(wr >= 99.999) & (fwr >= 99.999)] = 4
    return q


def rank_indices(metrics: np.ndarray) -> np.ndarray:
    closed = metrics[:,1]
    fclosed = metrics[:,8]
    quality = _quality_tier(metrics)

    # Primary: accuracy tier.
    # Inside 100% tier: most 30d trades, most total trades, then economics/risk/speed.
    return np.lexsort((
        metrics[:,6],                  # lower average hold
        metrics[:,5],                  # lower longest
        metrics[:,4],                  # lower MAE
        -metrics[:,3],                 # higher 120d pips
        -metrics[:,10],                # higher 30d pips
        metrics[:,11],                 # prefer no stranded/open trade
        -closed,                       # more total closed
        -fclosed,                      # more 30d closed
        -quality,                      # highest accuracy tier first
    ))


def build_top_rows(
    combos: np.ndarray,
    metrics: np.ndarray,
    cfgs: Dict[str, List[RailCfg]],
    top_n: int,
) -> pd.DataFrame:
    if len(combos) == 0:
        return pd.DataFrame()
    order = rank_indices(metrics)[:top_n]
    rows = []
    for rank, ix in enumerate(order, 1):
        combo = combos[ix]
        row = {"rank": rank}
        for si, slot in enumerate(SLOT_ORDER):
            cfg = cfgs[slot][int(combo[si])]
            row[f"{slot}_family"] = cfg.family
            row[f"{slot}_length"] = cfg.length
            row[f"{slot}_config"] = cfg.label() + " RAW"
        row["guardian"] = SLOT_ORDER[int(combo[5])]
        row["trigger"] = SLOT_ORDER[int(combo[6])]
        row["same_guard_trigger"] = bool(int(combo[5]) == int(combo[6]))
        row.update(metric_dict(metrics[ix]))
        rows.append(row)
    return pd.DataFrame(rows)


def prepare_banks(raw, daily, cfgs):
    out = []
    for slot in SLOT_ORDER:
        gran = SLOT_TF[slot]
        evt, price, direction = candidate_daily_arrays(raw[gran], daily, gran, cfgs[slot])
        out.append((evt, price, direction))
    return out


def baseline_combo(cfgs):
    vals = [cfg_index(cfgs[s], BASELINE[s]) for s in SLOT_ORDER]
    vals += [ROLE_INDEX[BASE_GUARDIAN], ROLE_INDEX[BASE_TRIGGER]]
    return np.asarray([vals], dtype=np.int16)


def prescreen_combos(cfgs):
    base = [cfg_index(cfgs[s], BASELINE[s]) for s in SLOT_ORDER]
    rows = []
    meta = []
    for si, slot in enumerate(SLOT_ORDER):
        for cand in range(len(cfgs[slot])):
            for g in range(len(SLOT_ORDER)):
                for tr in range(len(SLOT_ORDER)):
                    r = list(base)
                    r[si] = cand
                    r.extend([g, tr])
                    rows.append(r)
                    meta.append((si, cand))
    return np.asarray(rows, dtype=np.int16), meta


def _candidate_best_metric_for_slot(si, cfgs, pre_metrics):
    n = len(cfgs[SLOT_ORDER[si]])
    block = len(SLOT_ORDER) * len(SLOT_ORDER)  # 25 role combinations per candidate
    offset = sum(len(cfgs[SLOT_ORDER[k]]) * block for k in range(si))
    best = []
    for cand in range(n):
        a = offset + cand * block
        b = a + block
        m = pre_metrics[a:b]
        oi = rank_indices(m)[0]
        best.append((cand, m[oi].copy()))
    return best


def diversity_shortlist(si, cfgs, pre_metrics, k):
    slot = SLOT_ORDER[si]
    candidates = _candidate_best_metric_for_slot(si, cfgs, pre_metrics)
    all_metrics = np.asarray([x[1] for x in candidates], dtype=np.float64)
    order = rank_indices(all_metrics)

    chosen = []
    chosen_set = set()

    # Preserve current champion.
    base_ix = cfg_index(cfgs[slot], BASELINE[slot])
    chosen.append(base_ix)
    chosen_set.add(base_ix)

    # Preserve at least the best candidate from every rail family.
    for fam in FAMILIES:
        fam_ix = [i for i,(cand,_) in enumerate(candidates)
                  if cfgs[slot][cand].family == fam]
        if not fam_ix:
            continue
        fam_metrics = np.asarray([all_metrics[i] for i in fam_ix])
        winner_local = rank_indices(fam_metrics)[0]
        cand_ix = candidates[fam_ix[winner_local]][0]
        if cand_ix not in chosen_set:
            chosen.append(cand_ix)
            chosen_set.add(cand_ix)

    # Fill remaining slots by overall prescreen rank.
    for oi in order:
        cand_ix = candidates[int(oi)][0]
        if cand_ix not in chosen_set:
            chosen.append(cand_ix)
            chosen_set.add(cand_ix)
        if len(chosen) >= k:
            break

    return chosen[:k]


def random_benchmark_combos(cfgs, n, seed=73027):
    rng = np.random.default_rng(seed)
    arr = np.empty((n, 7), dtype=np.int16)
    for si, slot in enumerate(SLOT_ORDER):
        arr[:,si] = rng.integers(0, len(cfgs[slot]), size=n, dtype=np.int16)
    arr[:,5] = rng.integers(0, len(SLOT_ORDER), size=n, dtype=np.int16)
    arr[:,6] = rng.integers(0, len(SLOT_ORDER), size=n, dtype=np.int16)
    return arr


def choose_redline_k(rate, seconds_available, safety_fraction, max_shortlist, min_shortlist=4):
    safe_systems = max(1, int(rate * seconds_available * safety_fraction))
    k = max_shortlist
    while k > min_shortlist and (k ** 5) * 25 > safe_systems:
        k -= 1
    if (k ** 5) * 25 > safe_systems:
        k = min_shortlist
    return k, safe_systems, (k ** 5) * 25


def iter_joint_batches(shortlists, batch_size):
    product_iter = itertools.product(
        shortlists[0], shortlists[1], shortlists[2], shortlists[3], shortlists[4],
        range(5), range(5)
    )
    while True:
        chunk = list(itertools.islice(product_iter, batch_size))
        if not chunk:
            break
        yield np.asarray(chunk, dtype=np.int16)


def merge_leaders(best_c, best_m, new_c, new_m, keep_n):
    if best_c is None:
        cc, mm = new_c, new_m
    else:
        cc = np.vstack([best_c, new_c])
        mm = np.vstack([best_m, new_m])
    order = rank_indices(mm)[:keep_n]
    return cc[order].copy(), mm[order].copy()


def stream_search(
    batches, banks, o,h,l,c,ons,cns, eval_start_ns,fwd_start_ns,pip,registry_limit,
    keep_n, deadline=None, progress_label="joint",
):
    best_c = None
    best_m = None
    processed = 0
    t0 = time.time()

    for bi, combo_batch in enumerate(batches, 1):
        if deadline is not None and time.time() >= deadline:
            print(f"      REDLINE deadline reached before batch {bi}; stopping safely.")
            return best_c, best_m, processed, False

        m = simulate_many(
            combo_batch,
            *banks[0], *banks[1], *banks[2], *banks[3], *banks[4],
            o,h,l,c,ons,cns,eval_start_ns,fwd_start_ns,pip,registry_limit
        )
        best_c, best_m = merge_leaders(best_c,best_m,combo_batch,m,keep_n)
        processed += len(combo_batch)

        if bi == 1 or bi % 10 == 0:
            elapsed = max(0.001, time.time()-t0)
            rate = processed/elapsed
            print(f"      {progress_label}: {processed:,} systems | {rate:,.0f}/sec", flush=True)

    return best_c, best_m, processed, True


def refine_cfgs(seed_df, radius, max_len):
    banks = {}
    for slot in SLOT_ORDER:
        seen = set()
        arr = []
        for _, row in seed_df.iterrows():
            fam = str(row[f"{slot}_family"])
            n = int(row[f"{slot}_length"])
            for ln in range(max(2,n-radius), min(max_len,n+radius)+1):
                key=(fam,ln)
                if key not in seen:
                    seen.add(key)
                    arr.append(RailCfg(fam,ln))
        b = BASELINE[slot]
        if b not in seen:
            arr.append(RailCfg(*b))
        banks[slot] = arr
    return banks


def refine_combo_batches(seed_df, cfgs, radius, max_len, batch_size):
    maps = {
        s: {(c.family,c.length): i for i,c in enumerate(cfgs[s])}
        for s in SLOT_ORDER
    }

    seen = set()
    pending = []

    for _, row in seed_df.iterrows():
        per_slot = []
        for slot in SLOT_ORDER:
            fam = str(row[f"{slot}_family"])
            n = int(row[f"{slot}_length"])
            vals = []
            for ln in range(max(2,n-radius), min(max_len,n+radius)+1):
                ix = maps[slot].get((fam,ln))
                if ix is not None:
                    vals.append(ix)
            per_slot.append(vals)

        g = ROLE_INDEX[str(row["guardian"])]
        tr = ROLE_INDEX[str(row["trigger"])]

        for p in itertools.product(*per_slot):
            tup = tuple(int(x) for x in p) + (g,tr)
            if tup in seen:
                continue
            seen.add(tup)
            pending.append(tup)
            if len(pending) >= batch_size:
                yield np.asarray(pending,dtype=np.int16)
                pending = []

    # Baseline is always preserved.
    base = tuple(cfg_index(cfgs[s],BASELINE[s]) for s in SLOT_ORDER) + (
        ROLE_INDEX[BASE_GUARDIAN], ROLE_INDEX[BASE_TRIGGER]
    )
    if base not in seen:
        pending.append(base)

    if pending:
        yield np.asarray(pending,dtype=np.int16)


def main() -> int:
    print("=" * 72, flush=True)
    print(f"TGIM SWEEPER BUILD: {BUILD_ID}", flush=True)
    print("ARCHITECTURE: FIVE-R REDLINE | R1/R2/R8/R9/R10 | SAME-R G+T ALLOWED", flush=True)
    print("=" * 72, flush=True)
    ap = argparse.ArgumentParser(
        description="TGIM Redline five-R joint rail-family/length + Guardian/Trigger optimizer."
    )
    ap.add_argument("--instrument", default="EUR_USD")
    ap.add_argument("--env", choices=["practice","live"], default=os.getenv("OANDA_ENV","practice"))
    ap.add_argument("--token", default=os.getenv("OANDA_TOKEN",""))

    ap.add_argument("--history-days", type=int, default=190)
    ap.add_argument("--eval-days", type=int, default=120)
    ap.add_argument("--forward-days", type=int, default=30)

    ap.add_argument("--lengths", default="3,5,8,13,21,27,34")
    ap.add_argument("--registry-limit", type=int, default=27, choices=[20,27])

    ap.add_argument("--expected-total", type=int, default=None)
    ap.add_argument("--expected-forward", type=int, default=None)
    ap.add_argument("--force-sweep", action="store_true",
                    help="Diagnostic only: bypass BASE certification.")

    ap.add_argument("--runtime-hours", type=float, default=9.5,
                    help="Maximum intended wall-clock envelope. Keep below Render's job ceiling.")
    ap.add_argument("--budget-safety", type=float, default=0.78,
                    help="Fraction of benchmarked capacity allowed for joint sweep.")
    ap.add_argument("--benchmark-systems", type=int, default=12000)
    ap.add_argument("--max-shortlist", type=int, default=14)
    ap.add_argument("--batch-size", type=int, default=25000)
    ap.add_argument("--top", type=int, default=150)

    ap.add_argument("--refine-top", type=int, default=10)
    ap.add_argument("--refine-radius", type=int, default=3)
    ap.add_argument("--max-refine-length", type=int, default=60)

    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--cache-dir", default="./tgim_sweeper_cache")
    ap.add_argument("--output-dir", default="./tgim_redline_results")
    args = ap.parse_args()

    job_start = time.time()
    hard_deadline = job_start + args.runtime_hours * 3600.0

    instrument = instrument_norm(args.instrument)
    lengths = tuple(sorted({int(x.strip()) for x in args.lengths.split(",") if x.strip()}))
    if args.registry_limit > MAX_REGISTRY_LIMIT:
        raise SystemExit(f"registry-limit must be <= {MAX_REGISTRY_LIMIT}")

    for slot,b in BASELINE.items():
        if b[1] not in lengths:
            raise SystemExit(
                f"Length bank must include baseline {slot} length {b[1]}. "
                f"Current --lengths={lengths}"
            )

    cache_dir = Path(args.cache_dir)
    result_dir = Path(args.output_dir) / instrument / datetime.now().strftime("%Y%m%d_%H%M%S")
    result_dir.mkdir(parents=True, exist_ok=True)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.history_days + 7)

    print(f"[1/10] Fetching/caching OANDA {instrument} W/D/M15/M5/M1 ...")
    client = OandaHistory(args.token,args.env,cache_dir)
    raw = {}
    for gran in ("W","D","M15","M5","M1"):
        print(f"       {gran} ...", flush=True)
        raw[gran] = client.candles(instrument,gran,start,end,refresh=args.refresh)

    daily = daily_execution_frame(raw["D"])
    if len(daily) < 40:
        raise SystemExit("Not enough complete Daily candles.")

    last_bar_open_ns = int(daily["bar_open_ns"].iloc[-1])
    eval_start_ns = last_bar_open_ns - args.eval_days * 86_400_000_000_000
    fwd_start_ns = last_bar_open_ns - args.forward_days * 86_400_000_000_000

    print(f"[2/10] Building {len(lengths)*len(FAMILIES)} rail candidates per R bay ...")
    cfgs = coarse_cfgs(lengths)
    banks = prepare_banks(raw,daily,cfgs)

    o = daily["open"].to_numpy(np.float64)
    h = daily["high"].to_numpy(np.float64)
    l = daily["low"].to_numpy(np.float64)
    c = daily["close"].to_numpy(np.float64)
    ons = daily["bar_open_ns"].to_numpy(np.int64)
    cns = daily["bar_close_ns"].to_numpy(np.int64)
    pip = pip_size(instrument)

    print("[3/10] BASE certification ...")
    bc = baseline_combo(cfgs)
    bm = simulate_many(
        bc,
        *banks[0],*banks[1],*banks[2],*banks[3],*banks[4],
        o,h,l,c,ons,cns,eval_start_ns,fwd_start_ns,pip,args.registry_limit
    )[0]
    base_metrics = metric_dict(bm)

    expected_total = args.expected_total
    if expected_total is None:
        expected_total = EXPECTED_TOTAL.get(instrument)

    expected_forward = args.expected_forward
    if expected_forward is None:
        expected_forward = EXPECTED_FORWARD.get(instrument)

    print("       BASE:", " | ".join(
        f"{s} {BASELINE[s][0]}{BASELINE[s][1]} RAW" for s in SLOT_ORDER
    ))
    print(f"       Guardian={BASE_GUARDIAN} | Trigger={BASE_TRIGGER} | "
          f"same-R={BASE_GUARDIAN==BASE_TRIGGER} | registry={args.registry_limit}")
    print(f"       120d closed/wins: {base_metrics['closed_120d']}/{base_metrics['wins_120d']}")
    print(f"       30d  closed/wins: {base_metrics['closed_30d']}/{base_metrics['wins_30d']}")
    print(f"       MAE: {base_metrics['max_mae_pips_120d']:.2f} pips"
          f" | longest: {base_metrics['longest_days_120d']:.2f}d"
          f" | avg: {base_metrics['avg_hold_days_120d']:.2f}d"
          f" | net: {base_metrics['net_pips_120d']:.1f} pips")

    certified = True
    if expected_total is not None:
        certified = certified and (
            base_metrics["closed_120d"] == expected_total and
            base_metrics["wins_120d"] == expected_total
        )
    if expected_forward is not None:
        certified = certified and (
            base_metrics["closed_30d"] == expected_forward and
            base_metrics["wins_30d"] == expected_forward
        )

    cert = {
        "instrument": instrument,
        "baseline": {
            **{s: {"tf":SLOT_TF[s],"family":BASELINE[s][0],"length":BASELINE[s][1],"working":"RAW"}
               for s in SLOT_ORDER},
            "guardian": BASE_GUARDIAN,
            "trigger": BASE_TRIGGER,
            "registry_limit": args.registry_limit,
        },
        "expected_total": expected_total,
        "expected_forward": expected_forward,
        "metrics": base_metrics,
        "certified": bool(certified),
        "execution_model": "TradingView default 4 historical ticks/bar approximation",
    }
    (result_dir/"BASE_CERTIFICATION.json").write_text(json.dumps(cert,indent=2))

    if not certified and not args.force_sweep:
        print("\nBASE MISMATCH — REDLINE SWEEP ABORTED.")
        print("The optimizer will not search millions of systems until the production control reproduces.")
        print(f"Certification file: {result_dir/'BASE_CERTIFICATION.json'}")
        return 2

    print("[4/10] Prescreening every bay candidate across all 25 Guardian/Trigger role pairs ...")
    pc, meta = prescreen_combos(cfgs)
    pm = simulate_many(
        pc,
        *banks[0],*banks[1],*banks[2],*banks[3],*banks[4],
        o,h,l,c,ons,cns,eval_start_ns,fwd_start_ns,pip,args.registry_limit
    )

    # Persist a compact prescreen summary.
    pres_rows = []
    block = 25
    cursor = 0
    for si,slot in enumerate(SLOT_ORDER):
        for cand,cfg in enumerate(cfgs[slot]):
            m = pm[cursor:cursor+block]
            oi = rank_indices(m)[0]
            row = {
                "slot":slot, "candidate":cfg.label()+" RAW",
                "family":cfg.family, "length":cfg.length,
                "best_guardian":SLOT_ORDER[int(pc[cursor+oi,5])],
                "best_trigger":SLOT_ORDER[int(pc[cursor+oi,6])],
            }
            row.update(metric_dict(m[oi]))
            pres_rows.append(row)
            cursor += block
    pd.DataFrame(pres_rows).to_csv(result_dir/"PRESCREEN.csv",index=False)

    print("[5/10] Benchmarking this Render machine ...")
    bench = random_benchmark_combos(cfgs,args.benchmark_systems)
    t0 = time.time()
    _ = simulate_many(
        bench,
        *banks[0],*banks[1],*banks[2],*banks[3],*banks[4],
        o,h,l,c,ons,cns,eval_start_ns,fwd_start_ns,pip,args.registry_limit
    )
    bench_elapsed = max(0.001,time.time()-t0)
    rate = len(bench)/bench_elapsed

    remaining = max(60.0, hard_deadline - time.time())
    k, safe_systems, planned_systems = choose_redline_k(
        rate, remaining, args.budget_safety, args.max_shortlist
    )

    print(f"       Benchmark: {len(bench):,} systems in {bench_elapsed:.2f}s = {rate:,.0f}/sec")
    print(f"       Remaining envelope: {remaining/3600:.2f}h")
    print(f"       Safe compute budget: ~{safe_systems:,} systems")
    print(f"       REDLINE shortlist: K={k} per R bay")
    print(f"       Full joint search: {planned_systems:,} complete systems")

    print("[6/10] Building diversity-protected shortlists ...")
    shortlists = []
    short_rows = []
    for si,slot in enumerate(SLOT_ORDER):
        sl = diversity_shortlist(si,cfgs,pm,k)
        shortlists.append(sl)
        print(f"       {slot}: " + ", ".join(cfgs[slot][x].label() for x in sl))
        for rank_ix,x in enumerate(sl,1):
            short_rows.append({
                "slot":slot,"shortlist_rank":rank_ix,
                "family":cfgs[slot][x].family,
                "length":cfgs[slot][x].length,
                "config":cfgs[slot][x].label()+" RAW"
            })
    pd.DataFrame(short_rows).to_csv(result_dir/"REDLINE_SHORTLISTS.csv",index=False)

    print("[7/10] Running full five-R × Guardian × Trigger REDLINE joint search ...")
    joint_batches = iter_joint_batches(shortlists,args.batch_size)
    jc,jm,processed,complete = stream_search(
        joint_batches,banks,o,h,l,c,ons,cns,eval_start_ns,fwd_start_ns,pip,args.registry_limit,
        keep_n=args.top,deadline=hard_deadline,progress_label="REDLINE"
    )
    if jc is None:
        raise SystemExit("Joint search produced no results.")

    top = build_top_rows(jc,jm,cfgs,args.top)
    top.to_csv(result_dir/"TOP_REDLINE_JOINT.csv",index=False)

    print(f"       Joint processed: {processed:,}/{planned_systems:,} | complete={complete}")
    print("[8/10] Joint leaders ...")
    show_cols = [
        "rank","R1_config","R2_config","R8_config","R9_config","R10_config",
        "guardian","trigger","same_guard_trigger",
        "closed_30d","wins_30d","closed_120d","wins_120d",
        "net_pips_120d","max_mae_pips_120d","longest_days_120d"
    ]
    print(top[show_cols].head(15).to_string(index=False))

    final = top
    if args.refine_top > 0 and time.time() < hard_deadline - 120:
        print(f"[9/10] Exact-length local refinement around top {args.refine_top} systems ...")
        seeds = top.head(args.refine_top)
        rcfg = refine_cfgs(seeds,args.refine_radius,args.max_refine_length)
        rbanks = prepare_banks(raw,daily,rcfg)
        rbatches = refine_combo_batches(
            seeds,rcfg,args.refine_radius,args.max_refine_length,args.batch_size
        )
        rc,rm,rprocessed,rcomplete = stream_search(
            rbatches,rbanks,o,h,l,c,ons,cns,eval_start_ns,fwd_start_ns,pip,args.registry_limit,
            keep_n=args.top,deadline=hard_deadline,progress_label="REFINE"
        )
        if rc is not None:
            refined = build_top_rows(rc,rm,rcfg,args.top)
            refined.to_csv(result_dir/"TOP_REDLINE_REFINED.csv",index=False)
            final = refined
            print(f"       Refined processed: {rprocessed:,} | complete={rcomplete}")
    else:
        print("[9/10] Refinement skipped — runtime reserve protected.")

    print("[10/10] TradingView promotion package ...")
    final.to_csv(result_dir/"TOP_FOR_TRADINGVIEW_VERIFICATION.csv",index=False)

    promo = []
    for _,row in final.head(25).iterrows():
        item = {
            "rank":int(row["rank"]),
            "guardian":str(row["guardian"]),
            "trigger":str(row["trigger"]),
            "same_guard_trigger":bool(row["same_guard_trigger"]),
            "registry_limit":args.registry_limit,
        }
        for slot in SLOT_ORDER:
            item[slot] = {
                "tf":SLOT_TF[slot],
                "family":str(row[f"{slot}_family"]),
                "length":int(row[f"{slot}_length"]),
                "working":"RAW",
            }
        for key in (
            "closed_30d","wins_30d","closed_120d","wins_120d",
            "net_pips_30d","net_pips_120d","max_mae_pips_120d",
            "longest_days_120d","avg_hold_days_120d","open_or_pending_end"
        ):
            val=row[key]
            item[key]=int(val) if key.startswith(("closed","wins","open")) else float(val)
        promo.append(item)
    (result_dir/"TOP25_PROMOTION.json").write_text(json.dumps(promo,indent=2))

    run_manifest = {
        "instrument":instrument,
        "registry_limit":args.registry_limit,
        "length_bank":lengths,
        "benchmark_systems":args.benchmark_systems,
        "benchmark_rate_per_sec":rate,
        "runtime_hours":args.runtime_hours,
        "budget_safety":args.budget_safety,
        "selected_k":k,
        "planned_joint_systems":planned_systems,
        "processed_joint_systems":processed,
        "joint_complete":complete,
        "result_dir":str(result_dir),
    }
    (result_dir/"RUN_MANIFEST.json").write_text(json.dumps(run_manifest,indent=2))

    print("\nFINAL TOP 15")
    print(final[show_cols].head(15).to_string(index=False))
    print(f"\nResults: {result_dir}")
    print("Python ranks candidates; promote only after exact TradingView verification.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
