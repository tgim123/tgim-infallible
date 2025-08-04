from flask import Flask, request, jsonify
import requests
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ─── LIVE OANDA CREDENTIALS ────────────────────────────────────────────────
import os

OANDA_ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID")
OANDA_API_KEY    = os.environ.get("OANDA_API_KEY")

BASE_URL          = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}"
ORDERS_URL        = f"{BASE_URL}/orders"
POSITIONS_CLOSE_URL = f"{BASE_URL}/positions/{{instrument}}/close"

HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

@app.route("/", methods=["GET"])
def health_check():
    return "✅ Webhook service is up", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    app.logger.info("Received alert: %s", data)

    action     = data.get("action")
    instrument = data.get("instrument")
    units      = data.get("units")

    try:
        if action == "market_order":
            payload = {
                "order": {
                    "instrument":   instrument,
                    "units":        str(units),
                    "type":         "MARKET",
                    "timeInForce":  "FOK",
                    "positionFill": "DEFAULT"
                }
            }
            resp = requests.post(ORDERS_URL, headers=HEADERS, json=payload)
            app.logger.info("Order response: %s", resp.text)
            return jsonify(resp.json()), resp.status_code

        elif action == "close_all":
            url  = POSITIONS_CLOSE_URL.format(instrument=instrument)
            body = {"longUnits":"ALL","shortUnits":"ALL"}
            resp = requests.put(url, headers=HEADERS, json=body)
            app.logger.info("Close response: %s", resp.text)
            return jsonify(resp.json()), resp.status_code

        else:
            return jsonify({"error": f"Unknown action '{action}'"}), 400

    except Exception as e:
        app.logger.error("Exception handling webhook: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # For local testing; in production Render sets $PORT automatically
    app.run(host="0.0.0.0", port=5000, debug=True)
