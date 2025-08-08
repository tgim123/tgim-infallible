from flask import Flask, request
import os
import requests
import json

app = Flask(__name__)

# Load your OANDA credentials from environment
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
    print("Webhook payload:", data)  # for debugging in your Render logs

    action = data.get("action", "").lower()    # e.g. "buy", "sell", "close_buy", "close_sell"
    units  = int(data.get("units", 0))
    instr  = data.get("instrument", "")

    # Map actions to signed units:
    #  - "buy" and "close_buy" → positive (open long or close short)
    #  - "sell" and "close_sell" → negative (open short or close long)
    if action in ["buy", "close_buy"]:
        signed_units = units
    else:
        signed_units = -units

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
