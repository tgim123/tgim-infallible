#!/usr/bin/env python3
"""
TGIM REDLINE 5-R SWEEPER v2.4 — EXACT CONTROL PARITY
=============================================

BUILD ID: REDLINE-5R-V2.4-20260826-D

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
Parity v2.2 corrections:
    - same-R target lookup filters by source R
    - same source + origin bar updates the existing turn, matching Pine
    - Daily R2 rail/event state is recalculated on each synthetic O/H/L/C execution
    - Guardian current meaningful direction is separate from source-close committed direction
    - baseline trade ledger is emitted before optimization

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

BUILD_ID = "REDLINE-5R-V2.4-20260826-D"

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



def sample_source_to_daily_with_index(source, rail, daily, granularity):
    """Return request.security-style Daily snapshots plus selected source-row index."""
    n = len(daily)
    cur = np.full(n, np.nan, dtype=np.float64)
    inv = np.full(n, np.nan, dtype=np.float64)
    idx = np.full(n, -1, dtype=np.int32)

    src = source.sort_values("time").reset_index(drop=True)
    src_time = pd.to_datetime(src["time"], utc=True)
    complete = src["complete"].astype(bool).to_numpy()

    if granularity == "D":
        time_to_idx = {int(t.value): i for i, t in enumerate(src_time)}
        for j in range(n):
            k = time_to_idx.get(int(pd.Timestamp(daily.loc[j, "time"]).value), -1)
            if k >= 0:
                idx[j] = k
                cur[j] = rail[k]
                if k > 0:
                    inv[j] = rail[k - 1]
        return cur, inv, idx

    src_start = src_time.astype("int64").to_numpy()

    if granularity == "W":
        # OANDA weekly timestamps already respect requested alignment.  A completed
        # weekly source value becomes available at the next weekly timestamp.
        next_start = np.full(len(src_start), np.iinfo(np.int64).max, dtype=np.int64)
        if len(src_start) > 1:
            next_start[:-1] = src_start[1:]
        valid_idx = np.flatnonzero(complete & (next_start != np.iinfo(np.int64).max))
        valid_close = next_start[valid_idx]
        for j in range(n):
            boundary = int(daily.loc[j, "bar_close_ns"])
            pos = np.searchsorted(valid_close, boundary, side="right") - 1
            if pos >= 0:
                k = int(valid_idx[pos])
                idx[j] = k
                cur[j] = rail[k]
                if k > 0:
                    inv[j] = rail[k - 1]
        return cur, inv, idx

    sec_map = {"M1": 60, "M5": 300, "M15": 900}
    dur_ns = sec_map[granularity] * 1_000_000_000
    valid_idx = np.flatnonzero(complete)
    valid_close = src_start[valid_idx] + dur_ns
    for j in range(n):
        boundary = int(daily.loc[j, "bar_close_ns"])
        pos = np.searchsorted(valid_close, boundary, side="right") - 1
        if pos >= 0:
            k = int(valid_idx[pos])
            idx[j] = k
            cur[j] = rail[k]
            if k > 0:
                inv[j] = rail[k - 1]
    return cur, inv, idx


def _daily_tick_matrix(daily):
    o = daily["open"].to_numpy(np.float64)
    h = daily["high"].to_numpy(np.float64)
    l = daily["low"].to_numpy(np.float64)
    c = daily["close"].to_numpy(np.float64)
    out = np.empty((len(daily), 4), dtype=np.float64)
    for t in range(len(daily)):
        out[t, 0] = o[t]
        if abs(o[t] - h[t]) <= abs(o[t] - l[t]):
            out[t, 1], out[t, 2] = h[t], l[t]
        else:
            out[t, 1], out[t, 2] = l[t], h[t]
        out[t, 3] = c[t]
    return out


def _wma_last_override(close, t, px, n):
    if n <= 0 or t < n - 1:
        return np.nan
    vals = np.empty(n, dtype=np.float64)
    if n > 1:
        vals[:-1] = close[t - n + 1:t]
    vals[-1] = px
    if not np.all(np.isfinite(vals)):
        return np.nan
    w = np.arange(1.0, n + 1.0, dtype=np.float64)
    return float(np.dot(vals, w) / w.sum())


def _linreg_last_override(close, t, px, n):
    if n <= 1:
        return float(px)
    if t < n - 1:
        return np.nan
    y = np.empty(n, dtype=np.float64)
    if n > 1:
        y[:-1] = close[t - n + 1:t]
    y[-1] = px
    if not np.all(np.isfinite(y)):
        return np.nan
    xs = np.arange(n, dtype=np.float64)
    sx = xs.sum(); sxx = np.dot(xs, xs); den = n * sxx - sx * sx
    sy = y.sum(); sxy = np.dot(xs, y)
    slope = (n * sxy - sx * sy) / den
    intercept = (sy - slope * sx) / n
    return float(intercept + slope * (n - 1))


def _daily_tick_rail_value(close, final_rail, raw_hma, cfg, t, px):
    n = cfg.length
    if cfg.family == "EMA":
        if t == 0 or not np.isfinite(final_rail[t - 1]):
            return float(px)
        alpha = 2.0 / (n + 1.0)
        return float(alpha * px + (1.0 - alpha) * final_rail[t - 1])
    if cfg.family == "WMA":
        return _wma_last_override(close, t, px, n)
    if cfg.family == "KS":
        return _linreg_last_override(close, t, px, n)

    half = max(1, int(math.floor(n / 2.0 + 0.5)))
    root = max(1, int(math.floor(math.sqrt(n) + 0.5)))
    a_cur = _wma_last_override(close, t, px, half)
    b_cur = _wma_last_override(close, t, px, n)
    if not np.isfinite(a_cur) or not np.isfinite(b_cur):
        return np.nan
    raw_cur = 2.0 * a_cur - b_cur
    if root == 1:
        return float(raw_cur)
    if raw_hma is None or t < root - 1:
        return np.nan
    vals = np.empty(root, dtype=np.float64)
    vals[:-1] = raw_hma[t - root + 1:t]
    vals[-1] = raw_cur
    if not np.all(np.isfinite(vals)):
        return np.nan
    w = np.arange(1.0, root + 1.0, dtype=np.float64)
    return float(np.dot(vals, w) / w.sum())


def candidate_daily_tick_arrays(daily, cfgs):
    """Chart-TF 1D rail/event values at TradingView's synthetic O/H/L/C executions."""
    close = daily["close"].to_numpy(np.float64)
    ticks = _daily_tick_matrix(daily)
    nc, nd = len(cfgs), len(daily)
    evt = np.zeros((nc, nd, 4), dtype=np.int8)
    price = np.full((nc, nd, 4), np.nan, dtype=np.float64)
    direction = np.zeros((nc, nd, 4), dtype=np.int8)

    for ci, cfg in enumerate(cfgs):
        final_rail = rail_np(close, cfg.family, cfg.length)
        raw_hma = None
        if cfg.family == "HMA":
            half = max(1, int(math.floor(cfg.length / 2.0 + 0.5)))
            raw_hma = 2.0 * wma_np(close, half) - wma_np(close, cfg.length)

        for t in range(1, nd):
            prev = final_rail[t - 1]
            prevprev = final_rail[t - 2] if t >= 2 else np.nan
            if not np.isfinite(prev):
                continue
            for q in range(4):
                cur = _daily_tick_rail_value(close, final_rail, raw_hma, cfg, t, ticks[t, q])
                if not np.isfinite(cur):
                    continue
                direction[ci, t, q] = 1 if cur > prev else (-1 if cur < prev else 0)
                price[ci, t, q] = prev
                if t >= 2 and np.isfinite(prevprev):
                    if cur > prev and prev <= prevprev:
                        evt[ci, t, q] = 1
                    elif cur < prev and prev >= prevprev:
                        evt[ci, t, q] = -1
    return evt, price, direction



def candidate_daily_static_tick_arrays(daily, cfgs):
    """
    Confirmed/final Daily rail state repeated across the four historical executions.

    This is intentionally tested beside tick-dynamic Daily semantics because
    request.security(same-TF, lookahead_off) + TradingView's history-tick model
    must be established empirically against the production 36/36 control.
    """
    close = daily["close"].to_numpy(np.float64)
    nc, nd = len(cfgs), len(daily)
    evt = np.zeros((nc, nd, 4), dtype=np.int8)
    price = np.full((nc, nd, 4), np.nan, dtype=np.float64)
    direction = np.zeros((nc, nd, 4), dtype=np.int8)

    for ci, cfg in enumerate(cfgs):
        r = rail_np(close, cfg.family, cfg.length)
        for t in range(1, nd):
            cur = r[t]
            inv = r[t - 1]
            if not (np.isfinite(cur) and np.isfinite(inv)):
                continue
            d = 1 if cur > inv else (-1 if cur < inv else 0)
            typ = 0
            if t >= 2 and np.isfinite(r[t - 2]):
                if cur > inv and inv <= r[t - 2]:
                    typ = 1
                elif cur < inv and inv >= r[t - 2]:
                    typ = -1
            for q in range(4):
                direction[ci, t, q] = d
                price[ci, t, q] = inv
                evt[ci, t, q] = typ

    commit = np.zeros((nd, 4), dtype=np.bool_)
    commit[:, 0] = True
    return evt, price, direction, commit


def candidate_static_tick_arrays(source, daily, granularity, cfgs):
    """Expand historical request.security snapshots to the four Daily executions."""
    close = source["close"].to_numpy(dtype=np.float64)
    nc, nd = len(cfgs), len(daily)
    evt = np.zeros((nc, nd, 4), dtype=np.int8)
    price = np.full((nc, nd, 4), np.nan, dtype=np.float64)
    direction = np.zeros((nc, nd, 4), dtype=np.int8)
    source_idx_ref = np.full(nd, -1, dtype=np.int32)

    for ci, cfg in enumerate(cfgs):
        r = rail_np(close, cfg.family, cfg.length)
        cur, inv, source_idx = sample_source_to_daily_with_index(source, r, daily, granularity)
        if ci == 0:
            source_idx_ref[:] = source_idx
        for t in range(nd):
            prev_cur = cur[t - 1] if t >= 1 else np.nan
            prev_inv = inv[t - 1] if t >= 1 else np.nan
            for q in range(4):
                if granularity == "W" and t >= 1 and source_idx[t] != source_idx[t - 1] and q < 3:
                    tick_cur = cur[t - 1]; tick_inv = inv[t - 1]
                else:
                    tick_cur = cur[t]; tick_inv = inv[t]
                if not (np.isfinite(tick_cur) and np.isfinite(tick_inv)):
                    continue
                direction[ci, t, q] = 1 if tick_cur > tick_inv else (-1 if tick_cur < tick_inv else 0)
                price[ci, t, q] = tick_inv
                if t >= 1 and np.isfinite(prev_cur) and np.isfinite(prev_inv):
                    if tick_cur > tick_inv and prev_cur <= prev_inv:
                        evt[ci, t, q] = 1
                    elif tick_cur < tick_inv and prev_cur >= prev_inv:
                        evt[ci, t, q] = -1
    return evt, price, direction, source_idx_ref


def candidate_tick_arrays(source, daily, granularity, cfgs):
    nd = len(daily)
    if granularity == "D":
        evt, price, direction = candidate_daily_tick_arrays(daily, cfgs)
        commit = np.zeros((nd, 4), dtype=np.bool_)
        # Pine history bars report barstate.isconfirmed on every History Bar Tick.
        # Guardian source-period commit therefore happens on the first eligible
        # execution of the chart bar, before trade qualification.
        commit[:, 0] = True
        return evt, price, direction, commit

    evt, price, direction, source_idx = candidate_static_tick_arrays(source, daily, granularity, cfgs)
    commit = np.zeros((nd, 4), dtype=np.bool_)
    if granularity == "W":
        # The weekly source closes only on the chart bar whose close coincides
        # with the weekly close. On history ticks, that commit occurs at q0.
        # source_idx advances on the first Daily bar where the completed weekly
        # snapshot is visible, so mark that bar's first execution.
        for t in range(1, nd):
            if source_idx[t] >= 0 and source_idx[t] != source_idx[t - 1]:
                commit[t, 0] = True
    else:
        # For LTF request.security(..., lookahead_off), the Daily historical bar
        # owns the last intrabar snapshot. time_close(LTF) coincides with the
        # Daily close, and barstate.isconfirmed is true on every history tick.
        commit[:, 0] = True
    return evt, price, direction, commit


# ─────────────────────────────────────────────────────────────────────────────
# Redline joint simulator — five R bays / dynamic Guardian + Trigger
# ─────────────────────────────────────────────────────────────────────────────


@njit(cache=True)
def _find_target(reg_price, reg_type, reg_bar, reg_source, reg_count,
                 wanted_type, current_event_bar, wanted_source, same_rail_only):
    # Pine f_previous_pivot_target():
    #   Any Route R -> immediately previous opposite standalone route ray
    #   Same R      -> same search, additionally restricted to event source.
    for k in range(reg_count - 1, -1, -1):
        source_ok = (not same_rail_only) or (reg_source[k] == wanted_source)
        if source_ok and reg_bar[k] < current_event_bar and reg_type[k] == wanted_type:
            return reg_price[k]
    return np.nan


@njit(cache=True)
def _store_turn(reg_price, reg_type, reg_bar, reg_source, reg_count, price, typ, event_bar, source, registry_limit):
    for k in range(reg_count - 1, -1, -1):
        if reg_source[k] == source and reg_bar[k] == event_bar:
            reg_price[k] = price
            reg_type[k] = typ
            return reg_count
    if reg_count < registry_limit:
        reg_price[reg_count] = price; reg_type[reg_count] = typ; reg_bar[reg_count] = event_bar; reg_source[reg_count] = source
        return reg_count + 1
    for k in range(registry_limit - 1):
        reg_price[k] = reg_price[k+1]; reg_type[k] = reg_type[k+1]; reg_bar[k] = reg_bar[k+1]; reg_source[k] = reg_source[k+1]
    reg_price[registry_limit-1] = price; reg_type[registry_limit-1] = typ; reg_bar[registry_limit-1] = event_bar; reg_source[registry_limit-1] = source
    return registry_limit


@njit(cache=True)
def _tv_tick_path(o, h, l, c):
    out = np.empty(4, dtype=np.float64); out[0] = o
    if abs(o - h) <= abs(o - l): out[1], out[2] = h, l
    else: out[1], out[2] = l, h
    out[3] = c
    return out


@njit(cache=True)
def _selected_dir(role_idx,c0,c1,c2,c3,c4,d0,d1,d2,d3,d4,t,q):
    if role_idx == 0: return int(d0[c0,t,q])
    if role_idx == 1: return int(d1[c1,t,q])
    if role_idx == 2: return int(d2[c2,t,q])
    if role_idx == 3: return int(d3[c3,t,q])
    return int(d4[c4,t,q])


@njit(cache=True)
def _simulate_one(c0,c1,c2,c3,c4,guardian_role,trigger_role,
                  e0,p0,d0,e1,p1,d1,e2,p2,d2,e3,p3,d3,e4,p4,d4,commit_mask,
                  o,h,l,c,open_ns,close_ns,eval_start_ns,fwd_start_ns,pip,registry_limit,same_rail_only):
    nd = len(c)
    reg_price=np.empty(MAX_REGISTRY_LIMIT); reg_type=np.empty(MAX_REGISTRY_LIMIT,dtype=np.int8)
    reg_bar=np.empty(MAX_REGISTRY_LIMIT,dtype=np.int32); reg_source=np.empty(MAX_REGISTRY_LIMIT,dtype=np.int8); reg_count=0
    position=0; entry_price=0.0; target=np.nan; entry_time_ns=0; mae_pips=0.0
    order_pending=0; order_target=np.nan; order_signal_day=-1; order_signal_tick=-1
    guard_last=0; guard_committed=0; exit_day=-1
    entries_total=closed_total=wins_total=0; net_total=max_mae_total=longest_total=hold_sum_total=0.0
    entries_fwd=closed_fwd=wins_fwd=0; net_fwd=0.0; day_ns=86_400_000_000_000

    for t in range(nd):
        ticks=_tv_tick_path(o[t],h[t],l[t],c[t]); span=close_ns[t]-open_ns[t]
        if span<=0: span=day_ns
        for q in range(4):
            px=ticks[q]; tick_ns=open_ns[t]+(span*q)//3
            trigger_dir=_selected_dir(trigger_role,c0,c1,c2,c3,c4,d0,d1,d2,d3,d4,t,q)
            g_now=_selected_dir(guardian_role,c0,c1,c2,c3,c4,d0,d1,d2,d3,d4,t,q)
            if g_now!=0: guard_last=g_now
            if commit_mask[guardian_role,t,q] and g_now!=0: guard_committed=g_now

            event_types=np.empty(5,dtype=np.int8); event_sources=np.empty(5,dtype=np.int8); event_count=0
            typ=int(e0[c0,t,q])
            if typ!=0:
                reg_count=_store_turn(reg_price,reg_type,reg_bar,reg_source,reg_count,p0[c0,t,q],typ,t-1,0,registry_limit); event_types[event_count]=typ; event_sources[event_count]=0; event_count+=1
            typ=int(e1[c1,t,q])
            if typ!=0:
                reg_count=_store_turn(reg_price,reg_type,reg_bar,reg_source,reg_count,p1[c1,t,q],typ,t-1,1,registry_limit); event_types[event_count]=typ; event_sources[event_count]=1; event_count+=1
            typ=int(e2[c2,t,q])
            if typ!=0:
                reg_count=_store_turn(reg_price,reg_type,reg_bar,reg_source,reg_count,p2[c2,t,q],typ,t-1,2,registry_limit); event_types[event_count]=typ; event_sources[event_count]=2; event_count+=1
            typ=int(e3[c3,t,q])
            if typ!=0:
                reg_count=_store_turn(reg_price,reg_type,reg_bar,reg_source,reg_count,p3[c3,t,q],typ,t-1,3,registry_limit); event_types[event_count]=typ; event_sources[event_count]=3; event_count+=1
            typ=int(e4[c4,t,q])
            if typ!=0:
                reg_count=_store_turn(reg_price,reg_type,reg_bar,reg_source,reg_count,p4[c4,t,q],typ,t-1,4,registry_limit); event_types[event_count]=typ; event_sources[event_count]=4; event_count+=1

            if order_pending!=0 and ((t>order_signal_day) or (t==order_signal_day and q>order_signal_tick)) and position==0:
                position=order_pending; entry_price=px; target=order_target; entry_time_ns=tick_ns; mae_pips=0.0
                if tick_ns>=eval_start_ns: entries_total+=1
                if tick_ns>=fwd_start_ns: entries_fwd+=1
                order_pending=0; order_target=np.nan; order_signal_day=-1; order_signal_tick=-1

            if position!=0:
                adverse=((entry_price-px)/pip) if position==1 else ((px-entry_price)/pip)
                if adverse>mae_pips: mae_pips=adverse
                reached=(px>=target) if position==1 else (px<=target)
                if reached:
                    pnl=((px-entry_price)/pip) if position==1 else ((entry_price-px)/pip); hold=max(0.0,(tick_ns-entry_time_ns)/float(day_ns))
                    if tick_ns>=eval_start_ns:
                        closed_total+=1; wins_total += 1 if pnl>0 else 0; net_total+=pnl; max_mae_total=max(max_mae_total,mae_pips); longest_total=max(longest_total,hold); hold_sum_total+=hold
                    if tick_ns>=fwd_start_ns:
                        closed_fwd+=1; wins_fwd += 1 if pnl>0 else 0; net_fwd+=pnl
                    position=0; entry_price=0.0; target=np.nan; entry_time_ns=0; mae_pips=0.0; exit_day=t; continue

            if tick_ns<eval_start_ns or position!=0 or order_pending!=0 or exit_day==t or event_count==0: continue
            for ei in range(event_count):
                et=int(event_types[ei]); src=int(event_sources[ei]); cand=1 if et==1 else -1
                if cand!=guard_last or cand!=guard_committed or cand!=trigger_dir: continue
                tgt=_find_target(reg_price,reg_type,reg_bar,reg_source,reg_count,-et,t-1,src,same_rail_only)
                if not np.isfinite(tgt): continue
                if not ((tgt>px) if cand==1 else (tgt<px)): continue
                order_pending=cand; order_target=tgt; order_signal_day=t; order_signal_tick=q; break

    open_end=1 if (position!=0 or order_pending!=0) else 0
    avg_hold=hold_sum_total/closed_total if closed_total>0 else 9999.0
    out=np.empty(13); out[:]=[entries_total,closed_total,wins_total,net_total,max_mae_total,longest_total,avg_hold,entries_fwd,closed_fwd,wins_fwd,net_fwd,open_end,(closed_total/entries_total*100.0) if entries_total>0 else 0.0]
    return out


@njit(parallel=True, cache=True)
def simulate_many(combos,e0,p0,d0,e1,p1,d1,e2,p2,d2,e3,p3,d3,e4,p4,d4,commit_mask,
                  o,h,l,c,open_ns,close_ns,eval_start_ns,fwd_start_ns,pip,registry_limit,same_rail_only):
    n=combos.shape[0]; out=np.empty((n,13))
    for i in prange(n):
        out[i]=_simulate_one(combos[i,0],combos[i,1],combos[i,2],combos[i,3],combos[i,4],combos[i,5],combos[i,6],
                             e0,p0,d0,e1,p1,d1,e2,p2,d2,e3,p3,d3,e4,p4,d4,commit_mask,
                             o,h,l,c,open_ns,close_ns,eval_start_ns,fwd_start_ns,pip,registry_limit,same_rail_only)
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


def prepare_banks(raw, daily, cfgs, daily_mode="dynamic"):
    out=[]; commits=[]
    for slot in SLOT_ORDER:
        gran=SLOT_TF[slot]
        if gran == "D" and daily_mode == "static":
            evt,price,direction,commit = candidate_daily_static_tick_arrays(daily, cfgs[slot])
        else:
            evt,price,direction,commit = candidate_tick_arrays(raw[gran],daily,gran,cfgs[slot])
        out.append((evt,price,direction)); commits.append(commit)
    return out, np.stack(commits,axis=0)


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
    batches, banks, commit_mask, o,h,l,c,ons,cns, eval_start_ns,fwd_start_ns,pip,registry_limit,
    keep_n, same_rail_only, deadline=None, progress_label="joint",
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
            commit_mask,
            o,h,l,c,ons,cns,eval_start_ns,fwd_start_ns,pip,registry_limit,same_rail_only
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



def baseline_trade_ledger(combo,banks,commit_mask,daily,eval_start_ns,fwd_start_ns,pip,registry_limit,same_rail_only):
    cfg_idx=[int(combo[i]) for i in range(5)]; guardian_role=int(combo[5]); trigger_role=int(combo[6])
    o=daily["open"].to_numpy(np.float64); h=daily["high"].to_numpy(np.float64); l=daily["low"].to_numpy(np.float64); c=daily["close"].to_numpy(np.float64)
    ons=daily["bar_open_ns"].to_numpy(np.int64); cns=daily["bar_close_ns"].to_numpy(np.int64)
    reg=[]; guard_last=0; guard_committed=0; position=0; entry_price=np.nan; target=np.nan; entry_ns=0; entry_day_idx=-1; entry_source=-1; mae=0.0
    pending=0; pending_target=np.nan; pending_source=-1; pending_day=-1; pending_q=-1; pending_ns=0; exit_day=-1; rows=[]; day_ns=86_400_000_000_000
    def dsel(role,t,q): return int(banks[role][2][cfg_idx[role],t,q])
    def store(price_,typ_,bar_,source_):
        nonlocal reg
        found=None
        for k in range(len(reg)-1,-1,-1):
            if reg[k]["source"]==source_ and reg[k]["bar"]==bar_: found=k; break
        if found is None:
            reg.append({"price":float(price_),"type":int(typ_),"bar":int(bar_),"source":int(source_)})
            if len(reg)>registry_limit: reg=reg[-registry_limit:]
        else:
            reg[found]["price"]=float(price_); reg[found]["type"]=int(typ_)
    def find_target(typ_,bar_,source_):
        for x in reversed(reg):
            source_ok = (not same_rail_only) or x["source"] == source_
            if source_ok and x["bar"] < bar_ and x["type"] == typ_:
                return x["price"]
        return np.nan
    for t in range(len(daily)):
        path=[o[t], h[t] if abs(o[t]-h[t])<=abs(o[t]-l[t]) else l[t], l[t] if abs(o[t]-h[t])<=abs(o[t]-l[t]) else h[t], c[t]]
        span=int(cns[t]-ons[t]); span=span if span>0 else day_ns
        for q,px in enumerate(path):
            tick_ns=int(ons[t]+span*q//3); trigger=dsel(trigger_role,t,q); g=dsel(guardian_role,t,q)
            if g!=0: guard_last=g
            if bool(commit_mask[guardian_role,t,q]) and g!=0: guard_committed=g
            events=[]
            for src_i in range(5):
                e,p,_=banks[src_i]; typ=int(e[cfg_idx[src_i],t,q])
                if typ:
                    store(float(p[cfg_idx[src_i],t,q]),typ,t-1,src_i); events.append((src_i,typ))
            if pending and (t>pending_day or (t==pending_day and q>pending_q)) and position==0:
                position=pending; entry_price=float(px); target=float(pending_target); entry_ns=tick_ns; entry_day_idx=t; entry_source=pending_source; signal_ns=pending_ns; signal_q=pending_q; mae=0.0
                pending=0; pending_target=np.nan; pending_source=-1; pending_day=-1; pending_q=-1; pending_ns=0
            if position:
                mae=max(mae, ((entry_price-px)/pip) if position==1 else ((px-entry_price)/pip)); reached=px>=target if position==1 else px<=target
                if reached:
                    pnl=((px-entry_price)/pip) if position==1 else ((entry_price-px)/pip); hold=max(0.0,(tick_ns-entry_ns)/day_ns)
                    if tick_ns>=eval_start_ns:
                        rows.append({"signal_time_utc":pd.to_datetime(signal_ns,utc=True).isoformat(),"entry_time_utc":pd.to_datetime(entry_ns,utc=True).isoformat(),"exit_time_utc":pd.to_datetime(tick_ns,utc=True).isoformat(),"entry_day_index":int(entry_day_idx),"entry_price":float(entry_price),"exit_price":float(px),"source_R":SLOT_ORDER[entry_source],"side":"LONG" if position==1 else "SHORT","entry":entry_price,"target":target,"exit":float(px),"pips":float(pnl),"mae_pips":float(mae),"hold_days":float(hold),"in_last_30d":bool(tick_ns>=fwd_start_ns),"signal_tick":int(signal_q)})
                    position=0; entry_price=np.nan; target=np.nan; entry_ns=0; entry_day_idx=-1; entry_source=-1; mae=0.0; exit_day=t; continue
            if tick_ns<eval_start_ns or position or pending or exit_day==t or not events: continue
            for src_i,typ in events:
                cand=1 if typ==1 else -1
                if cand!=guard_last or cand!=guard_committed or cand!=trigger: continue
                tgt=find_target(-typ,t-1,src_i)
                if not np.isfinite(tgt) or not ((tgt>px) if cand==1 else (tgt<px)): continue
                pending=cand; pending_target=tgt; pending_source=src_i; pending_day=t; pending_q=q; pending_ns=tick_ns; break
    return pd.DataFrame(rows)


TV_CONTROL_TRADES = [
    ("2026-04-28",-1,1.17218,1.16775),
    ("2026-04-30", 1,1.16789,1.17418),
    ("2026-05-04",-1,1.17478,1.16810),
    ("2026-05-06", 1,1.16924,1.17967),
    ("2026-05-12",-1,1.17878,1.17218),
    ("2026-05-19",-1,1.16558,1.15922),
    ("2026-05-20",-1,1.16055,1.15828),
    ("2026-05-22",-1,1.16194,1.15883),
    ("2026-05-27",-1,1.16615,1.16258),
    ("2026-06-01",-1,1.16543,1.16068),
    ("2026-06-02",-1,1.16558,1.16310),
    ("2026-06-04",-1,1.16455,1.16110),
    ("2026-06-08",-1,1.15548,1.15030),
    ("2026-06-17",-1,1.16098,1.14779),
    ("2026-06-23",-1,1.14391,1.13757),
    ("2026-06-25",-1,1.13618,1.13335),
    ("2026-06-30", 1,1.14244,1.14367),
    ("2026-07-02", 1,1.13750,1.14730),
    ("2026-07-07",-1,1.14420,1.14080),
    ("2026-07-08",-1,1.14316,1.13912),
    ("2026-07-09", 1,1.14186,1.14494),
    ("2026-07-10",-1,1.14329,1.14116),
    ("2026-07-14", 1,1.13843,1.14628),
    ("2026-07-15", 1,1.14060,1.14824),
    ("2026-07-20",-1,1.14268,1.13974),
    ("2026-07-27",-1,1.13958,1.13670),
    ("2026-07-28", 1,1.13686,1.14053),
    ("2026-07-31", 1,1.15261,1.15476),
    ("2026-08-03", 1,1.15004,1.15341),
    ("2026-08-05", 1,1.15268,1.15594),
    ("2026-08-06", 1,1.15147,1.15808),
    ("2026-08-10", 1,1.15400,1.15634),
    ("2026-08-19", 1,1.15702,1.16792),
    ("2026-08-20", 1,1.16770,1.17105),
    ("2026-08-21", 1,1.16783,1.17116),
    ("2026-08-24", 1,1.16553,1.16798),
]

def _json_native(x):
    """Recursively convert NumPy/Pandas scalars into json.dumps-safe Python types."""
    if isinstance(x, dict):
        return {str(k): _json_native(v) for k,v in x.items()}
    if isinstance(x, (list,tuple)):
        return [_json_native(v) for v in x]
    if isinstance(x, np.generic):
        return x.item()
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    if isinstance(x, np.ndarray):
        return [_json_native(v) for v in x.tolist()]
    return x

def _tv_trade_alignment(ledger: pd.DataFrame, daily: pd.DataFrame):
    """
    Compare BASE trades to the exact TradingView control at Daily trading-date + side.
    Pine/TradingView displays the Forex trading date; for our OANDA-aligned Daily frame
    that is represented by the Daily bar CLOSE date.
    """
    tv = [{"date":d, "dir":int(side), "entry":float(ep), "exit":float(xp)}
          for d,side,ep,xp in TV_CONTROL_TRADES]

    py = []
    if ledger is not None and len(ledger):
        for _,r in ledger.iterrows():
            day_idx = int(r.get("entry_day_index",-1))
            if 0 <= day_idx < len(daily):
                td = pd.to_datetime(int(daily["bar_close_ns"].iloc[day_idx]), utc=True).date().isoformat()
            else:
                # Fallback if an older ledger shape is encountered.
                td = pd.Timestamp(r["entry_time_utc"]).date().isoformat()
            side = 1 if str(r.get("side","")).upper() == "LONG" else -1
            py.append({
                "date":td, "dir":side,
                "entry":float(r.get("entry_price",np.nan)),
                "exit":float(r.get("exit_price",np.nan)),
                "source":str(r.get("source_R","")),
            })

    # Sequence comparison is the strongest diagnostic because TV is one-trade-at-a-time.
    seq_matches = 0
    first_div = None
    for i in range(max(len(tv),len(py))):
        t = tv[i] if i < len(tv) else None
        p = py[i] if i < len(py) else None
        if t is not None and p is not None and t["date"] == p["date"] and t["dir"] == p["dir"]:
            seq_matches += 1
        elif first_div is None:
            first_div = {"index_1based":i+1, "tv":t, "python":p}

    tv_keys=[(x["date"],x["dir"]) for x in tv]
    py_keys=[(x["date"],x["dir"]) for x in py]
    missing=[]
    temp=list(py_keys)
    for k in tv_keys:
        if k in temp: temp.remove(k)
        else: missing.append(k)
    extra=[]
    temp=list(tv_keys)
    for k in py_keys:
        if k in temp: temp.remove(k)
        else: extra.append(k)

    return {
        "tv_trade_count":len(tv),
        "python_trade_count":len(py),
        "sequence_date_side_matches":seq_matches,
        "missing_tv_date_side":[{"date":d,"side":"LONG" if side==1 else "SHORT"} for d,side in missing],
        "extra_python_date_side":[{"date":d,"side":"LONG" if side==1 else "SHORT"} for d,side in extra],
        "first_sequence_divergence":first_div,
        "python_trades":py,
    }

def main() -> int:
    print("=" * 72, flush=True)
    print(f"TGIM SWEEPER BUILD: {BUILD_ID}", flush=True)
    print("ARCHITECTURE: FIVE-R EXACT PARITY v2.4 | TV 36/36 LEDGER | HISTORY-COMMIT FIX", flush=True)
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
    ap.add_argument("--registry-limit", type=int, default=20, choices=[20,27])
    ap.add_argument("--target-scope", choices=["any","same"], default="any",
                    help="Production BASE is always Any Route R in v2.4; retained only for CLI compatibility.")

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

    # Current TradingView control is exact and known from the exported Properties sheet:
    # Any Route R / One Leg Only / registry 20 / clutter OFF / R2 Guardian+Trigger.
    # LTF request.security(... lookahead_off) is the last intrabar snapshot. The only
    # remaining BASE uncertainty worth testing is whether same-TF Daily rail state is
    # dynamic across history ticks or presented as finalized throughout the bar.
    banks_dynamic, commit_dynamic = prepare_banks(raw,daily,cfgs,daily_mode="dynamic")
    banks_static,  commit_static  = prepare_banks(raw,daily,cfgs,daily_mode="static")

    o = daily["open"].to_numpy(np.float64)
    h = daily["high"].to_numpy(np.float64)
    l = daily["low"].to_numpy(np.float64)
    c = daily["close"].to_numpy(np.float64)
    ons = daily["bar_open_ns"].to_numpy(np.int64)
    cns = daily["bar_close_ns"].to_numpy(np.int64)
    pip = pip_size(instrument)

    expected_total = args.expected_total if args.expected_total is not None else EXPECTED_TOTAL.get(instrument)
    expected_forward = args.expected_forward if args.expected_forward is not None else EXPECTED_FORWARD.get(instrument)
    bc = baseline_combo(cfgs)

    print("[3/10] EXACT BASE certification against TradingView 36/36 ledger ...")
    modes = [
        ("STATIC_D + ANY_ROUTE + HISTORY_COMMIT_Q0",  banks_static,  commit_static),
        ("DYNAMIC_D + ANY_ROUTE + HISTORY_COMMIT_Q0", banks_dynamic, commit_dynamic),
    ]

    mode_rows=[]
    candidates=[]
    for label,mbanks,mcommit in modes:
        mm = simulate_many(
            bc,*mbanks[0],*mbanks[1],*mbanks[2],*mbanks[3],*mbanks[4],mcommit,
            o,h,l,c,ons,cns,eval_start_ns,fwd_start_ns,pip,args.registry_limit,False
        )[0]
        md=metric_dict(mm)
        ledger=baseline_trade_ledger(
            bc[0],mbanks,mcommit,daily,eval_start_ns,fwd_start_ns,pip,args.registry_limit,False
        )
        align=_tv_trade_alignment(ledger,daily)
        exact_counts=(md["closed_120d"]==expected_total and md["wins_120d"]==expected_total
                      and md["closed_30d"]==expected_forward and md["wins_30d"]==expected_forward)
        exact_ledger=(align["sequence_date_side_matches"]==36 and len(align["missing_tv_date_side"])==0
                      and len(align["extra_python_date_side"])==0)
        exact=bool(exact_counts and exact_ledger)
        print(f"       {label:<44} | 120d {md['closed_120d']}/{md['wins_120d']}"
              f" | 30d {md['closed_30d']}/{md['wins_30d']}"
              f" | TV-seq {align['sequence_date_side_matches']}/36"
              f" | MAE {md['max_mae_pips_120d']:.2f}"
              f" | {'EXACT' if exact else 'MISS'}")
        if align["first_sequence_divergence"] is not None:
            fd=align["first_sequence_divergence"]
            print(f"         first divergence #{fd['index_1based']}: TV={fd['tv']} | PY={fd['python']}")
        mode_rows.append({"mode":label,"exact":exact,**md,
                          "tv_sequence_matches":align["sequence_date_side_matches"],
                          "tv_missing":len(align["missing_tv_date_side"]),
                          "python_extra":len(align["extra_python_date_side"])})
        candidates.append((exact,label,mbanks,mcommit,md,ledger,align))

    pd.DataFrame(mode_rows).to_csv(result_dir/"BASE_PARITY_MATRIX.csv",index=False)

    exact_candidates=[x for x in candidates if x[0]]
    if exact_candidates:
        _,label,banks,commit_mask,base_metrics,base_ledger,alignment=exact_candidates[0]
        certified=True
        selected_daily_mode="static" if label.startswith("STATIC") else "dynamic"
        same_rail_only=False
        selected_scope="any"
        print(f"       SELECTED EXACT MODEL: {label}")
    else:
        # Keep STATIC + ANY as forensic default because TradingView explicitly returns
        # the last intrabar for LTF requests and the earlier matrix showed it closest.
        _,label,banks,commit_mask,base_metrics,base_ledger,alignment=candidates[0]
        certified=False
        selected_daily_mode="static"
        same_rail_only=False
        selected_scope="any"

    base_ledger.to_csv(result_dir/"BASELINE_TRADE_LEDGER.csv",index=False)
    (result_dir/"TV_ALIGNMENT.json").write_text(json.dumps(_json_native(alignment),indent=2))

    cert = {
        "instrument":instrument,
        "build_id":BUILD_ID,
        "expected_total":expected_total,
        "expected_forward":expected_forward,
        "exact_exported_properties":{
            "target_scope":"Any Route R",
            "after_target_exit":"One Leg Only",
            "registry_limit":args.registry_limit,
            "clutter":"OFF",
            "guardian":"R2",
            "trigger":"R2",
            "history_bar_tick":True,
            "bar_detailization":"Default 4 ticks",
            "order_execution_delay":"One tick",
        },
        "baseline":{
            **{slot:{"tf":SLOT_TF[slot],"family":BASELINE[slot][0],"length":BASELINE[slot][1],"working":"RAW"}
               for slot in SLOT_ORDER},
        },
        "selected_daily_mode":selected_daily_mode,
        "metrics":base_metrics,
        "alignment":alignment,
        "certified":bool(certified),
        "mode_matrix":mode_rows,
    }
    (result_dir/"BASE_CERTIFICATION.json").write_text(json.dumps(_json_native(cert),indent=2))

    print(f"       TV reference trades: 36 | Python ledger: {len(base_ledger)}")
    print(f"       Sequence date/side matches: {alignment['sequence_date_side_matches']}/36")
    print(f"       Missing TV trades: {len(alignment['missing_tv_date_side'])}"
          f" | Extra Python trades: {len(alignment['extra_python_date_side'])}")
    if alignment["missing_tv_date_side"]:
        print("       First missing:", alignment["missing_tv_date_side"][:5])
    if alignment["extra_python_date_side"]:
        print("       First extra:  ", alignment["extra_python_date_side"][:5])
    print()

    if not certified and not args.force_sweep:
        print("\nBASE MISMATCH — REDLINE SWEEP ABORTED.")
        print("The optimizer remains locked, but this run is no longer aggregate-only.")
        print("It compared Python directly to all 36 TradingView entry dates/sides.")
        print(f"Parity matrix:       {result_dir/'BASE_PARITY_MATRIX.csv'}")
        print(f"TV alignment:        {result_dir/'TV_ALIGNMENT.json'}")
        print(f"Certification file: {result_dir/'BASE_CERTIFICATION.json'}")
        print(f"Trade ledger:        {result_dir/'BASELINE_TRADE_LEDGER.csv'}")
        print("Do NOT force-sweep a mismatched model.")
        return 2

    print("[4/10] Prescreening every bay candidate across all 25 Guardian/Trigger role pairs ...")
    pc, meta = prescreen_combos(cfgs)
    pm = simulate_many(
        pc,
        *banks[0],*banks[1],*banks[2],*banks[3],*banks[4],
        commit_mask,
        o,h,l,c,ons,cns,eval_start_ns,fwd_start_ns,pip,args.registry_limit,same_rail_only
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
        commit_mask,
        o,h,l,c,ons,cns,eval_start_ns,fwd_start_ns,pip,args.registry_limit,same_rail_only
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
        joint_batches,banks,commit_mask,o,h,l,c,ons,cns,eval_start_ns,fwd_start_ns,pip,args.registry_limit,
        keep_n=args.top,same_rail_only=same_rail_only,deadline=hard_deadline,progress_label="REDLINE"
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
        rbanks, rcommit_mask = prepare_banks(raw,daily,rcfg,daily_mode=selected_daily_mode)
        rbatches = refine_combo_batches(
            seeds,rcfg,args.refine_radius,args.max_refine_length,args.batch_size
        )
        rc,rm,rprocessed,rcomplete = stream_search(
            rbatches,rbanks,rcommit_mask,o,h,l,c,ons,cns,eval_start_ns,fwd_start_ns,pip,args.registry_limit,
            keep_n=args.top,same_rail_only=same_rail_only,deadline=hard_deadline,progress_label="REFINE"
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
