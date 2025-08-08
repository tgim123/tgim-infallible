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

# ─── HEALTH-CHECK ─────────────────────────────────────────────────
@app.route("/", methods=["GET", "HEAD"])
def health_check():
    return "OK", 200

# ─── TRADINGVIEW WEBHOOK ───────────────────────────────────────────
@app.route("/tv-webhook", methods=["POST"])
def tv_webhook():
    data   = request.get_json(force=True)
    action = data["action"]             # e.g. "buy" / "sell" / "close_buy" / "close_sell"
    units  = int(data.get("units", 1))  # default to 1
    instr  = data["instrument"]         # e.g. "EUR_USD"
    side   = "MARKET"

    # sign the units
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
