# app.py
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# ✅ LIVE OANDA CONFIG (NO PLACEHOLDERS)
OANDA_ACCOUNT_ID = "001-001-5528021-001"
OANDA_API_KEY   = "e6a7d8cac04118841ce0df0648160386-3c9cbdb8edeee1d64004daa4fd24277f"
OANDA_API_URL   = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"

HEADERS = {
    "Content-Type":  "application/json",
    "Authorization": f"Bearer {OANDA_API_KEY}"
}

@app.route("/")
def index():
    return "TGIM Auto Webhook is LIVE!"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("🔔 Incoming Alert:", data)

    action     = data.get("action")
    instrument = data.get("instrument")
    units      = int(data.get("units", 0))

    if action == "market_order":
        # buy vs sell
        side = data.get("side", "buy")
        factor = 1 if side == "buy" else -1

        payload = {
            "order": {
                "instrument":    instrument,
                "units":         str(units * factor),
                "type":          "MARKET",
                "positionFill": "DEFAULT"
            }
        }

        resp = requests.post(OANDA_API_URL, headers=HEADERS, json=payload)
        print(f"➡️ Market Order [{resp.status_code}]: {resp.text}")
        return jsonify(resp.json()), resp.status_code

    elif action == "close_all":
        close_url = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/positions/{instrument}/close"
        payload   = {"longUnits":"ALL","shortUnits":"ALL"}

        resp = requests.put(close_url, headers=HEADERS, json=payload)
        print(f"✂️ Close Position [{resp.status_code}]: {resp.text}")
        return jsonify(resp.json()), resp.status_code

    else:
        return jsonify({"error":"Unknown action"}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
