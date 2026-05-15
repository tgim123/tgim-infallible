# TGIM OANDA Sync Webhook v3 — TV Safe ACK — OANDA-only, old/new Pine compatible
# ------------------------------------------------------------------
# Drop-in replacement for app.py on Render/Replit.
# Keeps the same environment variables as the working app:
#   OANDA_ACCOUNT_ID
#   OANDA_API_KEY
#
# Supports old Pine actions:
#   buy, sell, close_buy, close_sell, close_all
#
# Supports new sync Pine actions:
#   buy/sell with position_policy:"sync"
#   close with side:"long"/"short"
#   flip with target:"buy"/"sell"
#   ignore_if_flat:true

from __future__ import annotations

import os
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Optional, Tuple

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

# ──────────────────────────────────────────────
# Environment Setup — same names as old working app
# ──────────────────────────────────────────────
ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID", "").strip()
API_KEY = os.environ.get("OANDA_API_KEY", "").strip()

if not ACCOUNT_ID or not API_KEY:
    raise RuntimeError("Missing OANDA_ACCOUNT_ID or OANDA_API_KEY in environment.")

# LIVE host. Change to fxpractice only if you intentionally use an OANDA practice account.
BASE_HOST = os.environ.get("OANDA_BASE_HOST", "https://api-fxtrade.oanda.com").strip()
BASE_URL = f"{BASE_HOST}/v3/accounts/{ACCOUNT_ID}"
ORDERS_URL = f"{BASE_URL}/orders"
POSITIONS_URL = f"{BASE_URL}/positions"
OPEN_POSITIONS_URL = f"{BASE_URL}/openPositions"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

# ──────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────
def normalize(sym: str) -> str:
    """Normalize common TradingView/OANDA symbols to OANDA format, e.g. EURUSD -> EUR_USD."""
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


def to_int_units(val: Any) -> int:
    """OANDA forex units are integer units. This keeps OANDA-only behavior clean."""
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


def parse_bool(val: Any, default: bool = False) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


def log_oanda_response(tag: str, response: requests.Response) -> Dict[str, Any]:
    try:
        body = response.json()
    except Exception:
        body = {"text": response.text}

    print(f"\n🔹 [{tag}] Status: {response.status_code}")
    print("🔸 URL:", response.url)
    try:
        req_body = response.request.body
        if isinstance(req_body, (bytes, bytearray)):
            req_body = req_body.decode(errors="replace")
    except Exception:
        req_body = "<unavailable>"
    print("📦 Payload snippet:", str(req_body)[:500])
    print("📜 Response snippet:", str(body)[:1000])
    print("──────────────────────────────────────────────\n")
    return body


def ok_response(payload: Dict[str, Any], status: int = 200):
    return jsonify(payload), status


def oanda_error_payload(tag: str, status: int, body: Any) -> Dict[str, Any]:
    return {"ok": False, "tag": tag, "status": status, "oanda": body}

# ──────────────────────────────────────────────
# OANDA functions
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
    r = requests.post(ORDERS_URL, headers=HEADERS, json=payload, timeout=20)
    body = log_oanda_response("OANDA-ORDER", r)
    return r.status_code, body


def get_open_position(instrument: str) -> Tuple[bool, int, int, Optional[Dict[str, Any]]]:
    """Return (found, long_units, short_units_abs, raw_position)."""
    r = requests.get(OPEN_POSITIONS_URL, headers=HEADERS, timeout=20)
    body = log_oanda_response("OANDA-OPEN-POSITIONS", r)
    if r.status_code >= 300:
        return False, 0, 0, None

    for pos in body.get("positions", []):
        if pos.get("instrument") == instrument:
            long_units = int(Decimal(pos.get("long", {}).get("units", "0")))
            short_units = int(abs(Decimal(pos.get("short", {}).get("units", "0"))))
            return True, long_units, short_units, pos
    return False, 0, 0, None


def close_position(instrument: str, side: str, ignore_if_flat: bool = True) -> Tuple[int, Dict[str, Any]]:
    side_norm = str(side or "").lower().strip()
    if side_norm in {"buy", "long", "close_buy"}:
        close_field = "longUnits"
        human_side = "long"
    elif side_norm in {"sell", "short", "close_sell"}:
        close_field = "shortUnits"
        human_side = "short"
    else:
        return 400, {"ok": False, "error": "bad_close_side", "side": side}

    found, long_units, short_units, _ = get_open_position(instrument)
    has_side = (human_side == "long" and long_units > 0) or (human_side == "short" and short_units > 0)

    if not has_side and ignore_if_flat:
        return 200, {
            "ok": True,
            "ignored": True,
            "reason": "already_flat_or_no_matching_side",
            "instrument": instrument,
            "side": human_side,
            "found_position": found,
            "long_units": long_units,
            "short_units": short_units,
        }

    payload = {close_field: "ALL"}
    url = f"{POSITIONS_URL}/{instrument}/close"
    r = requests.put(url, headers=HEADERS, json=payload, timeout=20)
    body = log_oanda_response(f"OANDA-CLOSE-{human_side.upper()}", r)

    if r.status_code >= 300 and ignore_if_flat:
        text = json.dumps(body).lower()
        if "no such position" in text or "position does not exist" in text or "no position" in text:
            return 200, {"ok": True, "ignored": True, "reason": "oanda_already_flat", "oanda": body}

    return r.status_code, body


def close_all(instrument: str, ignore_if_flat: bool = True) -> Dict[str, Any]:
    long_status, long_body = close_position(instrument, "long", ignore_if_flat=ignore_if_flat)
    short_status, short_body = close_position(instrument, "short", ignore_if_flat=ignore_if_flat)
    ok = long_status < 300 and short_status < 300
    return {
        "ok": ok,
        "instrument": instrument,
        "long_close": {"status": long_status, "body": long_body},
        "short_close": {"status": short_status, "body": short_body},
    }


def synced_entry(action: str, instrument: str, units: int, policy: str = "sync") -> Tuple[int, Dict[str, Any]]:
    """Buy/sell with optional close-opposite-first behavior."""
    action_norm = action.lower().strip()
    if action_norm not in {"buy", "sell"}:
        return 400, {"ok": False, "error": "bad_entry_action", "action": action}

    if policy.lower().strip() == "sync":
        opposite = "short" if action_norm == "buy" else "long"
        close_status, close_body = close_position(instrument, opposite, ignore_if_flat=True)
        if close_status >= 300:
            return close_status, {"ok": False, "stage": "close_opposite", "close": close_body}

    signed = units if action_norm == "buy" else -units
    order_status, order_body = place_market_order(instrument, signed)
    return order_status, {
        "ok": order_status < 300,
        "action": action_norm,
        "instrument": instrument,
        "units": signed,
        "order": order_body,
    }


def flip_position(instrument: str, target: str, units: int) -> Tuple[int, Dict[str, Any]]:
    target_norm = str(target or "").lower().strip()
    if target_norm in {"buy", "long"}:
        return synced_entry("buy", instrument, units, policy="sync")
    if target_norm in {"sell", "short"}:
        return synced_entry("sell", instrument, units, policy="sync")
    return 400, {"ok": False, "error": "bad_flip_target", "target": target}

# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────
@app.route("/", methods=["GET"])
def root():
    return jsonify({"ok": True, "service": "TGIM OANDA Sync Webhook v3 — TV Safe ACK", "route": "/webhook"})


@app.route("/webhook", methods=["GET"])
def webhook_get():
    return jsonify({"ok": True, "route": "/webhook", "expect": "POST JSON"})


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return ok_response({"ok": False, "error": "expected_json_object"}, 400)

    print("📩 TradingView payload:", json.dumps(data, ensure_ascii=False)[:1000])

    action = str(data.get("action", "")).lower().strip()
    raw_instrument = data.get("instrument") or data.get("pair") or data.get("symbol")
    instrument = normalize(raw_instrument)
    ignore_if_flat = parse_bool(data.get("ignore_if_flat"), default=True)
    policy = str(data.get("position_policy", "sync")).lower().strip()

    if not action:
        return ok_response({"ok": False, "error": "missing_action", "payload": data}, 400)
    if not instrument:
        return ok_response({"ok": False, "error": "missing_instrument", "payload": data}, 400)

    try:
        # Old format support: close_buy / close_sell
        if action == "close_buy":
            status, body = close_position(instrument, "long", ignore_if_flat=ignore_if_flat)
            return ok_response({"ok": status < 300, "broker_status": status, "action": action, "instrument": instrument, "result": body}, 200)

        if action == "close_sell":
            status, body = close_position(instrument, "short", ignore_if_flat=ignore_if_flat)
            return ok_response({"ok": status < 300, "broker_status": status, "action": action, "instrument": instrument, "result": body}, 200)

        # New format close: {action:"close", side:"long"/"short"}
        if action == "close":
            side = data.get("side") or data.get("target")
            status, body = close_position(instrument, str(side), ignore_if_flat=ignore_if_flat)
            return ok_response({"ok": status < 300, "broker_status": status, "action": action, "instrument": instrument, "side": side, "result": body}, 200)

        if action == "close_all":
            body = close_all(instrument, ignore_if_flat=ignore_if_flat)
            return ok_response(body, 200)

        if action in {"buy", "sell"}:
            units = to_int_units(data.get("units"))
            status, body = synced_entry(action, instrument, units, policy=policy)
            return ok_response({**body, "broker_status": status}, 200)

        if action == "flip":
            units = to_int_units(data.get("units"))
            target = data.get("target") or data.get("side")
            status, body = flip_position(instrument, str(target), units)
            return ok_response({**body, "broker_status": status}, 200)

        return ok_response({"ok": False, "error": "unsupported_action", "action": action, "supported": ["buy", "sell", "close_buy", "close_sell", "close", "close_all", "flip"]}, 200)

    except ValueError as e:
        return ok_response({"ok": False, "error": str(e), "payload": data}, 200)
    except requests.RequestException as e:
        return ok_response({"ok": False, "error": "oanda_request_exception", "detail": str(e)}, 200)
    except Exception as e:
        app.logger.exception("Unhandled webhook error")
        return ok_response({"ok": False, "error": "unhandled_exception", "detail": str(e)}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
