from flask import Flask, request, abort
import os, requests

app = Flask(__name__)

# environment‐pulled OANDA creds
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]
OANDA_URL        = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"

HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

@app.route("/", methods=["POST"])
def root():
    # force JSON parse (415 if wrong media type)
    data = request.get_json(force=True)

    action     = data.get("action")
    instrument = data.get("instrument")
    units      = data.get("units")
    if not all([action, instrument, units]):
        abort(400, "Missing 'action', 'instrument', or 'units'")

    # sign the units
    sign = 1 if action.lower() in ("buy", "close_sell") else -1
    order_units = str(int(units) * sign)

    order_body = {
        "order": {
            "instrument":   instrument,
            "units":        order_units,
            "type":         "MARKET",
            "positionFill": "DEFAULT"
        }
    }

    resp = requests.post(OANDA_URL, headers=HEADERS, json=order_body)
    return (resp.text, resp.status_code)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
