# app.py
from flask import Flask, request, jsonify
import os, json, requests
from datetime import datetime

app = Flask(__name__)

# ---- OANDA (LIVE) ----
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]
OANDA_URL        = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"
HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

# Map Pine actions -> signed units (buy/close short = +, sell/close long = -)
SIGN = {
    "buy":        +1,
    "sell":       -1,
    "close_buy":  -1,  # close a long by selling
    "close_sell": +1   # close a short by buying
}

ALLOWED_ACTIONS = set(SIGN.keys())

def parse_body(req):
    """
    TradingView may send application/json or text/plain with a JSON string.
    Be tolerant either way.
    """
    data = req.get_json(silent=True)
    if data is None:
        raw = (req.data or b"").decode("utf-8").strip()
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return None, raw
    return data, None

@app.route("/", methods=["GET"])
def root():
    return f"✅ TGIM Webhook live @ {datetime.utcnow().isoformat()}Z", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    payload, raw = parse_body(request)
    if payload is None:
        return jsonify(error="Invalid JSON", raw=raw), 400

    # Expected: {"action":"buy|sell|close_buy|close_sell","instrument":"EUR_USD","units":123}
    action = str(payload.get("action", "")).strip().lower()
    instrument = str(payload.get("instrument", "")).strip().upper()
    units_in = payload.get("units", 1)

    if action not in ALLOWED_ACTIONS:
        return jsonify(error="Unsupported action", allowed=list(ALLOWED_ACTIONS), got=action), 400
    if not instrument or "_" not in instrument:
        return jsonify(error="Invalid instrument. Use e.g. 'EUR_USD'.", got=instrument), 400
    try:
        units = int(units_in)
    except Exception:
        return jsonify(error="Units must be an integer", got=units_in), 400
    if units <= 0:
        return jsonify(error="Units must be > 0", got=units), 400

    signed_units = units * SIGN[action]

    order = {
        "order": {
            "instrument":   instrument,
            "units":        str(signed_units),
            "type":         "MARKET",
            "positionFill": "DEFAULT"
        }
    }

    try:
        resp = requests.post(OANDA_URL, headers=HEADERS, data=json.dumps(order), timeout=10)
        ok = 200 <= resp.status_code < 300
        return (jsonify(
            ok=ok,
            action=action,
            instrument=instrument,
            requested_units=units,
            signed_units=signed_units,
            oanda_status=resp.status_code,
            oanda_response=try_json(resp.text)
        ), resp.status_code)
    except requests.RequestException as e:
        return jsonify(ok=False, error="RequestException", detail=str(e)), 502

def try_json(text):
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}

if __name__ == "__main__":
    # Render/Heroku/etc will set PORT; default to 8000 for local dev
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
