from flask import Flask, request, jsonify
import os
import requests
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

OANDA_API_KEY = os.getenv("OANDA_API_KEY")
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID")

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    action = data.get("action")
    instrument = data.get("instrument", {})
    units = data.get("units", 0)

    headers = {
        "Authorization": f"Bearer {OANDA_API_KEY}",
        "Content-Type": "application/json"
    }

    if action == "market_order":
        payload = {
            "order": {
                "units": str(units) if data.get("side") == "buy" else f"-{units}",
                "instrument": instrument.get("symbol"),
                "timeInForce": "FOK",
                "type": "MARKET",
                "positionFill": "DEFAULT"
            }
        }
        r = requests.post(
            f"https://api-fxpractice.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders",
            headers=headers, json=payload)
        return jsonify(r.json())

    elif action == "close_all":
        symbol = instrument.get("symbol")
        r = requests.put(
            f"https://api-fxpractice.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/positions/{symbol}/close",
            headers=headers,
            json={"longUnits": "ALL", "shortUnits": "ALL"})
        return jsonify(r.json())

    return jsonify({"status": "invalid action"}), 400
