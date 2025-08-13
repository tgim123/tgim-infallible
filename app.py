# app.py
from flask import Flask, request, jsonify
import os, requests, json

app = Flask(__name__)

# ---- Config (env vars on Render) ----
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]  # e.g. 001-001-xxxxxxx-001
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]     # live or practice key
OANDA_URL        = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"
# For practice accounts use: https://api-fxpractice.oanda.com/...
HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

# action -> sign (+ = buy, - = sell). close_* are REDUCE_ONLY market orders.
SIGN = {
    "buy":        +1,
    "sell":       -1,
    "close_buy":  -1,   # close long by selling
    "close_sell": +1    # close short by buying
}

def sanitize_instrument(sym: str) -> str:
    # Ensure OANDA format like EUR_USD
    s = (sym or "").upper().replace("-", "_").strip()
    return s

def build_order_payload(action: str, instrument: str, units: int) -> dict:
    signed_units = SIGN[action] * int(units)
    payload = {
        "order": {
            "instrument": instrument,
            "units": str(signed_units),     # OANDA wants string
            "timeInForce": "FOK",
            "type": "MARKET",
            "positionFill": "DEFAULT"
        }
    }
    # Close-only so we don't flip by accident
    if action.startswith("close_"):
        payload["order"]["positionFill"] = "REDUCE_ONLY"
    return payload

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return "✅ TGIM Webhook is live", 200

    # Accept both raw JSON and plain text; never crash
    raw = (request.data or b"").decode("utf-8").strip()
    data = request.get_json(silent=True)
    if data is None:
        try:
            data = json.loads(raw)
        except Exception:
            return jsonify({"ok": False, "error": "Invalid JSON", "raw": raw}), 400

    action = str(data.get("action", "")).strip()
    instrument = sanitize_instrument(str(data.get("instrument", "")))
    units = data.get("units", None)

    # Validate inputs
    if action not in SIGN:
        return jsonify({"ok": False, "error": f"Unsupported action '{action}'", "allowed": list(SIGN)}), 400
    if not instrument:
        return jsonify({"ok": False, "error": "Missing instrument"}), 400
    try:
        units = int(units)
        if units <= 0:
            raise ValueError()
    except Exception:
        return jsonify({"ok": False, "error": "Invalid units (must be positive integer)"}), 400

    # Build and send OANDA Market Order
    order_payload = build_order_payload(action, instrument, units)
    try:
        r = requests.post(OANDA_URL, headers=HEADERS, json=order_payload, timeout=15)
        resp_text = r.text
    except Exception as e:
        return jsonify({"ok": False, "error": f"Request to OANDA failed: {e}"}), 502

    # Bubble up OANDA result (no silent 200s)
    try:
        resp_json = r.json()
    except Exception:
        resp_json = {"raw": resp_text}

    status_ok = 200 <= r.status_code < 300
    return (
        jsonify({"ok": status_ok, "status": r.status_code, "oanda": resp_json, "sent": order_payload}),
        r.status_code if not status_ok else 200
    )

# Optional health route for Render
@app.route("/", methods=["GET"])
def root():
    return "TGIM up", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
