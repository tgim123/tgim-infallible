# TGIM OANDA Dynamic Margin + Spread Webhook v7
# ------------------------------------------------------------
# Drop-in replacement for app.py on Render.
# OANDA-only.
#
# Required Render environment variables:
#   OANDA_ACCOUNT_ID
#   OANDA_API_KEY
#
# Optional Render environment variables:
#   OANDA_BASE_HOST=https://api-fxtrade.oanda.com
#   TGIM_FORCE_DYNAMIC_SIZING=true
#   TGIM_DEFAULT_RISK_PCT=75
#   TGIM_MARGIN_SAFETY=0.95
#   TGIM_ALLOW_ADD_SAME_SIDE=false
#   TGIM_MARGIN_RETRY=2
#   TGIM_MAX_SPREAD_PIPS=0          # 0/off = do not block by spread
#   TGIM_SPREAD_BUFFER_PIPS=0       # optional extra reserve in sizing math
#
# Main protections:
#   1) No hedge: opposite side must close and verify before new side opens.
#   2) No duplicate same-side stacking by default.
#   3) Dynamic OANDA margin sizing per instrument using live marginRate.
#   4) Live spread fetched from OANDA pricing endpoint and logged/returned.
#   5) Optional max-spread blocker.

from __future__ import annotations

import json
import os
import time
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP, getcontext
from typing import Any, Dict, Optional, Tuple

import requests
from flask import Flask, jsonify, request

getcontext().prec = 28
app = Flask(__name__)

# ──────────────────────────────────────────────
# Environment
# ──────────────────────────────────────────────
ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID", "").strip()
API_KEY = os.environ.get("OANDA_API_KEY", "").strip()
if not ACCOUNT_ID or not API_KEY:
    raise RuntimeError("Missing OANDA_ACCOUNT_ID or OANDA_API_KEY in environment.")

BASE_HOST = os.environ.get("OANDA_BASE_HOST", "https://api-fxtrade.oanda.com").strip().rstrip("/")
BASE_URL = f"{BASE_HOST}/v3/accounts/{ACCOUNT_ID}"
ORDERS_URL = f"{BASE_URL}/orders"
POSITIONS_URL = f"{BASE_URL}/positions"
OPEN_POSITIONS_URL = f"{BASE_URL}/openPositions"
SUMMARY_URL = f"{BASE_URL}/summary"
INSTRUMENTS_URL = f"{BASE_URL}/instruments"
PRICING_URL = f"{BASE_URL}/pricing"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}
REQUEST_TIMEOUT = 20

FORCE_DYNAMIC_SIZING = os.environ.get("TGIM_FORCE_DYNAMIC_SIZING", "false").strip().lower() == "true"
DEFAULT_RISK_PCT = Decimal(os.environ.get("TGIM_DEFAULT_RISK_PCT", "75"))
MARGIN_SAFETY = Decimal(os.environ.get("TGIM_MARGIN_SAFETY", "0.95"))
ALLOW_ADD_SAME_SIDE = os.environ.get("TGIM_ALLOW_ADD_SAME_SIDE", "false").strip().lower() == "true"
MARGIN_RETRY = int(os.environ.get("TGIM_MARGIN_RETRY", "2"))
MAX_SPREAD_PIPS = Decimal(os.environ.get("TGIM_MAX_SPREAD_PIPS", "0"))
SPREAD_BUFFER_PIPS = Decimal(os.environ.get("TGIM_SPREAD_BUFFER_PIPS", "0"))

# ──────────────────────────────────────────────
# Generic helpers
# ──────────────────────────────────────────────
def d(x: Any, default: str = "0") -> Decimal:
    try:
        if x is None or x == "":
            return Decimal(default)
        return Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def parse_bool(val: Any, default: bool = False) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


def normalize(sym: Any) -> str:
    s = str(sym or "").upper().strip()
    s = (
        s.replace("OANDA:", "")
        .replace("FX:", "")
        .replace("FOREXCOM:", "")
        .replace("IDC:", "")
    )
    s = s.replace(":", "").replace("-", "").replace("/", "").replace(" ", "")
    special = {"XAUUSD": "XAU_USD", "XAGUSD": "XAG_USD"}
    if s in special:
        return special[s]
    if "_" in s:
        return s
    if len(s) == 6 and s.isalpha():
        return f"{s[:3]}_{s[3:]}"
    return s


def instrument_parts(instrument: str) -> Tuple[str, str]:
    parts = instrument.split("_")
    if len(parts) == 2:
        return parts[0], parts[1]
    return instrument[:3], instrument[-3:]


def pip_size(instrument: str) -> Decimal:
    # JPY pairs generally quote one pip as 0.01. Most FX pairs quote one pip as 0.0001.
    _base, quote = instrument_parts(instrument)
    if quote == "JPY":
        return Decimal("0.01")
    if instrument.startswith("XAU_") or instrument.startswith("XAG_"):
        return Decimal("0.01")
    return Decimal("0.0001")


def to_int_units(val: Any) -> int:
    q = d(val, "0").to_integral_value(rounding=ROUND_HALF_UP)
    n = int(q)
    if n < 1:
        raise ValueError(f"units_must_be_positive_integer: got={val!r}")
    return n


def floor_units(val: Decimal) -> int:
    n = int(val.to_integral_value(rounding=ROUND_DOWN))
    return max(1, n)


def response_json(response: requests.Response) -> Dict[str, Any]:
    try:
        return response.json()
    except Exception:
        return {"text": response.text}


def log_event(tag: str, payload: Any) -> None:
    print(f"\n===== {tag} =====")
    try:
        print(json.dumps(payload, indent=2, ensure_ascii=False)[:5000])
    except Exception:
        print(str(payload)[:5000])
    print("====================\n")


def log_oanda_response(tag: str, response: requests.Response) -> Dict[str, Any]:
    body = response_json(response)
    try:
        req_body = response.request.body
        if isinstance(req_body, (bytes, bytearray)):
            req_body = req_body.decode(errors="replace")
    except Exception:
        req_body = "<unavailable>"
    print(f"\n🔹 [{tag}] Status: {response.status_code}")
    print("🔸 URL:", response.url)
    print("📦 Payload snippet:", str(req_body)[:1500])
    print("📜 Response snippet:", json.dumps(body, ensure_ascii=False)[:3000])
    print("──────────────────────────────────────────────\n")
    return body


def tv_response(payload: Dict[str, Any], status: int = 200):
    # Keep TradingView alerts from pausing on broker/account issues; details live in payload.ok/result.
    return jsonify(payload), status


def hard_error(payload: Dict[str, Any], status: int = 400):
    return jsonify(payload), status

# ──────────────────────────────────────────────
# OANDA read helpers
# ──────────────────────────────────────────────
def get_account_summary() -> Tuple[int, Dict[str, Any]]:
    r = requests.get(SUMMARY_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    body = log_oanda_response("OANDA-ACCOUNT-SUMMARY", r)
    return r.status_code, body


def get_account_snapshot() -> Tuple[int, Dict[str, Any]]:
    status, body = get_account_summary()
    if status >= 300:
        return status, {"ok": False, "error": "account_summary_failed", "body": body}
    acct = body.get("account", {})
    return status, {
        "ok": True,
        "currency": acct.get("currency", "USD"),
        "NAV": str(acct.get("NAV", acct.get("balance", "0"))),
        "balance": str(acct.get("balance", "0")),
        "marginAvailable": str(acct.get("marginAvailable", "0")),
        "marginUsed": str(acct.get("marginUsed", "0")),
        "unrealizedPL": str(acct.get("unrealizedPL", "0")),
        "raw": acct,
    }


def get_instruments_map() -> Tuple[int, Dict[str, Any]]:
    r = requests.get(INSTRUMENTS_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    body = log_oanda_response("OANDA-INSTRUMENTS", r)
    if r.status_code >= 300:
        return r.status_code, {"ok": False, "body": body}
    m = {}
    for inst in body.get("instruments", []):
        name = inst.get("name")
        if name:
            m[name] = inst
    return r.status_code, {"ok": True, "instruments": m}


def get_instrument_details(instrument: str) -> Tuple[int, Dict[str, Any]]:
    status, body = get_instruments_map()
    if status >= 300 or not body.get("ok"):
        return status, {"ok": False, "error": "instruments_lookup_failed", "body": body}
    inst = body["instruments"].get(instrument)
    if not inst:
        return 404, {"ok": False, "error": "instrument_not_found_for_account", "instrument": instrument}
    margin_rate = d(inst.get("marginRate"), "0")
    leverage = (Decimal("1") / margin_rate) if margin_rate > 0 else Decimal("0")
    return 200, {
        "ok": True,
        "instrument": instrument,
        "marginRate": str(margin_rate),
        "impliedLeverage": str(leverage),
        "pipLocation": inst.get("pipLocation"),
        "displayPrecision": inst.get("displayPrecision"),
        "tradeUnitsPrecision": inst.get("tradeUnitsPrecision"),
        "minimumTradeSize": inst.get("minimumTradeSize"),
        "raw": inst,
    }


def get_pricing(instruments: list[str]) -> Tuple[int, Dict[str, Any]]:
    params = {"instruments": ",".join(instruments), "includeHomeConversions": "true"}
    r = requests.get(PRICING_URL, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
    body = log_oanda_response("OANDA-PRICING", r)
    return r.status_code, body


def best_bid_ask(price_obj: Dict[str, Any]) -> Tuple[Decimal, Decimal]:
    bids = price_obj.get("bids") or []
    asks = price_obj.get("asks") or []
    bid = d(bids[0].get("price") if bids else price_obj.get("closeoutBid"), "0")
    ask = d(asks[0].get("price") if asks else price_obj.get("closeoutAsk"), "0")
    return bid, ask


def extract_quote_to_home_conversion(price_obj: Dict[str, Any], quote_ccy: str, home_ccy: str) -> Decimal:
    # Most reliable when includeHomeConversions=true. Different OANDA responses can expose conversion factors in slightly different shapes.
    if quote_ccy == home_ccy:
        return Decimal("1")
    convs = price_obj.get("homeConversions") or []
    for c in convs:
        ccy = str(c.get("currency", "")).upper()
        if ccy == quote_ccy:
            # For margin reserve, use a conservative factor. Prefer positive ask, then bid, then factor.
            for k in ("accountGain", "accountLoss", "positionValue", "ask", "bid", "factor"):
                val = d(c.get(k), "0")
                if val > 0:
                    return val
    return Decimal("1")


def get_market_snapshot(instrument: str, account_currency: str = "USD") -> Tuple[int, Dict[str, Any]]:
    status, body = get_pricing([instrument])
    if status >= 300:
        return status, {"ok": False, "error": "pricing_failed", "body": body}
    prices = body.get("prices") or []
    if not prices:
        return 404, {"ok": False, "error": "no_price_returned", "instrument": instrument, "body": body}
    p = prices[0]
    bid, ask = best_bid_ask(p)
    if bid <= 0 or ask <= 0:
        return 409, {"ok": False, "error": "bad_bid_ask", "instrument": instrument, "price": p}
    mid = (bid + ask) / Decimal("2")
    spread_price = ask - bid
    pip = pip_size(instrument)
    spread_pips = spread_price / pip if pip > 0 else Decimal("0")
    base, quote = instrument_parts(instrument)
    quote_to_home = extract_quote_to_home_conversion(p, quote, str(account_currency or "USD").upper())
    return 200, {
        "ok": True,
        "instrument": instrument,
        "status": p.get("status"),
        "tradeable": p.get("tradeable", p.get("status") == "tradeable"),
        "time": p.get("time"),
        "bid": str(bid),
        "ask": str(ask),
        "mid": str(mid),
        "spread": str(spread_price),
        "spreadPips": str(spread_pips),
        "pipSize": str(pip),
        "quoteCurrency": quote,
        "accountCurrency": account_currency,
        "quoteToHomeConversion": str(quote_to_home),
        "raw": p,
    }


def get_open_positions_raw() -> Tuple[int, Dict[str, Any]]:
    r = requests.get(OPEN_POSITIONS_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    body = log_oanda_response("OANDA-OPEN-POSITIONS", r)
    return r.status_code, body


def get_position(instrument: str) -> Tuple[bool, int, int, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    status, body = get_open_positions_raw()
    if status >= 300:
        return False, 0, 0, None, {"status": status, "body": body}
    for pos in body.get("positions", []):
        if pos.get("instrument") == instrument:
            long_units = int(d(pos.get("long", {}).get("units", "0")))
            short_units_abs = int(abs(d(pos.get("short", {}).get("units", "0"))))
            return True, long_units, short_units_abs, pos, None
    return False, 0, 0, None, None


def snapshot_position(instrument: str) -> Dict[str, Any]:
    found, long_units, short_units_abs, raw, err = get_position(instrument)
    return {"instrument": instrument, "found": found, "long_units": long_units, "short_units": short_units_abs, "raw": raw, "error": err}

# ──────────────────────────────────────────────
# Dynamic sizing
# ──────────────────────────────────────────────
def dynamic_units_for_instrument(instrument: str, risk_pct: Decimal, side: str, max_spread_pips_override: Optional[Decimal] = None) -> Tuple[int, Dict[str, Any]]:
    acct_status, acct = get_account_snapshot()
    if acct_status >= 300 or not acct.get("ok"):
        raise RuntimeError(f"account_snapshot_failed: {acct}")
    account_ccy = acct.get("currency", "USD")

    inst_status, inst = get_instrument_details(instrument)
    if inst_status >= 300 or not inst.get("ok"):
        raise RuntimeError(f"instrument_details_failed: {inst}")

    mkt_status, mkt = get_market_snapshot(instrument, account_ccy)
    if mkt_status >= 300 or not mkt.get("ok"):
        raise RuntimeError(f"market_snapshot_failed: {mkt}")

    spread_pips = d(mkt.get("spreadPips"), "0")
    effective_max_spread_pips = MAX_SPREAD_PIPS
    if max_spread_pips_override is not None:
        effective_max_spread_pips = max_spread_pips_override

    if effective_max_spread_pips > 0 and spread_pips > effective_max_spread_pips:
        raise RuntimeError(f"spread_too_wide: spread_pips={spread_pips} max={effective_max_spread_pips}")

    nav = d(acct.get("NAV"), "0")
    margin_avail = d(acct.get("marginAvailable"), "0")
    margin_rate = d(inst.get("marginRate"), "0")
    quote_to_home = d(mkt.get("quoteToHomeConversion"), "1")
    mid = d(mkt.get("mid"), "0")
    pip = d(mkt.get("pipSize"), "0.0001")

    if nav <= 0 or margin_rate <= 0 or mid <= 0:
        raise RuntimeError(f"bad_sizing_inputs: nav={nav} margin_rate={margin_rate} mid={mid}")

    target_margin = nav * (risk_pct / Decimal("100"))
    margin_cap = margin_avail * MARGIN_SAFETY
    margin_to_use = min(target_margin, margin_cap) if margin_avail > 0 else target_margin

    # OANDA margin approximation for account currency:
    # units * mid price in quote currency * quote-to-home conversion * marginRate.
    margin_per_unit = mid * quote_to_home * margin_rate

    # Optional spread buffer reserve: units * spread_buffer_pips * pip * quote_to_home.
    # This is intentionally conservative and small by default/off.
    spread_buffer_per_unit = SPREAD_BUFFER_PIPS * pip * quote_to_home
    cost_per_unit = margin_per_unit + spread_buffer_per_unit
    if cost_per_unit <= 0:
        raise RuntimeError(f"bad_cost_per_unit: {cost_per_unit}")

    units_raw = margin_to_use / cost_per_unit
    units = floor_units(units_raw)

    return units, {
        "mode": "dynamic_margin",
        "instrument": instrument,
        "side": side,
        "riskPct": str(risk_pct),
        "NAV": str(nav),
        "marginAvailable": str(margin_avail),
        "marginSafety": str(MARGIN_SAFETY),
        "targetMargin": str(target_margin),
        "marginCap": str(margin_cap),
        "marginToUse": str(margin_to_use),
        "marginRate": str(margin_rate),
        "impliedLeverage": inst.get("impliedLeverage"),
        "bid": mkt.get("bid"),
        "ask": mkt.get("ask"),
        "mid": mkt.get("mid"),
        "spread": mkt.get("spread"),
        "spreadPips": mkt.get("spreadPips"),
        "maxSpreadPipsEnv": str(MAX_SPREAD_PIPS),
        "maxSpreadPipsPayload": str(max_spread_pips_override) if max_spread_pips_override is not None else None,
        "maxSpreadPipsEffective": str(effective_max_spread_pips),
        "pipSize": mkt.get("pipSize"),
        "quoteToHomeConversion": str(quote_to_home),
        "marginPerUnit": str(margin_per_unit),
        "spreadBufferPips": str(SPREAD_BUFFER_PIPS),
        "spreadBufferPerUnit": str(spread_buffer_per_unit),
        "costPerUnit": str(cost_per_unit),
        "unitsRaw": str(units_raw),
        "finalUnits": units,
        "account": acct,
        "instrumentDetails": inst,
        "market": mkt,
    }


def choose_units(data: Dict[str, Any], instrument: str, action: str) -> Tuple[int, Dict[str, Any]]:
    sizing_mode = str(data.get("sizing_mode", data.get("sizingMode", ""))).lower().strip()
    risk_pct = d(data.get("risk_pct", data.get("riskPct", DEFAULT_RISK_PCT)), str(DEFAULT_RISK_PCT))
    max_spread_raw = data.get("max_spread_pips", data.get("maxSpreadPips", None))
    max_spread_pips_override = None if max_spread_raw in (None, "") else d(max_spread_raw, "0")
    use_dynamic = FORCE_DYNAMIC_SIZING or sizing_mode in {"percent_equity", "dynamic_margin", "margin", "account_percent"}
    if use_dynamic:
        return dynamic_units_for_instrument(instrument, risk_pct, action, max_spread_pips_override=max_spread_pips_override)
    units = to_int_units(data.get("units"))
    return units, {"mode": "payload_units", "finalUnits": units, "payloadUnits": data.get("units")}

# ──────────────────────────────────────────────
# OANDA write helpers
# ──────────────────────────────────────────────
def place_market_order(instrument: str, signed_units: int) -> Tuple[int, Dict[str, Any]]:
    payload = {
        "order": {
            "instrument": instrument,
            "units": str(int(signed_units)),
            "type": "MARKET",
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
        }
    }
    r = requests.post(ORDERS_URL, headers=HEADERS, json=payload, timeout=REQUEST_TIMEOUT)
    body = log_oanda_response("OANDA-ORDER", r)
    return r.status_code, body


def close_position(instrument: str, side: str, ignore_if_flat: bool = True) -> Tuple[int, Dict[str, Any]]:
    side_norm = str(side or "").lower().strip()
    if side_norm in {"buy", "long", "close_buy"}:
        human_side, close_field = "long", "longUnits"
    elif side_norm in {"sell", "short", "close_sell"}:
        human_side, close_field = "short", "shortUnits"
    else:
        return 400, {"ok": False, "error": "bad_close_side", "side": side}

    found, long_units, short_units_abs, raw, pos_err = get_position(instrument)
    if pos_err:
        return pos_err["status"], {"ok": False, "stage": "position_check_before_close", "error": pos_err}

    has_side = (human_side == "long" and long_units > 0) or (human_side == "short" and short_units_abs > 0)
    if not has_side:
        if ignore_if_flat:
            return 200, {"ok": True, "ignored": True, "reason": "already_flat_or_no_matching_side", "instrument": instrument, "side": human_side, "long_units": long_units, "short_units": short_units_abs}
        return 409, {"ok": False, "error": "no_matching_position_to_close", "instrument": instrument, "side": human_side, "long_units": long_units, "short_units": short_units_abs}

    url = f"{POSITIONS_URL}/{instrument}/close"
    payload = {close_field: "ALL"}
    r = requests.put(url, headers=HEADERS, json=payload, timeout=REQUEST_TIMEOUT)
    body = log_oanda_response(f"OANDA-CLOSE-{human_side.upper()}", r)
    if r.status_code >= 300:
        return r.status_code, {"ok": False, "stage": "close_position", "oanda": body}

    time.sleep(0.15)
    found2, long2, short2, raw2, err2 = get_position(instrument)
    if err2:
        return err2["status"], {"ok": False, "stage": "verify_close", "error": err2, "close_response": body}
    still_open = (human_side == "long" and long2 > 0) or (human_side == "short" and short2 > 0)
    if still_open:
        return 409, {"ok": False, "stage": "verify_close", "error": "side_still_open_after_close", "instrument": instrument, "side": human_side, "long_units": long2, "short_units": short2, "close_response": body, "position_after_close": raw2}

    return 200, {"ok": True, "instrument": instrument, "side": human_side, "closed": True, "oanda": body, "position_after_close": {"found": found2, "long_units": long2, "short_units": short2}}


def strict_synced_entry(action: str, instrument: str, units: int, sizing: Dict[str, Any], policy: str = "sync") -> Tuple[int, Dict[str, Any]]:
    action_norm = str(action or "").lower().strip()
    if action_norm not in {"buy", "sell"}:
        return 400, {"ok": False, "error": "bad_entry_action", "action": action}

    before = snapshot_position(instrument)
    if before.get("error"):
        return before["error"]["status"], {"ok": False, "stage": "pre_entry_position_check", "position": before, "sizing": sizing}

    opposite_side = "short" if action_norm == "buy" else "long"
    same_side = "long" if action_norm == "buy" else "short"
    opposite_units = before["short_units"] if action_norm == "buy" else before["long_units"]
    same_units = before["long_units"] if action_norm == "buy" else before["short_units"]

    if same_units > 0 and not ALLOW_ADD_SAME_SIDE:
        return 200, {"ok": True, "ignored": True, "reason": "same_side_position_already_open_no_stacking", "action_requested": action_norm, "instrument": instrument, "same_side": same_side, "same_units_before": same_units, "position_before": before, "sizing": sizing}

    close_status = None
    close_body = None
    if str(policy or "sync").lower().strip() == "sync" and opposite_units > 0:
        close_status, close_body = close_position(instrument, opposite_side, ignore_if_flat=False)
        if close_status >= 300 or not close_body.get("ok", False):
            return 409, {"ok": False, "blocked_new_entry": True, "reason": "opposite_close_failed_no_hedge_enforced", "action_requested": action_norm, "instrument": instrument, "units_requested": units, "opposite_side": opposite_side, "opposite_units_before": opposite_units, "position_before": before, "close_attempt": {"broker_status": close_status, "body": close_body}, "sizing": sizing}

    verified = snapshot_position(instrument)
    if verified.get("error"):
        return verified["error"]["status"], {"ok": False, "stage": "verify_before_entry", "position": verified, "sizing": sizing}
    verified_opposite_units = verified["short_units"] if action_norm == "buy" else verified["long_units"]
    if verified_opposite_units > 0:
        return 409, {"ok": False, "blocked_new_entry": True, "reason": "opposite_position_still_exists_before_entry", "action_requested": action_norm, "instrument": instrument, "opposite_side": opposite_side, "opposite_units": verified_opposite_units, "position_before": before, "position_verified": verified, "close_attempt": {"broker_status": close_status, "body": close_body}, "sizing": sizing}

    signed_units = units if action_norm == "buy" else -units
    order_status, order_body = place_market_order(instrument, signed_units)

    # Retry margin rejection with smaller units.
    attempts = [{"units": signed_units, "broker_status": order_status, "body": order_body}]
    retry_units = abs(signed_units)
    retries_left = max(0, MARGIN_RETRY)
    while order_status >= 300 and retries_left > 0 and retry_units > 1:
        txt = json.dumps(order_body).lower()
        if "margin" not in txt and "insufficient" not in txt:
            break
        retry_units = max(1, int(Decimal(retry_units) * Decimal("0.90")))
        signed_retry = retry_units if action_norm == "buy" else -retry_units
        order_status, order_body = place_market_order(instrument, signed_retry)
        attempts.append({"units": signed_retry, "broker_status": order_status, "body": order_body})
        retries_left -= 1
        signed_units = signed_retry

    after = snapshot_position(instrument)
    return order_status, {"ok": order_status < 300, "action": action_norm, "instrument": instrument, "units": signed_units, "policy": policy, "position_before": before, "opposite_close": {"broker_status": close_status, "body": close_body}, "order_attempts": attempts, "order": {"broker_status": order_status, "body": order_body}, "position_after": after, "sizing": sizing}


def close_all(instrument: str, ignore_if_flat: bool = True) -> Dict[str, Any]:
    long_status, long_body = close_position(instrument, "long", ignore_if_flat=ignore_if_flat)
    short_status, short_body = close_position(instrument, "short", ignore_if_flat=ignore_if_flat)
    return {"ok": long_status < 300 and short_status < 300, "instrument": instrument, "long_close": {"broker_status": long_status, "body": long_body}, "short_close": {"broker_status": short_status, "body": short_body}}

# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────
@app.route("/", methods=["GET", "HEAD"])
def root():
    return jsonify({
        "ok": True,
        "service": "TGIM OANDA Dynamic Margin + Spread Webhook v7",
        "route": "/webhook",
        "dynamic_margin_sizing": True,
        "force_dynamic_sizing": FORCE_DYNAMIC_SIZING,
        "default_risk_pct": str(DEFAULT_RISK_PCT),
        "margin_safety": str(MARGIN_SAFETY),
        "max_spread_pips_env": str(MAX_SPREAD_PIPS),
        "max_spread_payload_override": True,
        "spread_buffer_pips": str(SPREAD_BUFFER_PIPS),
        "no_hedge_enforced": True,
    })


@app.route("/webhook", methods=["GET", "HEAD"])
def webhook_get():
    return jsonify({"ok": True, "route": "/webhook", "expect": "POST JSON", "service": "v7", "spread_endpoint": "/spread/<instrument>"})


@app.route("/spread/<instrument>", methods=["GET"])
def spread_route(instrument: str):
    inst = normalize(instrument)
    acct_status, acct = get_account_snapshot()
    acct_ccy = acct.get("currency", "USD") if acct_status < 300 and acct.get("ok") else "USD"
    status, snap = get_market_snapshot(inst, acct_ccy)
    return tv_response({"ok": status < 300, "instrument": inst, "broker_status": status, "spread": snap}, 200)


@app.route("/status/<instrument>", methods=["GET"])
def status_route(instrument: str):
    inst = normalize(instrument)
    acct_status, acct = get_account_snapshot()
    acct_ccy = acct.get("currency", "USD") if acct_status < 300 and acct.get("ok") else "USD"
    mkt_status, mkt = get_market_snapshot(inst, acct_ccy)
    inst_status, details = get_instrument_details(inst)
    pos = snapshot_position(inst)
    return tv_response({"ok": True, "instrument": inst, "account": acct, "instrumentDetails": details, "market": mkt, "position": pos})


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return hard_error({"ok": False, "error": "expected_json_object"}, 400)
    log_event("TRADINGVIEW-PAYLOAD", data)

    action = str(data.get("action", "")).lower().strip()
    raw_instrument = data.get("instrument") or data.get("pair") or data.get("symbol")
    instrument = normalize(raw_instrument)
    ignore_if_flat = parse_bool(data.get("ignore_if_flat"), default=True)
    policy = str(data.get("position_policy", "sync")).lower().strip()

    if not action:
        return hard_error({"ok": False, "error": "missing_action", "payload": data}, 400)
    if not instrument:
        return hard_error({"ok": False, "error": "missing_instrument", "payload": data}, 400)

    try:
        if action == "status":
            acct_status, acct = get_account_snapshot()
            acct_ccy = acct.get("currency", "USD") if acct_status < 300 and acct.get("ok") else "USD"
            mkt_status, mkt = get_market_snapshot(instrument, acct_ccy)
            details_status, details = get_instrument_details(instrument)
            pos = snapshot_position(instrument)
            return tv_response({"ok": True, "action": action, "instrument": instrument, "account": acct, "instrumentDetails": details, "market": mkt, "position": pos})

        if action == "spread":
            acct_status, acct = get_account_snapshot()
            acct_ccy = acct.get("currency", "USD") if acct_status < 300 and acct.get("ok") else "USD"
            mkt_status, mkt = get_market_snapshot(instrument, acct_ccy)
            return tv_response({"ok": mkt_status < 300, "action": action, "instrument": instrument, "broker_status": mkt_status, "spread": mkt})

        if action == "close_buy":
            status, body = close_position(instrument, "long", ignore_if_flat=ignore_if_flat)
            return tv_response({"ok": status < 300, "action": action, "instrument": instrument, "broker_status": status, "result": body})

        if action == "close_sell":
            status, body = close_position(instrument, "short", ignore_if_flat=ignore_if_flat)
            return tv_response({"ok": status < 300, "action": action, "instrument": instrument, "broker_status": status, "result": body})

        if action == "close":
            side = data.get("side") or data.get("target")
            status, body = close_position(instrument, str(side), ignore_if_flat=ignore_if_flat)
            return tv_response({"ok": status < 300, "action": action, "instrument": instrument, "side": side, "broker_status": status, "result": body})

        if action == "close_all":
            body = close_all(instrument, ignore_if_flat=ignore_if_flat)
            return tv_response({"ok": body.get("ok", False), "action": action, "instrument": instrument, "result": body})

        if action in {"buy", "sell"}:
            units, sizing = choose_units(data, instrument, action)
            status, body = strict_synced_entry(action, instrument, units, sizing, policy=policy)
            return tv_response({"ok": status < 300 and body.get("ok", False), "action": action, "instrument": instrument, "broker_status": status, "result": body})

        if action == "flip":
            target = str(data.get("target") or data.get("side") or "").lower().strip()
            if target in {"buy", "long"}:
                units, sizing = choose_units({**data, "action": "buy"}, instrument, "buy")
                status, body = strict_synced_entry("buy", instrument, units, sizing, policy="sync")
            elif target in {"sell", "short"}:
                units, sizing = choose_units({**data, "action": "sell"}, instrument, "sell")
                status, body = strict_synced_entry("sell", instrument, units, sizing, policy="sync")
            else:
                return hard_error({"ok": False, "error": "bad_flip_target", "target": target}, 400)
            return tv_response({"ok": status < 300 and body.get("ok", False), "action": action, "instrument": instrument, "target": target, "broker_status": status, "result": body})

        return hard_error({"ok": False, "error": "unsupported_action", "action": action}, 400)

    except ValueError as e:
        return hard_error({"ok": False, "error": str(e), "payload": data}, 400)
    except requests.RequestException as e:
        return tv_response({"ok": False, "error": "oanda_request_exception", "detail": str(e)}, 200)
    except Exception as e:
        app.logger.exception("Unhandled webhook error")
        return tv_response({"ok": False, "error": "unhandled_exception", "detail": str(e)}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
