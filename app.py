from flask import Flask, request, jsonify
import requests, logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ─── LIVE OANDA CREDENTIALS ────────────────────────────────────────────────
OANDA_ACCOUNT_ID = "001-001-3116191-001"
OANDA_API_KEY    = "56a54fc17014aaca9539155a433d01e3-c273c6e3707a45c8e2fb6ef24e5d4ec7"

BASE_URL            = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}"
ORDERS_URL          = f"{BASE_URL}/orders"
POSITIONS_CLOSE_URL = f"{BASE_URL}/positions/{{instrument}}/close"

HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

@app.route("/", methods=["GET","POST"])
def root():
    if request.method == "GET":
        return "✅ Webhook service is up", 200

    data = request.get_json(force=True)
    app.logger.info("Received alert: %s", data)

    action     = data.get("action")
    instrument = data.get("instrument")
    units      = data.get("units")

    try:
        if action == "market_order":
            payload = {
                "order": {
                    "instrument":   instrument,
                    "units":        str(units),
                    "type":         "MARKET",
                    "timeInForce":  "FOK",
                    "positionFill": "DEFAULT"
                }
            }
            resp = requests.post(ORDERS_URL, headers=HEADERS, json=payload)
            app.logger.info("Order response: %s", resp.text)
            return jsonify(resp.json()), resp.status_code

        if action == "close_all":
            url  = POSITIONS_CLOSE_URL.format(instrument=instrument)
            body = {"longUnits":"ALL","shortUnits":"ALL"}
            resp = requests.put(url, headers=HEADERS, json=body)
            app.logger.info("Close response: %s", resp.text)
            return jsonify(resp.json()), resp.status_code

        return jsonify({"error": f"Unknown action '{action}'"}), 400

    except Exception as e:
        app.logger.error("Exception: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
