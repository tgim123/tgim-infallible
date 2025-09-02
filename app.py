from flask import Flask, request, jsonify
import os, requests, json
from datetime import datetime

app = Flask(__name__)

# ── Env / Config ─────────────────────────────────────────────────────────────
OANDA_ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID", "").strip()
OANDA_API_KEY    = os.environ.get("OANDA_API_KEY", "").strip()
WEBHOOK_SECRET   = os.environ.get("WEBHOOK_SECRET", "").strip()  # optional

if not OANDA_ACCOUNT_ID or not OANDA_API_KEY:
    raise RuntimeError("Missing OANDA_ACCOUNT_ID or OANDA_API_KEY env vars")

OANDA_BASE      = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}"
OANDA_ORDER_URL = f"{OANDA_BASE}/orders"
HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type": "application/json"
}

LOG_FILE = "webhook.log"

def log_event(event_type, content):
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{datetime.utcnow().isoformat()}Z | {event_type} | {content}\n")
    except Exception as e:
        print(f"Logging error: {e}")

# ── Health + favicon ─────────────────────────────────────────────────────────
@app.get("/")
def health():
    return "✅ TGIM Web Service live", 200

@app.get("/favicon.ico")
def favicon():
    return ("", 204)

# ── Webhook (POST-only) ──────────────────────────────────────────────────────
@app.post("/webhook")
def webhook():
    try:
        # Optional shared-secret check (set WEBHOOK_SECRET in Render)
        if WEBHOOK_SECRET:
            got = request.headers.get("X-Webhook-Secret", "")
            if got != WEBHOOK_SECRET:
                log_event("AUTH_FAIL", f"bad secret: {got!r}")
                return jsonify({"error": "unauthorized"}), 401

        raw = (request.data or b"").decode("utf-8", errors="ignore").strip()
        log_event("RAW_REQUEST", raw[:2000])

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict) and raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                log_event("ERROR", "Invalid JSON")
                return jsonify({"error": "invalid_json"}), 400
        if not isinstance(data, dict):
            return jsonify({"error": "invalid_payload"}), 400

        # Accept both old and new keys
        action     = (data.get("action") or "").strip().lower()
        instrument = (data.get("instrument") or data.get("symbol") or "").strip()
        units_val  = data.get("units", data.get("qty", 0))
        try:
            units = int(units_val)
        except Exception:
            units = 0

        if not action or not instrument:
            log_event("ERROR", f"missing fields | action={action} instrument={instrument}")
            return jsonify({"error": "missing_action_or_instrument"}), 400
        if units == 0 and action in ("buy", "sell"):
            return jsonify({"error": "units_must_be_nonzero"}), 400

        # Build request per action
        if action == "buy":
            order = {"order": {
                "instrument": instrument,
                "units": str(abs(units)),  # positive
                "type": "MARKET",
                "timeInForce": "FOK",
                "positionFill": "DEFAULT"
            }}
            resp = requests.post(OANDA_ORDER_URL, headers=HEADERS, json=order, timeout=15)

        elif action == "sell":
            order = {"order": {
                "instrument": instrument,
                "units": str(-abs(units)),  # negative
                "type": "MARKET",
                "timeInForce": "FOK",
                "positionFill": "DEFAULT"
            }}
            resp = requests.post(OANDA_ORDER_URL, headers=HEADERS, json=order, timeout=15)

        elif action == "close_buy":
            close_url = f"{OANDA_BASE}/positions/{instrument}/close"
            resp = requests.put(close_url, headers=HEADERS, json={"longUnits": "ALL"}, timeout=15)

        elif action == "close_sell":
            close_url = f"{OANDA_BASE}/positions/{instrument}/close"
            resp = requests.put(close_url, headers=HEADERS, json={"shortUnits": "ALL"}, timeout=15)

        else:
            return jsonify({"error": "unknown_action"}), 400

        # Safe log/return (OANDA errors aren’t always JSON)
        try:
            body = resp.json()
        except ValueError:
            body = {"status_code": resp.status_code, "text": resp.text[:2000]}

        log_event("OANDA_RESPONSE", json.dumps(body)[:2000])
        return jsonify(body), resp.status_code

    except Exception as e:
        log_event("ERROR", str(e))
        return jsonify({"error": str(e)}), 500

# ── Local run ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # In Render, you should run via gunicorn; this is fine for local testing.
    app.run(host="0.0.0.0", port=5000)
