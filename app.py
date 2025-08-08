from flask import Flask, request, jsonify
import os, requests, json

app = Flask(__name__)

# OANDA credentials from environment
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]

OANDA_URL = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"
HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

@app.route("/", methods=["GET", "POST"])  # ← FIXED TO MATCH YOUR WEBHOOK URL
def root():
    if request.method == "GET":
        return "✅ TGIM Webhook is live", 200

    try:
        data = request.get_json()
        action = data.get("action")
        units = int(data.get("units", 1))
        instr = "EUR_USD"  # default pair

        order_units = units if action in ["buy", "close_sell"] else -units

        order_data = {
            "order": {
                "instrument": instr,
                "units": str(order_units),
                "type": "MARKET",
                "positionFill": "DEFAULT"
            }
        }

        response = requests.post(OANDA_URL, headers=HEADERS, json=order_data)
        return jsonify({"status": "sent", "response": response.json()}), response.status_code

    except Exception as e:
        return jsonify({"error": str(e)}), 400

