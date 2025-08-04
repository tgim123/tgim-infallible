from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# ───────────────────────────────────────────────
# ✅ YOUR LIVE OANDA CREDENTIALS (FULLY FILLED)
# ───────────────────────────────────────────────
OANDA_API_KEY = "d5941ebf3f7d9d86640e5c174ec0e9b9-373d609200ea155798a5be3cde108b22"
OANDA_ACCOUNT_ID = "001-001-5528021-001"
OANDA_API_URL = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"

HEADERS = {
    "Authorization": "Bearer d5941ebf3f7d9d86640e5c174ec0e9b9-373d609200ea155798a5be3cde108b22",
    "Content-Type": "application/json"
}

# ───────────────────────────────────────────────
@app.route("/")
def index():
    return "TGIM Auto Webhook is LIVE (LIVE TRADING MODE ENABLED)"

# ───────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    try:
        action = data.get("action")
        side = data.get("side")
        instrument = data.get("instrument")
        units = data.get("units")

        if action == "market_order":
            payload = {
                "order": {
                    "instrument": instrument,
                    "units": units if side == "buy" else f"-{units}",
                    "type": "MARKET",
                    "positionFill": "DEFAULT"
                }
            }
            response = requests.post(OANDA_API_URL, headers=HEADERS, json=payload)

        elif action == "close_all":
            close_url = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/positions/{instrument}/close"
            payload = {
                "longUnits": "ALL",
                "shortUnits": "ALL"
            }
            response = requests.put(close_url, headers=HEADERS, json=payload)

        else:
            return jsonify({"error": "Invalid action"}), 400

        return jsonify({
            "status": "success" if response.ok else "error",
            "status_code": response.status_code,
            "response": response.json() if response.ok else response.text
        }), response.status_code

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ───────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True)
