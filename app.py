from flask import Flask, request, jsonify
import os, requests, json

app = Flask(__name__)

OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]

OANDA_URL = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"
HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
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
            pass

    if not isinstance(data, dict):
        # log and reply 200 so TV stops retrying; nothing to do
        print("WARN: Invalid/empty payload:", raw, flush=True)
        return jsonify({"ignored": "invalid or empty payload"}), 200

    try:
        action = str(data.get("action"))
        units  = int(data.get("units", 1))
        instr  = str(data.get("instrument", "EUR_USD"))

        order_units = units if action in ["buy", "close_sell"] else -units
        order = {
            "order": {
                "instrument": instr,
                "units": str(order_units),
                "type": "MARKET",
                "positionFill": "DEFAULT"
            }
        }

        resp = requests.post(OANDA_URL, headers=HEADERS, json=order)
        print("IN:", data, "OUT:", resp.status_code, resp.text, flush=True)
        try:
            return jsonify({"status": "sent", "response": resp.json()}), resp.status_code
        except Exception:
            return jsonify({"status": "sent", "raw": resp.text}), resp.status_code

    except Exception as e:
        print("ERR:", e, "PAYLOAD:", data, flush=True)
        return jsonify({"error": str(e)}), 200
