# app.py
from flask import Flask, request, jsonify
import os, json, requests

app = Flask(__name__)

# ── ENV ─────────────────────────────────────────────
OANDA_ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID", "").strip()
OANDA_API_KEY    = os.environ.get("OANDA_API_KEY", "").strip()
# Optional override (recommended you set this in Render):
OANDA_URL        = os.environ.get("OANDA_URL", "").strip()

# Fallback to LIVE if OANDA_URL not provided
if not OANDA_URL and OANDA_ACCOUNT_ID:
    OANDA_URL = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"

HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json",
    "Accept":        "application/json",
}

ALLOWED_ACTIONS = {"buy", "sell", "close_buy", "close_sell"}

# ── Helpers ─────────────────────────────────────────
def fmt_instrument(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if "_" in s: return s
    return s[:3] + "_" + s[3:] if len(s) >= 6 else s

def build_order_payload(action: str, instrument: str, units: int) -> dict:
    instrument = fmt_instrument(instrument)
    u = abs(int(units))
    if action == "buy":          signed, fill = +u, "DEFAULT"
    elif action == "sell":       signed, fill = -u, "DEFAULT"
    elif action == "close_buy":  signed, fill = -u, "REDUCE_ONLY"
    elif action == "close_sell": signed, fill = +u, "REDUCE_ONLY"
    else: raise ValueError("Unsupported action")
    return {"order": {"instrument": instrument, "units": str(signed),
                      "type": "MARKET", "positionFill": fill}}

def parse_body(req) -> dict:
    data = req.get_json(silent=True)
    if not data:
        raw = (req.data or b"").decode("utf-8", "ignore").strip()
        if not raw: raise ValueError("Empty body")
        try: data = json.loads(raw)
        except json.JSONDecodeError: raise ValueError("Invalid JSON body")
    if not isinstance(data, dict): raise ValueError("Body must be a JSON object")
    missing = [k for k in ("action","instrument","units") if k not in data]
    if missing: raise ValueError(f"Missing fields: {', '.join(missing)}")
    action = str(data["action"]).strip().lower()
    if action not in ALLOWED_ACTIONS: raise ValueError(f"Invalid action '{action}'")
    instrument = str(data["instrument"]).strip()
    try: units = int(data["units"])
    except: raise ValueError("units must be an integer")
    if units <= 0: raise ValueError("units must be > 0")
    return {"action": action, "instrument": instrument, "units": units}

def env_ok():
    if not OANDA_ACCOUNT_ID: return False, "OANDA_ACCOUNT_ID missing"
    if not OANDA_API_KEY:    return False, "OANDA_API_KEY missing"
    if not OANDA_URL:        return False, "OANDA_URL missing"
    return True, "ok"

# ── Routes ──────────────────────────────────────────
@app.get("/")
def index():
    return "✅ TGIM OANDA Webhook is up. Try GET /health or POST /webhook", 200

@app.get("/health")
def health():
    ok, msg = env_ok()
    return jsonify({
        "ok": ok, "message": msg,
        "account": OANDA_ACCOUNT_ID,
        "orders_url": OANDA_URL
    }), 200 if ok else 500

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return "✅ /webhook alive. POST JSON to execute.", 200
    try:
        # debug to logs
        print("=== HEADERS ===", dict(request.headers))
        print("=== RAW BODY ===", (request.data or b"").decode("utf-8", "ignore"))
        print("=== OANDA_URL ==", OANDA_URL)

        ok, msg = env_ok()
        if not ok:
            return jsonify({"ok": False, "error": msg}), 500

        p = parse_body(request)
        order = build_order_payload(**p)

        # send to OANDA, mirror their reply
        r = requests.post(OANDA_URL, headers=HEADERS, json=order, timeout=15)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text}
        print("=== OANDA RESP ===", r.status_code, body)
        return jsonify(body), r.status_code

    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except requests.RequestException as e:
        return jsonify({"ok": False, "error": f"OANDA request failed: {e}"}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": f"Server error: {e}"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
