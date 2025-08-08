from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# Get environment variables
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]

# OANDA REST API URL (for live account, not practice)
OANDA_URL = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"
HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

@app.route("/", methods=["POST"])
def receive_order():
    try:
        data = request.get_json()
        action     = data.get("action")
        instrument = data.get("instrument")
        units      = int(data.get("units"))

        if not action or not instrument or units == 0:
            return jsonify({"error": "Invalid or missing fields"}), 400

        order = {
            "order": {
                "instrument": instrument,
                "units": str(units if action == "buy" else -units),
                "type": "MARKET",
                "positionFill": "DEFAULT"
            }
        }

        response = requests.post(OANDA_URL, headers=HEADERS, json=order)
        return jsonify(response.json()), response.status_code

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
