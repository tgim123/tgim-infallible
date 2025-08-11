from flask import Flask, request, jsonify
import os, requests, json

app = Flask(__name__)

# === OANDA creds (Render env vars) ===
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]

# LIVE endpoint (you said you're live)
OANDA_URL = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"
HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

# Optional: map action to signed units (buy/close short = +, sell/close long = -)
SIGN_MAP = {
    "buy":        +1,
    "sell":       -1,
    "close_buy":  -1,   # close a long by selling
    "close_sell": +1    # close a short by buying
}

@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return "✅ TGIM Webhook is live", 200

    # Be tolerant to empty/plain-text bodies
    raw = (request.data or b"").decode("utf-8").strip()
    data = request.get_json(silent=True)
    if data is None and raw.startswith("{"):
        try:
            data = json.loads(raw)
        except Exception:
            data = None

    if not isinstance(data, dict):
        print("WARN: Invalid/empty payload:", raw, flush=True)
        return jsonify({"ignored": "invalid or empty payload"}), 200  # TV stops retrying

    try:
        action = str(data.get("action"))
        units  = int(data.get("units", 1))
        instr  = str(data.get("instrument", "EUR_USD"))

        if action not in SIGN_MAP:
            return jsonify({"error": f"unknown action '{action}'"}), 200

        signed_units = SIGN_MAP[action] * abs(units)
        body = {
            "order": {
                "instrument":  instr,
                "units":       str(signed_units),
                "type":        "MARKET",
                "positionFill":"DEFAULT"
            }
        }

        resp = requests.post(OANDA_URL, headers=HEADERS, json=body, timeout=15)
        print("IN:", data, "| OUT:", resp.status_code, resp.text[:400], flush=True)

        try:
            return jsonify({"status": "sent", "response": resp.json()}), resp.status_code
        except Exception:
            return jsonify({"status": "sent", "raw": resp.text}), resp.status_code

    except Exception as e:
        print("ERR:", e, "PAYLOAD:", data, flush=True)
        return jsonify({"error": str(e)}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
