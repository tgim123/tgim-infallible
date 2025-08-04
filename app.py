from flask import Flask, request, jsonify
import requests, logging, os, json, math

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ─── OANDA ENV & ENDPOINTS ────────────────────────────────────────────────
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]
DOMAIN           = "api-fxtrade.oanda.com"  # live
BASE_URL         = f"https://{DOMAIN}/v3/accounts/{OANDA_ACCOUNT_ID}"
PRICING_URL      = f"https://{DOMAIN}/v3/accounts/{OANDA_ACCOUNT_ID}/pricing"
ORDERS_URL       = f"{BASE_URL}/orders"
POSITIONS_URL    = f"{BASE_URL}/positions/{{instrument}}/close"

HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

@app.route("/", methods=["GET","POST"])
def root():
    if request.method == "GET":
        return "✅ Webhook service is up", 200

    # 1) Parse incoming JSON
    raw = request.get_data(as_text=True)
    app.logger.info("📥 Raw payload: %s", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return jsonify({"error":"Invalid JSON"}), 400

    action     = data.get("action")
    instrument = data.get("instrument")
    risk_pct   = data.get("risk_pct")    # e.g. 0.02 for 2%
    app.logger.info("▶ Parsed → action=%s instrument=%s risk_pct=%s",
                    action, instrument, risk_pct)

    if action != "market_order":
        # fallback to close_all logic
        if action == "close_all":
            resp = requests.put(
                POSITIONS_URL.format(instrument=instrument),
                headers=HEADERS,
                json={"longUnits":"ALL","shortUnits":"ALL"}
            )
            app.logger.info("✅ Close-all response: %s", resp.text)
            return jsonify(resp.json()), resp.status_code
        return jsonify({"error":f"Unknown action '{action}'"}), 400

    # 2) Fetch account equity
    acct = requests.get(f"{BASE_URL}/summary", headers=HEADERS).json()["account"]
    equity = float(acct["NAV"] or acct["balance"])
    app.logger.info("💰 Account equity: %s", equity)

    # 3) Fetch current mid‐price for instrument
    pr = requests.get(
        PRICING_URL,
        headers=HEADERS,
        params={"instruments": instrument}
    ).json()["prices"][0]
    bid = float(pr["bids"][0]["price"])
    ask = float(pr["asks"][0]["price"])
    price = (bid+ask)/2
    app.logger.info("📊 Current price: %s (bid=%s ask=%s)", price, bid, ask)

    # 4) Compute units = (equity * risk_pct) / price
    units = math.floor(equity * float(risk_pct) / price)
    app.logger.info("⚖️ Computed units: %s", units)

    # 5) Auto-close opposite side if needed
    pos = requests.get(f"{BASE_URL}/positions/{instrument}", headers=HEADERS).json()["position"]
    long_u  = float(pos["long"]["units"])
    short_u = float(pos["short"]["units"])
    if units > 0 and short_u != 0:
        requests.put(
            f"{BASE_URL}/positions/{instrument}/close",
            headers=HEADERS, json={"shortUnits":"ALL"}
        )
    if units < 0 and long_u != 0:
        requests.put(
            f"{BASE_URL}/positions/{instrument}/close",
            headers=HEADERS, json={"longUnits":"ALL"}
        )

    # 6) Place the market order
    payload = {
        "order": {
            "instrument":   instrument,
            "units":        str(units),
            "type":         "MARKET",
            "timeInForce":  "FOK",
            "positionFill": "DEFAULT"
        }
    }
    resp = requests.post(ORDERS_URL, headers=HEADERS, json=payload)
    app.logger.info("✅ Order response: %s", resp.text)
    return jsonify(resp.json()), resp.status_code

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
