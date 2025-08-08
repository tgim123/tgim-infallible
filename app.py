# app.py

from flask import Flask, request, abort
import os, requests, json

app = Flask(__name__)

# Live OANDA credentials from environment
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]

OANDA_URL = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"
HEADERS   = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

# Only root endpoint—no /webhook, no mirror
@app.route("/", methods=["POST"])
def root():
    if request.headers.get("Content-Type") != "application/json":
        abort(400, "Expected JSON")

    data       = request.get_json()
    action     = data.get("action")
    instrument = data.get("instrument")
    units      = int(data.get("units", 0))

    if not all([action, instrument, units]):
        abort(400, "Missing 'action', 'instrument', or 'units'")

    if action.lower() in ("buy", "close_sell"):
        order_units = units
    elif action.lower() in ("sell", "close_buy"):
        order_units = -units
    else:
        abort(400, f"Unknown action '{action}'")

    payload = {
        "order": {
            "instrument":   instrument,
            "units":        str(order_units),
            "type":         "MARKET",
            "positionFill": "DEFAULT"
        }
    }

    resp = requests.post(OANDA_URL, headers=HEADERS, data=json.dumps(payload))
    return (resp.text, resp.status_code)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
