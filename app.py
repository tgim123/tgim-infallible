# app.py
from flask import Flask, request, jsonify
import os, requests, json
from datetime import datetime

app = Flask(__name__)

# ── OANDA config (LIVE host by default)
OANDA_ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID", "").strip()
OANDA_API_KEY    = os.environ.get("OANDA_API_KEY", "").strip()
WEBHOOK_SECRET   = os.environ.get("WEBHOOK_SECRET", "").strip()  # optional

if not OANDA_ACCOUNT_ID or not OANDA_API_KEY:
    raise RuntimeError("Missing OANDA_ACCOUNT_ID or OANDA_API_KEY env vars")

OANDA_BASE      = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}"
OANDA_ORDER_URL = f"{OANDA_BASE}/orders"
OANDA_POS_URL   = f"{OANDA_BASE}/positions"

HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type": "application/json"
}

def log_line(kind, content):
    print(f"{datetime.utcnow().isoformat()}Z | {kind} | {content}", flush=True)

def to_json(resp):
    try:
        return resp.json()
    except ValueError:
        return {"status_code": resp.status_code, "text": resp.text[:2000]}

@app.get("/")
def health():
    return "✅ TGIM Web Service live", 200

@app.post("/webhook")
def webhook():
    if WEBHOOK_SECRET:
        got = request.headers.get("X-Webhook-Secret", "")
        if got != WEBHOOK_SECRET:
            log_line("AUTH_FAIL", f"bad secret {got!r}")
            return jsonify({"error": "unauthorized"}), 401

    raw = (request.data or b"").decode("utf-8", errors="ignore")
    log_line("RX", raw[:2000])

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return jsonify({"error": "invalid_json"}), 400

    action     = (data.get("action") or "").strip().lower()          # buy | sell | close_buy | close_sell
    instrument = (data.get("instrument") or data.get("symbol") or "").strip()
    units_val  = data.get("units", data.get("qty", 0))

    try:
        units = int(round(float(units_val)))
    except Exception:
        units = 0

    if not action or not instrument:
        return jsonify({"error": "missing_action_or_instrument"}), 400

    try:
        if action == "buy":
            if units <= 0: return jsonify({"error":"units_must_be_positive"}), 400
            order = {"order":{
                "instrument": instrument,
                "units": str(units),        # positive
                "type": "MARKET",
                "timeInForce": "FOK",
                "positionFill": "DEFAULT"
            }}
            r = requests.post(OANDA_ORDER_URL, headers=HEADERS, json=order, timeout=15)
            body = to_json(r)
            log_line("ORDER", {"inst":instrument,"units":units,"code":r.status_code})
            return jsonify(body), r.status_code

        if action == "sell":
            if units <= 0: return jsonify({"error":"units_must_be_positive"}), 400
            order = {"order":{
                "instrument": instrument,
                "units": str(-abs(units)),  # negative
                "type": "MARKET",
                "timeInForce": "FOK",
                "positionFill": "DEFAULT"
            }}
            r = requests.post(OANDA_ORDER_URL, headers=HEADERS, json=order, timeout=15)
            body = to_json(r)
            log_line("ORDER", {"inst":instrument,"units":-abs(units),"code":r.status_code})
            return jsonify(body), r.status_code

        if action == "close_buy":
            url = f"{OANDA_POS_URL}/{instrument}/close"
            r = requests.put(url, headers=HEADERS, json={"longUnits":"ALL"}, timeout=15)
            body = to_json(r)
            log_line("CLOSE", {"inst":instrument,"side":"long","code":r.status_code})
            return jsonify(body), r.status_code

        if action == "close_sell":
            url = f"{OANDA_POS_URL}/{instrument}/close"
            r = requests.put(url, headers=HEADERS, json={"shortUnits":"ALL"}, timeout=15)
            body = to_json(r)
            log_line("CLOSE", {"inst":instrument,"side":"short","code":r.status_code})
            return jsonify(body), r.status_code

        return jsonify({"error": f"unknown_action:{action}"}), 400

    except Exception as e:
        log_line("ERROR", str(e))
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
