from flask import Flask, request, jsonify
import os, requests, json

app = Flask(__name__)

# OANDA ENV VARS — set in Render or .env
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]

# Live trading endpoint — for real account
OANDA_URL = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"

HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

@app.route("/", methods=["GET"])
def home():
    return "✅ TGIM Webhook is live", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        action = data.get("action")
        units_str = data.get("units", "1")
        units = int(units_str) if units_str.isdigit() else 1
        instr = "EUR_USD"  # Default/fallback if pair not provided

        # BUY or SELL (positive = buy, negative = sell)
        order_units = units if action in ["buy", "close_sell"] else -units

        order_data = {
            "order": {
                "instrument": instr,
                "units": str(order_units),
                "type": "MARKET",
                "positionFill": "DEFAULT"
            }
        }

        resp = requests.post(OANDA_URL, headers=HEADERS, data=json.dumps(order_data))
        return jsonify({"status": "sent", "response": resp.json()}), resp.status_code

    except Exception as e:
        return jsonify({"error": str(e)}), 400

if __name__ == "__main__":
    app.run(debug=True, port=5000)
