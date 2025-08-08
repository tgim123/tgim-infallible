from flask import Flask, request
import os, requests, json

app = Flask(__name__)

# ─── OANDA SETTINGS ───────────────────────────────────────────────
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]
OANDA_URL        = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"
HEADERS          = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

# ─── ROOT ENDPOINT (health-check + webhook) ───────────────────────
@app.route("/", methods=["GET", "HEAD", "POST"])
def root():
    # Health‐check for GET/HEAD
    if request.method in ("GET", "HEAD"):
        return "OK", 200

    # POST → TradingView webhook
    data   = request.get_json(force=True)
    action = data["action"]             # "buy", "sell", "close_buy", "close_sell"
    units  = int(data.get("units", 1))  # default 1 if missing
    instr  = data["instrument"]         # e.g. "EUR_USD"
    side   = "MARKET"

    # Determine signed units
    order_units = str(units) if action in ["buy", "close_sell"] else str(-units)

    order_body = {
        "order": {
            "instrument":   instr,
            "units":        order_units,
            "type":         side,
            "positionFill": "DEFAULT"
        }
    }

    resp = requests.post(OANDA_URL, headers=HEADERS, data=json.dumps(order_body))
    return resp.text, resp.status_code


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
