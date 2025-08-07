# main.py
from flask import Flask, request
import os, requests, json

app = Flask(__name__)

// pull in your Render env-vars
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]
WEBHOOK_KEY      = os.environ["WEBHOOK_KEY"]  # optional: to lock down your endpoint

OANDA_URL = f"https://api-fxpractice.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"
HEADERS   = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

# if you want to require the webhook key in the path:
@app.route(f"/tv-webhook/{WEBHOOK_KEY}", methods=["POST"])
def tv_webhook():
    data   = request.json
    action = data["action"]       # "buy", "sell", etc.
    units  = int(data["units"])
    instr  = data["instrument"]
    side   = "MARKET"

    # positive for buys/closes of shorts, negative for sells/closes of longs
    sign =  1 if action in ["buy", "close_sell"] else -1

    order_body = {
      "order": {
        "instrument":    instr,
        "units":         str(sign * units),
        "type":          side,
        "positionFill":  "DEFAULT"
      }
    }

    resp = requests.post(OANDA_URL,
                         headers=HEADERS,
                         json=order_body)
    return (resp.text, resp.status_code)

if __name__ == "__main__":
    # in production you’ll run under Gunicorn, but this is fine locally
    app.run(host="0.0.0.0", port=5000)
