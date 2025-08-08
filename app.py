from flask import Flask, request
import os
import requests
import json

app = Flask(__name__)

OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]

OANDA_URL = f"https://api-fxpractice.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"
HEADERS   = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

@app.route("/", methods=["POST"])
def tv_webhook():
    data   = request.json
    action = data["action"]       # "buy", "sell", etc.
    units  = int(data["units"])
    instr  = data["instrument"]
    side   = "MARKET"

    order_body = {
        "order": {
            "instrument": instr,
            "units":  str(units if action in ["buy", "close_sell"] else -units),
            "type":    side,
            "positionFill": "DEFAULT"
        }
    }

    resp = requests.post(OANDA_URL, headers=HEADERS, data=json.dumps(order_body))
    return (resp.text, resp.status_code)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
