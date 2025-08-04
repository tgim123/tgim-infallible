from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# ✅ LIVE OANDA CONFIG (no placeholders)
OANDA_ACCOUNT_ID = "001-001-3116191-001"
OANDA_API_KEY   = "e6a7d8cac04118841ce0df0648160386-3c9cbdb8edeee1d64004daa4fd24277f"
BASE_URL        = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}"

HEADERS = {
  "Content-Type":  "application/json",
  "Authorization": f"Bearer {OANDA_API_KEY}"
}


@app.route("/webhook", methods=["POST"])
def webhook():
    data       = request.get_json()
    action     = data.get("action")       # "market_order" or "close_all"
    instrument = data.get("instrument")   # e.g. "EUR_USD"
    # note: for market_order alerts you're passing a positive integer for buys
    #       and a positive integer for sells too (we’ll flip it below)
    units      = int(data.get("units", 0))

    # ——————— MARKET ORDER (BUY or SELL) ———————
    if action == "market_order":
        # determine sign: negative for sells
        side = data.get("side", "").lower()
        if side == "sell":
            units = -abs(units)
        else:
            units = abs(units)

        payload = {
          "order": {
            "instrument":   instrument,
            "units":        str(units),
            "timeInForce":  "FOK",
            "type":         "MARKET",
            "positionFill": "DEFAULT"
          }
        }

        resp = requests.post(
          f"{BASE_URL}/orders",
          headers=HEADERS,
          json=payload
        )

        app.logger.info("OANDA market_order response: %s", resp.text)
        return jsonify(resp.json()), resp.status_code


    # ——————— CLOSE ALL POSITIONS FOR THIS INSTRUMENT ———————
    elif action == "close_all":
        # OANDA: PUT /v3/accounts/{accountID}/positions/{instrument}/close
        resp = requests.put(
          f"{BASE_URL}/positions/{instrument}/close",
          headers=HEADERS
        )

        app.logger.info("OANDA close_all response: %s", resp.text)
        return jsonify(resp.json()), resp.status_code


    # ——————— IGNORE EVERYTHING ELSE ———————
    else:
        return jsonify({"ignored": True}), 200


if __name__ == "__main__":
    # Render binds to $PORT automatically, but locally we’ll use 10000
    app.run(port=10000)
