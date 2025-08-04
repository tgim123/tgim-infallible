from flask import Flask, request, jsonify
import requests, os, json

app = Flask(__name__)

# ─── OANDA ENV & ENDPOINTS ────────────────────────────────────────────────
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]
DOMAIN           = "api-fxtrade.oanda.com"
BASE_URL         = f"https://{DOMAIN}/v3/accounts/{OANDA_ACCOUNT_ID}"
ORDERS_URL       = f"{BASE_URL}/orders"
POSITIONS_URL    = f"{BASE_URL}/positions/{{instrument}}/close"

HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

@app.route("/", methods=["GET", "POST"])
def root():
    if request.method == "GET":
        return "✅ Webhook service is up", 200

    # ——— 1) Parse incoming JSON —————————————————————
    raw = request.get_data(as_text=True)
    app.logger.info("📥 Raw payload: %s", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON"}), 400

    action     = data.get("action")
    instrument = data.get("instrument")
    app.logger.info("▶ Parsed → action=%s instrument=%s", action, instrument)

    # ——— BUY and SELL —————————————————————————————
    if action in ("buy", "sell"):
        # positive for buy, negative for sell
        signed_units = int(data.get("units", 0)) * (1 if action == "buy" else -1)
        order_payload = {
            "order": {
                "instrument":   instrument,
                "units":        str(signed_units),
                "type":         "MARKET",
                "timeInForce":  "FOK",
                "positionFill": "DEFAULT"
            }
        }
        resp = requests.post(ORDERS_URL, headers=HEADERS, json=order_payload)
        app.logger.info(f"✅ {action.upper()} response: {resp.text}")
        return jsonify(resp.json()), resp.status_code

    # ——— CLOSE LONG or SHORT ——————————————————————
    if action == "close_buy":
        resp = requests.put(
            POSITIONS_URL.format(instrument=instrument),
            headers=HEADERS,
            json={"longUnits": "ALL"}
        )
        app.logger.info("✅ Close-buy response: %s", resp.text)
        return jsonify(resp.json()), resp.status_code

    if action == "close_sell":
        resp = requests.put(
            POSITIONS_URL.format(instrument=instrument),
            headers=HEADERS,
            json={"shortUnits": "ALL"}
        )
        app.logger.info("✅ Close-sell response: %s", resp.text)
        return jsonify(resp.json()), resp.status_code

    # ——— OPTIONAL: close both sides ————————————————————
    if action == "close_all":
        resp = requests.put(
            POSITIONS_URL.format(instrument=instrument),
            headers=HEADERS,
            json={"longUnits": "ALL", "shortUnits": "ALL"}
        )
        app.logger.info("✅ Close-all response: %s", resp.text)
        return jsonify(resp.json()), resp.status_code

    # ——— UNKNOWN ACTION —————————————————————————
    return jsonify({"error": f"Unknown action '{action}'"}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
