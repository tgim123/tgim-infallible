# app.py
from flask import Flask, request, jsonify
import os, requests, math

app = Flask(__name__)

# —— ENV (live, not practice)
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]
BASE             = "https://api-fxtrade.oanda.com/v3"  # live

HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

# Force % of equity for order sizing (80% default)
RISK_PCT = float(os.getenv("FORCE_RISK_PCT", "80"))

# Map action to sign
SIGN = {
    "buy":        +1,
    "sell":       -1,
    "close_buy":  -1,  # reduce a long
    "close_sell": +1   # reduce a short
}

def normalize_instr(instr: str) -> str:
    """Accept EUR_USD or EUR/USD and return OANDA 'EUR_USD'."""
    return instr.replace("/", "_").upper()

def get_balance() -> float:
    """Live account balance (base currency)"""
    url = f"{BASE}/accounts/{OANDA_ACCOUNT_ID}/summary"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return float(r.json()["account"]["balance"])

def calc_units(balance: float, price: float | None = None) -> int:
    """
    Very simple sizing: units = floor(balance * RISK_PCT%)
    (You’re trading FX units directly; adjust if you want price- or leverage-based sizing.)
    """
    units = math.floor(balance * (RISK_PCT / 100.0))
    return max(units, 1)

def place_market_order(instr: str, signed_units: int, reduce_only: bool = False):
    """Send a MARKET order. If reduce_only, use REDUCE_ONLY positionFill."""
    body = {
        "order": {
            "instrument": instr,
            "units": str(signed_units),
            "type": "MARKET",
            "positionFill": "REDUCE_ONLY" if reduce_only else "DEFAULT"
        }
    }
    url = f"{BASE}/accounts/{OANDA_ACCOUNT_ID}/orders"
    r = requests.post(url, headers=HEADERS, json=body, timeout=20)
    return r

@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return "✅ TGIM Webhook is live (forced 80% equity sizing)", 200

    data = request.get_json(silent=True) or {}
    action = str(data.get("action", "")).lower().strip()
    instr  = normalize_instr(str(data.get("instrument", "")))

    if action not in SIGN or not instr or "_" not in instr:
        return jsonify({"ok": False, "error": "bad payload", "got": data}), 400

    try:
        balance = get_balance()
        # If you want to fetch price to do price-based sizing, do it here.
        units = calc_units(balance)
        signed_units = SIGN[action] * units
        reduce_only  = action in ("close_buy", "close_sell")

        resp = place_market_order(instr, signed_units, reduce_only=reduce_only)
        ok   = resp.status_code in (200, 201)

        return jsonify({
            "ok": ok,
            "action": action,
            "instrument": instr,
            "equity": balance,
            "risk_pct": RISK_PCT,
            "units_forced": abs(units),
            "signed_units": signed_units,
            "reduce_only": reduce_only,
            "oanda_status": resp.status_code,
            "oanda_body": resp.json() if resp.headers.get("content-type","").startswith("application/json") else resp.text
        }), resp.status_code
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
