from flask import Flask, request, jsonify, abort
import os, requests, json, logging

# ─── Setup & Logging ─────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# ─── Required ENV VARS ──────────────────────────────────────────────────────
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]
WEBHOOK_ID       = os.environ["WEBHOOK_ID"]    # e.g. "001-001-3116191-001"
WEBHOOK_KEY      = os.environ["WEBHOOK_KEY"]   # your webhook API key

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
    data = request.get_json(force=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    # ——— Authenticate webhook —————————————————————————————
    if data.get("id") != WEBHOOK_ID or data.get("api_key") != WEBHOOK_KEY:
        abort(401)

    # —── Normalize instrument ─────────────────────────────────────
    raw_inst   = data.get("instrument", "")
    instrument = raw_inst.replace("OANDA:", "").replace("/", "_")

    action = data.get("action")
    units  = int(data.get("units", 0))

    # ——— BUY / SELL —————————————————————————————
    if action in ("buy", "sell"):
        signed_units = units if action == "buy" else -units
        payload = {
            "order": {
                "instrument":   instrument,
                "units":        str(signed_units),
                "type":         "MARKET",
                "timeInForce":  "FOK",
                "positionFill": "DEFAULT"
            }
        }
        try:
            resp = requests.post(ORDERS_URL, headers=HEADERS, json=payload, timeout=10)
            resp.raise_for_status()
        except requests.RequestException as e:
            logging.error("OANDA order failed: %s", e)
            return jsonify({"error": "OANDA request failed"}), 502
        return jsonify(resp.json()), resp.status_code

    # ——— CLOSE LONG —————————————————————————————
    if action == "close_buy":
        try:
            resp = requests.put(
                POSITIONS_URL.format(instrument=instrument),
                headers=HEADERS,
                json={"longUnits": "ALL"},
                timeout=10
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logging.error("OANDA close_buy failed: %s", e)
            return jsonify({"error": "OANDA close_buy failed"}), 502
        return jsonify(resp.json()), resp.status_code

    # ——— CLOSE SHORT —————————————————————————————
    if action == "close_sell":
        try:
            resp = requests.put(
                POSITIONS_URL.format(instrument=instrument),
                headers=HEADERS,
                json={"shortUnits": "ALL"},
                timeout=10
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logging.error("OANDA close_sell failed: %s", e)
            return jsonify({"error": "OANDA close_sell failed"}), 502
        return jsonify(resp.json()), resp.status_code

    # ——— CLOSE ALL —————————————————————————————
    if action == "close_all":
        try:
            resp = requests.put(
                POSITIONS_URL.format(instrument=instrument),
                headers=HEADERS,
                json={"longUnits": "ALL", "shortUnits": "ALL"},
                timeout=10
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logging.error("OANDA close_all failed: %s", e)
            return jsonify({"error": "OANDA close_all failed"}), 502
        return jsonify(resp.json()), resp.status_code

    # ——— UNKNOWN ACTION —————————————————————————
    return jsonify({"error": f"Unknown action '{action}'"}), 400


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
