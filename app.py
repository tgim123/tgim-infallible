# app.py
from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# ─── LIVE OANDA CREDENTIALS ────────────────────────────────────────────────
OANDA_ACCOUNT_ID = "001-001-3116191-001"
OANDA_API_KEY    = "d5941ebf3f7d9d86640e5c174ec0e9b9-373d609200ea155798a5be3cde108b22"

BASE_URL = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}"
HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

@app.route("/")
def index():
    return "TGIM Auto-Trade Webhook is LIVE!"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    action     = data.get("action")
    instrument = data.get("instrument")
    units      = data.get("units")

    # 1) MARKET ORDER (BUY or SELL)
    if action == "market_order":
        # POST /accounts/{accountID}/orders
        url = f"{BASE_URL}/orders"
        body = {
            "order": {
                "instrument":   instrument,
                "units":        str(units),
                "type":         "MARKET",
                "timeInForce":  "FOK",
                "positionFill": "DEFAULT"
            }
        }
        resp = requests.post(url, headers=HEADERS, json=body)
        return _respond(resp)

    # 2) CLOSE ALL POSITIONS FOR AN INSTRUMENT
    elif action == "close_all":
        # PUT /accounts/{accountID}/positions/{instrument}/close
        url = f"{BASE_URL}/positions/{instrument}/close"
        body = {
            "longUnits":  "ALL",
            "shortUnits": "ALL"
        }
        resp = requests.put(url, headers=HEADERS, json=body)
        return _respond(resp)

    # 3) UNKNOWN ACTION
    else:
        return jsonify({"error": f"Unknown action '{action}'"}), 400

def _respond(resp):
    """Forward OANDA’s JSON + status code back to the caller."""
    try:
        return jsonify(resp.json()), resp.status_code
    except ValueError:
        return (resp.text, resp.status_code, {"Content-Type": "text/plain"})

if __name__ == "__main__":
    # local dev port fallback
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
