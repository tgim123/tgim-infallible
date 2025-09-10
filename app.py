from flask import Flask, request, jsonify
import os, json, requests
from decimal import Decimal, InvalidOperation

app = Flask(__name__)

ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID", "").strip()
API_KEY    = os.environ.get("OANDA_API_KEY", "").strip()
if not ACCOUNT_ID or not API_KEY:
    raise RuntimeError("Missing OANDA_ACCOUNT_ID or OANDA_API_KEY in environment.")

# LIVE host (intentional)
BASE_HOST  = "https://api-fxtrade.oanda.com"
BASE_URL   = f"{BASE_HOST}/v3/accounts/{ACCOUNT_ID}"
ORDERS_URL = f"{BASE_URL}/orders"
HEADERS    = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

def normalize(sym: str) -> str:
    """Normalize common symbol forms to OANDA format like 'EUR_USD' or 'XAU_USD'."""
    s = str(sym or "").upper().strip()
    s = s.replace("OANDA:", "").replace("FX:", "").replace("FOREXCOM:", "").replace("IDC:", "")
    s = s.replace(":", "").replace("-", "").replace("/", "").replace(" ", "")
    if s == "XAUUSD": return "XAU_USD"
    if "_" in s:      return s
    if len(s) == 6 and s.isalpha():
        return f"{s[:3]}_{s[3:]}"
    return s

def to_int_units(val) -> int:
    """Exact integer coercion with sane rounding; avoids float precision issues."""
    if val is None:
        raise ValueError("units missing")
    try:
        q = Decimal(str(val)).to_integral_value(rounding="ROUND_HALF_UP")
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"units_not_int_castable: got={val!r}")
    n = int(q)
    return 1 if n < 1 else n

def place_market_order(instrument: str, signed_units: int):
    payload = {
        "order": {
            "instrument": instrument,
            "units": str(int(signed_units)),   # OANDA expects string int
            "type": "MARKET",
            "timeInForce": "FOK",
            "positionFill": "DEFAULT"
        }
    }
    r = requests.post(ORDERS_URL, headers=HEADERS, json=payload, timeout=15)
    try:
        body = r.json()
    except Exception:
        body = {"text": r.text}
    app.logger.info({"action": "order", "status": r.status_code, "units": signed_units, "instrument": instrument, "resp_snip": str(body)[:300]})
    return r.status_code, body

def close_position(instrument: str, side: str = "both"):
    url = f"{BASE_URL}/positions/{instrument}/close"
    body = {}
    side = (side or "both").lower().strip()
    if side in ("long", "both"):  body["longUnits"]  = "ALL"
    if side in ("short", "both"): body["shortUnits"] = "ALL"
    r = requests.put(url, headers=HEADERS, json=body, timeout=15)
    try:
        resp = r.json()
    except Exception:
        resp = {"text": r.text}
    app.logger.info({"action": "close", "status": r.status_code, "instrument": instrument, "side": side, "resp_snip": str(resp)[:300]})
    return r.status_code, resp

@app.route("/", methods=["GET"])
def root():
    return "TGIM Infallible online. Use POST /webhook."

@app.route("/webhook", methods=["GET","POST"])
def webhook():
    if request.method == "GET":
        return jsonify(ok=True, route="/webhook", expect="POST JSON"), 200

    # Parse JSON safely
    data = request.get_json(silent=True)
    if data is None:
        try:
            data = json.loads(request.data.decode("utf-8"))
        except Exception:
            data = {}
    app.logger.info({"incoming": data})

    action     = str(data.get("action", "")).lower().strip()
    mode       = str(data.get("mode", "")).lower().strip()  # optional; prefer "units"
    instrument = normalize(data.get("instrument") or data.get("symbol") or "")

    if not action or not instrument:
        return jsonify(ok=False, error="missing_fields", got={"action": action, "instrument": instrument}), 400

    # ---- RAW UNITS MODE (preferred) ----
    # Enforce when mode == "units"; if mode is empty (back-compat) we still treat as raw units.
    if mode in ("units", ""):
        if action in ("buy", "sell"):
            # accept "units" or fallback "qty"
            raw_units = data.get("units", data.get("qty"))
            try:
                units_abs = to_int_units(raw_units)
            except ValueError as e:
                return jsonify(ok=False, error=str(e)), 400

            signed = units_abs if action == "buy" else -units_abs
            status, resp = place_market_order(instrument, signed)
            return jsonify(resp), status

        if action == "close":
            side = str(data.get("side", "both")).lower().strip()
            status, resp = close_position(instrument, side=side)
            return jsonify(resp), status

        if action == "close_all":
            status, resp = close_position(instrument, side="both")
            return jsonify(resp), status

        return jsonify(ok=False, error="unsupported_action"), 400

    # ---- Any other mode is blocked (prevents accidental percent/lot paths) ----
    return jsonify(ok=False, error="unsupported_mode", hint="send mode:'units'"), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
