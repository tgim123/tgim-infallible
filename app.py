from flask import Flask, request, jsonify, abort
import os, requests

app = Flask(__name__)

OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY   = os.environ["OANDA_API_KEY"]

BASE = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}"
ORDERS_URL    = f"{BASE}/orders"
POSITIONS_URL = f"{BASE}/positions/{{instrument}}/close"
HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

@app.route("/", methods=["POST","GET"])
def root():
    if request.method == "GET":
        return "✅ OK", 200

    data = request.get_json(force=True)
    action     = data["action"]
    instrument = data["instrument"]
    units      = int(data["units"])

    # BUY / SELL
    if action in ("buy","sell"):
        signed = units if action=="buy" else -units
        payload = {
          "order":{
            "instrument": instrument,
            "units":      str(signed),
            "type":       "MARKET",
            "timeInForce":"FOK",
            "positionFill":"DEFAULT"
          }
        }
        resp = requests.post(ORDERS_URL, headers=HEADERS, json=payload)
        return jsonify(resp.json()), resp.status_code

    # CLOSE LONG/SHORT/ALL:
    if action=="close_buy":
        resp = requests.put(POSITIONS_URL.format(instrument=instrument),
                            headers=HEADERS, json={"longUnits":"ALL"})
        return jsonify(resp.json()), resp.status_code

    if action=="close_sell":
        resp = requests.put(POSITIONS_URL.format(instrument=instrument),
                            headers=HEADERS, json={"shortUnits":"ALL"})
        return jsonify(resp.json()), resp.status_code

    if action=="close_all":
        resp = requests.put(POSITIONS_URL.format(instrument=instrument),
                            headers=HEADERS, json={"longUnits":"ALL","shortUnits":"ALL"})
        return jsonify(resp.json()), resp.status_code

    return jsonify({"error":f"Unknown action {action}"}), 400

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",5000)))
