# TGIM OANDA Dynamic Margin Sizing Webhook v5
# ------------------------------------------------------------------
# Drop-in replacement for app.py on Render/Replit.
# OANDA-only. Preserves strict no-hedge behavior and adds pair-by-pair
# dynamic leverage/margin sizing from OANDA account instrument marginRate.
#
# Required environment variables:
#   OANDA_ACCOUNT_ID
#   OANDA_API_KEY
#
# Optional environment variables:
#   OANDA_BASE_HOST=https://api-fxtrade.oanda.com      # live default
#   OANDA_BASE_HOST=https://api-fxpractice.oanda.com   # practice
#   TGIM_FORCE_DYNAMIC_SIZING=false                    # true = ignore payload units for buy/sell and use dynamic risk pct
#   TGIM_DEFAULT_RISK_PCT=75                           # used when payload does not include risk_pct
#   TGIM_MARGIN_SAFETY=0.95                            # cap target margin to 95% safety
#   TGIM_ALLOW_ADD_SAME_SIDE=false                     # false = repeated buy while long / sell while short is ignored
#   TGIM_MAX_UNITS=0                                   # 0 = no max cap; otherwise hard cap units
#   TGIM_MARGIN_RETRY=2                                # reduce units and retry on margin rejection
#
# Best TradingView payload for dynamic sizing:
#   {"action":"buy","instrument":"EUR_NZD","sizing_mode":"percent_equity","risk_pct":75,"position_policy":"sync"}
#
# Current units-only Pine payloads still work:
#   {"action":"sell","instrument":"EUR_NZD","units":"1000","position_policy":"sync"}
#
# If your Pine still sends units only but you want app-side dynamic sizing,
# set Render env var:
#   TGIM_FORCE_DYNAMIC_SIZING=true
#
# Main safety rules:
#   1. Opposite side must close and verify before a new entry is placed.
#   2. Same-side repeated entries are ignored by default to prevent duplicates.
#   3. Dynamic units are calculated from live OANDA NAV, marginAvailable,
#      instrument marginRate, and base-currency-to-home-currency conversion.

from __future__ import annotations

import json
import os
import time
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

# ──────────────────────────────────────────────
# Environment Setup
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

FORCE_DYNAMIC_SIZING = os.environ.get("TGIM_FORCE_DYNAMIC_SIZING", "false").strip().lower() in {"1", "true", "yes", "y", "on"}
DEFAULT_RISK_PCT = Decimal(os.environ.get("TGIM_DEFAULT_RISK_PCT", "75"))
MARGIN_SAFETY = Decimal(os.environ.get("TGIM_MARGIN_SAFETY", "0.95"))
ALLOW_ADD_SAME_SIDE = os.environ.get("TGIM_ALLOW_ADD_SAME_SIDE", "false").strip().lower() in {"1", "true", "yes", "y", "on"}
MAX_UNITS = int(os.environ.get("TGIM_MAX_UNITS", "0") or "0")
MARGIN_RETRY = int(os.environ.get("TGIM_MARGIN_RETRY", "2") or "0")

# ──────────────────────────────────────────────
# Generic helpers
# ──────────────────────────────────────────────
def D(x: Any, default: str = "0") -> Decimal:
    try:
        if x is None or x == "":
            return Decimal(default)
        return Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def normalize(sym: Any) -> str:
    """Normalize common TradingView/OANDA symbols to OANDA format, e.g. EURNZD -> EUR_NZD."""
    s = str(sym or "").upper().strip()
    s = (
        s.replace("OANDA:", "")
        .replace("FX:", "")
        .replace("FOREXCOM:", "")
        .replace("IDC:", "")
    )
    s = s.replace(":", "").replace("-", "").replace("/", "").replace(" ", "")

    special = {
        "XAUUSD": "XAU_USD",
        "XAGUSD": "XAG_USD",
    }
    if s in special:
        return special[s]
    if "_" in s:
        return s
    if len(s) == 6 and s.isalpha():
        return f"{s[:3]}_{s[3:]}"
    return s


def parse_bool(val: Any, default: bool = False) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


def to_int_units(val: Any) -> int:
    """OANDA FX units are integer units."""
    if val is None:
        raise ValueError("units missing")
    try:
        q = Decimal(str(val)).to_integral_value(rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"units_not_int_castable: got={val!r}")
    n = int(q)
    if n < 1:
        raise ValueError(f"units_must_be_positive_integer: got={val!r}")
    return n


def floor_int(x: Decimal) -> int:
    if x <= 0:
        return 0
    return int(x.to_integral_value(rounding=ROUND_FLOOR))


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
    print("📦 Payload snippet:", str(req_body)[:1200])
    print("📜 Response snippet:", json.dumps(body, ensure_ascii=False)[:2500])
    print("──────────────────────────────────────────────\n")
    return body


def tv_response(payload: Dict[str, Any], status: int = 200):
    """
    Return HTTP 200 to TradingView for broker rejects so alerts do not pause.
    Malformed webhook payloads still return 400.
    """
    return jsonify(payload), status


def hard_error(payload: Dict[str, Any], status: int = 400):
    return jsonify(payload), status

# ──────────────────────────────────────────────
# OANDA read functions
# ──────────────────────────────────────────────
def oanda_get(url: str, params: Optional[Dict[str, Any]] = None, tag: str = "OANDA-GET") -> Tuple[int, Dict[str, Any]]:
    r = requests.get(url, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
    body = log_oanda_response(tag, r)
    return r.status_code, body


def get_account_summary() -> Tuple[int, Dict[str, Any]]:
    return oanda_get(SUMMARY_URL, tag="OANDA-ACCOUNT-SUMMARY")


def get_open_positions_raw() -> Tuple[int, Dict[str, Any]]:
    return oanda_get(OPEN_POSITIONS_URL, tag="OANDA-OPEN-POSITIONS")


@lru_cache(maxsize=1)
def get_account_instruments_cached() -> Dict[str, Any]:
    status, body = oanda_get(INSTRUMENTS_URL, tag="OANDA-ACCOUNT-INSTRUMENTS")
    if status >= 300:
        raise RuntimeError(f"Could not fetch OANDA instruments: {status} {body}")
    by_name = {}
    for inst in body.get("instruments", []):
        name = inst.get("name")
        if name:
            by_name[name] = inst
    return by_name


def get_instrument_details(instrument: str) -> Dict[str, Any]:
    instruments = get_account_instruments_cached()
    inst = instruments.get(instrument)
    if not inst:
        # Force a refresh once in case account instruments changed.
        get_account_instruments_cached.cache_clear()
        instruments = get_account_instruments_cached()
        inst = instruments.get(instrument)
    if not inst:
        raise ValueError(f"instrument_not_available_for_account: {instrument}")
    return inst


def get_mid_price(instrument: str) -> Tuple[Optional[Decimal], Optional[Dict[str, Any]]]:
    status, body = oanda_get(PRICING_URL, params={"instruments": instrument}, tag=f"OANDA-PRICING-{instrument}")
    if status >= 300:
        return None, {"status": status, "body": body}
    prices = body.get("prices") or []
    if not prices:
        return None, {"status": status, "body": body, "error": "no_prices_returned"}
    p = prices[0]

    bid = D(p.get("closeoutBid"))
    ask = D(p.get("closeoutAsk"))

    # Fallback to top-of-book prices if closeoutBid/Ask are absent.
    if bid <= 0:
        bids = p.get("bids") or []
        if bids:
            bid = D(bids[0].get("price"))
    if ask <= 0:
        asks = p.get("asks") or []
        if asks:
            ask = D(asks[0].get("price"))

    if bid > 0 and ask > 0:
        return (bid + ask) / Decimal("2"), p
    if bid > 0:
        return bid, p
    if ask > 0:
        return ask, p
    return None, {"status": status, "body": body, "error": "bad_price_fields"}


def split_instrument(instrument: str) -> Tuple[str, str]:
    if "_" not in instrument:
        raise ValueError(f"cannot_split_instrument: {instrument}")
    a, b = instrument.split("_", 1)
    return a, b


def conversion_factor_to_home(from_ccy: str, home_ccy: str) -> Tuple[Decimal, Dict[str, Any]]:
    """
    Returns how many home_ccy one unit of from_ccy is worth.
    Example: from EUR to USD => EUR_USD mid price.
    Example: from CAD to USD => 1 / USD_CAD mid price.
    """
    from_ccy = from_ccy.upper().strip()
    home_ccy = home_ccy.upper().strip()
    if from_ccy == home_ccy:
        return Decimal("1"), {"method": "same_currency", "from": from_ccy, "home": home_ccy}

    direct = normalize(f"{from_ccy}{home_ccy}")
    inv = normalize(f"{home_ccy}{from_ccy}")

    px, raw = get_mid_price(direct)
    if px and px > 0:
        return px, {"method": "direct", "instrument": direct, "price": str(px), "raw": raw}

    px2, raw2 = get_mid_price(inv)
    if px2 and px2 > 0:
        return Decimal("1") / px2, {"method": "inverse", "instrument": inv, "price": str(px2), "factor": str(Decimal("1") / px2), "raw": raw2}

    raise RuntimeError(f"conversion_unavailable: {from_ccy}_to_{home_ccy}; direct={direct} raw={raw}; inverse={inv} raw={raw2}")


def get_position(instrument: str) -> Tuple[bool, int, int, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Returns: found, long_units, short_units_abs, raw_position, error"""
    status, body = get_open_positions_raw()
    if status >= 300:
        return False, 0, 0, None, {"status": status, "body": body}

    for pos in body.get("positions", []):
        if pos.get("instrument") == instrument:
            long_units = int(D(pos.get("long", {}).get("units", "0")))
            short_units_abs = int(abs(D(pos.get("short", {}).get("units", "0"))))
            return True, long_units, short_units_abs, pos, None

    return False, 0, 0, None, None


def snapshot_position(instrument: str) -> Dict[str, Any]:
    found, long_units, short_units_abs, raw, err = get_position(instrument)
    return {
        "instrument": instrument,
        "found": found,
        "long_units": long_units,
        "short_units": short_units_abs,
        "raw": raw,
        "error": err,
    }

# ──────────────────────────────────────────────
# Dynamic margin sizing
# ──────────────────────────────────────────────
def should_use_dynamic_sizing(data: Dict[str, Any]) -> bool:
    if FORCE_DYNAMIC_SIZING:
        return True
    mode = str(data.get("sizing_mode") or data.get("size_mode") or "").lower().strip()
    if mode in {"percent_equity", "percent", "%_equity", "% of equity", "equity_pct", "dynamic"}:
        return True
    return False


def dynamic_units(instrument: str, data: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """
    Calculates units from live OANDA account/instrument data:
      target_margin = NAV * risk_pct
      margin_per_unit = base_currency_to_home_currency * marginRate
      units = target_margin / margin_per_unit
    Capped by marginAvailable * safety.
    """
    summary_status, summary = get_account_summary()
    if summary_status >= 300:
        raise RuntimeError(f"account_summary_failed: {summary_status} {summary}")

    acct = summary.get("account", {})
    home_ccy = str(acct.get("currency") or "USD").upper()
    nav = D(acct.get("NAV") or acct.get("balance"))
    margin_available = D(acct.get("marginAvailable"), default=str(nav))

    risk_pct = D(data.get("risk_pct") or data.get("riskPct") or data.get("risk_percent") or DEFAULT_RISK_PCT)
    if risk_pct <= 0:
        raise ValueError(f"risk_pct_must_be_positive: {risk_pct}")
    if risk_pct > 100:
        # This app treats risk_pct as actual percent, not multiplier.
        risk_pct = Decimal("100")

    inst = get_instrument_details(instrument)
    margin_rate = D(inst.get("marginRate"))
    if margin_rate <= 0:
        raise RuntimeError(f"missing_or_bad_marginRate_for_{instrument}: {inst}")
    leverage = Decimal("1") / margin_rate

    base_ccy, quote_ccy = split_instrument(instrument)
    base_to_home, conversion_info = conversion_factor_to_home(base_ccy, home_ccy)
    if base_to_home <= 0:
        raise RuntimeError(f"bad_base_to_home_conversion: {base_ccy}->{home_ccy} = {base_to_home}")

    margin_per_unit = base_to_home * margin_rate
    target_margin = nav * (risk_pct / Decimal("100"))
    available_cap_margin = margin_available * MARGIN_SAFETY
    usable_margin = min(target_margin, available_cap_margin)

    raw_units = usable_margin / margin_per_unit if margin_per_unit > 0 else Decimal("0")
    units = floor_int(raw_units)

    if MAX_UNITS > 0:
        units = min(units, MAX_UNITS)

    if units < 1:
        raise ValueError(
            f"dynamic_units_too_small: units={units}, nav={nav}, marginAvailable={margin_available}, "
            f"risk_pct={risk_pct}, marginRate={margin_rate}, base_to_home={base_to_home}"
        )

    details = {
        "sizing_mode": "percent_equity_dynamic_oanda_margin",
        "instrument": instrument,
        "home_currency": home_ccy,
        "base_currency": base_ccy,
        "quote_currency": quote_ccy,
        "nav": str(nav),
        "margin_available": str(margin_available),
        "risk_pct": str(risk_pct),
        "margin_safety": str(MARGIN_SAFETY),
        "target_margin": str(target_margin),
        "available_cap_margin": str(available_cap_margin),
        "usable_margin": str(usable_margin),
        "instrument_margin_rate": str(margin_rate),
        "implied_leverage": str(leverage),
        "base_to_home": str(base_to_home),
        "margin_per_unit": str(margin_per_unit),
        "raw_units": str(raw_units),
        "units": units,
        "conversion_info": conversion_info,
    }
    log_event("DYNAMIC-SIZING", details)
    return units, details


def resolve_entry_units(instrument: str, data: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    if should_use_dynamic_sizing(data):
        return dynamic_units(instrument, data)

    # Payload/fixed units path. This preserves old Pine compatibility.
    units = to_int_units(data.get("units"))
    return units, {"sizing_mode": "payload_units", "units": units}

# ──────────────────────────────────────────────
# OANDA write functions
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


def is_margin_reject(body: Dict[str, Any]) -> bool:
    txt = json.dumps(body, ensure_ascii=False).upper()
    return "MARGIN" in txt or "INSUFFICIENT" in txt or "UNITS_INVALID" in txt


def place_market_order_with_retry(instrument: str, signed_units: int) -> Tuple[int, Dict[str, Any]]:
    status, body = place_market_order(instrument, signed_units)
    attempts = [{"units": signed_units, "status": status, "body": body}]
    if status < 300:
        return status, {"ok": True, "final_units": signed_units, "attempts": attempts}

    # If dynamic sizing still hit broker margin limits, step down and retry.
    units_abs = abs(int(signed_units))
    side_mult = 1 if signed_units > 0 else -1
    for i in range(max(0, MARGIN_RETRY)):
        if not is_margin_reject(body):
            break
        units_abs = floor_int(Decimal(units_abs) * Decimal("0.90"))
        if units_abs < 1:
            break
        retry_signed = side_mult * units_abs
        status, body = place_market_order(instrument, retry_signed)
        attempts.append({"units": retry_signed, "status": status, "body": body})
        if status < 300:
            return status, {"ok": True, "final_units": retry_signed, "attempts": attempts, "reduced_after_margin_reject": True}

    return status, {"ok": False, "final_units": signed_units, "attempts": attempts}


def close_position(instrument: str, side: str, ignore_if_flat: bool = True) -> Tuple[int, Dict[str, Any]]:
    side_norm = str(side or "").lower().strip()

    if side_norm in {"buy", "long", "close_buy"}:
        human_side = "long"
        close_field = "longUnits"
    elif side_norm in {"sell", "short", "close_sell"}:
        human_side = "short"
        close_field = "shortUnits"
    else:
        return 400, {"ok": False, "error": "bad_close_side", "side": side}

    found, long_units, short_units_abs, raw, pos_err = get_position(instrument)
    if pos_err:
        return pos_err["status"], {"ok": False, "stage": "position_check_before_close", "error": pos_err}

    has_side = (human_side == "long" and long_units > 0) or (human_side == "short" and short_units_abs > 0)

    if not has_side:
        if ignore_if_flat:
            return 200, {
                "ok": True,
                "ignored": True,
                "reason": "already_flat_or_no_matching_side",
                "instrument": instrument,
                "side": human_side,
                "long_units": long_units,
                "short_units": short_units_abs,
            }
        return 409, {
            "ok": False,
            "error": "no_matching_position_to_close",
            "instrument": instrument,
            "side": human_side,
            "long_units": long_units,
            "short_units": short_units_abs,
        }

    payload = {close_field: "ALL"}
    url = f"{POSITIONS_URL}/{instrument}/close"
    r = requests.put(url, headers=HEADERS, json=payload, timeout=REQUEST_TIMEOUT)
    body = log_oanda_response(f"OANDA-CLOSE-{human_side.upper()}", r)

    if r.status_code >= 300:
        return r.status_code, {"ok": False, "stage": "close_position", "oanda": body}

    # Verify close actually removed the side.
    time.sleep(0.15)
    found2, long2, short2, raw2, err2 = get_position(instrument)
    if err2:
        return err2["status"], {"ok": False, "stage": "verify_close", "error": err2, "close_response": body}

    still_open = (human_side == "long" and long2 > 0) or (human_side == "short" and short2 > 0)
    if still_open:
        return 409, {
            "ok": False,
            "stage": "verify_close",
            "error": "side_still_open_after_close",
            "instrument": instrument,
            "side": human_side,
            "long_units": long2,
            "short_units": short2,
            "close_response": body,
            "position_after_close": raw2,
        }

    return 200, {
        "ok": True,
        "instrument": instrument,
        "side": human_side,
        "closed": True,
        "oanda": body,
        "position_after_close": {"found": found2, "long_units": long2, "short_units": short2},
    }


def close_all(instrument: str, ignore_if_flat: bool = True) -> Dict[str, Any]:
    long_status, long_body = close_position(instrument, "long", ignore_if_flat=ignore_if_flat)
    short_status, short_body = close_position(instrument, "short", ignore_if_flat=ignore_if_flat)
    ok = long_status < 300 and short_status < 300
    return {
        "ok": ok,
        "instrument": instrument,
        "long_close": {"broker_status": long_status, "body": long_body},
        "short_close": {"broker_status": short_status, "body": short_body},
    }


def strict_synced_entry(action: str, instrument: str, units: int, sizing_details: Dict[str, Any], policy: str = "sync", allow_add_same_side: bool = ALLOW_ADD_SAME_SIDE) -> Tuple[int, Dict[str, Any]]:
    """
    No-hedge entry.
    If opposite side exists, it must close and verify before new order is placed.
    If same side exists, ignore by default to avoid duplicate stacking.
    """
    action_norm = str(action or "").lower().strip()
    if action_norm not in {"buy", "sell"}:
        return 400, {"ok": False, "error": "bad_entry_action", "action": action}

    before = snapshot_position(instrument)
    if before.get("error"):
        return before["error"]["status"], {"ok": False, "stage": "pre_entry_position_check", "position": before}

    opposite_side = "short" if action_norm == "buy" else "long"
    same_side = "long" if action_norm == "buy" else "short"
    opposite_units = before["short_units"] if action_norm == "buy" else before["long_units"]
    same_units = before["long_units"] if action_norm == "buy" else before["short_units"]

    if same_units > 0 and opposite_units == 0 and not allow_add_same_side:
        return 200, {
            "ok": True,
            "ignored": True,
            "reason": "already_in_same_side_no_duplicate_added",
            "action_requested": action_norm,
            "instrument": instrument,
            "same_side": same_side,
            "same_units_existing": same_units,
            "units_requested": units,
            "sizing": sizing_details,
            "position_before": before,
        }

    close_status = None
    close_body = None

    if str(policy or "sync").lower().strip() == "sync" and opposite_units > 0:
        close_status, close_body = close_position(instrument, opposite_side, ignore_if_flat=False)
        if close_status >= 300 or not close_body.get("ok", False):
            return 409, {
                "ok": False,
                "blocked_new_entry": True,
                "reason": "opposite_close_failed_no_hedge_enforced",
                "action_requested": action_norm,
                "instrument": instrument,
                "units_requested": units,
                "sizing": sizing_details,
                "opposite_side": opposite_side,
                "opposite_units_before": opposite_units,
                "position_before": before,
                "close_attempt": {"broker_status": close_status, "body": close_body},
            }

    # Re-check immediately before entry.
    verified = snapshot_position(instrument)
    if verified.get("error"):
        return verified["error"]["status"], {"ok": False, "stage": "verify_before_entry", "position": verified}

    verified_opposite_units = verified["short_units"] if action_norm == "buy" else verified["long_units"]
    verified_same_units = verified["long_units"] if action_norm == "buy" else verified["short_units"]

    if verified_opposite_units > 0:
        return 409, {
            "ok": False,
            "blocked_new_entry": True,
            "reason": "opposite_position_still_exists_before_entry",
            "action_requested": action_norm,
            "instrument": instrument,
            "opposite_side": opposite_side,
            "opposite_units": verified_opposite_units,
            "position_before": before,
            "position_verified": verified,
            "close_attempt": {"broker_status": close_status, "body": close_body},
        }

    if verified_same_units > 0 and not allow_add_same_side:
        return 200, {
            "ok": True,
            "ignored": True,
            "reason": "already_in_same_side_after_sync_no_duplicate_added",
            "action_requested": action_norm,
            "instrument": instrument,
            "same_side": same_side,
            "same_units_existing": verified_same_units,
            "units_requested": units,
            "sizing": sizing_details,
            "position_before": before,
            "position_verified": verified,
        }

    signed_units = units if action_norm == "buy" else -units
    order_status, order_body = place_market_order_with_retry(instrument, signed_units)

    after = snapshot_position(instrument)

    return order_status, {
        "ok": order_status < 300,
        "action": action_norm,
        "instrument": instrument,
        "units_requested": signed_units,
        "units_final": order_body.get("final_units", signed_units),
        "policy": policy,
        "same_side": same_side,
        "sizing": sizing_details,
        "position_before": before,
        "opposite_close": {"broker_status": close_status, "body": close_body},
        "order": {"broker_status": order_status, "body": order_body},
        "position_after": after,
    }


def flip_position(instrument: str, target: str, units: int, sizing_details: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    target_norm = str(target or "").lower().strip()
    if target_norm in {"buy", "long"}:
        return strict_synced_entry("buy", instrument, units, sizing_details, policy="sync")
    if target_norm in {"sell", "short"}:
        return strict_synced_entry("sell", instrument, units, sizing_details, policy="sync")
    return 400, {"ok": False, "error": "bad_flip_target", "target": target}

# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────
@app.route("/", methods=["GET", "HEAD"])
def root():
    return jsonify({
        "ok": True,
        "service": "TGIM OANDA Dynamic Margin Sizing Webhook v5",
        "route": "/webhook",
        "no_hedge_enforced": True,
        "dynamic_margin_sizing": True,
        "force_dynamic_sizing": FORCE_DYNAMIC_SIZING,
        "default_risk_pct": str(DEFAULT_RISK_PCT),
        "margin_safety": str(MARGIN_SAFETY),
    })


@app.route("/webhook", methods=["GET", "HEAD"])
def webhook_get():
    return jsonify({
        "ok": True,
        "route": "/webhook",
        "expect": "POST JSON",
        "no_hedge_enforced": True,
        "dynamic_margin_sizing": True,
        "force_dynamic_sizing": FORCE_DYNAMIC_SIZING,
    })


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
    allow_add = parse_bool(data.get("allow_add_same_side"), default=ALLOW_ADD_SAME_SIDE)

    if not action:
        return hard_error({"ok": False, "error": "missing_action", "payload": data}, 400)
    if not instrument:
        return hard_error({"ok": False, "error": "missing_instrument", "payload": data}, 400)

    try:
        # Diagnostics/status
        if action == "status":
            pos = snapshot_position(instrument)
            inst = get_instrument_details(instrument)
            sizing_preview = None
            try:
                preview_units, preview = dynamic_units(instrument, data)
                sizing_preview = preview
            except Exception as e:
                sizing_preview = {"ok": False, "error": str(e)}
            return tv_response({
                "ok": not bool(pos.get("error")),
                "action": action,
                "instrument": instrument,
                "position": pos,
                "instrument_details": inst,
                "dynamic_sizing_preview": sizing_preview,
            })

        # Legacy close formats
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

        # Strict no-hedge entries with optional dynamic margin sizing
        if action in {"buy", "sell"}:
            units, sizing_details = resolve_entry_units(instrument, data)
            status, body = strict_synced_entry(action, instrument, units, sizing_details, policy=policy, allow_add_same_side=allow_add)
            return tv_response({"ok": status < 300 and body.get("ok", False), "action": action, "instrument": instrument, "broker_status": status, "result": body})

        if action == "flip":
            target = data.get("target") or data.get("side")
            units, sizing_details = resolve_entry_units(instrument, data)
            status, body = flip_position(instrument, str(target), units, sizing_details)
            return tv_response({"ok": status < 300 and body.get("ok", False), "action": action, "instrument": instrument, "target": target, "broker_status": status, "result": body})

        return hard_error({
            "ok": False,
            "error": "unsupported_action",
            "action": action,
            "supported": ["buy", "sell", "close_buy", "close_sell", "close", "close_all", "flip", "status"],
        }, 400)

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
