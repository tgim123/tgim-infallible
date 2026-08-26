#!/usr/bin/env python3
"""
TGIM REDLINE 5-R SWEEPER v2.2 — PARITY ENGINE
=============================================

BUILD ID: REDLINE-5R-V2.2-20260826-B

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

Parity corrections in v2.2:
    - source-keyed SAME-R target lookup
    - source/origin turn replacement instead of duplicate append
    - Guardian confirmed/source-close state separation
    - tick-dynamic Daily R2 EMA5 state across historical O/H/L/C ticks
    - baseline trade ledger on certification failure

Adaptive REDLINE behavior remains:
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

BUILD_ID = "REDLINE-5R-V2.2-20260826-B"

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
SOURCE_CODE = {slot: i + 1 for i, slot in enumerate(SLOT_ORDER)}

BASE_GUARDIAN = "R2"
BASE_TRIGGER = "R2"

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
            raise ValueError("OANDA_TOKEN is empty. Set it in Render Environment.")
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
                    raise RuntimeError(f"OANDA HTTP {r.status_code}: {body} | url={r.url}")
                return r.json()
            except Exception as exc:
                last_err = exc
                time.sleep(min(5.0, 0.5 * (2 ** attempt)))
        raise RuntimeError(f"OANDA request failed after retries: {last_err}")

    def candles(self, instrument: str, granularity: str, start: datetime, end: datetime, refresh: bool = False) -> pd.DataFrame:
        key = f"{instrument}_{granularity}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv.gz"
        cache = self.cache_dir / key
        if cache.exists() and not refresh:
            df = pd.read_csv(cache, compression="gzip")
            df["time"] = pd.to_datetime(df["time"], utc=True)
            return df

        rows = []
        cursor = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)
        path = f"/v3/instruments/{instrument}/candles"
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
            cursor = last_time.to_pydatetime() + timedelta(seconds=step_sec)
            if len(candles) < 5000:
                break
            if last_time.to_pydatetime() >= end - timedelta(seconds=step_sec):
                break

        if not rows:
            raise RuntimeError(f"No {granularity} candles returned for {instrument}")

        df = pd.DataFrame(rows).drop_duplicates("time", keep="last").sort_values("time").reset_index(drop=True)
        df.to_csv(cache, index=False, compression="gzip")
        return df


def ema_np(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    alpha = 2.0 / (n + 1.0)
    seed = np.nan
    for i, v in enumerate(x):
        if not np.isfinite(v):
            continue
        seed = v if not np.isfinite(seed) else alpha * v + (1.0 - alpha) * seed
        out[i] = seed
    return out


def wma_np(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    w = np.arange(1.0, n + 1.0, dtype=np.float64)
    den = w.sum()
    for i in range(n - 1, len(x)):
        win = x[i - n + 1:i + 1]
        if np.all(np.isfinite(win)):
            out[i] = np.dot(win, w) / den
    return out


def linreg_np(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if n <= 1:
        return x.copy()
    xs = np.arange(n, dtype=np.float64)
    sx = xs.sum(); sxx = np.dot(xs, xs); den = n * sxx - sx * sx
    for i in range(n - 1, len(x)):
        y = x[i - n + 1:i + 1]
        if not np.all(np.isfinite(y)):
            continue
        sy = y.sum(); sxy = np.dot(xs, y)
        slope = (n * sxy - sx * sy) / den
        intercept = (sy - slope * sx) / n
        out[i] = intercept + slope * (n - 1)
    return out


def hma_np(x: np.ndarray, n: int) -> np.ndarray:
    half = max(1, int(math.floor(n / 2.0 + 0.5)))
    root = max(1, int(math.floor(math.sqrt(n) + 0.5)))
    return wma_np(2.0 * wma_np(x, half) - wma_np(x, n), root)


def rail_np(close: np.ndarray, family: str, length: int) -> np.ndarray:
    if family == "EMA": return ema_np(close, length)
    if family == "HMA": return hma_np(close, length)
    if family == "KS": return linreg_np(close, length)
    if family == "WMA": return wma_np(close, length)
    raise ValueError(f"Unknown rail family {family}")


def daily_execution_frame(d_all: pd.DataFrame) -> pd.DataFrame:
    d = d_all.sort_values("time").reset_index(drop=True).copy()
    d["next_time"] = d["time"].shift(-1)
    d = d.loc[d["complete"].astype(bool) & d["next_time"].notna()].copy().reset_index(drop=True)
    d["bar_open_ns"] = d["time"].astype("int64")
    d["bar_close_ns"] = d["next_time"].astype("int64")
    return d


def sample_source_to_daily(source, rail, daily, granularity):
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
                if k > 0: inv[j] = rail[k - 1]
        return cur, inv

    sec_map = {"M1": 60, "M5": 300, "M15": 900, "W": 604800}
    dur_ns = sec_map[granularity] * 1_000_000_000
    src = source.sort_values("time").reset_index(drop=True)
    src_start = pd.to_datetime(src["time"], utc=True).astype("int64").to_numpy()
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
            if k > 0: inv[j] = rail[k - 1]
    return cur, inv


def candidate_daily_arrays(source, daily, granularity, cfgs):
    close = source["close"].to_numpy(dtype=np.float64)
    nc, nd = len(cfgs), len(daily)
    evt = np.zeros((nc, nd), dtype=np.int8)
    price = np.full((nc, nd), np.nan, dtype=np.float64)
    direction = np.zeros((nc, nd), dtype=np.int8)

    for ci, cfg in enumerate(cfgs):
        r = rail_np(close, cfg.family, cfg.length)
        cur, inv = sample_source_to_daily(source, r, daily, granularity)
        d = np.where(np.isfinite(cur) & np.isfinite(inv), np.where(cur > inv, 1, np.where(cur < inv, -1, 0)), 0).astype(np.int8)
        direction[ci] = d
        for t in range(1, nd):
            if not (np.isfinite(cur[t]) and np.isfinite(inv[t]) and np.isfinite(cur[t-1]) and np.isfinite(inv[t-1])):
                continue
            up = cur[t] > inv[t] and cur[t-1] <= inv[t-1]
            dn = cur[t] < inv[t] and cur[t-1] >= inv[t-1]
            if up:
                evt[ci,t] = 1; price[ci,t] = inv[t]
            elif dn:
                evt[ci,t] = -1; price[ci,t] = inv[t]
    return evt, price, direction


def build_daily_dynamic_ema5(source_d: pd.DataFrame, daily: pd.DataFrame) -> Tuple[np.ndarray,np.ndarray,np.ndarray,np.ndarray]:
    """R2 baseline only: EMA5 recalculated at the synthetic O/H/L/C history ticks."""
    src = source_d.sort_values("time").reset_index(drop=True)
    src_times = pd.to_datetime(src["time"], utc=True)
    idx_map = {int(t.value): i for i,t in enumerate(src_times)}
    closes = src["close"].to_numpy(np.float64)
    prev_ema = ema_np(closes, 5)
    alpha = 2.0 / 6.0
    nd = len(daily)
    dyn_dir = np.zeros((nd,4),dtype=np.int8)
    dyn_evt = np.zeros((nd,4),dtype=np.int8)
    dyn_price = np.full((nd,4),np.nan,dtype=np.float64)
    committed = np.zeros(nd,dtype=np.int8)

    for t in range(nd):
        k = idx_map.get(int(pd.Timestamp(daily.loc[t,"time"]).value), -1)
        if k <= 0 or not np.isfinite(prev_ema[k-1]):
            continue
        prev = prev_ema[k-1]
        prev_prev = prev_ema[k-2] if k > 1 and np.isfinite(prev_ema[k-2]) else prev
        o,h,l,c = [float(daily.loc[t,x]) for x in ("open","high","low","close")]
        ticks = [o, h, l, c] if abs(o-h) <= abs(o-l) else [o, l, h, c]
        last_d = 1 if prev > prev_prev else (-1 if prev < prev_prev else 0)
        for q,px in enumerate(ticks):
            e = alpha * px + (1.0-alpha) * prev
            d = 1 if e > prev else (-1 if e < prev else 0)
            dyn_dir[t,q] = d
            if d != 0 and last_d != 0 and d != last_d:
                dyn_evt[t,q] = 1 if d > 0 else -1
                dyn_price[t,q] = prev
            last_d = d if d != 0 else last_d
        committed[t] = dyn_dir[t,3]
    return dyn_dir,dyn_evt,dyn_price,committed


@njit(cache=True)
def _tv_tick_path(o,h,l,c):
    out=np.empty(4,np.float64); out[0]=o
    if abs(o-h)<=abs(o-l): out[1]=h; out[2]=l
    else: out[1]=l; out[2]=h
    out[3]=c
    return out


@njit(cache=True)
def _selected_dir(role_idx,c0,c1,c2,c3,c4,d0,d1,d2,d3,d4,t):
    if role_idx==0:return int(d0[c0,t])
    if role_idx==1:return int(d1[c1,t])
    if role_idx==2:return int(d2[c2,t])
    if role_idx==3:return int(d3[c3,t])
    return int(d4[c4,t])


@njit(cache=True)
def _find_target_source(reg_price,reg_type,reg_bar,reg_source,reg_count,wanted_type,wanted_source,current_event_bar):
    for k in range(reg_count-1,-1,-1):
        if reg_bar[k] < current_event_bar and reg_type[k]==wanted_type and reg_source[k]==wanted_source:
            return reg_price[k]
    return np.nan


@njit(cache=True)
def _store_or_update_turn(reg_price,reg_type,reg_bar,reg_source,reg_count,price,typ,event_bar,source,registry_limit):
    for k in range(reg_count-1,-1,-1):
        if reg_source[k]==source and reg_bar[k]==event_bar:
            reg_price[k]=price; reg_type[k]=typ
            return reg_count
    if reg_count < registry_limit:
        reg_price[reg_count]=price; reg_type[reg_count]=typ; reg_bar[reg_count]=event_bar; reg_source[reg_count]=source
        return reg_count+1
    for k in range(registry_limit-1):
        reg_price[k]=reg_price[k+1]; reg_type[k]=reg_type[k+1]; reg_bar[k]=reg_bar[k+1]; reg_source[k]=reg_source[k+1]
    z=registry_limit-1
    reg_price[z]=price; reg_type[z]=typ; reg_bar[z]=event_bar; reg_source[z]=source
    return registry_limit


@njit(cache=True)
def _simulate_one(
    c0,c1,c2,c3,c4,guardian_role,trigger_role,
    e0,p0,d0,e1,p1,d1,e2,p2,d2,e3,p3,d3,e4,p4,d4,
    dyn_r2_dir,dyn_r2_evt,dyn_r2_price,
    o,h,l,c,open_ns,close_ns,eval_start_ns,fwd_start_ns,pip,registry_limit,
):
    nd=len(c)
    reg_price=np.empty(MAX_REGISTRY_LIMIT,np.float64)
    reg_type=np.empty(MAX_REGISTRY_LIMIT,np.int8)
    reg_bar=np.empty(MAX_REGISTRY_LIMIT,np.int32)
    reg_source=np.empty(MAX_REGISTRY_LIMIT,np.int8)
    reg_count=0

    position=0; entry_price=0.0; target=np.nan; entry_time_ns=0; mae=0.0
    order_pending=0; order_target=np.nan; order_source=0; signal_day=-1; signal_tick=-1
    guardian_confirmed=0; exit_day=-1
    etot=ctot=wtot=efwd=cfwd=wfwd=0
    net=netf=0.0; maxmae=longest=holdsum=0.0
    day_ns=86_400_000_000_000

    for t in range(nd):
        # non-D events are stable within the Daily historical bar; R2 baseline is tick-dynamic.
        static_types=np.empty(4,np.int8); static_prices=np.empty(4,np.float64); static_sources=np.empty(4,np.int8); static_n=0
        typ=int(e0[c0,t])
        if typ!=0:
            reg_count=_store_or_update_turn(reg_price,reg_type,reg_bar,reg_source,reg_count,p0[c0,t],typ,t-1,1,registry_limit)
            static_types[static_n]=typ; static_prices[static_n]=p0[c0,t]; static_sources[static_n]=1; static_n+=1
        typ=int(e2[c2,t])
        if typ!=0:
            reg_count=_store_or_update_turn(reg_price,reg_type,reg_bar,reg_source,reg_count,p2[c2,t],typ,t-1,3,registry_limit)
            static_types[static_n]=typ; static_prices[static_n]=p2[c2,t]; static_sources[static_n]=3; static_n+=1
        typ=int(e3[c3,t])
        if typ!=0:
            reg_count=_store_or_update_turn(reg_price,reg_type,reg_bar,reg_source,reg_count,p3[c3,t],typ,t-1,4,registry_limit)
            static_types[static_n]=typ; static_prices[static_n]=p3[c3,t]; static_sources[static_n]=4; static_n+=1
        typ=int(e4[c4,t])
        if typ!=0:
            reg_count=_store_or_update_turn(reg_price,reg_type,reg_bar,reg_source,reg_count,p4[c4,t],typ,t-1,5,registry_limit)
            static_types[static_n]=typ; static_prices[static_n]=p4[c4,t]; static_sources[static_n]=5; static_n+=1

        ticks=_tv_tick_path(o[t],h[t],l[t],c[t]); span=close_ns[t]-open_ns[t]
        if span<=0: span=day_ns

        for q in range(4):
            px=ticks[q]; tick_ns=open_ns[t]+(span*q)//3

            # Guardian source semantics: selected current dir; committed meaningful state updates at source close.
            if guardian_role==1:
                g_current=int(dyn_r2_dir[t,q])
                if q==3 and g_current!=0: guardian_confirmed=g_current
            else:
                g_current=_selected_dir(guardian_role,c0,c1,c2,c3,c4,d0,d1,d2,d3,d4,t)
                if g_current!=0: guardian_confirmed=g_current
            guardian_dir = g_current if g_current!=0 else guardian_confirmed

            if trigger_role==1:
                trigger_dir=int(dyn_r2_dir[t,q])
            else:
                trigger_dir=_selected_dir(trigger_role,c0,c1,c2,c3,c4,d0,d1,d2,d3,d4,t)

            # R2 tick-dynamic event is stored/updated exactly under source R2.
            r2typ=int(dyn_r2_evt[t,q])
            if r2typ!=0:
                reg_count=_store_or_update_turn(reg_price,reg_type,reg_bar,reg_source,reg_count,dyn_r2_price[t,q],r2typ,t-1,2,registry_limit)

            if order_pending!=0:
                later=(t>signal_day) or (t==signal_day and q>signal_tick)
                if later and position==0:
                    position=order_pending; entry_price=px; target=order_target; entry_time_ns=tick_ns; mae=0.0
                    if tick_ns>=eval_start_ns: etot+=1
                    if tick_ns>=fwd_start_ns: efwd+=1
                    order_pending=0; order_target=np.nan; order_source=0; signal_day=-1; signal_tick=-1

            if position!=0:
                adverse=(entry_price-px)/pip if position==1 else (px-entry_price)/pip
                if adverse>mae: mae=adverse
                reached=px>=target if position==1 else px<=target
                if reached:
                    pp=(px-entry_price)/pip if position==1 else (entry_price-px)/pip
                    hd=max(0.0,(tick_ns-entry_time_ns)/float(day_ns))
                    if tick_ns>=eval_start_ns:
                        ctot+=1; wtot+=1 if pp>0 else 0; net+=pp; maxmae=max(maxmae,mae); longest=max(longest,hd); holdsum+=hd
                    if tick_ns>=fwd_start_ns:
                        cfwd+=1; wfwd+=1 if pp>0 else 0; netf+=pp
                    position=0; entry_price=0.0; target=np.nan; entry_time_ns=0; mae=0.0; exit_day=t
                    continue

            if tick_ns<eval_start_ns or position!=0 or order_pending!=0 or exit_day==t:
                continue

            # Candidate events for this execution: R2 tick event plus static R1/R8/R9/R10 events.
            # Preserve source identity because Same-R target scope is source-keyed in Pine.
            if r2typ!=0:
                cand_dir=1 if r2typ==1 else -1
                if cand_dir==guardian_dir and cand_dir==trigger_dir:
                    tgt=_find_target_source(reg_price,reg_type,reg_bar,reg_source,reg_count,-r2typ,2,t-1)
                    if np.isfinite(tgt) and ((tgt>px) if cand_dir==1 else (tgt<px)):
                        order_pending=cand_dir; order_target=tgt; order_source=2; signal_day=t; signal_tick=q
                        continue

            for ei in range(static_n):
                et=int(static_types[ei]); src=int(static_sources[ei]); cand_dir=1 if et==1 else -1
                if cand_dir!=guardian_dir or cand_dir!=trigger_dir: continue
                tgt=_find_target_source(reg_price,reg_type,reg_bar,reg_source,reg_count,-et,src,t-1)
                if not np.isfinite(tgt): continue
                if not ((tgt>px) if cand_dir==1 else (tgt<px)): continue
                order_pending=cand_dir; order_target=tgt; order_source=src; signal_day=t; signal_tick=q
                break

    avg=holdsum/ctot if ctot>0 else 9999.0
    out=np.empty(13,np.float64)
    out[0]=etot;out[1]=ctot;out[2]=wtot;out[3]=net;out[4]=maxmae;out[5]=longest;out[6]=avg
    out[7]=efwd;out[8]=cfwd;out[9]=wfwd;out[10]=netf;out[11]=1 if (position!=0 or order_pending!=0) else 0
    out[12]=(ctot/etot*100.0) if etot>0 else 0.0
    return out


@njit(parallel=True,cache=True)
def simulate_many(combos,e0,p0,d0,e1,p1,d1,e2,p2,d2,e3,p3,d3,e4,p4,d4,dyn_r2_dir,dyn_r2_evt,dyn_r2_price,o,h,l,c,open_ns,close_ns,eval_start_ns,fwd_start_ns,pip,registry_limit):
    n=combos.shape[0]; out=np.empty((n,13),np.float64)
    for i in prange(n):
        out[i]=_simulate_one(combos[i,0],combos[i,1],combos[i,2],combos[i,3],combos[i,4],combos[i,5],combos[i,6],e0,p0,d0,e1,p1,d1,e2,p2,d2,e3,p3,d3,e4,p4,d4,dyn_r2_dir,dyn_r2_evt,dyn_r2_price,o,h,l,c,open_ns,close_ns,eval_start_ns,fwd_start_ns,pip,registry_limit)
    return out


def coarse_cfgs(lengths):
    bank=[RailCfg(f,n) for f in FAMILIES for n in lengths]
    return {s:list(bank) for s in SLOT_ORDER}


def cfg_index(cfgs,wanted):
    for i,c in enumerate(cfgs):
        if c.family==wanted[0] and c.length==wanted[1]: return i
    raise ValueError(wanted)


def metric_dict(row):
    return {
        "entries_120d":int(row[0]),"closed_120d":int(row[1]),"wins_120d":int(row[2]),
        "win_pct_120d":row[2]/row[1]*100.0 if row[1]>0 else 0.0,
        "net_pips_120d":float(row[3]),"max_mae_pips_120d":float(row[4]),"longest_days_120d":float(row[5]),"avg_hold_days_120d":float(row[6]),
        "entries_30d":int(row[7]),"closed_30d":int(row[8]),"wins_30d":int(row[9]),
        "win_pct_30d":row[9]/row[8]*100.0 if row[8]>0 else 0.0,
        "net_pips_30d":float(row[10]),"open_or_pending_end":int(row[11]),"completion_pct_120d":float(row[12]),
    }


def _quality_tier(m):
    closed=m[:,1]; wins=m[:,2]; fc=m[:,8]; fw=m[:,9]
    wr=wins/np.maximum(closed,1)*100.0; fwr=fw/np.maximum(fc,1)*100.0
    q=np.zeros(len(m),np.int16); q[(wr>=90)&(fwr>=90)]=1; q[(wr>=95)&(fwr>=95)]=2; q[(wr>=97.5)&(fwr>=97.5)]=3; q[(wr>=99.999)&(fwr>=99.999)]=4
    return q


def rank_indices(m):
    closed=m[:,1]; fc=m[:,8]; q=_quality_tier(m)
    return np.lexsort((m[:,6],m[:,5],m[:,4],-m[:,3],-m[:,10],m[:,11],-closed,-fc,-q))


def build_top_rows(combos,metrics,cfgs,top_n):
    order=rank_indices(metrics)[:top_n]; rows=[]
    for rank,ix in enumerate(order,1):
        combo=combos[ix]; row={"rank":rank}
        for si,slot in enumerate(SLOT_ORDER):
            cf=cfgs[slot][int(combo[si])]; row[f"{slot}_family"]=cf.family; row[f"{slot}_length"]=cf.length; row[f"{slot}_config"]=cf.label()+" RAW"
        row["guardian"]=SLOT_ORDER[int(combo[5])];row["trigger"]=SLOT_ORDER[int(combo[6])];row["same_guard_trigger"]=bool(combo[5]==combo[6]);row.update(metric_dict(metrics[ix]));rows.append(row)
    return pd.DataFrame(rows)


def prepare_banks(raw,daily,cfgs):
    return [candidate_daily_arrays(raw[SLOT_TF[s]],daily,SLOT_TF[s],cfgs[s]) for s in SLOT_ORDER]


def baseline_combo(cfgs):
    vals=[cfg_index(cfgs[s],BASELINE[s]) for s in SLOT_ORDER]+[ROLE_INDEX[BASE_GUARDIAN],ROLE_INDEX[BASE_TRIGGER]]
    return np.asarray([vals],np.int16)


def prescreen_combos(cfgs):
    base=[cfg_index(cfgs[s],BASELINE[s]) for s in SLOT_ORDER]; rows=[]
    for si,slot in enumerate(SLOT_ORDER):
        for cand in range(len(cfgs[slot])):
            for g in range(5):
                for tr in range(5):
                    r=list(base);r[si]=cand;r.extend([g,tr]);rows.append(r)
    return np.asarray(rows,np.int16)


def diversity_shortlist(si,cfgs,pre_metrics,k):
    block=25; offset=sum(len(cfgs[SLOT_ORDER[z]])*block for z in range(si)); slot=SLOT_ORDER[si]
    best=[]
    for cand in range(len(cfgs[slot])):
        m=pre_metrics[offset+cand*block:offset+(cand+1)*block]; oi=rank_indices(m)[0]; best.append((cand,m[oi].copy()))
    am=np.asarray([x[1] for x in best]); order=rank_indices(am); chosen=[]; seen=set()
    b=cfg_index(cfgs[slot],BASELINE[slot]);chosen.append(b);seen.add(b)
    for fam in FAMILIES:
        ids=[j for j,(cand,_) in enumerate(best) if cfgs[slot][cand].family==fam]
        if ids:
            fm=np.asarray([am[j] for j in ids]); winner=best[ids[rank_indices(fm)[0]]][0]
            if winner not in seen:chosen.append(winner);seen.add(winner)
    for oi in order:
        cand=best[int(oi)][0]
        if cand not in seen:chosen.append(cand);seen.add(cand)
        if len(chosen)>=k:break
    return chosen[:k]


def choose_redline_k(rate,seconds_available,safety,max_shortlist,min_shortlist=4):
    safe=max(1,int(rate*seconds_available*safety));k=max_shortlist
    while k>min_shortlist and (k**5)*25>safe:k-=1
    return k,safe,(k**5)*25


def iter_joint_batches(shortlists,batch_size):
    it=itertools.product(*shortlists,range(5),range(5))
    while True:
        ch=list(itertools.islice(it,batch_size))
        if not ch:break
        yield np.asarray(ch,np.int16)


def merge_leaders(bc,bm,nc,nm,keep):
    cc=nc if bc is None else np.vstack([bc,nc]); mm=nm if bm is None else np.vstack([bm,nm]);o=rank_indices(mm)[:keep]
    return cc[o].copy(),mm[o].copy()


def stream_search(batches,banks,dyn,o,h,l,c,ons,cns,es,fs,pip,reg,keep,deadline,label):
    bc=bm=None; processed=0;t0=time.time()
    for bi,batch in enumerate(batches,1):
        if time.time()>=deadline:return bc,bm,processed,False
        m=simulate_many(batch,*banks[0],*banks[1],*banks[2],*banks[3],*banks[4],*dyn,o,h,l,c,ons,cns,es,fs,pip,reg)
        bc,bm=merge_leaders(bc,bm,batch,m,keep);processed+=len(batch)
        if bi==1 or bi%10==0:print(f"      {label}: {processed:,} | {processed/max(.001,time.time()-t0):,.0f}/sec",flush=True)
    return bc,bm,processed,True


def baseline_trade_ledger(combo,banks,dyn,daily,pip,eval_start_ns,fwd_start_ns,registry_limit):
    # Diagnostic Python ledger mirrors the baseline simulator in ordinary Python for forensic comparison.
    # It intentionally focuses on R2 baseline G+T, because certification must pass before generalized sweep.
    rows=[]
    cidx=[int(x) for x in combo[0,:5]]
    e=[banks[i][0][cidx[i]] for i in range(5)]; p=[banks[i][1][cidx[i]] for i in range(5)]; d=[banks[i][2][cidx[i]] for i in range(5)]
    dyn_dir,dyn_evt,dyn_price=dyn
    reg=[]; position=0;pending=None;exit_day=-1;guardian_confirmed=0;trade_no=0
    for t in range(len(daily)):
        for si in (0,2,3,4):
            typ=int(e[si][t])
            if typ:
                source=si+1; origin=t-1; price=float(p[si][t]); hit=next((j for j,x in enumerate(reg) if x[0]==source and x[1]==origin),None)
                item=(source,origin,typ,price)
                if hit is None:reg.append(item)
                else:reg[hit]=item
                reg=reg[-registry_limit:]
        o,h,l,c=[float(daily.loc[t,x]) for x in ("open","high","low","close")]; ticks=[o,h,l,c] if abs(o-h)<=abs(o-l) else [o,l,h,c]
        ons=int(daily.loc[t,"bar_open_ns"]);cns=int(daily.loc[t,"bar_close_ns"]);span=cns-ons
        for q,px in enumerate(ticks):
            tn=ons+span*q//3;g=int(dyn_dir[t,q]);
            if q==3 and g:guardian_confirmed=g
            gd=g or guardian_confirmed;td=int(dyn_dir[t,q]);rt=int(dyn_evt[t,q])
            if rt:
                origin=t-1;pr=float(dyn_price[t,q]);hit=next((j for j,x in enumerate(reg) if x[0]==2 and x[1]==origin),None);item=(2,origin,rt,pr)
                if hit is None:reg.append(item)
                else:reg[hit]=item
                reg=reg[-registry_limit:]
            if pending is not None and position==0 and (t>pending[4] or q>pending[5]):
                position=pending[0];ep=px;tgt=pending[1];signal_ns=pending[2];src=pending[3];entry_ns=tn;mae=0.0;pending=None
            if position:
                mae=max(mae,(ep-px)/pip if position==1 else (px-ep)/pip); reached=px>=tgt if position==1 else px<=tgt
                if reached:
                    pp=(px-ep)/pip if position==1 else (ep-px)/pip;trade_no+=1
                    rows.append({"trade":trade_no,"signal_time_utc":pd.to_datetime(signal_ns,utc=True),"entry_time_utc":pd.to_datetime(entry_ns,utc=True),"exit_time_utc":pd.to_datetime(tn,utc=True),"source":SLOT_ORDER[src-1],"side":"LONG" if position==1 else "SHORT","entry":ep,"target":tgt,"exit":px,"pips":pp,"mae_pips":mae,"hold_hours":(tn-entry_ns)/3.6e12,"latest_30d":tn>=fwd_start_ns})
                    position=0;exit_day=t;continue
            if tn<eval_start_ns or position or pending is not None or exit_day==t or not rt:continue
            cd=1 if rt==1 else -1
            if cd!=gd or cd!=td:continue
            tgt=next((x[3] for x in reversed(reg) if x[0]==2 and x[1]<t-1 and x[2]==-rt),np.nan)
            if np.isfinite(tgt) and ((tgt>px) if cd==1 else (tgt<px)):pending=(cd,tgt,tn,2,t,q)
    return pd.DataFrame(rows)


def main():
    print("="*72,flush=True);print(f"TGIM SWEEPER BUILD: {BUILD_ID}",flush=True);print("ARCHITECTURE: FIVE-R REDLINE PARITY v2.2 | SOURCE-KEYED SAME-R TARGETS | TICK-DYNAMIC 1D",flush=True);print("="*72,flush=True)
    ap=argparse.ArgumentParser();ap.add_argument("--instrument",default="EUR_USD");ap.add_argument("--env",choices=["practice","live"],default=os.getenv("OANDA_ENV","practice"));ap.add_argument("--token",default=os.getenv("OANDA_TOKEN",""));ap.add_argument("--history-days",type=int,default=190);ap.add_argument("--eval-days",type=int,default=120);ap.add_argument("--forward-days",type=int,default=30);ap.add_argument("--lengths",default="3,5,8,13,21,27,34");ap.add_argument("--registry-limit",type=int,default=27,choices=[20,27]);ap.add_argument("--expected-total",type=int,default=None);ap.add_argument("--expected-forward",type=int,default=None);ap.add_argument("--force-sweep",action="store_true");ap.add_argument("--runtime-hours",type=float,default=9.5);ap.add_argument("--budget-safety",type=float,default=.78);ap.add_argument("--benchmark-systems",type=int,default=12000);ap.add_argument("--max-shortlist",type=int,default=14);ap.add_argument("--batch-size",type=int,default=25000);ap.add_argument("--top",type=int,default=150);ap.add_argument("--refresh",action="store_true");ap.add_argument("--cache-dir",default="./tgim_sweeper_cache");ap.add_argument("--output-dir",default="./tgim_redline_results");args=ap.parse_args()
    start_wall=time.time();deadline=start_wall+args.runtime_hours*3600;inst=instrument_norm(args.instrument);lengths=tuple(sorted({int(x) for x in args.lengths.split(",")}));outdir=Path(args.output_dir)/inst/datetime.now().strftime("%Y%m%d_%H%M%S");outdir.mkdir(parents=True,exist_ok=True)
    end=datetime.now(timezone.utc);start=end-timedelta(days=args.history_days+7);client=OandaHistory(args.token,args.env,Path(args.cache_dir));raw={}
    print(f"[1/10] Fetching/caching OANDA {inst} W/D/M15/M5/M1 ...")
    for g in ("W","D","M15","M5","M1"):print("      ",g,"...",flush=True);raw[g]=client.candles(inst,g,start,end,args.refresh)
    daily=daily_execution_frame(raw["D"]);last=int(daily["bar_open_ns"].iloc[-1]);es=last-args.eval_days*86_400_000_000_000;fs=last-args.forward_days*86_400_000_000_000
    cfgs=coarse_cfgs(lengths);print(f"[2/10] Building {len(lengths)*4} rail candidates per R bay ...");banks=prepare_banks(raw,daily,cfgs);dyn=build_daily_dynamic_ema5(raw["D"],daily)
    o=daily.open.to_numpy(float);h=daily.high.to_numpy(float);l=daily.low.to_numpy(float);c=daily.close.to_numpy(float);ons=daily.bar_open_ns.to_numpy(np.int64);cns=daily.bar_close_ns.to_numpy(np.int64);pip=pip_size(inst);bc=baseline_combo(cfgs)
    print("[3/10] BASE certification ...");bm=simulate_many(bc,*banks[0],*banks[1],*banks[2],*banks[3],*banks[4],*dyn,o,h,l,c,ons,cns,es,fs,pip,args.registry_limit)[0];md=metric_dict(bm);et=args.expected_total if args.expected_total is not None else EXPECTED_TOTAL.get(inst);ef=args.expected_forward if args.expected_forward is not None else EXPECTED_FORWARD.get(inst)
    print("       BASE: R1 HMA5 RAW | R2 EMA5 RAW | R8 HMA27 RAW | R9 KS27 RAW | R10 KS27 RAW");print(f"       Guardian=R2 | Trigger=R2 | same-R=True | registry={args.registry_limit}");print(f"       120d closed/wins: {md['closed_120d']}/{md['wins_120d']}");print(f"       30d  closed/wins: {md['closed_30d']}/{md['wins_30d']}");print(f"       MAE {md['max_mae_pips_120d']:.2f} | longest {md['longest_days_120d']:.2f}d | avg {md['avg_hold_days_120d']:.2f}d | net {md['net_pips_120d']:.1f}")
    cert=(et is None or (md['closed_120d']==et and md['wins_120d']==et)) and (ef is None or (md['closed_30d']==ef and md['wins_30d']==ef));ledger=baseline_trade_ledger(bc,banks,dyn,daily,pip,es,fs,args.registry_limit);ledger.to_csv(outdir/"BASELINE_TRADE_LEDGER.csv",index=False);(outdir/"BASE_CERTIFICATION.json").write_text(json.dumps({"build":BUILD_ID,"metrics":md,"expected_total":et,"expected_forward":ef,"certified":cert},indent=2))
    if not cert and not args.force_sweep:
        print("\nBASE MISMATCH — REDLINE SWEEP ABORTED.");print(f"Baseline ledger rows: {len(ledger)} -> {outdir/'BASELINE_TRADE_LEDGER.csv'}");print("First 20 Python baseline trades:");print(ledger.head(20).to_string(index=False));return 2
    print("[4/10] Prescreening rail candidates × all 25 Guardian/Trigger pairs ...");pc=prescreen_combos(cfgs);pm=simulate_many(pc,*banks[0],*banks[1],*banks[2],*banks[3],*banks[4],*dyn,o,h,l,c,ons,cns,es,fs,pip,args.registry_limit)
    print("[5/10] Benchmarking Render ...");rng=np.random.default_rng(73027);bench=np.empty((args.benchmark_systems,7),np.int16)
    for si,s in enumerate(SLOT_ORDER):bench[:,si]=rng.integers(0,len(cfgs[s]),size=len(bench));bench[:,5]=rng.integers(0,5,size=len(bench));bench[:,6]=rng.integers(0,5,size=len(bench));t0=time.time();_=simulate_many(bench,*banks[0],*banks[1],*banks[2],*banks[3],*banks[4],*dyn,o,h,l,c,ons,cns,es,fs,pip,args.registry_limit);rate=len(bench)/max(.001,time.time()-t0);k,safe,planned=choose_redline_k(rate,max(60,deadline-time.time()),args.budget_safety,args.max_shortlist);print(f"       {rate:,.0f}/sec | safe {safe:,} | K={k} | planned {planned:,}")
    print("[6/10] Diversity shortlists ...");short=[diversity_shortlist(i,cfgs,pm,k) for i in range(5)]
    for i,s in enumerate(SLOT_ORDER):print("      ",s,":",", ".join(cfgs[s][x].label() for x in short[i]))
    print("[7/10] REDLINE joint search ...");jc,jm,processed,complete=stream_search(iter_joint_batches(short,args.batch_size),banks,dyn,o,h,l,c,ons,cns,es,fs,pip,args.registry_limit,args.top,deadline,"REDLINE");top=build_top_rows(jc,jm,cfgs,args.top);top.to_csv(outdir/"TOP_FOR_TRADINGVIEW_VERIFICATION.csv",index=False);print("[8/10] TOP 15");print(top.head(15).to_string(index=False));print("[9/10] Exact-length refinement reserved for post-parity promotion.");print("[10/10] Results:",outdir);return 0


if __name__=="__main__":raise SystemExit(main())
