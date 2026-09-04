#!/usr/bin/env python3
"""TGIM nested R-ZAG gearbox research — Forex/OANDA.

Tests arbitrary parent/child R pairs using causal bar-close ZAG turns, then compares:
  parent-only baseline vs netting gearbox (trim -> reload -> optional boost).

Data sources:
  --csv path.csv         Preferred for exact reproducibility.
  OANDA candle REST API  Used when --csv is omitted and OANDA_TOKEN is present.

This is research code. It does not place trades.
"""
import os, argparse, math, json
from pathlib import Path
import numpy as np
import pandas as pd
import requests

R_TF={"R1":"1W","R2":"1D","R3":"12H","R4":"8H","R5":"6H","R6":"4H","R7":"1H","R11":"30min","R8":"15min","R9":"5min","R10":"1min"}
TF_RULE={"1W":"W","1D":"1D","12H":"12h","8H":"8h","6H":"6h","4H":"4h","1H":"1h","30min":"30min","15min":"15min","5min":"5min","1min":"1min"}
DEFAULT_GEOM={"R1":("WMA",2),"R2":("WMA",2),"R3":("HMA",28),"R4":("WMA",9),"R5":("KS",27),"R6":("WMA",2),"R7":("KS",27),"R11":("EMA",2),"R8":("KS",28),"R9":("KS",27),"R10":("KS",5)}
OANDA_SPREAD={"EUR_USD":1.2,"AUD_USD":1.4,"NZD_USD":1.5,"USD_CAD":1.8,"USD_CHF":1.6,"GBP_USD":1.6}

def wma(s,n):
    w=np.arange(1,n+1,dtype=float)
    return s.rolling(n).apply(lambda x: np.dot(x,w)/w.sum(),raw=True)
def hma(s,n):
    return wma(2*wma(s,max(1,round(n/2)))-wma(s,n),max(1,round(math.sqrt(n))))
def ks(s,n):
    x=np.arange(n,dtype=float); xm=x.mean(); den=((x-xm)**2).sum()
    def f(y):
        ym=y.mean(); slope=((x-xm)*(y-ym)).sum()/den if den else 0.0
        return ym+slope*(n-1-xm)
    return s.rolling(n).apply(f,raw=True)
def ma(s,t,n):
    t=t.upper()
    if t=="EMA": return s.ewm(span=n,adjust=False,min_periods=n).mean()
    if t=="WMA": return wma(s,n)
    if t=="HMA": return hma(s,n)
    return ks(s,n)
def load_csv(path):
    df=pd.read_csv(path)
    cmap={c.lower():c for c in df.columns}
    tc=next((cmap[k] for k in ("time","timestamp","datetime","date") if k in cmap),None)
    if tc is None: raise ValueError("CSV needs time/timestamp/datetime/date")
    df[tc]=pd.to_datetime(df[tc],utc=True); df=df.set_index(tc).sort_index()
    ren={}
    for k in ["open","high","low","close"]:
        if k not in cmap: raise ValueError(f"CSV missing {k}")
        ren[cmap[k]]=k
    return df.rename(columns=ren)[["open","high","low","close"]].astype(float)
def fetch_oanda(instr,days):
    tok=os.getenv("OANDA_TOKEN"); env=os.getenv("OANDA_ENV","practice")
    if not tok: raise RuntimeError("OANDA_TOKEN missing; use --csv or set OANDA_TOKEN")
    host="api-fxpractice.oanda.com" if env.lower()!="live" else "api-fxtrade.oanda.com"
    end=pd.Timestamp.now(tz="UTC"); start=end-pd.Timedelta(days=days+3)
    rows=[]; cur=start
    while cur<end:
        params={"granularity":"M1","price":"M","from":cur.isoformat(),"count":5000}
        r=requests.get(f"https://{host}/v3/instruments/{instr}/candles",headers={"Authorization":f"Bearer {tok}"},params=params,timeout=30); r.raise_for_status()
        cs=r.json().get("candles",[])
        if not cs: break
        for c in cs:
            if c.get("complete"):
                m=c["mid"]; rows.append((c["time"],m["o"],m["h"],m["l"],m["c"]))
        nxt=pd.Timestamp(cs[-1]["time"])+pd.Timedelta(minutes=1)
        if nxt<=cur: break
        cur=nxt
    df=pd.DataFrame(rows,columns=["time","open","high","low","close"]); df["time"]=pd.to_datetime(df.time,utc=True)
    return df.drop_duplicates("time").set_index("time").astype(float).tail(days*24*60)
def resample(df,rule):
    if rule=="1min": return df.copy()
    return df.resample(rule,label="right",closed="right").agg({"open":"first","high":"max","low":"min","close":"last"}).dropna()
def events(df,r,t,l):
    x=resample(df,TF_RULE[R_TF[r]])
    rail=ma(x.close,t,l); inv=ma(x.close.shift(1),t,l); d=rail-inv
    up=(d>0)&(d.shift(1)<=0); dn=(d<0)&(d.shift(1)>=0)
    ev=pd.Series(np.where(up,1,np.where(dn,-1,0)),index=x.index,dtype=int)
    state=pd.Series(np.where(d>=0,1,-1),index=x.index,dtype=int)
    return pd.DataFrame({"event":ev,"state":state}).dropna()
def pip_size(instr): return 0.01 if instr.endswith("JPY") else 0.0001

def simulate(df,pe,ce,instr,start_eq=100.0,notional_x=1.0,trim=.25,boost=.25,min_x=0.0,max_x=2.0,spread_pips=1.85):
    e=pd.DataFrame(index=df.index)
    e["p_evt"]=pe.event.reindex(e.index,method="ffill").fillna(0)
    # true events must only appear at their own timestamp, not forward filled
    e["p_evt"]=0; e.loc[e.index.intersection(pe.index),"p_evt"]=pe.loc[e.index.intersection(pe.index),"event"]
    e["c_evt"]=0; e.loc[e.index.intersection(ce.index),"c_evt"]=ce.loc[e.index.intersection(ce.index),"event"]
    e["c_state"]=ce.state.reindex(e.index,method="ffill").fillna(0)
    eq0=eqg=float(start_eq); pos0=posg=0.0; pstate=0; base=trimmed=0.0; had=False
    peak0=peakg=start_eq; mdd0=mddg=0.0; actions=trims=reloads=boosts=0
    ps=pip_size(instr); cost_per_unit=ps*spread_pips
    prev=None
    for ts,row in df.iterrows():
        px=row.close
        if prev is not None:
            dp=px-prev; eq0+=pos0*dp; eqg+=posg*dp
        pevt=int(e.at[ts,"p_evt"]); cevt=int(e.at[ts,"c_evt"]); cstate=int(e.at[ts,"c_state"])
        if pevt:
            pstate=pevt
            q=max(1.0,(eqg*notional_x)/px); q0=max(1.0,(eq0*notional_x)/px)
            new0=pstate*q0; eq0-=abs(new0-pos0)*cost_per_unit; pos0=new0
            base=q; trimmed=0; had=False; newg=pstate*base; eqg-=abs(newg-posg)*cost_per_unit; actions+=int(newg!=posg); posg=newg
        elif pstate and cevt and base>0:
            old=abs(posg); new=old
            if cstate==-pstate:
                req=base*trim; floor=base*min_x; new=max(floor,old-req); actual=max(0,old-new); trimmed+=actual; had|=actual>0; trims+=int(actual>0)
            elif cstate==pstate:
                restore=trimmed; b=base*boost if had else 0; new=min(base*max_x,old+restore+b); reloads+=int(restore>0 and new>old); boosts+=int(new-old>restore+1e-12); trimmed=0; had=False
            tgt=pstate*new
            if tgt!=posg: eqg-=abs(tgt-posg)*cost_per_unit; actions+=1; posg=tgt
        peak0=max(peak0,eq0); peakg=max(peakg,eqg); mdd0=max(mdd0,(peak0-eq0)/peak0 if peak0 else 0); mddg=max(mddg,(peakg-eqg)/peakg if peakg else 0)
        prev=px
    return {"baseline_equity":eq0,"gear_equity":eqg,"edge":eqg-eq0,"baseline_max_dd_pct":100*mdd0,"gear_max_dd_pct":100*mddg,"gear_actions":actions,"trims":trims,"reloads":reloads,"boosts":boosts}

def parse_geom(s):
    g=DEFAULT_GEOM.copy()
    if not s: return g
    for item in s.split(","):
        r,v=item.split("="); typ=''.join(filter(str.isalpha,v)).upper(); n=int(''.join(filter(str.isdigit,v))); g[r.upper()]=(typ,n)
    return g

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--instrument",default="AUD_USD"); ap.add_argument("--csv"); ap.add_argument("--days",type=int,default=120)
    ap.add_argument("--parent",default="R7"); ap.add_argument("--child",default="R8"); ap.add_argument("--trim",type=float,default=25); ap.add_argument("--boost",type=float,default=25); ap.add_argument("--min-x",type=float,default=0); ap.add_argument("--max-x",type=float,default=2)
    ap.add_argument("--start-equity",type=float,default=100); ap.add_argument("--notional-x",type=float,default=1); ap.add_argument("--spread-pips",default="AUTO"); ap.add_argument("--geometry",help="e.g. R7=KS27,R8=KS28,R9=EMA2"); ap.add_argument("--sweep-r-pairs",action="store_true"); ap.add_argument("--output",default="tgim_nested_forex_results.csv"); ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args()
    if a.self_test:
        idx=pd.date_range("2026-01-01",periods=2000,freq="1min",tz="UTC"); px=1.1+np.sin(np.arange(len(idx))/45)*.003+np.arange(len(idx))*1e-6; df=pd.DataFrame({"open":px,"high":px+.0002,"low":px-.0002,"close":px},index=idx); a.instrument="EUR_USD"
    else: df=load_csv(a.csv) if a.csv else fetch_oanda(a.instrument,a.days)
    geom=parse_geom(a.geometry); spread=OANDA_SPREAD.get(a.instrument,1.85) if str(a.spread_pips).upper()=="AUTO" else float(a.spread_pips)
    pairs=[]
    if a.sweep_r_pairs:
        order=list(R_TF); secs={r:pd.Timedelta(TF_RULE[R_TF[r]] if R_TF[r]!="1W" else "7D").total_seconds() for r in order}
        pairs=[(p,c) for p in order for c in order if secs[p]>secs[c]]
    else: pairs=[(a.parent,a.child)]
    rows=[]
    for p,c in pairs:
        pt,pl=geom[p]; ct,cl=geom[c]; pe=events(df,p,pt,pl); ce=events(df,c,ct,cl)
        res=simulate(df,pe,ce,a.instrument,a.start_equity,a.notional_x,a.trim/100,a.boost/100,a.min_x,a.max_x,spread); rows.append({"parent":p,"child":c,"parent_ma":f"{pt}{pl}","child_ma":f"{ct}{cl}","spread_pips":spread,**res})
    out=pd.DataFrame(rows).sort_values(["edge","gear_equity"],ascending=False); out.to_csv(a.output,index=False); print(out.head(30).to_string(index=False)); print(f"\nWROTE {a.output}")
if __name__=="__main__": main()
