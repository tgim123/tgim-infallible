from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# ✅ LIVE OANDA CONFIG (NO PLACEHOLDERS)
OANDA_ACCOUNT_ID = "001-001-5528021-001"
OANDA_API_KEY = "e6a7d8cac04118841ce0df0648160386-3c9cbdb8edeee1d64004daa4fd24277f"
OANDA_API_URL = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {OANDA_API_KEY}"
}

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        print("Received alert:", data)

        action = data.get("action")
        side = data.get("side")
        instrument_info = data.get("instrument", {})
        symbol = instrument_info.get("symbol", "")
        units = int(float(data.get("units", 0)))

        if action == "market_order":
            order_data = {
                "order": {
                    "instrument": symbol.replace("OANDA:", ""),  # Ex: "EURUSD"
                    "units": str(units if side == "buy" else -units),
                    "type": "MARKET",
                    "positionFill": "DEFAULT"
                }
            }

            r = requests.post(OANDA_API_URL, headers=HEADERS, json=order_data)
            print("Order response:", r.text)
            return jsonify({"status": "market order sent", "response": r.json()}), 200

        elif action == "close_all":
            close_url = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/positions/{symbol.replace('OANDA:', '')}/close"
            close_data = {
                "longUnits": "ALL",
                "shortUnits": "ALL"
            }

            r = requests.put(close_url, headers=HEADERS, json=close_data)
            print("Close response:", r.text)
            return jsonify({"status": "position closed", "response": r.json()}), 200

        else:
            return jsonify({"error": "Invalid action"}), 400

    except Exception as e:
        print("Error:", str(e))
        return jsonify({"error": str(e)}), 500

@app.route('/')
def home():
    return "✅ TGIM Webhook Live & Ready for OANDA Execution"

if __name__ == '__main__':
    app.run(debug=True, port=5000)
