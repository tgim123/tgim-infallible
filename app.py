from flask import Flask, request, jsonify, abort
import requests, os, json

app = Flask(__name__)

# ─── Required ENV VARS ──────────────────────────────────────────────────────
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]
WEBHOOK_ID       = os.environ["WEBHOOK_ID"]    # e.g. "001-001-3116191-001"
WEBHOOK_KEY      = os.environ["WEBHOOK_KEY"]   # e.g. "56a54fc17014aaca9539155a433d01e3-c273c6e3707a45c8e2fb6ef24e5d4ec7"

# ─── OANDA ENDPOINTS ─────────────────────────────────────────────────────────
DOMAIN        = "api-fxtrade.oanda.com"
BASE_URL      = f"https://{DOMAIN}/v3/accounts/{OANDA_ACCOUNT_ID}"
ORDERS_URL    = f"{BASE_URL}/orders"
POSITIONS_URL = f"{BASE_URL}/positions/{{instrument}}/close"

HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

@app.route("/", methods=["GET", "POST"])
def root():
    if request.method == "GET":
        return "✅ Webhook service is up", 200

    # ——— Parse incoming JSON —————————————————————————————
    raw = request.get_data(as_text=True)
    app.logger.info("📥 Raw payload: %s", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON"}), 400

    # ——— Authenticate webhook —————————————————————————————
    if data.get("id")  != WEBHOOK_ID or data.get("api_key") != WEBHOOK_KEY:
        app.logger.warning("❌ Unauthorized: id=%s api_key=%s", data.get("id"), data.get("api_key"))
        abort(401)

    action     = data.get("action")
    instrument = data.get("instrument")
    units      = int(data.get("units", 0))
    app.logger.info("▶ Authenticated → action=%s instrument=%s units=%s", action, instrument, units)

    # ——— BUY and SELL —————————————————————————————
    if action in ("buy", "sell"):
        signed_units = units * (1 if action == "buy" else -1)
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
        app.logger.info("✅ %s response: %s", action.upper(), resp.text)
        return jsonify(resp.json()), resp.status_code

    # ——— CLOSE LONG —————————————————————————————
    if action == "close_buy":
        resp = requests.put(
            POSITIONS_URL.format(instrument=instrument),
            headers=HEADERS,
            json={"longUnits": "ALL"}
        )
        app.logger.info("✅ Close-buy response: %s", resp.text)
        return jsonify(resp.json()), resp.status_code

    # ——— CLOSE SHORT —————————————————————————————
    if action == "close_sell":
        resp = requests.put(
            POSITIONS_URL.format(instrument=instrument),
            headers=HEADERS,
            json={"shortUnits": "ALL"}
        )
        app.logger.info("✅ Close-sell response: %s", resp.text)
        return jsonify(resp.json()), resp.status_code

    # ——— OPTIONAL: CLOSE ALL —————————————————————————
    if action == "close_all":
        resp = requests.put(
            POSITIONS_URL.format(instrument=instrument),
            headers=HEADERS,
            json={"longUnits": "ALL", "shortUnits": "ALL"}
        )
        app.logger.info("✅ Close-all response: %s", resp.text)
        return jsonify(resp.json()), resp.status_code

    # ——— UNKNOWN ACTION —————————————————————————
    app.logger.warning("❌ Unknown action '%s'", action)
    return jsonify({"error": f"Unknown action '{action}'"}), 400

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
