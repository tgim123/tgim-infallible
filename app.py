from flask import Flask, request, jsonify
import os, requests, json
from datetime import datetime

app = Flask(__name__)

# ── Env / Config ─────────────────────────────────────────────────────────────
OANDA_ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID", "").strip()
OANDA_API_KEY    = os.environ.get("OANDA_API_KEY", "").strip()
WEBHOOK_SECRET   = os.environ.get("WEBHOOK_SECRET", "").strip()  # optional shared secret

if not OANDA_ACCOUNT_ID or not OANDA_API_KEY:
    raise RuntimeError("Missing OANDA_ACCOUNT_ID or OANDA_API_KEY env vars")

# Live (your preference)
OANDA_BASE      = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}"
OANDA_ORDER_URL = f"{OANDA_BASE}/orders"
OANDA_POS_URL   = f"{OANDA_BASE}/positions"

HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type": "application/json"
}

LOG_FILE = "webhook.log"

def log_line(kind, content):
    line = f"{datetime.utcnow().isoformat()}Z | {kind} | {content}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

def to_json(resp):
    try:
        return resp.json()
    except ValueError:
        return {"status_code": resp.status_code, "text": resp.text[:2000]}

# ── Health + favicon ─────────────────────────────────────────────────────────
@app.get("/")
def health():
    return "✅ TGIM Web Service live", 200

@app.get("/favicon.ico")
def favicon():
    return ("", 204)

# ── Echo route (for fast wire testing) ───────────────────────────────────────
@app.route("/echo", methods=["GET", "POST"])
def echo():
    raw = (request.data or b"").decode("utf-8", errors="ignore")
    log_line("ECHO_" + request.method, raw[:2000])
    payload = {}
    try:
        payload = request.get_json(force=True, silent=True) or {}
    except Exception:
        pass
    return jsonify({"ok": True, "method": request.method, "json": payload}), 200

# ── Webhook (accepts modern + legacy actions) ────────────────────────────────
@app.post("/webhook")
def webhook():
    # Optional shared-secret check
    if WEBHOOK_SECRET:
        got = request.headers.get("X-Webhook-Secret", "")
        if got != WEBHOOK_SECRET:
            log_line("AUTH_FAIL", f"bad secret: {got!r}")
            return jsonify({"error": "unauthorized"}), 401

    raw = (request.data or b"").decode("utf-8", errors="ignore").strip()
    log_line("RX", raw[:2000])

    # Robust JSON parse
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return jsonify({"error": "invalid_json"}), 400

    action     = (data.get("action") or "").strip().lower()
    instrument = (data.get("instrument") or data.get("symbol") or "").strip()
    side       = (data.get("side") or "").strip().lower()  # optional for "close"
    units_val  = data.get("units", data.get("qty", 0))

    try:
        units = int(round(float(units_val)))
    except Exception:
        units = 0

    if not action or not instrument:
        log_line("BAD_REQ", f"missing action/instrument | {data}")
        return jsonify({"error": "missing_action_or_instrument"}), 400

    # Dispatch
    try:
        if action in ("buy", "sell"):
            if units == 0:
                return jsonify({"error": "units_must_be_nonzero"}), 400
            signed = units if action == "buy" else -abs(units)
            order = {
                "order": {
                    "instrument": instrument,
                    "units": str(int(signed)),
                    "type": "MARKET",
                    "timeInForce": "FOK",
                    "positionFill": "DEFAULT"
                }
            }
            r = requests.post(OANDA_ORDER_URL, headers=HEADERS, json=order, timeout=15)
            body = to_json(r)
            log_line("ORDER", json.dumps({"inst": instrument, "units": signed, "code": r.status_code})[:2000])
            return jsonify(body), r.status_code

        elif action in ("close", "close_all", "close_buy", "close_sell"):
            # Normalize legacy variants
            if action == "close_buy":
                side = "long"
            elif action == "close_sell":
                side = "short"
            url = f"{OANDA_POS_URL}/{instrument}/close"
            if action == "close_all" or side == "":
                body = {"longUnits": "ALL", "shortUnits": "ALL"}
            elif side == "long":
                body = {"longUnits": "ALL"}
            elif side == "short":
                body = {"shortUnits": "ALL"}
            else:
                return jsonify({"error": "invalid_close_side"}), 400
            r = requests.put(url, headers=HEADERS, json=body, timeout=15)
            payload = to_json(r)
            log_line("CLOSE", json.dumps({"inst": instrument, "side": side or "both", "code": r.status_code})[:2000])
            return jsonify(payload), r.status_code

        else:
            log_line("UNKNOWN_ACTION", action)
            return jsonify({"error": f"unknown_action:{action}"}), 400

    except Exception as e:
        log_line("ERROR", str(e))
        return jsonify({"error": str(e)}), 500

# ── Local run ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # In Render you’ll typically use gunicorn, but this keeps local tests sane.
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
