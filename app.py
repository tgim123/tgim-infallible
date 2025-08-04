@app.route("/", methods=["GET","POST"])
def root():
    if request.method == "GET":
        return "✅ Webhook service is up", 200

    data       = request.get_json(force=True)
    action     = data.get("action")
    instrument = data.get("instrument")
    units      = int(data.get("units"))

    app.logger.info("Received alert: %s", data)

    try:
        if action == "market_order":
            # 1) Fetch current position for this instrument
            pos_resp = requests.get(
                f"{BASE_URL}/positions/{instrument}",
                headers=HEADERS
            ).json()["position"]

            long_u  = float(pos_resp["long"]["units"])
            short_u = float(pos_resp["short"]["units"])

            # 2) If we're about to BUY but have a short open, close it first
            if units > 0 and short_u != 0:
                close_sh = {"shortUnits": "ALL"}
                r1 = requests.put(
                    f"{BASE_URL}/positions/{instrument}/close",
                    headers=HEADERS, json=close_sh
                )
                app.logger.info("Auto-closed short: %s", r1.text)

            # 3) If we're about to SELL but have a long open, close it first
            if units < 0 and long_u != 0:
                close_lg = {"longUnits": "ALL"}
                r2 = requests.put(
                    f"{BASE_URL}/positions/{instrument}/close",
                    headers=HEADERS, json=close_lg
                )
                app.logger.info("Auto-closed long: %s", r2.text)

            # 4) Now place the new market order
            payload = {
                "order": {
                    "instrument":   instrument,
                    "units":        str(units),
                    "type":         "MARKET",
                    "timeInForce":  "FOK",
                    "positionFill": "DEFAULT"
                }
            }
            resp = requests.post(ORDERS_URL, headers=HEADERS, json=payload)
            app.logger.info("Order response: %s", resp.text)
            return jsonify(resp.json()), resp.status_code

        elif action == "close_all":
            body = {"longUnits":"ALL","shortUnits":"ALL"}
            resp = requests.put(
                POSITIONS_CLOSE_URL.format(instrument=instrument),
                headers=HEADERS, json=body
            )
            app.logger.info("Close-all response: %s", resp.text)
            return jsonify(resp.json()), resp.status_code

        else:
            return jsonify({"error": f"Unknown action '{action}'"}), 400

    except Exception as e:
        app.logger.error("Exception: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500
