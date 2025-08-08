from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# OANDA API settings
OANDA_ACCOUNT_ID = "YOUR_OANDA_ACCOUNT_ID"
OANDA_API_KEY = "YOUR_OANDA_API_KEY"
OANDA_URL = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"

HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type": "application/json"
}

@app.route("/", methods=["POST"])
def webhook():
    data = request.json
    action = data.get("action")
    instrument = data.get("instrument")
    units = data.get("units")

    # Construct the OANDA order payload
    order_data = {
        "order": {
            "instrument": instrument,
            "units": str(units) if action == "buy" else "-" + str(units),
            "type": "MARKET",
            "positionFill": "DEFAULT"
        }
    }

    # Send the order to OANDA
    response = requests.post(OANDA_URL, headers=HEADERS, json=order_data)
    return jsonify(response.json()), response.status_code

if __name__ == "__main__":
    app.run(port=5000)
