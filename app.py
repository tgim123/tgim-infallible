from flask import Flask, request, jsonify
import os
import requests
import json
from datetime import datetime

app = Flask(__name__)

# OANDA config from environment
OANDA_ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID")
OANDA_API_KEY    = os.environ.get("OANDA_API_KEY")

OANDA_BASE       = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}"
OANDA_ORDER_URL  = f"{OANDA_BASE}/orders"
HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type": "application/json"
}

LOG_FILE = "webhook.log"

def log_event(event_type, content):
    """Append a timestamped log entry to webhook.log"""
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{datetime.utcnow().isoformat()}Z | {event_type} | {content}\n")
    except Exception as e:
        print(f"Logging error: {e}")

@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return "✅ TGIM Webhook is live", 200

    try:
        raw  = (request.data or b"").decode("utf-8").strip()
        data = request.get_json(silent=True)

        log_event("RAW_REQUEST", raw)

        if data is None and raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                log_event("ERROR", "Invalid JSON payload")
                return jsonify({"error": "Invalid JSON"}), 400

        if not isinstance(data, dict):
            log_event("ERROR", "Invalid payload format")
            return jsonify({"error": "Invalid payload format"}), 400

        action     = data.get("action")
        instrument = data.get("instrument")
        units      = int(data.get("units", 0)) if "units" in data else 0

        if not action or not instrument:
            log_event("ERROR", "Missing action or instrument")
            return jsonify({"error": "Missing action or instrument"}), 400

        # ---- BUY ----
        if action == "buy":
            order = {
                "order": {
                    "instrument": instrument,
                    "units": str(abs(units)),
                    "type": "MARKET",
                    "positionFill": "DEFAULT"
                }
            }
            r = requests.post(OANDA_ORDER_URL, headers=HEADERS, json=order)

        # ---- SELL ----
        elif action == "sell":
            order = {
                "order": {
                    "instrument": instrument,
                    "units": str(-abs(units)),
                    "type": "MARKET",
                    "positionFill": "DEFAULT"
                }
            }
            r = requests.post(OANDA_ORDER_URL, headers=HEADERS, json=order)

        # ---- CLOSE LONG ----
        elif action == "close_buy":
            close_url = f"{OANDA_BASE}/positions/{instrument}/close"
            r = requests.put(close_url, headers=HEADERS, json={"longUnits": "ALL"})

        # ---- CLOSE SHORT ----
        elif action == "close_sell":
            close_url = f"{OANDA_BASE}/positions/{instrument}/close"
            r = requests.put(close_url, headers=HEADERS, json={"shortUnits": "ALL"})

        else:
            log_event("ERROR", f"Unknown action: {action}")
            return jsonify({"error": "Unknown action"}), 400

        log_event("OANDA_RESPONSE", json.dumps(r.json()))
        return jsonify(r.json()), r.status_code

    except Exception as e:
        log_event("ERROR", str(e))
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
