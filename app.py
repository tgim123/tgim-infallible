from flask import Flask, request, jsonify, abort
import os, requests, logging

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# ─── Required ENV VARS ────────────────────────────────────────────
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]

# ─── OANDA ENDPOINTS ──────────────────────────────────────────────
DOMAIN         = "api-fxtrade.oanda.com"
BASE_URL       = f"https://{DOMAIN}/v3/accounts/{OANDA_ACCOUNT_ID}"
ORDERS_URL     = f"{BASE_URL}/orders"
POSITIONS_URL  = f"{BASE_URL}/positions/{{instrument}}/close"

HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}


@app.route("/", methods=["GET", "POST"])
def root():
    if request.method == "GET":
        return "✅ Webhook up", 200

    data = request.get_json(force=True) or {}
    # ─── Authenticate by matching the TradingView payload key to your OANDA key ───
    if data.get("api_key") != OANDA_API_KEY:
        abort(401)

    action     = data.get("action")
    raw_inst   = data.get("instrument","")
    # Strip any prefix like "OANDA:" and convert "/" to "_"
    instrument = raw_inst.replace("OANDA:","").replace("/","_")
    units      = int(data.get("units", 0))

    # ─── BUY / SELL ────────────────────────────────────────────────────────────
    if action in ("buy","sell"):
        signed = units if action=="buy" else -units
        payload = {"order":{
            "instrument":   instrument,
            "units":        str(signed),
            "type":         "MARKET",
            "timeInForce":  "FOK",
            "positionFill": "DEFAULT"
        }}
        try:
            r = requests.post(ORDERS_URL, headers=HEADERS, json=payload, timeout=10)
            r.raise_for_status()
        except Exception as e:
            logging.error("Order error: %s", e)
            return jsonify({"error":"order failed"}),502
        return jsonify(r.json()), r.status_code

    # ─── CLOSE LONG ───────────────────────────────────────────────────────────
    if action=="close_buy":
        try:
            r = requests.put(
                POSITIONS_URL.format(instrument=instrument),
                headers=HEADERS,
                json={"longUnits":"ALL"},
                timeout=10
            )
            r.raise_for_status()
        except Exception as e:
            logging.error("Close long error: %s", e)
            return jsonify({"error":"close_buy failed"}),502
        return jsonify(r.json()), r.status_code

    # ─── CLOSE SHORT ──────────────────────────────────────────────────────────
    if action=="close_sell":
        try:
            r = requests.put(
                POSITIONS_URL.format(instrument=instrument),
                headers=HEADERS,
                json={"shortUnits":"ALL"},
                timeout=10
            )
            r.raise_for_status()
        except Exception as e:
            logging.error("Close short error: %s", e)
            return jsonify({"error":"close_sell failed"}),502
        return jsonify(r.json()), r.status_code

    # ─── CLOSE ALL ────────────────────────────────────────────────────────────
    if action=="close_all":
        try:
            r = requests.put(
                POSITIONS_URL.format(instrument=instrument),
                headers=HEADERS,
                json={"longUnits":"ALL","shortUnits":"ALL"},
                timeout=10
            )
            r.raise_for_status()
        except Exception as e:
            logging.error("Close all error: %s", e)
            return jsonify({"error":"close_all failed"}),502
        return jsonify(r.json()), r.status_code

    return jsonify({"error":f"Unknown action '{action}'"}),400


if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",5000)))
