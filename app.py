# app.py
from flask import Flask, request, jsonify
import os, json, requests

app = Flask(__name__)

# ---- OANDA (LIVE) CREDS ----
# Set these in your environment (Render -> Environment)
OANDA_ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
OANDA_API_KEY    = os.environ["OANDA_API_KEY"]

# LIVE endpoint (not practice)
OANDA_URL = f"https://api-fxtrade.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/orders"
HEADERS   = {
    "Authorization": f"Bearer {OANDA_API_KEY}",
    "Content-Type":  "application/json"
}

ALLOWED_ACTIONS = {"buy", "sell", "close_buy", "close_sell"}


def fmt_instrument(symbol: str) -> str:
    """
    Accepts 'EURUSD' or 'EUR_USD' and returns 'EUR_USD' (OANDA format).
    Leaves non-forex underscores alone (best effort).
    """
    s = (symbol or "").strip().upper()
    if "_" in s:
        return s
    if len(s) >= 6:
        return s[:3] + "_" + s[3:]
    return s  # fallback


def build_order_payload(action: str, instrument: str, units: int) -> dict:
    """
    Maps action to signed units and positionFill mode.
    - buy:        +units, DEFAULT
    - sell:       -units, DEFAULT
    - close_buy:  -units, REDUCE_ONLY  (sell to close long)
    - close_sell: +units, REDUCE_ONLY  (buy to close short)
    """
    instrument = fmt_instrument(instrument)

    if action == "buy":
        signed_units = +abs(int(units))
        position_fill = "DEFAULT"
    elif action == "sell":
        signed_units = -abs(int(units))
        position_fill = "DEFAULT"
    elif action == "close_buy":
        signed_units = -abs(int(units))
        position_fill = "REDUCE_ONLY"
    elif action == "close_sell":
        signed_units = +abs(int(units))
        position_fill = "REDUCE_ONLY"
    else:
        raise ValueError("Unsupported action")

    return {
        "order": {
            "instrument":   instrument,
            "units":        str(signed_units),
            "type":         "MARKET",
            "positionFill": position_fill
        }
    }


def parse_body(req) -> dict:
    """
    Be tolerant to TradingView sending raw text or JSON.
    Returns a dict with keys: action, instrument, units
    """
    data = req.get_json(silent=True)
    if not data:
        raw = (req.data or b"").decode("utf-8").strip()
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                # Allow simple key=value or other mishaps
                raise ValueError("Invalid JSON body")

    if not isinstance(data, dict):
        raise ValueError("Body must be a JSON object")

    missing = [k for k in ("action", "instrument", "units") if k not in data]
    if missing:
        raise ValueError(f"Missing fields: {', '.join(missing)}")

    action = str(data["action"]).strip().lower()
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"Invalid action '{action}'")

    instrument = str(data["instrument"]).strip()
    try:
        units = int(data["units"])
    except Exception:
        raise ValueError("units must be an integer")

    if units <= 0:
        raise ValueError("units must be > 0")

    return {"action": action, "instrument": instrument, "units": units}


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return "✅ TGIM OANDA Webhook (LIVE) is up", 200

    try:
        payload = parse_body(request)
        order   = build_order_payload(
            action=payload["action"],
            instrument=payload["instrument"],
            units=payload["units"]
        )

        resp = requests.post(OANDA_URL, headers=HEADERS, data=json.dumps(order), timeout=15)
        # Pass OANDA response straight through for transparency
        return (resp.text, resp.status_code)

    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except requests.RequestException as e:
        return jsonify({"ok": False, "error": f"OANDA request failed: {e}"}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": f"Server error: {e}"}), 500


if __name__ == "__main__":
    # For local testing; Render/production will use gunicorn
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
