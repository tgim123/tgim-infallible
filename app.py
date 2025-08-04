from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# Fully hardcoded OANDA credentials and URLs
OANDA_API_KEY = "e6a7d8cac04118841ce0df0648160386-3c9cbdb8edeee1d64004daa4fd24277f"
OANDA_ACCOUNT_ID = "001-001-5528021-001"

HEADERS = {
    "Authorization": "Bearer e6a7d8cac04118841ce0df0648160386-3c9cbdb8edeee1d64004daa4fd24277f",
    "Content-Type": "application/json"
}

@app.route("/")
def index():
    return "TGIM Auto Webhook is LIVE!"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    try:
        action = data.get("action")
        side = data.get("side")
        instrument = data.get("instrument")
        units = str(data.get("units"))

        if not all([action, side, instrument, units]):
            return jsonify({"error": "Missing required fields"}), 400

        if action == "market_order":
            order_data = {
                "order": {
                    "units": units if side == "buy" else f"-{units}",
                    "instrument": instrument,
                    "timeInForce": "FOK",
                    "type": "MARKET",
                    "positionFill": "DEFAULT"
                }
            }

            url = "https://api-fxpractice.oanda.com/v3/accounts/001-001-5528021-001/orders"
            response = requests.post(url, headers=HEADERS, json=order_data)

            if response.status_code == 201:
                return jsonify({"status": "success", "details": response.json()})
            else:
                return jsonify({"error": "order failed", "details": response.text}), response.status_code

        elif action == "close_all":
            url = f"https://api-fxpractice.oanda.com/v3/accounts/001-001-5528021-001/positions/{instrument}/close"
            close_data = {
                "longUnits" if side == "buy" else "shortUnits": "ALL"
            }

            response = requests.put(url, headers=HEADERS, json=close_data)

            if response.status_code == 200:
                return jsonify({"status": "position closed", "details": response.json()})
            else:
                return jsonify({"error": "close failed", "details": response.text}), response.status_code

        else:
            return jsonify({"error": "Invalid action"}), 400

    except Exception as e:
        return jsonify({"error": "Exception occurred", "details": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
