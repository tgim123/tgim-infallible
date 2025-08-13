# app.py
from flask import Flask, request, jsonify
import os, requests, json, re

app = Flask(__name__)

# ==== OANDA (LIVE) ====
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]
OANDA_URL = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"  # LIVE, not practice
HEADERS = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

ALLOWED = {"buy","sell","close_buy","close_sell"}

def parse_body():
    """
    Accept TradingView text/plain or JSON.
    Try JSON first, then parse simple k=v or raw text.
    """
    # 1) JSON if possible
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data, None

    raw = (request.data or b"").decode("utf-8").strip()
    if not raw:
        return None, "Empty body"

    # 2) Raw JSON string with single quotes? -> convert to valid JSON
    if raw.startswith("{") and raw.endswith("}"):
        try:
            return json.loads(raw.replace("'", '"')), None
        except Exception as e:
            return None, f"Invalid JSON: {e}"

    # 3) Fallback: parse key=value;key2=value2 or action:buy, etc.
    # e.g., action=buy;instrument=EURUSD;units=100
    kv = {}
    for part in re.split(r"[;,&\n ]+", raw):
        if "=" in part:
            k,v = part.split("=",1)
            kv[k.strip()] = v.strip()
        elif ":" in part:
            k,v = part.split(":",1)
            kv[k.strip()] = v.strip()
    if kv:
        return kv, None

    return None, "Unrecognized body format"

def norm_instrument(instr: str) -> str:
    if not instr: 
        return ""
    # Accept EURUSD, eurusd, EUR_USD, OANDA:EUR_USD, FX:GBPJPY, etc.
    t = instr.upper()
    t = t.split(":")[-1]               # drop prefix
    t = t.replace("-", "").replace(" ", "").replace("/", "").replace(".", "")
    t = t.replace("__","_")
    t = t.replace("_","")              # strip underscores to rebuild cleanly
    if len(t) < 6: 
        return ""
    base, quote = t[:3], t[3:6]
    return f"{base}_{quote}"

def norm_units(val) -> int:
    try:
        return int(float(val))
    except:
        return 0

def map_action_to_signed_units(action: str, units: int) -> int:
    # buy / close short => +units; sell / close long => -units
    if action == "buy":         return +units
    if action == "sell":        return -units
    if action == "close_buy":   return -units   # closing a long by selling
    if action == "close_sell":  return +units   # closing a short by buying
    return 0

@app.route("/health", methods=["GET"])
def health():
    return "✅ TGIM Webhook live", 200

@app.route("/webhook", methods=["POST","GET"])
def webhook():
    if request.method == "GET":
        return "✅ TGIM Webhook live", 200

    data, err = parse_body()
    if err:
        return jsonify({"ok": False, "reason": err}), 400

    action = str(data.get("action","")).strip().lower()
    instrument_raw = str(data.get("instrument","")).strip()
    units_raw = data.get("units", "")
    instrument = norm_instrument(instrument_raw)
    units = norm_units(units_raw)

    if action not in ALLOWED:
        return jsonify({"ok": False, "reason": f"Invalid action '{action}'. Allowed: {sorted(ALLOWED)}"}), 400
    if not instrument:
        return jsonify({"ok": False, "reason": f"Invalid instrument '{instrument_raw}'. Expect e.g. EUR_USD or EURUSD"}), 400
    if units <= 0:
        return jsonify({"ok": False, "reason": f"Invalid units '{units_raw}'"}), 400

    signed_units = map_action_to_signed_units(action, units)

    payload = {
        "order": {
            "units": str(signed_units),
            "instrument": instrument,
            "timeInForce": "FOK",
            "type": "MARKET",
            "positionFill": "DEFAULT"
        }
    }

    try:
        r = requests.post(OANDA_URL, headers=HEADERS, data=json.dumps(payload), timeout=10)
        if r.status_code >= 200 and r.status_code < 300:
            return jsonify({"ok": True, "action": action, "instrument": instrument, "units": signed_units, "oanda_status": r.status_code}), 200
        else:
            # Bubble up OANDA error for debugging
            return jsonify({"ok": False, "reason": "OANDA rejected", "status": r.status_code, "body": r.text}), 502
    except Exception as e:
        return jsonify({"ok": False, "reason": f"Exception posting to OANDA: {e}"}), 502

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
