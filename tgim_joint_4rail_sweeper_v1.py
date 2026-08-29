#!/usr/bin/env python3
"""
TGIM ROLE-FIRST PAIR SWEEPER v3.0
=================================

BUILD ID: TGIM-ROLE-FIRST-V3.0-20260829

Purpose
-------
The first optimization dimension for a new pair is Guardian Timeframe Source R
and Trigger Timeframe Source R.  Guardian/Trigger independent MA profiles are
FORCED OFF in this stage.  The selected role consumes the chosen R bay exactly.

This build deliberately does NOT aim for 51/51 on every instrument.  51/51
AUDUSD and 47/47 EURUSD are seed/reference profiles only.  Every pair is ranked
on its own results.

Default staged run
------------------
1) For each route seed (AUD51 and EUR47), test the four high-priority role pairs:
       G R1 / T R1
       G R1 / T R2
       G R2 / T R1
       G R2 / T R2
2) Expand Guardian x Trigger to all R1..R10 (100 combinations per seed).
   R3/R4/R5 are allowed as ROLE-ONLY sources using their seed math while their
   route rays remain OFF.  If one wins, the promotion file tells Pine to enable
   that R for calculation but keep its route rays OFF.
3) Rank each instrument independently:
       zero closed losses / 100% first
       then more closed trades
       then net pips
       then lower max MAE
       then shorter average hold

Fixed trade architecture for this stage
---------------------------------------
- Same TGIM pivot-ray -> previous-ray trade logic
- Any Route R
- One Leg Only
- Delayed Confirmation
- Historical turn registry 27 by default
- Clutter averaging OFF
- Per-R ADX gates OFF
- Guardian Break Definition = Guardian Direction Flip
- Guardian independent profile OFF
- Trigger independent profile OFF

Seed route profiles
-------------------
AUD51 (current AUDUSD 51/51 manual champion family):
    R1  1W   EMA2  RAW   route ON
    R2  1D   KS2   RAW   route ON
    R3  12H  HMA28 RAW   route OFF
    R4  8H   WMA9  RAW   route OFF
    R5  6H   KS27  RAW   route OFF
    R6  4H   HMA27 ZAG   route ON
    R7  1H   KS27  RAW   route ON
    R8  15m  KS27  RAW   route ON
    R9  5m   KS27  RAW   route ON
    R10 1m   KS2   RAW   route ON

EUR47 (EURUSD GT47 seed family):
    R1  1W   WMA2  RAW   route ON
    R2  1D   WMA2  RAW   route ON
    R3  12H  HMA28 RAW   route OFF
    R4  8H   WMA9  RAW   route OFF
    R5  6H   KS27  RAW   route OFF
    R6  4H   WMA2  RAW   route ON
    R7  1H   KS27  RAW   route ON
    R8  15m  KS28  RAW   route ON
    R9  5m   KS27  RAW   route ON
    R10 1m   KS5   RAW   route ON

Important
---------
This is a research/ranking program.  It cannot place orders.  TradingView Pine
remains the final promotion verifier.  The Python simulator intentionally keeps
this stage narrow: role-source discovery first, then later sweep stages mutate
route families/lengths/RAW-ZAG around the winning role relationship.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import requests

try:
    from numba import njit
except Exception as exc:
    raise SystemExit(f"numba is required: {exc}")

BUILD_ID = "TGIM-ROLE-FIRST-V3.0-20260829"
SLOTS = tuple(f"R{i}" for i in range(1, 11))
SLOT_INDEX = {s: i for i, s in enumerate(SLOTS)}
TF = {
    "R1": "W", "R2": "D", "R3": "H12", "R4": "H8", "R5": "H6",
    "R6": "H4", "R7": "H1", "R8": "M15", "R9": "M5", "R10": "M1",
}
TF_LABEL = {
    "R1":"1W","R2":"1D","R3":"12H","R4":"8H","R5":"6H",
    "R6":"4H","R7":"1H","R8":"15m","R9":"5m","R10":"1m",
}
MAX_REGISTRY = 128


@dataclass(frozen=True)
class RSpec:
    family: str
    length: int
    working: str = "RAW"
    route: bool = False


@dataclass(frozen=True)
class SeedProfile:
    name: str
    rails: Dict[str, RSpec]


AUD51 = SeedProfile("AUD51", {
    "R1": RSpec("EMA",2,"RAW",True),
    "R2": RSpec("KS",2,"RAW",True),
    "R3": RSpec("HMA",28,"RAW",False),
    "R4": RSpec("WMA",9,"RAW",False),
    "R5": RSpec("KS",27,"RAW",False),
    "R6": RSpec("HMA",27,"ZAG",True),
    "R7": RSpec("KS",27,"RAW",True),
    "R8": RSpec("KS",27,"RAW",True),
    "R9": RSpec("KS",27,"RAW",True),
    "R10": RSpec("KS",2,"RAW",True),
})

EUR47 = SeedProfile("EUR47", {
    "R1": RSpec("WMA",2,"RAW",True),
    "R2": RSpec("WMA",2,"RAW",True),
    "R3": RSpec("HMA",28,"RAW",False),
    "R4": RSpec("WMA",9,"RAW",False),
    "R5": RSpec("KS",27,"RAW",False),
    "R6": RSpec("WMA",2,"RAW",True),
    "R7": RSpec("KS",27,"RAW",True),
    "R8": RSpec("KS",28,"RAW",True),
    "R9": RSpec("KS",27,"RAW",True),
    "R10": RSpec("KS",5,"RAW",True),
})

SEEDS = {"AUD51": AUD51, "EUR47": EUR47}


def instrument_norm(raw: str) -> str:
    s = raw.upper().replace("OANDA:", "").replace("/", "_").replace("-", "_")
    if "_" not in s and len(s) == 6:
        s = s[:3] + "_" + s[3:]
    if len(s) != 7 or s[3] != "_":
        raise ValueError(f"Bad instrument: {raw!r}")
    return s


def pair_key(inst: str) -> str:
    return inst.replace("_", "")


def pip_size(inst: str) -> float:
    return 0.01 if inst.endswith("_JPY") else 0.0001


class OandaHistory:
    def __init__(self, token: str, env: str, cache_dir: Path, timeout: float = 20.0):
        if not token:
            raise ValueError("OANDA_TOKEN is empty. Set it or pass --token.")
        self.base = "https://api-fxpractice.oanda.com" if env == "practice" else "https://api-fxtrade.oanda.com"
        self.timeout = timeout
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Accept-Datetime-Format": "RFC3339"})

    def _request(self, path: str, params: dict) -> dict:
        last = None
        for attempt in range(6):
            try:
                r = self.s.get(self.base + path, params=params, timeout=self.timeout)
                if r.status_code == 429:
                    time.sleep(min(8.0, 0.75 * (2 ** attempt)))
                    continue
                if r.status_code >= 400:
                    raise RuntimeError(f"OANDA HTTP {r.status_code}: {(r.text or '')[:800]} | {r.url}")
                return r.json()
            except Exception as exc:
                last = exc
                time.sleep(min(5.0, 0.5 * (2 ** attempt)))
        raise RuntimeError(f"OANDA request failed: {last}")

    def candles(self, instrument: str, granularity: str, start: datetime, end: datetime, refresh: bool=False) -> pd.DataFrame:
        key = f"{instrument}_{granularity}_{start:%Y%m%d}_{end:%Y%m%d}.csv.gz"
        fp = self.cache_dir / key
        if fp.exists() and not refresh:
            df = pd.read_csv(fp, compression="gzip")
            df["time"] = pd.to_datetime(df["time"], utc=True)
            return df

        dur_sec = {"M1":60,"M5":300,"M15":900,"H1":3600,"H4":14400,"H6":21600,"H8":28800,"H12":43200,"D":86400,"W":604800}
        rows = []
        cursor = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)
        path = f"/v3/instruments/{instrument}/candles"
        while cursor < end:
            params = {
                "price":"M","granularity":granularity,
                "from":cursor.isoformat().replace("+00:00","Z"),
                "count":5000,"includeFirst":"true","smooth":"false",
            }
            if granularity == "D":
                params.update({"dailyAlignment":17,"alignmentTimezone":"America/New_York"})
            elif granularity == "W":
                params.update({"weeklyAlignment":"Friday","alignmentTimezone":"America/New_York"})
            data = self._request(path, params)
            cs = data.get("candles", [])
            if not cs:
                break
            last_time = None
            for c in cs:
                t = pd.Timestamp(c["time"])
                t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
                if t.to_pydatetime() > end:
                    continue
                m = c.get("mid") or {}
                rows.append({
                    "time":t,"open":float(m.get("o","nan")),"high":float(m.get("h","nan")),
                    "low":float(m.get("l","nan")),"close":float(m.get("c","nan")),
                    "volume":int(c.get("volume",0) or 0),"complete":bool(c.get("complete",False)),
                })
                last_time = t
            if last_time is None:
                break
            nxt = last_time.to_pydatetime() + timedelta(seconds=dur_sec[granularity])
            if nxt <= cursor:
                break
            cursor = nxt
            if len(cs) < 5000:
                break
        if not rows:
            raise RuntimeError(f"No {granularity} candles returned for {instrument}")
        df = pd.DataFrame(rows).drop_duplicates("time", keep="last").sort_values("time").reset_index(drop=True)
        df.to_csv(fp, index=False, compression="gzip")
        return df


# ── Pine rail math ───────────────────────────────────────────────────────────
def ema_np(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan, dtype=np.float64)
    a = 2.0/(n+1.0)
    seed = np.nan
    for i,v in enumerate(x):
        if not np.isfinite(v):
            continue
        seed = v if not np.isfinite(seed) else a*v + (1-a)*seed
        out[i] = seed
    return out


def wma_np(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan, dtype=np.float64)
    if n <= 0: return out
    w = np.arange(1.0, n+1.0); den = w.sum()
    for i in range(n-1, len(x)):
        y = x[i-n+1:i+1]
        if np.all(np.isfinite(y)): out[i] = np.dot(y,w)/den
    return out


def linreg_np(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan, dtype=np.float64)
    if n <= 1:
        out[:] = x; return out
    xs = np.arange(n,dtype=np.float64); sx=xs.sum(); sxx=np.dot(xs,xs); den=n*sxx-sx*sx
    for i in range(n-1,len(x)):
        y=x[i-n+1:i+1]
        if not np.all(np.isfinite(y)): continue
        sy=y.sum(); sxy=np.dot(xs,y); slope=(n*sxy-sx*sy)/den; intercept=(sy-slope*sx)/n
        out[i]=intercept+slope*(n-1)
    return out


def hma_np(x: np.ndarray, n: int) -> np.ndarray:
    half=max(1,int(math.floor(n/2.0+0.5))); root=max(1,int(math.floor(math.sqrt(n)+0.5)))
    return wma_np(2.0*wma_np(x,half)-wma_np(x,n), root)


def rail_np(x: np.ndarray, family: str, n: int) -> np.ndarray:
    if family=="EMA": return ema_np(x,n)
    if family=="WMA": return wma_np(x,n)
    if family=="KS": return linreg_np(x,n)
    if family=="HMA": return hma_np(x,n)
    raise ValueError(family)


def daily_execution_frame(d: pd.DataFrame) -> pd.DataFrame:
    d=d.sort_values("time").reset_index(drop=True).copy(); d["next_time"]=d["time"].shift(-1)
    d=d.loc[d["complete"].astype(bool) & d["next_time"].notna()].copy().reset_index(drop=True)
    d["bar_open_ns"]=d["time"].astype("int64"); d["bar_close_ns"]=d["next_time"].astype("int64")
    return d


def _daily_ticks(daily: pd.DataFrame) -> np.ndarray:
    o=daily.open.to_numpy(float); h=daily.high.to_numpy(float); l=daily.low.to_numpy(float); c=daily.close.to_numpy(float)
    out=np.empty((len(daily),4),dtype=np.float64)
    for t in range(len(daily)):
        out[t,0]=o[t]
        if abs(o[t]-h[t]) <= abs(o[t]-l[t]): out[t,1],out[t,2]=h[t],l[t]
        else: out[t,1],out[t,2]=l[t],h[t]
        out[t,3]=c[t]
    return out


def _wma_last_override(close,t,px,n):
    if t<n-1: return np.nan
    vals=np.empty(n); vals[:-1]=close[t-n+1:t] if n>1 else []; vals[-1]=px
    if not np.all(np.isfinite(vals)): return np.nan
    w=np.arange(1.0,n+1.0); return float(np.dot(vals,w)/w.sum())


def _linreg_last_override(close,t,px,n):
    if n<=1: return float(px)
    if t<n-1: return np.nan
    y=np.empty(n); y[:-1]=close[t-n+1:t]; y[-1]=px
    if not np.all(np.isfinite(y)): return np.nan
    xs=np.arange(n,dtype=float); sx=xs.sum(); sxx=np.dot(xs,xs); den=n*sxx-sx*sx
    sy=y.sum(); sxy=np.dot(xs,y); slope=(n*sxy-sx*sy)/den; intercept=(sy-slope*sx)/n
    return float(intercept+slope*(n-1))


def _daily_tick_rail(close, final_rail, raw_hma, spec: RSpec, t, px):
    n=spec.length
    if spec.family=="EMA":
        if t==0 or not np.isfinite(final_rail[t-1]): return float(px)
        a=2.0/(n+1.0); return float(a*px+(1-a)*final_rail[t-1])
    if spec.family=="WMA": return _wma_last_override(close,t,px,n)
    if spec.family=="KS": return _linreg_last_override(close,t,px,n)
    half=max(1,int(math.floor(n/2.0+0.5))); root=max(1,int(math.floor(math.sqrt(n)+0.5)))
    a=_wma_last_override(close,t,px,half); b=_wma_last_override(close,t,px,n)
    if not np.isfinite(a) or not np.isfinite(b): return np.nan
    raw=2*a-b
    if root==1: return float(raw)
    if raw_hma is None or t<root-1: return np.nan
    vals=np.empty(root); vals[:-1]=raw_hma[t-root+1:t]; vals[-1]=raw
    if not np.all(np.isfinite(vals)): return np.nan
    w=np.arange(1.0,root+1.0); return float(np.dot(vals,w)/w.sum())


def daily_slot_arrays(daily: pd.DataFrame, spec: RSpec):
    close=daily.close.to_numpy(float); ticks=_daily_ticks(daily); nd=len(daily)
    evt=np.zeros((nd,4),np.int8); price=np.full((nd,4),np.nan); direction=np.zeros((nd,4),np.int8)
    final=rail_np(close,spec.family,spec.length); raw_hma=None
    if spec.family=="HMA":
        half=max(1,int(math.floor(spec.length/2.0+0.5)))
        raw_hma=2*wma_np(close,half)-wma_np(close,spec.length)
    last_meaningful=0
    for t in range(1,nd):
        prev=final[t-1]; prevprev=final[t-2] if t>=2 else np.nan
        if not np.isfinite(prev): continue
        for q in range(4):
            cur=_daily_tick_rail(close,final,raw_hma,spec,t,ticks[t,q])
            if not np.isfinite(cur): continue
            d=1 if cur>prev else -1 if cur<prev else 0
            if d!=0: last_meaningful=d
            # ZAG direction is the current raw last meaningful direction in this Pine architecture.
            direction[t,q]=last_meaningful if spec.working=="ZAG" else d
            price[t,q]=prev
            if t>=2 and np.isfinite(prevprev):
                if cur>prev and prev<=prevprev: evt[t,q]=1
                elif cur<prev and prev>=prevprev: evt[t,q]=-1
    commit=np.zeros((nd,4),np.bool_); commit[:,0]=True
    return evt,price,direction,commit


def sample_static_to_daily(source: pd.DataFrame, rail: np.ndarray, daily: pd.DataFrame, granularity: str):
    nd=len(daily); cur=np.full(nd,np.nan); inv=np.full(nd,np.nan); idx=np.full(nd,-1,np.int32)
    src=source.sort_values("time").reset_index(drop=True); st=pd.to_datetime(src.time,utc=True).astype("int64").to_numpy()
    complete=src.complete.astype(bool).to_numpy()
    if granularity=="W":
        next_start=np.full(len(st),np.iinfo(np.int64).max,dtype=np.int64)
        if len(st)>1: next_start[:-1]=st[1:]
        valid=np.flatnonzero(complete & (next_start!=np.iinfo(np.int64).max)); closes=next_start[valid]
    else:
        dur={"H1":3600,"H4":14400,"H6":21600,"H8":28800,"H12":43200,"M15":900,"M5":300,"M1":60}[granularity]*1_000_000_000
        valid=np.flatnonzero(complete); closes=st[valid]+dur
    for j in range(nd):
        boundary=int(daily.loc[j,"bar_close_ns"]); pos=np.searchsorted(closes,boundary,side="right")-1
        if pos>=0:
            k=int(valid[pos]); idx[j]=k; cur[j]=rail[k]; inv[j]=rail[k-1] if k>0 else np.nan
    return cur,inv,idx


def static_slot_arrays(source: pd.DataFrame, daily: pd.DataFrame, granularity: str, spec: RSpec):
    close=source.close.to_numpy(float); r=rail_np(close,spec.family,spec.length)
    cur,inv,idx=sample_static_to_daily(source,r,daily,granularity); nd=len(daily)
    evt=np.zeros((nd,4),np.int8); price=np.full((nd,4),np.nan); rawdir=np.zeros((nd,4),np.int8)
    last_meaningful=0
    for t in range(nd):
        prev_cur=cur[t-1] if t>=1 else np.nan; prev_inv=inv[t-1] if t>=1 else np.nan
        for q in range(4):
            if granularity=="W" and t>=1 and idx[t]!=idx[t-1] and q<3:
                tc,ti=cur[t-1],inv[t-1]
            else:
                tc,ti=cur[t],inv[t]
            if not (np.isfinite(tc) and np.isfinite(ti)): continue
            d=1 if tc>ti else -1 if tc<ti else 0
            if d!=0: last_meaningful=d
            rawdir[t,q]=last_meaningful if spec.working=="ZAG" else d
            price[t,q]=ti
            if t>=1 and np.isfinite(prev_cur) and np.isfinite(prev_inv):
                if tc>ti and prev_cur<=prev_inv: evt[t,q]=1
                elif tc<ti and prev_cur>=prev_inv: evt[t,q]=-1
    commit=np.zeros((nd,4),np.bool_)
    if granularity=="W":
        for t in range(1,nd):
            if idx[t]>=0 and idx[t]!=idx[t-1]: commit[t,0]=True
    else:
        commit[:,0]=True
    return evt,price,rawdir,commit


def prepare_seed_arrays(raw: Dict[str,pd.DataFrame], daily: pd.DataFrame, seed: SeedProfile):
    nd=len(daily)
    evt=np.zeros((10,nd,4),np.int8); price=np.full((10,nd,4),np.nan); dirs=np.zeros((10,nd,4),np.int8); commits=np.zeros((10,nd,4),np.bool_)
    route=np.zeros(10,np.bool_)
    for si,slot in enumerate(SLOTS):
        spec=seed.rails[slot]; route[si]=spec.route
        if TF[slot]=="D": e,p,d,cm=daily_slot_arrays(daily,spec)
        else: e,p,d,cm=static_slot_arrays(raw[TF[slot]],daily,TF[slot],spec)
        evt[si]=e; price[si]=p; dirs[si]=d; commits[si]=cm
    return evt,price,dirs,commits,route


# ── TGIM one-leg delayed-confirmation simulator ──────────────────────────────
@njit(cache=True)
def _tv_path(o,h,l,c):
    z=np.empty(4,np.float64); z[0]=o
    if abs(o-h)<=abs(o-l): z[1],z[2]=h,l
    else: z[1],z[2]=l,h
    z[3]=c; return z


@njit(cache=True)
def _store_turn(reg_price,reg_type,reg_bar,reg_source,count,price,typ,bar,source,limit):
    for k in range(count-1,-1,-1):
        if reg_source[k]==source and reg_bar[k]==bar:
            reg_price[k]=price; reg_type[k]=typ; return count
    if count<limit:
        reg_price[count]=price; reg_type[count]=typ; reg_bar[count]=bar; reg_source[count]=source; return count+1
    for k in range(limit-1):
        reg_price[k]=reg_price[k+1]; reg_type[k]=reg_type[k+1]; reg_bar[k]=reg_bar[k+1]; reg_source[k]=reg_source[k+1]
    reg_price[limit-1]=price; reg_type[limit-1]=typ; reg_bar[limit-1]=bar; reg_source[limit-1]=source
    return limit


@njit(cache=True)
def _find_target(reg_price,reg_type,reg_bar,reg_source,count,wanted_type,current_bar,route_on):
    for k in range(count-1,-1,-1):
        s=reg_source[k]
        if route_on[s] and reg_bar[k] < current_bar and reg_type[k]==wanted_type:
            return reg_price[k]
    return np.nan


@njit(cache=True)
def _simulate_role_pair(guardian,trigger,evt,ray_price,dirs,commits,route_on,o,h,l,c,open_ns,close_ns,eval_start_ns,fwd_start_ns,pip,registry_limit):
    nd=len(c); day_ns=86_400_000_000_000
    reg_price=np.empty(MAX_REGISTRY,np.float64); reg_type=np.empty(MAX_REGISTRY,np.int8); reg_bar=np.empty(MAX_REGISTRY,np.int32); reg_source=np.empty(MAX_REGISTRY,np.int8); reg_count=0
    position=0; entry_price=0.0; target=np.nan; entry_ns=0; mae=0.0
    order_pending=0; order_target=np.nan; signal_day=-1; signal_tick=-1
    guard_last=0; guard_committed=0; exit_day=-1
    armed=False; armed_dir=0; armed_source=0; armed_type=0; armed_target=np.nan
    entries=closed=wins=0; entries30=closed30=wins30=0; net=net30=0.0; max_mae=0.0; longest=0.0; hold_sum=0.0

    for t in range(nd):
        ticks=_tv_path(o[t],h[t],l[t],c[t]); span=close_ns[t]-open_ns[t]
        if span<=0: span=day_ns
        for q in range(4):
            px=ticks[q]; tick_ns=open_ns[t]+(span*q)//3
            gd=int(dirs[guardian,t,q]); td=int(dirs[trigger,t,q])
            if gd!=0: guard_last=gd
            if commits[guardian,t,q] and gd!=0: guard_committed=gd

            # Store raw route-ray events in R order; role-only rails never cast route rays.
            event_sources=np.empty(10,np.int8); event_types=np.empty(10,np.int8); event_count=0
            for s in range(10):
                typ=int(evt[s,t,q])
                if typ!=0 and route_on[s]:
                    rp=ray_price[s,t,q]
                    if np.isfinite(rp):
                        reg_count=_store_turn(reg_price,reg_type,reg_bar,reg_source,reg_count,rp,typ,t-1,s,registry_limit)
                        event_sources[event_count]=s; event_types[event_count]=typ; event_count+=1

            # Next-tick market fill.
            if order_pending!=0 and ((t>signal_day) or (t==signal_day and q>signal_tick)) and position==0:
                position=order_pending; entry_price=px; target=order_target; entry_ns=tick_ns; mae=0.0
                if tick_ns>=eval_start_ns: entries+=1
                if tick_ns>=fwd_start_ns: entries30+=1
                order_pending=0; order_target=np.nan; signal_day=-1; signal_tick=-1

            # Historical target market exit.
            if position!=0:
                adverse=(entry_price-px)/pip if position==1 else (px-entry_price)/pip
                if adverse>mae: mae=adverse
                reached=px>=target if position==1 else px<=target
                if reached:
                    pnl=(px-entry_price)/pip if position==1 else (entry_price-px)/pip
                    hold=max(0.0,(tick_ns-entry_ns)/float(day_ns))
                    if tick_ns>=eval_start_ns:
                        closed+=1; wins += 1 if pnl>0 else 0; net+=pnl; max_mae=max(max_mae,mae); longest=max(longest,hold); hold_sum+=hold
                    if tick_ns>=fwd_start_ns:
                        closed30+=1; wins30 += 1 if pnl>0 else 0; net30+=pnl
                    position=0; entry_price=0.0; target=np.nan; entry_ns=0; mae=0.0; exit_day=t
                    continue

            # A new finalized pivot supersedes an older delayed arm before qualification.
            if event_count>0 and armed:
                armed=False

            can_enter = tick_ns>=eval_start_ns and position==0 and order_pending==0 and exit_day!=t
            submitted=False
            if can_enter and event_count>0:
                for ei in range(event_count):
                    src=int(event_sources[ei]); typ=int(event_types[ei]); cand=1 if typ==1 else -1
                    # Current Guardian bias + committed direction-flip protection.
                    guardian_ok=(guard_last==cand and guard_committed==cand)
                    tgt=_find_target(reg_price,reg_type,reg_bar,reg_source,reg_count,-typ,t-1,route_on)
                    ahead=np.isfinite(tgt) and ((tgt>px) if cand==1 else (tgt<px))
                    if not guardian_ok or not ahead:
                        continue
                    if td==cand:
                        order_pending=cand; order_target=tgt; signal_day=t; signal_tick=q; submitted=True
                        break
                    else:
                        # Delayed Confirmation: Guardian-valid pivot arms while Trigger retraces/flat.
                        armed=True; armed_dir=cand; armed_source=src; armed_type=typ; armed_target=tgt
                        break

            # Delayed follow-through if nothing was submitted by a newer event.
            if can_enter and (not submitted) and armed:
                ahead=np.isfinite(armed_target) and ((armed_target>px) if armed_dir==1 else (armed_target<px))
                if not ahead:
                    armed=False
                elif guard_last==armed_dir and guard_committed==armed_dir and td==armed_dir:
                    order_pending=armed_dir; order_target=armed_target; signal_day=t; signal_tick=q; armed=False

    avg_hold=hold_sum/closed if closed>0 else 9999.0
    losses=closed-wins; losses30=closed30-wins30
    out=np.empty(14,np.float64)
    out[:] = [entries,closed,wins,losses,net,max_mae,longest,avg_hold,entries30,closed30,wins30,losses30,net30,1 if (position!=0 or order_pending!=0) else 0]
    return out


def metric_row(seed: str, g: str, tr: str, m: np.ndarray, role_only_flags: Dict[str,bool]) -> dict:
    closed=int(m[1]); wins=int(m[2]); losses=int(m[3]); closed30=int(m[9]); wins30=int(m[10]); losses30=int(m[11])
    wr=100.0*wins/closed if closed else 0.0
    return {
        "seed":seed,"guardian":g,"trigger":tr,"same_guard_trigger":g==tr,
        "guardian_role_only":bool(role_only_flags.get(g,False)),"trigger_role_only":bool(role_only_flags.get(tr,False)),
        "closed_120d":closed,"wins_120d":wins,"losses_120d":losses,"win_rate_120d":wr,
        "net_pips_120d":float(m[4]),"max_mae_pips_120d":float(m[5]),"longest_days_120d":float(m[6]),"avg_hold_days_120d":float(m[7]),
        "closed_30d":closed30,"wins_30d":wins30,"losses_30d":losses30,"net_pips_30d":float(m[12]),"open_or_pending_end":int(m[13]),
        "sample_quality":sample_quality(closed),
    }


def sample_quality(n: int) -> str:
    if n>=80: return "VERY STRONG"
    if n>=40: return "STRONG"
    if n>=15: return "DEVELOPING"
    if n>0: return "SMALL SAMPLE"
    return "NO SAMPLE"


def rank_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty: return df
    z=df.copy()
    z["perfect"]=(z.losses_120d==0) & (z.closed_120d>0)
    z=z.sort_values(
        ["perfect","win_rate_120d","closed_120d","net_pips_120d","max_mae_pips_120d","avg_hold_days_120d","closed_30d"],
        ascending=[False,False,False,False,True,True,False], kind="mergesort"
    ).reset_index(drop=True)
    z.insert(0,"rank",np.arange(1,len(z)+1))
    return z


def role_pairs(scope: str, route_on: np.ndarray) -> List[Tuple[str,str]]:
    if scope=="priority":
        universe=("R1","R2")
    elif scope=="active":
        universe=tuple(SLOTS[i] for i in range(10) if route_on[i])
    else:
        universe=SLOTS
    return [(g,t) for g in universe for t in universe]


def seed_manifest(seed: SeedProfile) -> dict:
    return {slot:{"tf":TF_LABEL[slot],**asdict(seed.rails[slot])} for slot in SLOTS}


def run_seed(seed: SeedProfile, arrays, daily, inst, eval_start_ns, fwd_start_ns, registry_limit, scope: str) -> pd.DataFrame:
    evt,ray_price,dirs,commits,route_on=arrays
    o=daily.open.to_numpy(float); h=daily.high.to_numpy(float); l=daily.low.to_numpy(float); c=daily.close.to_numpy(float)
    ons=daily.bar_open_ns.to_numpy(np.int64); cns=daily.bar_close_ns.to_numpy(np.int64); pip=pip_size(inst)
    role_only={slot:(not seed.rails[slot].route) for slot in SLOTS}
    rows=[]
    for g,tr in role_pairs(scope,route_on):
        m=_simulate_role_pair(SLOT_INDEX[g],SLOT_INDEX[tr],evt,ray_price,dirs,commits,route_on,o,h,l,c,ons,cns,eval_start_ns,fwd_start_ns,pip,registry_limit)
        rows.append(metric_row(seed.name,g,tr,m,role_only))
    return rank_df(pd.DataFrame(rows))


def parse_args():
    p=argparse.ArgumentParser(description="TGIM role-first Guardian/Trigger source sweeper")
    p.add_argument("--instrument",required=False,default="EUR_USD")
    p.add_argument("--token",default=os.getenv("OANDA_TOKEN", ""))
    p.add_argument("--env",choices=["practice","live"],default=os.getenv("OANDA_ENV","practice"))
    p.add_argument("--seed",choices=["both","AUD51","EUR47"],default="both")
    p.add_argument("--eval-days",type=int,default=120)
    p.add_argument("--forward-days",type=int,default=30)
    p.add_argument("--warmup-days",type=int,default=90)
    p.add_argument("--registry-limit",type=int,default=27)
    p.add_argument("--expanded-scope",choices=["active","all10"],default="all10")
    p.add_argument("--skip-expanded",action="store_true")
    p.add_argument("--refresh",action="store_true")
    p.add_argument("--cache-dir",default="./cache")
    p.add_argument("--result-dir",default="")
    p.add_argument("--self-test",action="store_true")
    return p.parse_args()


def self_test() -> int:
    # Exercise the JIT simulator on deterministic synthetic arrays.
    nd=20; evt=np.zeros((10,nd,4),np.int8); rp=np.full((10,nd,4),np.nan); dirs=np.ones((10,nd,4),np.int8); cm=np.zeros((10,nd,4),np.bool_); cm[:,:,0]=True
    route=np.zeros(10,np.bool_); route[0]=route[1]=True
    for t in (3,6,9,12,15):
        typ=1 if (t//3)%2 else -1
        evt[0,t,0]=typ; rp[0,t,0]=1.0 + 0.01*t
    x=np.linspace(1.0,1.3,nd); o=x.copy(); h=x+0.01; l=x-0.01; c=x+0.005
    ons=np.arange(nd,dtype=np.int64)*86_400_000_000_000; cns=ons+86_400_000_000_000
    m=_simulate_role_pair(0,0,evt,rp,dirs,cm,route,o,h,l,c,ons,cns,0,ons[-5],0.0001,27)
    print("SELF TEST OK", m.tolist()); return 0


def main() -> int:
    args=parse_args()
    if args.self_test: return self_test()
    inst=instrument_norm(args.instrument)
    if args.forward_days<=0 or args.eval_days<=0 or args.forward_days>args.eval_days:
        raise SystemExit("Require 0 < forward-days <= eval-days")
    if args.registry_limit<3 or args.registry_limit>MAX_REGISTRY:
        raise SystemExit(f"registry-limit must be 3..{MAX_REGISTRY}")

    now=datetime.now(timezone.utc)
    start=now-timedelta(days=args.eval_days+args.warmup_days+30)
    end=now+timedelta(days=1)
    cache=Path(args.cache_dir)
    hist=OandaHistory(args.token,args.env,cache)

    print(f"TGIM ROLE-FIRST v3.0 | {inst}")
    print("[1/6] Fetching fixed R1-R10 timeframe history ...")
    raw={}
    for gran in sorted(set(TF.values()), key=lambda x:(x!="D",x)):
        raw[gran]=hist.candles(inst,gran,start,end,args.refresh)
        print(f"      {gran:>3}: {len(raw[gran]):,} candles")
    daily=daily_execution_frame(raw["D"])
    if len(daily)<20: raise SystemExit("Not enough complete Daily bars")
    last_close_ns=int(daily.bar_close_ns.iloc[-1])
    eval_start_ns=last_close_ns-args.eval_days*86_400_000_000_000
    fwd_start_ns=last_close_ns-args.forward_days*86_400_000_000_000

    selected=[AUD51,EUR47] if args.seed=="both" else [SEEDS[args.seed]]
    outdir=Path(args.result_dir) if args.result_dir else Path("results")/f"{inst}_{BUILD_ID}"
    outdir.mkdir(parents=True,exist_ok=True)

    print("[2/6] Preparing seed rail/event arrays ...")
    arrays={s.name:prepare_seed_arrays(raw,daily,s) for s in selected}

    print("[3/6] PRIORITY role sweep: R1/R2 x R1/R2, independent profiles OFF ...")
    pri=[]
    for s in selected:
        d=run_seed(s,arrays[s.name],daily,inst,eval_start_ns,fwd_start_ns,args.registry_limit,"priority")
        pri.append(d)
    priority=rank_df(pd.concat(pri,ignore_index=True))
    priority.to_csv(outdir/"STAGE1_PRIORITY_R1_R2.csv",index=False)
    print(priority[["rank","seed","guardian","trigger","closed_120d","wins_120d","losses_120d","win_rate_120d","closed_30d","net_pips_120d"]].head(12).to_string(index=False))

    expanded=priority
    if not args.skip_expanded:
        print(f"[4/6] EXPANDED role sweep: {args.expanded_scope} Guardian x Trigger ...")
        allrows=[]
        for s in selected:
            d=run_seed(s,arrays[s.name],daily,inst,eval_start_ns,fwd_start_ns,args.registry_limit,args.expanded_scope)
            allrows.append(d)
        expanded=rank_df(pd.concat(allrows,ignore_index=True))
        expanded.to_csv(outdir/"STAGE1_EXPANDED_GUARD_TRIGGER.csv",index=False)
        print(expanded[["rank","seed","guardian","trigger","guardian_role_only","trigger_role_only","closed_120d","wins_120d","losses_120d","win_rate_120d","closed_30d","net_pips_120d"]].head(20).to_string(index=False))
    else:
        print("[4/6] Expanded sweep skipped by request.")

    print("[5/6] Writing pair-profile promotion package ...")
    best=expanded.iloc[0].to_dict()
    best_seed=SEEDS[str(best["seed"])]
    promotion={
        "build_id":BUILD_ID,
        "instrument":inst,
        "pair_key":pair_key(inst),
        "stage":"GUARD_TRIGGER_SOURCE_FIRST",
        "guardian_independent_profile":False,
        "trigger_independent_profile":False,
        "guardian_source":str(best["guardian"]),
        "trigger_source":str(best["trigger"]),
        "same_guard_trigger":bool(best["same_guard_trigger"]),
        "role_only_enable_required":sorted(set([
            x for x,flag in ((str(best["guardian"]),bool(best["guardian_role_only"])),(str(best["trigger"]),bool(best["trigger_role_only"]))) if flag
        ])),
        "seed_route_profile":best_seed.name,
        "route_profile":seed_manifest(best_seed),
        "trade_contract":{
            "target_scope":"Any Route R","after_target_exit":"One Leg Only","entry_qualification":"Delayed Confirmation",
            "historical_turns":args.registry_limit,"clutter":False,"adx_gates":False,"guardian_break":"Guardian Direction Flip"
        },
        "metrics":{
            k:(int(best[k]) if k.startswith(("closed","wins","losses","open")) else float(best[k]))
            for k in ["closed_120d","wins_120d","losses_120d","win_rate_120d","net_pips_120d","max_mae_pips_120d","longest_days_120d","avg_hold_days_120d","closed_30d","wins_30d","losses_30d","net_pips_30d","open_or_pending_end"]
        },
        "sample_quality":str(best["sample_quality"]),
        "next_stage":"Freeze winning Guardian/Trigger relationship, then sweep active route bays / MA family / length / RAW-ZAG around this pair-specific winner.",
        "tradingview_verification_required":True,
    }
    (outdir/"PAIR_PROFILE_PROMOTION.json").write_text(json.dumps(promotion,indent=2))
    expanded.head(50).to_csv(outdir/"TOP50_ROLE_SOURCE_CANDIDATES.csv",index=False)
    (outdir/"SEED_PROFILES.json").write_text(json.dumps({s.name:seed_manifest(s) for s in selected},indent=2))
    manifest={
        "build_id":BUILD_ID,"instrument":inst,"eval_days":args.eval_days,"forward_days":args.forward_days,
        "registry_limit":args.registry_limit,"seeds":[s.name for s in selected],"expanded_scope":args.expanded_scope,
        "priority_tests":len(priority),"expanded_tests":len(expanded),"result_dir":str(outdir),
    }
    (outdir/"RUN_MANIFEST.json").write_text(json.dumps(manifest,indent=2))

    print("[6/6] DONE")
    print(f"      Winner: {best_seed.name} | Guardian {best['guardian']} | Trigger {best['trigger']} | {int(best['wins_120d'])}/{int(best['closed_120d'])} | {float(best['win_rate_120d']):.2f}%")
    if promotion["role_only_enable_required"]:
        print("      Role-only R enable required (route rays remain OFF): " + ", ".join(promotion["role_only_enable_required"]))
    print(f"      Results: {outdir}")
    print("      This pair is NOT required to match AUDUSD 51/51 or EURUSD 47/47. It wins on its own statistics.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
