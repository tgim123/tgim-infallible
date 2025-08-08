from flask import Flask, request, jsonify
import os, requests, json

app = Flask(__name__)

# ───────────────────────────────
# 🔐 REQUIRED ENV VARIABLES
# ───────────────────────────────
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]

# 🔁 Change this to "api-fxpractice.oanda.com" for demo
DOMAIN     = "api-fxtrade.oanda.com"
BASE_URL   = f"https://{DOMAIN}/v3/accounts/{OANDA_ACCOUNT_ID}"
ORDERS_URL = f"{BASE_URL}/orders"
CLOSE_URL  = f"{BASE_URL}/positions/{{instrument}}/close"

HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type": "application/json"
}

# ───────────────────────────────
# 🧠 CREATE ORDER PAYLOAD
# ───────────────────────────────
def create_order_payload(action, instrument, units):
    side_multiplier = 1 if action in ["buy", "close_sell"] else -1
    order = {
        "order": {
            "instrument": instrument,
            "units": str(units * side_multiplier),
            "type": "MARKET",
            "positionFill": "DEFAULT"
        }
    }
    return json.dumps(order)

# ───────────────────────────────
# ❌ CLOSE POSITION
# ───────────────────────────────
def close_position(action, instrument):
    payload = {
        "longUnits":  "ALL" if action == "close_buy"  else "NONE",
        "shortUnits": "ALL" if action == "close_sell" else "NONE"
    }
    url = CLOSE_URL.format(instrument=instrument)
    return requests.put(url, headers=HEADERS, data=json.dumps(payload))

# ───────────────────────────────
# 🔥 ROOT WEBHOOK ENDPOINT "/"
# ───────────────────────────────
@app.route("/", methods=["POST"])
def webhook_root():
    try:
        data = request.json
        action     = data.get("action")
        instrument = data.get("instrument")
        units      = int(data.get("units", 1))

        if not all([action, instrument, units]):
            return jsonify({"error": "Missing parameters"}), 400

        if action in ["buy", "sell"]:
            payload = create_order_payload(action, instrument, units)
            resp    = requests.post(ORDERS_URL, headers=HEADERS, data=payload)
            return jsonify({"status": "order sent", "response": resp.json()}), resp.status_code

        elif action in ["close_buy", "close_sell"]:
            resp = close_position(action, instrument)
            return jsonify({"status": "position closed", "response": resp.json()}), resp.status_code

        else:
            return jsonify({"error": "Invalid action"}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ───────────────────────────────
# ✅ HEALTH CHECK (GET /)
# ───────────────────────────────
@app.route("/", methods=["GET"])
def health_check():
    return "✅ OANDA Webhook Listener is Active", 200

# ───────────────────────────────
# 🚀 APP RUNNER
# ───────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
