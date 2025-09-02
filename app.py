from flask import Flask, request, jsonify 
import os
import requests
import json
import uuid
from datetime import datetime, timezone

app = Flask(__name__)

# ── Env / Config ─────────────────────────────────────────────────────────────
OANDA_ACCOUNT_ID = (os.environ.get("OANDA_ACCOUNT_ID") or "").strip()
OANDA_API_KEY    = (os.environ.get("OANDA_API_KEY") or "").strip()

# true/false, 1/0, yes/no all supported (default: practice TRUE)
USE_PRACTICE     = (os.environ.get("USE_PRACTICE", "true").strip().lower()
                    in ("1", "true", "yes", "y"))

WEBHOOK_SECRET   = (os.environ.get("WEBHOOK_SECRET") or "").strip()  # optional
DEFAULT_UNITS    = int((os.environ.get("DEFAULT_UNITS") or "0").strip() or "0")
LOG_FILE         = os.environ.get("LOG_FILE", "webhook.log")

if not OANDA_ACCOUNT_ID or not OANDA_API_KEY:
    raise RuntimeError("Missing OANDA_ACCOUNT_ID or OANDA_API_KEY env vars.")

BASE_HOST        = "https://api-fxpractice.oanda.com" if USE_PRACTICE else "https://api-fxtrade.oanda.com"
OANDA_BASE       = f"{BASE_HOST}/v3/accounts/{OANDA_ACCOUNT_ID}"
OANDA_ORDER_URL  = f"{OANDA_BASE}/orders"

HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type": "application/json",
    # Idempotency helpful during retries; per-request UUID
    "X-Request-ID": str(uuid.uuid4()),
}

# ── Logging ──────────────────────────────────────────────────────────────────
def log_event(event_type, content):
    line = f"{datetime.now(timezone.utc).isoformat()}Z | {event_type} | {content}"
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)

# ── Helpers ──────────────────────────────────────────────────────────────────
def parse_units(value):
    """Accept int/float/str -> int. '100.0' → 100. None/invalid → 0."""
    if value is None:
        return 0
    try:
        if isinstance(value, str):
            v = value.strip()
            if v.upper() == "ALL":  # for close payloads (not used in market orders)
                return v
            return int(float(v))
        return int(float(value))
    except Exception:
        return 0

def normalize_instrument(sym):
    """
    Accepts: 'OANDA:EURUSD', 'EURUSD', 'EUR_USD', 'XAUUSD', 'NAS100USD'
    Returns: 'EUR_USD', 'XAU_USD', 'NAS100_USD'
    """
    if not sym:
        return None
    s = str(sym).strip().upper()
    if ":" in s:
        s = s.split(":", 1)[1]  # drop 'OANDA:' prefix
    s = s.replace("_", "").replace("/", "").replace("-", "")
    if len(s) < 6:
        return None
    base = s[:-3]
    quote = s[-3:]
    return f"{base}_{quote}"

def get_secret_from_request(req_json):
    # Allow header or JSON field
    header_secret = request.headers.get("X-Webhook-Secret")
    body_secret   = None
    if isinstance(req_json, dict):
        body_secret = req_json.get("secret")
    return header_secret or body_secret

def post_oanda(url, payload):
    log_event("OANDA_REQUEST", json.dumps(payload))
    r = requests.post(url, headers=HEADERS, json=payload, timeout=15)
    try:
        resp_json = r.json()
    except Exception:
        resp_json = {"text": r.text}
    log_event("OANDA_RESPONSE", json.dumps({"status": r.status_code, "body": resp_json}))
    return r.status_code, resp_json

def put_oanda(url, payload):
    log_event("OANDA_REQUEST", json.dumps(payload))
    r = requests.put(url, headers=HEADERS, json=payload, timeout=15)
    try:
        resp_json = r.json()
    except Exception:
        resp_json = {"text": r.text}
    log_event("OANDA_RESPONSE", json.dumps({"status": r.status_code, "body": resp_json}))
    return r.status_code, resp_json

# ── Routes ───────────────────────────────────────────────────────────────────
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = "practice" if USE_PRACTICE else "live"
        return f"✅ TGIM Webhook is live ({mode})", 200

    try:
        raw = (request.data or b"").decode("utf-8", errors="ignore").strip()
        data = request.get_json(silent=True)

        log_event("RAW_REQUEST", raw if raw else "<empty>")

        if data is None and raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                log_event("ERROR", "Invalid JSON payload")
                return jsonify({"error": "Invalid JSON"}), 400

        if not isinstance(data, dict):
            log_event("ERROR", "Invalid payload format")
            return jsonify({"error": "Invalid payload format"}), 400

        # Optional secret gate
        if WEBHOOK_SECRET:
            sent = get_secret_from_request(data)
            if sent != WEBHOOK_SECRET:
                log_event("ERROR", "Unauthorized: bad/missing secret")
                return jsonify({"error": "Unauthorized"}), 401

        # Accept old & new keys
        action_raw  = data.get("action") or data.get("side") or ""
        action      = str(action_raw).strip().lower()

        instr_raw   = data.get("ins_
