from flask import Flask, request, jsonify
import os, requests, json

app = Flask(__name__)

# ENV variables (set in Render or your local .env)
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]

# LIVE endpoint (change to fxpractice.oanda.com for demo)
OANDA_URL = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"

HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

# Health check route
@app.route("/", methods=["GET"])
def home():
    return "✅ TGIM Webhook is LIVE", 200

# Webhook POST — root path ONLY
@app.route("/", methods=["POST"])
def webhook():
    try:
        data = request.json
        action = data.get("action")
        units  = int(data.get("units", 1))

        # Basic pair — change if needed
        instrument = "EUR_USD"

        # Determine direction
        direction = units if action in ["buy", "close_sell"] else -units

        order = {
            "order": {
                "instrument": instrument,
                "units": str(direction),
                "type": "MARKET",
                "positionFill": "DEFAULT"
            }
        }

        resp = requests.post(OANDA_URL, headers=HEADERS, data=json.dumps(order))
        return jsonify({"status": "sent", "response": resp.json()}), resp.status_code

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

if __name__ == "__main__":
    app.run(debug=True, port=5000)
