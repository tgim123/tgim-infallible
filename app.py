# TGIM OANDA Strict Sync Webhook v4 — No-Hedge Enforcement
# ------------------------------------------------------------------
# Drop-in replacement for app.py on Render/Replit.
# OANDA-only. Keeps the same working environment variables:
#   OANDA_ACCOUNT_ID
#   OANDA_API_KEY
# Optional:
#   OANDA_BASE_HOST=https://api-fxtrade.oanda.com     # live default
#   OANDA_BASE_HOST=https://api-fxpractice.oanda.com  # practice only if needed
#
# Main safety rule:
#   If a new BUY would conflict with an existing SHORT, the SHORT must close first.
#   If that close fails, the BUY is blocked.
#   If a new SELL would conflict with an existing LONG, the LONG must close first.
#   If that close fails, the SELL is blocked.
#
# Supported TradingView actions:
#   buy
#   sell
#   close_buy      # legacy close long
#   close_sell     # legacy close short
#   close           with side: long/short/buy/sell
#   close_all
#   flip            with target: buy/sell/long/short
#   status
#
# Compatible Pine examples:
#   {"action":"buy","instrument":"EUR_NZD","units":"33","position_policy":"sync"}
#   {"action":"sell","instrument":"EUR_NZD","units":"33","position_policy":"sync"}
#   {"action":"close","instrument":"EUR_NZD","side":"long","ignore_if_flat":true}
#   {"action":"flip","instrument":"EUR_NZD","target":"sell","units":"33"}

from __future__ import annotations

import json
import os
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
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

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

REQUEST_TIMEOUT = 20

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
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


def response_json(response: requests.Response) -> Dict[str, Any]:
    try:
        return response.json()
    except Exception:
        return {"text": response.text}


def log_event(tag: str, payload: Any) -> None:
    print(f"\n===== {tag} =====")
    try:
        print(json.dumps(payload, indent=2, ensure_ascii=False)[:4000])
    except Exception:
        print(str(payload)[:4000])
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
    print("📦 Payload snippet:", str(req_body)[:1000])
    print("📜 Response snippet:", json.dumps(body, ensure_ascii=False)[:2000])
    print("──────────────────────────────────────────────\n")
    return body


def tv_response(payload: Dict[str, Any], status: int = 200):
    """
    Return HTTP 200 to TradingView unless the payload itself is unusable.
    This avoids TradingView pausing alerts. The actual broker result is inside payload['ok'] and payload['broker_status'].
    """
    return jsonify(payload), status


def hard_error(payload: Dict[str, Any], status: int = 400):
    """Use non-200 only for malformed webhook payloads, not broker rejections."""
    return jsonify(payload), status


# ──────────────────────────────────────────────
# OANDA read functions
# ──────────────────────────────────────────────
def get_open_positions_raw() -> Tuple[int, Dict[str, Any]]:
    r = requests.get(OPEN_POSITIONS_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    body = log_oanda_response("OANDA-OPEN-POSITIONS", r)
    return r.status_code, body


def get_position(instrument: str) -> Tuple[bool, int, int, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Returns:
      found, long_units, short_units_abs, raw_position, error
    """
    status, body = get_open_positions_raw()
    if status >= 300:
        return False, 0, 0, None, {"status": status, "body": body}

    for pos in body.get("positions", []):
        if pos.get("instrument") == instrument:
            long_units = int(Decimal(pos.get("long", {}).get("units", "0")))
            short_units_abs = int(abs(Decimal(pos.get("short", {}).get("units", "0"))))
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


def strict_synced_entry(action: str, instrument: str, units: int, policy: str = "sync") -> Tuple[int, Dict[str, Any]]:
    """
    No-hedge entry.
    If opposite side exists, it must close and verify before the new order is placed.
    If close fails, new order is blocked.
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
                "opposite_side": opposite_side,
                "opposite_units_before": opposite_units,
                "position_before": before,
                "close_attempt": {"broker_status": close_status, "body": close_body},
            }

    # Re-check immediately before entry. This is the important no-hedge guard.
    verified = snapshot_position(instrument)
    if verified.get("error"):
        return verified["error"]["status"], {"ok": False, "stage": "verify_before_entry", "position": verified}

    verified_opposite_units = verified["short_units"] if action_norm == "buy" else verified["long_units"]
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

    signed_units = units if action_norm == "buy" else -units
    order_status, order_body = place_market_order(instrument, signed_units)

    after = snapshot_position(instrument)

    return order_status, {
        "ok": order_status < 300,
        "action": action_norm,
        "instrument": instrument,
        "units": signed_units,
        "policy": policy,
        "same_side": same_side,
        "position_before": before,
        "opposite_close": {"broker_status": close_status, "body": close_body},
        "order": {"broker_status": order_status, "body": order_body},
        "position_after": after,
    }


def flip_position(instrument: str, target: str, units: int) -> Tuple[int, Dict[str, Any]]:
    target_norm = str(target or "").lower().strip()
    if target_norm in {"buy", "long"}:
        return strict_synced_entry("buy", instrument, units, policy="sync")
    if target_norm in {"sell", "short"}:
        return strict_synced_entry("sell", instrument, units, policy="sync")
    return 400, {"ok": False, "error": "bad_flip_target", "target": target}


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────
@app.route("/", methods=["GET", "HEAD"])
def root():
    return jsonify({
        "ok": True,
        "service": "TGIM OANDA Strict Sync Webhook v4",
        "route": "/webhook",
        "no_hedge_enforced": True,
    })


@app.route("/webhook", methods=["GET", "HEAD"])
def webhook_get():
    return jsonify({
        "ok": True,
        "route": "/webhook",
        "expect": "POST JSON",
        "no_hedge_enforced": True,
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

    if not action:
        return hard_error({"ok": False, "error": "missing_action", "payload": data}, 400)
    if not instrument:
        return hard_error({"ok": False, "error": "missing_instrument", "payload": data}, 400)

    try:
        # Diagnostics/status
        if action == "status":
            pos = snapshot_position(instrument)
            return tv_response({"ok": not bool(pos.get("error")), "action": action, "position": pos})

        # Legacy close formats
        if action == "close_buy":
            status, body = close_position(instrument, "long", ignore_if_flat=ignore_if_flat)
            return tv_response({"ok": status < 300, "action": action, "instrument": instrument, "broker_status": status, "result": body})

        if action == "close_sell":
            status, body = close_position(instrument, "short", ignore_if_flat=ignore_if_flat)
            return tv_response({"ok": status < 300, "action": action, "instrument": instrument, "broker_status": status, "result": body})

        # New close format: {action:"close", side:"long"/"short"}
        if action == "close":
            side = data.get("side") or data.get("target")
            status, body = close_position(instrument, str(side), ignore_if_flat=ignore_if_flat)
            return tv_response({"ok": status < 300, "action": action, "instrument": instrument, "side": side, "broker_status": status, "result": body})

        if action == "close_all":
            body = close_all(instrument, ignore_if_flat=ignore_if_flat)
            return tv_response({"ok": body.get("ok", False), "action": action, "instrument": instrument, "result": body})

        # Strict no-hedge entries
        if action in {"buy", "sell"}:
            units = to_int_units(data.get("units"))
            status, body = strict_synced_entry(action, instrument, units, policy=policy)
            # Always 200 to TradingView, but include broker_status + ok.
            return tv_response({"ok": status < 300 and body.get("ok", False), "action": action, "instrument": instrument, "broker_status": status, "result": body})

        if action == "flip":
            units = to_int_units(data.get("units"))
            target = data.get("target") or data.get("side")
            status, body = flip_position(instrument, str(target), units)
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
