#!/usr/bin/env python3
"""
TGIM Joint 4-Rail Sweeper v1
============================

Purpose
-------
Search the FOUR-RAIL ORGANISM, not one rail at a time.

Fixed timeframe bays:
    R2  = 1D
    R8  = 15m
    R9  = 5m
    R10 = 1m

RAW only. ADX/DI gates OFF during this search.

Each bay varies:
    Rail family: EMA / HMA / KS / WMA
    Length:      5 / 8 / 13 / 21 / 27 / 34

Coarse Cartesian search:
    24 x 24 x 24 x 24 = 331,776 complete four-rail systems.

Current production control:
    R2  = EMA 5 RAW
    R8  = HMA 27 RAW
    R9  = KS 27 RAW
    R10 = KS 27 RAW

The search is BASELINE-GATED. By default the script refuses to rank candidates
when its production-control result does not match the expected TradingView total
trade count for the selected 50SET pair.

Historical engine ported for this RAW / One-Leg-Only research phase:
- OANDA candle data
- TradingView/OANDA Daily chart as the execution clock
- source-timeframe HMA/WMA/KS(ta.linreg)/EMA rail math
- raw rail/inverse turn detection
- global 27-turn R registry
- clutter averaging OFF
- Any Route R previous-opposite target
- R2 Trigger direction + R8 Guardian direction
- one open trade at a time
- new-ray entries only
- entry fills next Daily bar open
- target exits when Daily realClose reaches/crosses the stored target
- no Guardian exit while a trade is open
- one-leg-only cooldown after target payment
- normalized pips / MAE / duration metrics

This is a research accelerator. TradingView remains the final verifier.
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

try:
    from numba import njit, prange
except Exception as exc:
    raise SystemExit(
        "numba is required. Install requirements.txt first. "
        f"Import error: {exc}"
    )

FAMILIES = ("EMA", "HMA", "KS", "WMA")
DEFAULT_LENGTHS = (5, 8, 13, 21, 27, 34)

BASELINE = {
    "R2": ("EMA", 5),
    "R8": ("HMA", 27),
    "R9": ("KS", 27),
    "R10": ("KS", 27),
}
SLOT_TF = {"R2": "D", "R8": "M15", "R9": "M5", "R10": "M1"}
SLOT_ORDER = ("R2", "R8", "R9", "R10")

# Current 50SET screenshots supplied by the user.
EXPECTED_TOTAL = {
    "EUR_USD": 25,
    "USD_CAD": 30,
    "EUR_CAD": 22,
    "USD_DKK": 27,
}

REGISTRY_LIMIT = 27


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
                r.raise_for_status()
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
        sec_map = {"M1": 60, "M5": 300, "M15": 900, "D": 86400}
        step_sec = sec_map[granularity]

        while cursor < end:
            params = {
                "price": "M",
                "granularity": granularity,
                "from": cursor.isoformat().replace("+00:00", "Z"),
                "count": 5000,
                "includeFirst": "true",
                "smooth": "false",
                "dailyAlignment": 17,
                "alignmentTimezone": "America/New_York",
            }
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
            if len(candles) < 5000 and last_time.to_pydatetime() >= end - timedelta(seconds=step_sec):
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

    sec_map = {"M1": 60, "M5": 300, "M15": 900}
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
# Joint simulator — RAW / Any Route R / One Leg Only
# ─────────────────────────────────────────────────────────────────────────────

@njit(cache=True)
def _find_target(reg_price, reg_type, reg_bar, reg_count, wanted_type, current_event_bar):
    for k in range(reg_count - 1, -1, -1):
        if reg_bar[k] < current_event_bar and reg_type[k] == wanted_type:
            return reg_price[k]
    return np.nan


@njit(cache=True)
def _push_turn(reg_price, reg_type, reg_bar, reg_count, price, typ, event_bar):
    if reg_count < REGISTRY_LIMIT:
        reg_price[reg_count] = price
        reg_type[reg_count] = typ
        reg_bar[reg_count] = event_bar
        return reg_count + 1

    # Pine shifts the oldest after pushing beyond limit: preserve latest 27.
    for k in range(REGISTRY_LIMIT - 1):
        reg_price[k] = reg_price[k + 1]
        reg_type[k] = reg_type[k + 1]
        reg_bar[k] = reg_bar[k + 1]
    reg_price[REGISTRY_LIMIT - 1] = price
    reg_type[REGISTRY_LIMIT - 1] = typ
    reg_bar[REGISTRY_LIMIT - 1] = event_bar
    return REGISTRY_LIMIT


@njit(cache=True)
def _simulate_one(
    c0, c1, c2, c3,
    e0, p0, d0,
    e1, p1, d1,
    e2, p2, d2,
    e3, p3, d3,
    o, h, l, c,
    open_ns, close_ns,
    eval_start_ns, fwd_start_ns,
    pip,
):
    nd = len(c)

    reg_price = np.empty(REGISTRY_LIMIT, dtype=np.float64)
    reg_type = np.empty(REGISTRY_LIMIT, dtype=np.int8)
    reg_bar = np.empty(REGISTRY_LIMIT, dtype=np.int32)
    reg_count = 0

    position = 0
    entry_price = 0.0
    target = np.nan
    entry_day = -1
    entry_time_ns = 0
    mae_pips = 0.0

    pending_dir = 0
    pending_target = np.nan
    pending_signal_day = -1

    guard_meaningful = 0

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

    for t in range(nd):
        # Current raw directions.
        trigger_dir = int(d0[c0, t])
        g_now = int(d1[c1, t])
        if g_now != 0:
            guard_meaningful = g_now
        guardian_dir = guard_meaningful

        # Orders submitted on previous Daily close fill this Daily open.
        if pending_dir != 0 and t > pending_signal_day and position == 0:
            position = pending_dir
            entry_price = o[t]
            target = pending_target
            entry_day = t
            entry_time_ns = open_ns[t]
            mae_pips = 0.0
            if open_ns[t] >= eval_start_ns:
                entries_total += 1
            if open_ns[t] >= fwd_start_ns:
                entries_fwd += 1
            pending_dir = 0
            pending_target = np.nan
            pending_signal_day = -1

        # Store every new raw R turn BEFORE target selection, same source order as Pine.
        event_types = np.empty(4, dtype=np.int8)
        event_prices = np.empty(4, dtype=np.float64)
        event_count = 0

        typ = int(e0[c0, t])
        if typ != 0:
            pr = p0[c0, t]
            reg_count = _push_turn(reg_price, reg_type, reg_bar, reg_count, pr, typ, t - 1)
            event_types[event_count] = typ
            event_prices[event_count] = pr
            event_count += 1

        typ = int(e1[c1, t])
        if typ != 0:
            pr = p1[c1, t]
            reg_count = _push_turn(reg_price, reg_type, reg_bar, reg_count, pr, typ, t - 1)
            event_types[event_count] = typ
            event_prices[event_count] = pr
            event_count += 1

        typ = int(e2[c2, t])
        if typ != 0:
            pr = p2[c2, t]
            reg_count = _push_turn(reg_price, reg_type, reg_bar, reg_count, pr, typ, t - 1)
            event_types[event_count] = typ
            event_prices[event_count] = pr
            event_count += 1

        typ = int(e3[c3, t])
        if typ != 0:
            pr = p3[c3, t]
            reg_count = _push_turn(reg_price, reg_type, reg_bar, reg_count, pr, typ, t - 1)
            event_types[event_count] = typ
            event_prices[event_count] = pr
            event_count += 1

        # Open-trade MAE + target market close.
        exited_today = False
        if position != 0:
            adverse = (entry_price - l[t]) / pip if position == 1 else (h[t] - entry_price) / pip
            if adverse > mae_pips:
                mae_pips = adverse

            reached = (c[t] >= target) if position == 1 else (c[t] <= target)
            if reached:
                exit_price = c[t]
                pnl_pips = ((exit_price - entry_price) / pip) if position == 1 else ((entry_price - exit_price) / pip)
                hold_days = (close_ns[t] - entry_time_ns) / 86_400_000_000_000.0

                if close_ns[t] >= eval_start_ns:
                    closed_total += 1
                    if pnl_pips > 0:
                        wins_total += 1
                    net_total += pnl_pips
                    if mae_pips > max_mae_total:
                        max_mae_total = mae_pips
                    if hold_days > longest_total:
                        longest_total = hold_days
                    hold_sum_total += hold_days

                if close_ns[t] >= fwd_start_ns:
                    closed_fwd += 1
                    if pnl_pips > 0:
                        wins_fwd += 1
                    net_fwd += pnl_pips

                position = 0
                entry_price = 0.0
                target = np.nan
                entry_day = -1
                entry_time_ns = 0
                mae_pips = 0.0
                exited_today = True

        # One Leg Only: no same-Daily-bar re-entry after payment.
        if close_ns[t] < eval_start_ns:
            continue
        if position != 0 or pending_dir != 0 or exited_today:
            continue

        # New finalized R rays. Process in R2,R8,R9,R10 storage order.
        # Candidate direction is ray type: valley=long(+1), peak=short(-1).
        for ei in range(event_count):
            et = int(event_types[ei])
            candidate_dir = 1 if et == 1 else -1

            # RAW qualification:
            # selected Guardian must agree/intact; selected Trigger must agree.
            if candidate_dir != guardian_dir or candidate_dir != trigger_dir:
                continue

            tgt = _find_target(
                reg_price, reg_type, reg_bar, reg_count,
                -et, t - 1
            )
            if not np.isfinite(tgt):
                continue

            target_valid = (tgt > c[t]) if candidate_dir == 1 else (tgt < c[t])
            if not target_valid:
                continue

            pending_dir = candidate_dir
            pending_target = tgt
            pending_signal_day = t
            break

    open_end = 1 if (position != 0 or pending_dir != 0) else 0
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
    o, h, l, c,
    open_ns, close_ns,
    eval_start_ns, fwd_start_ns,
    pip,
):
    n = combos.shape[0]
    out = np.empty((n, 13), dtype=np.float64)
    for i in prange(n):
        out[i] = _simulate_one(
            combos[i,0], combos[i,1], combos[i,2], combos[i,3],
            e0,p0,d0,e1,p1,d1,e2,p2,d2,e3,p3,d3,
            o,h,l,c,open_ns,close_ns,eval_start_ns,fwd_start_ns,pip
        )
    return out


def coarse_cfgs(lengths: Tuple[int, ...]) -> Dict[str, List[RailCfg]]:
    c = [RailCfg(f, n) for f in FAMILIES for n in lengths]
    return {slot: list(c) for slot in SLOT_ORDER}


def cfg_index(cfgs: List[RailCfg], wanted: Tuple[str,int]) -> int:
    for i, c in enumerate(cfgs):
        if c.family == wanted[0] and c.length == wanted[1]:
            return i
    raise ValueError(f"Baseline {wanted} not found in candidate bank")


def cartesian_indices(cfgs: Dict[str, List[RailCfg]]) -> np.ndarray:
    dims = [range(len(cfgs[s])) for s in SLOT_ORDER]
    return np.asarray(list(itertools.product(*dims)), dtype=np.int16)


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


def rank_indices(metrics: np.ndarray) -> np.ndarray:
    closed = metrics[:,1]
    wins = metrics[:,2]
    fclosed = metrics[:,8]
    fwins = metrics[:,9]
    wr = np.where(closed > 0, wins / np.maximum(closed,1) * 100.0, 0.0)
    fwr = np.where(fclosed > 0, fwins / np.maximum(fclosed,1) * 100.0, 0.0)

    quality = np.zeros(len(metrics), dtype=np.int16)
    quality[(wr >= 90.0) & (fwr >= 90.0)] = 1
    quality[(wr >= 95.0) & (fwr >= 95.0)] = 2
    quality[(wr >= 99.999) & (fwr >= 99.999)] = 3

    # lexsort: last key is primary. Negative = descending.
    order = np.lexsort((
        metrics[:,5],                  # lower longest
        metrics[:,4],                  # lower MAE
        -metrics[:,3],                 # total pips
        -metrics[:,10],                # 30d pips
        metrics[:,11],                 # prefer no open/pending end
        -closed,                       # total closed
        -fclosed,                      # 30d closed
        -quality,                      # accuracy tier
    ))
    return order


def build_top_rows(
    combos: np.ndarray,
    metrics: np.ndarray,
    cfgs: Dict[str, List[RailCfg]],
    top_n: int,
) -> pd.DataFrame:
    order = rank_indices(metrics)[:top_n]
    rows = []
    for rank, ix in enumerate(order, 1):
        combo = combos[ix]
        m = metric_dict(metrics[ix])
        row = {"rank": rank}
        for si, slot in enumerate(SLOT_ORDER):
            cfg = cfgs[slot][int(combo[si])]
            row[f"{slot}_family"] = cfg.family
            row[f"{slot}_length"] = cfg.length
            row[f"{slot}_config"] = cfg.label() + " RAW"
        row.update(m)
        rows.append(row)
    return pd.DataFrame(rows)


def local_refine(
    seed_df: pd.DataFrame,
    radius: int,
    max_len: int,
) -> Dict[str, List[RailCfg]]:
    banks = {}
    for slot in SLOT_ORDER:
        seen = set()
        arr = []
        for _, row in seed_df.iterrows():
            fam = str(row[f"{slot}_family"])
            n = int(row[f"{slot}_length"])
            for ln in range(max(2, n-radius), min(max_len, n+radius)+1):
                key=(fam,ln)
                if key not in seen:
                    seen.add(key)
                    arr.append(RailCfg(fam,ln))
        # Always preserve baseline candidate in bank.
        b = BASELINE[slot]
        key=(b[0],b[1])
        if key not in seen:
            arr.append(RailCfg(*b))
        banks[slot]=arr
    return banks


def local_combo_union(
    seed_df: pd.DataFrame,
    cfgs: Dict[str,List[RailCfg]],
    radius: int,
    max_len: int,
) -> np.ndarray:
    maps = {
        s: {(c.family,c.length): i for i,c in enumerate(cfgs[s])}
        for s in SLOT_ORDER
    }
    combos = set()
    for _, row in seed_df.iterrows():
        per_slot=[]
        for slot in SLOT_ORDER:
            fam=str(row[f"{slot}_family"])
            n=int(row[f"{slot}_length"])
            vals=[]
            for ln in range(max(2,n-radius),min(max_len,n+radius)+1):
                ix=maps[slot].get((fam,ln))
                if ix is not None:
                    vals.append(ix)
            per_slot.append(vals)
        for tup in itertools.product(*per_slot):
            combos.add(tuple(int(x) for x in tup))
    # Baseline too.
    combos.add(tuple(cfg_index(cfgs[s], BASELINE[s]) for s in SLOT_ORDER))
    return np.asarray(sorted(combos),dtype=np.int16)


def prepare_banks(
    raw: Dict[str,pd.DataFrame],
    daily: pd.DataFrame,
    cfgs: Dict[str,List[RailCfg]],
):
    out=[]
    for slot in SLOT_ORDER:
        gran=SLOT_TF[slot]
        evt, price, direction = candidate_daily_arrays(raw[gran], daily, gran, cfgs[slot])
        out.append((evt,price,direction))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="TGIM joint R2/R8/R9/R10 rail-family + length sweeper."
    )
    ap.add_argument("--instrument", default="EUR_USD")
    ap.add_argument("--env", choices=["practice","live"],
                    default=os.getenv("OANDA_ENV","practice"))
    ap.add_argument("--token", default=os.getenv("OANDA_TOKEN",""))
    ap.add_argument("--history-days", type=int, default=180,
                    help="OANDA history to fetch. 180 gives 120d evaluation plus registry warmup.")
    ap.add_argument("--eval-days", type=int, default=120)
    ap.add_argument("--forward-days", type=int, default=30)
    ap.add_argument("--lengths", default="5,8,13,21,27,34")
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--refine-top", type=int, default=12,
                    help="0 disables local exact-length refinement.")
    ap.add_argument("--refine-radius", type=int, default=4)
    ap.add_argument("--max-refine-length", type=int, default=60)
    ap.add_argument("--expected-total", type=int, default=None)
    ap.add_argument("--force-sweep", action="store_true",
                    help="Rank even when BASE does not certify. Use only diagnostically.")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--cache-dir", default="./tgim_sweeper_cache")
    ap.add_argument("--output-dir", default="./tgim_sweeper_results")
    args = ap.parse_args()

    instrument=instrument_norm(args.instrument)
    lengths=tuple(sorted({int(x.strip()) for x in args.lengths.split(",") if x.strip()}))
    for slot,b in BASELINE.items():
        if b[1] not in lengths:
            raise SystemExit(
                f"Length bank must include baseline {slot} length {b[1]}. "
                f"Current --lengths={lengths}"
            )

    cache_dir=Path(args.cache_dir)
    result_dir=Path(args.output_dir) / instrument / datetime.now().strftime("%Y%m%d_%H%M%S")
    result_dir.mkdir(parents=True,exist_ok=True)

    end=datetime.now(timezone.utc)+timedelta(days=2)
    start=end-timedelta(days=args.history_days+5)

    print(f"[1/7] Fetching/caching OANDA {instrument} D/M15/M5/M1 ...")
    client=OandaHistory(args.token,args.env,cache_dir)
    raw={}
    for gran in ("D","M15","M5","M1"):
        print(f"      {gran} ...",flush=True)
        raw[gran]=client.candles(instrument,gran,start,end,refresh=args.refresh)

    daily=daily_execution_frame(raw["D"])
    if len(daily)<40:
        raise SystemExit("Not enough complete Daily candles.")

    last_bar_open_ns=int(daily["bar_open_ns"].iloc[-1])
    eval_start_ns=last_bar_open_ns-args.eval_days*86_400_000_000_000
    fwd_start_ns=last_bar_open_ns-args.forward_days*86_400_000_000_000

    print(f"[2/7] Building {len(lengths)*len(FAMILIES)} candidates per R bay ...")
    cfgs=coarse_cfgs(lengths)
    banks=prepare_banks(raw,daily,cfgs)

    base_combo=np.asarray([[
        cfg_index(cfgs[s],BASELINE[s]) for s in SLOT_ORDER
    ]],dtype=np.int16)

    o=daily["open"].to_numpy(np.float64)
    h=daily["high"].to_numpy(np.float64)
    l=daily["low"].to_numpy(np.float64)
    c=daily["close"].to_numpy(np.float64)
    ons=daily["bar_open_ns"].to_numpy(np.int64)
    cns=daily["bar_close_ns"].to_numpy(np.int64)
    pip=pip_size(instrument)

    print("[3/7] BASE certification ...")
    bm=simulate_many(
        base_combo,
        *banks[0],*banks[1],*banks[2],*banks[3],
        o,h,l,c,ons,cns,eval_start_ns,fwd_start_ns,pip
    )[0]
    base_metrics=metric_dict(bm)
    expected=args.expected_total
    if expected is None:
        expected=EXPECTED_TOTAL.get(instrument)

    print("      BASE:",
          " | ".join(f"{s} {BASELINE[s][0]}{BASELINE[s][1]} RAW" for s in SLOT_ORDER))
    print(f"      120d closed/wins: {base_metrics['closed_120d']}/{base_metrics['wins_120d']}")
    print(f"      30d  closed/wins: {base_metrics['closed_30d']}/{base_metrics['wins_30d']}")
    print(f"      MAE: {base_metrics['max_mae_pips_120d']:.2f} pips"
          f" | longest: {base_metrics['longest_days_120d']:.2f}d"
          f" | net: {base_metrics['net_pips_120d']:.1f} pips")

    certified = (
        expected is None or
        (base_metrics["closed_120d"] == expected and
         base_metrics["wins_120d"] == expected)
    )
    cert = {
        "instrument":instrument,
        "expected_total_closed":expected,
        "baseline":{s:{"family":BASELINE[s][0],"length":BASELINE[s][1],"working":"RAW"}
                    for s in SLOT_ORDER},
        "metrics":base_metrics,
        "certified":bool(certified),
        "note":"TradingView remains final verifier. Exact OANDA-vs-TradingView candle alignment can expose a residual mismatch."
    }
    (result_dir/"BASE_CERTIFICATION.json").write_text(json.dumps(cert,indent=2))

    if not certified and not args.force_sweep:
        print("\nBASE MISMATCH — SWEEP ABORTED.")
        print(f"TradingView reference for {instrument}: {expected} closed wins; "
              f"Python got {base_metrics['closed_120d']}.")
        print("The engine is doing its job: it will not optimize a mismatched model.")
        print(f"Send BASE_CERTIFICATION.json back for parity diagnosis: {result_dir}")
        return 2

    print("[4/7] Creating full joint Cartesian grid ...")
    combos=cartesian_indices(cfgs)
    print(f"      {len(combos):,} complete four-rail systems.")

    print("[5/7] Running coarse joint sweep (Numba parallel) ...")
    t0=time.time()
    metrics=simulate_many(
        combos,
        *banks[0],*banks[1],*banks[2],*banks[3],
        o,h,l,c,ons,cns,eval_start_ns,fwd_start_ns,pip
    )
    print(f"      done in {time.time()-t0:.1f}s")

    top=build_top_rows(combos,metrics,cfgs,args.top)
    top.to_csv(result_dir/"TOP_COARSE.csv",index=False)
    np.savez_compressed(result_dir/"COARSE_METRICS.npz",combos=combos,metrics=metrics)

    final_top=top.copy()
    if args.refine_top>0:
        print(f"[6/7] Local exact-length refinement around top {args.refine_top} coarse systems ...")
        seeds=top.head(args.refine_top)
        rcfg=local_refine(seeds,args.refine_radius,args.max_refine_length)
        rbanks=prepare_banks(raw,daily,rcfg)
        rcombos=local_combo_union(seeds,rcfg,args.refine_radius,args.max_refine_length)
        print(f"      {len(rcombos):,} local joint systems.")
        rm=simulate_many(
            rcombos,
            *rbanks[0],*rbanks[1],*rbanks[2],*rbanks[3],
            o,h,l,c,ons,cns,eval_start_ns,fwd_start_ns,pip
        )
        rtop=build_top_rows(rcombos,rm,rcfg,args.top)
        rtop.to_csv(result_dir/"TOP_REFINED.csv",index=False)
        np.savez_compressed(result_dir/"REFINED_METRICS.npz",combos=rcombos,metrics=rm)
        final_top=rtop

    print("[7/7] Writing promotion package ...")
    final_top.to_csv(result_dir/"TOP_FOR_TRADINGVIEW_VERIFICATION.csv",index=False)
    winner_json=[]
    for _,row in final_top.head(20).iterrows():
        winner_json.append({
            "rank":int(row["rank"]),
            "R2":{"tf":"1D","family":row["R2_family"],"length":int(row["R2_length"]),"working":"RAW","role":"TRIGGER"},
            "R8":{"tf":"15m","family":row["R8_family"],"length":int(row["R8_length"]),"working":"RAW","role":"GUARD"},
            "R9":{"tf":"5m","family":row["R9_family"],"length":int(row["R9_length"]),"working":"RAW","role":"ROUTE"},
            "R10":{"tf":"1m","family":row["R10_family"],"length":int(row["R10_length"]),"working":"RAW","role":"ROUTE"},
            "closed_30d":int(row["closed_30d"]),
            "wins_30d":int(row["wins_30d"]),
            "closed_120d":int(row["closed_120d"]),
            "wins_120d":int(row["wins_120d"]),
            "net_pips_30d":float(row["net_pips_30d"]),
            "net_pips_120d":float(row["net_pips_120d"]),
            "max_mae_pips_120d":float(row["max_mae_pips_120d"]),
            "longest_days_120d":float(row["longest_days_120d"]),
            "open_or_pending_end":int(row["open_or_pending_end"]),
        })
    (result_dir/"TOP20_PROMOTION.json").write_text(json.dumps(winner_json,indent=2))

    print("\nTOP 10")
    cols=[
        "rank","R2_config","R8_config","R9_config","R10_config",
        "closed_30d","wins_30d","closed_120d","wins_120d",
        "max_mae_pips_120d","longest_days_120d","net_pips_120d"
    ]
    print(final_top[cols].head(10).to_string(index=False))
    print(f"\nResults: {result_dir}")
    print("Next step: verify TOP20_PROMOTION.json candidates in the actual Pine strategy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
