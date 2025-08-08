from flask import Flask, request
import os
import requests
import json

app = Flask(__name__)

# Load your LIVE OANDA credentials from environment
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]
WEBHOOK_KEY      = os.environ["WEBHOOK_KEY"]   # your TradingView webhook secret

# ▶ LIVE OANDA REST endpoint (not practice)
OANDA_URL = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"
HEADERS   = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

@app.route("/tv-webhook/<key>", methods=["POST"])
def tv_webhook(key):
    # 1) Authenticate
    if key != WEBHOOK_KEY:
        return ("unauthorized", 401)

    # 2) Parse incoming JSON
    data = request.get_json(force=True)
    print("Webhook payload:", data)

    action = data.get("action", "").lower()    # "buy"/"sell"/"close_buy"/"close_sell"
    units  = int(data.get("units", 0))
    instr  = data.get("instrument", "")

    # 3) Determine signed units for LIVE account
    signed_units = units if action in ["buy", "close_buy"] else -units

    # 4) Build and send order
    order_body = {
        "order": {
            "instrument":   instr,
            "units":        str(signed_units),
            "type":         "MARKET",
            "positionFill": "DEFAULT"
        }
    }
    resp = requests.post(OANDA_URL, headers=HEADERS, data=json.dumps(order_body))

    return (resp.text, resp.status_code)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
