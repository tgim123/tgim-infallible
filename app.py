from flask import Flask, request, jsonify
import os, json, requests

app = Flask(__name__)

ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID", "").strip()
API_KEY    = os.environ.get("OANDA_API_KEY", "").strip()
if not ACCOUNT_ID or not API_KEY:
    raise RuntimeError("Missing OANDA_ACCOUNT_ID or OANDA_API_KEY in environment.")

BASE_HOST  = "https://api-fxtrade.oanda.com"  # LIVE host (intentional)
BASE_URL   = f"{BASE_HOST}/v3/accounts/{ACCOUNT_ID}"
ORDERS_URL = f"{BASE_URL}/orders"
HEADERS    = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

def normalize(sym):
    s = str(sym).replace("OANDA:", "").replace(":", "").upper()
    if "_" in s: return s
    if len(s) == 6: return f"{s[:3]}_{s[3:]}"
    if s == "XAUUSD": return "XAU_USD"
    return s

def place_market_order(instrument, units):
    payload = {
        "order": {
            "instrument": instrument,
            "units": str(int(units)),
            "type": "MARKET",
            "timeInForce": "FOK",
            "positionFill": "DEFAULT"
        }
    }
    r = requests.post(ORDERS_URL, headers=HEADERS, data=json.dumps(payload), timeout=15)
    app.logger.info(f"OANDA POST /orders status={r.status_code} resp={r.text[:300]}")
    return r.status_code, (r.json() if r.content else {})

def close_position(instrument, side="both"):
    url = f"{BASE_URL}/positions/{instrument}/close"
    body = {}
    if side in ("long", "both"):  body["longUnits"]  = "ALL"
    if side in ("short", "both"): body["shortUnits"] = "ALL"
    r = requests.put(url, headers=HEADERS, data=json.dumps(body), timeout=15)
    app.logger.info(f"OANDA PUT /positions/{instrument}/close status={r.status_code} resp={r.text[:300]}")
    return r.status_code, (r.json() if r.content else {})

@app.route("/", methods=["GET"])
def root():
    return "TGIM Infallible online. Use POST /webhook."

@app.route("/webhook", methods=["GET","POST"])
def webhook():
    if request.method == "GET":
        return jsonify(ok=True, route="/webhook", expect="POST JSON"), 200

    data = request.get_json(silent=True) or {}
    if isinstance(data, str):
        data = json.loads(data)
    app.logger.info(f"Incoming TV payload: {data}")

    action     = str(data.get("action", "")).lower().strip()
    instrument = normalize(data.get("instrument") or data.get("symbol") or "")
    units      = int(float(data.get("units", data.get("qty", 0) or 0)))

    if action == "buy":
        return jsonify(place_market_order(instrument, abs(units)))
    elif action == "sell":
        return jsonify(place_market_order(instrument, -abs(units)))
    elif action == "close":
        side = str(data.get("side", "both")).lower()
        return jsonify(close_position(instrument, side=side))
    elif action == "close_all":
        return jsonify(close_position(instrument, side="both"))
    else:
        app.logger.info("Ignored payload (no action).")
        return jsonify(ok=True, ignored=True), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
