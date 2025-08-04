from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# ✅ LIVE OANDA CONFIG (no placeholders)
OANDA_ACCOUNT_ID = "001-001-3116191-001"
OANDA_API_KEY    = "d5941ebf3f7d9d86640e5c174ec0e9b9-373d609200ea155798a5be3cde108b22"
OANDA_API_URL    = "https://api-fxtrade.oanda.com"

HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

@app.route("/", methods=["GET"])
def index():
    return "TGIM Auto Webhook is LIVE"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    print("📨 Incoming Alert:", data)

    action     = data.get("action")
    instrument = data.get("instrument")
    units      = data.get("units")

    if action == "market_order":
        payload = {
            "order": {
                "units":       str(units),
                "instrument":  instrument,
                "timeInForce": "FOK",
                "type":        "MARKET",
                "positionFill":"DEFAULT"
            }
        }
        resp = requests.post(
            f"{OANDA_API_URL}/v3/accounts/{OANDA_ACCOUNT_ID}/orders",
            headers=HEADERS,
            json=payload
        )
        print("→ Market Order:", resp.status_code, resp.text)
        return jsonify(resp.json()), resp.status_code

    elif action == "close_all":
        resp = requests.put(
            f"{OANDA_API_URL}/v3/accounts/{OANDA_ACCOUNT_ID}/positions/{instrument}/close",
            headers=HEADERS
        )
        print("→ Close Position:", resp.status_code, resp.text)
        return jsonify(resp.json()), resp.status_code

    else:
        return jsonify({"error": f"Unknown action '{action}'"}), 400

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
