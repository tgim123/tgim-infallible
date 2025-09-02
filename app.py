from flask import Flask, request, jsonify
app = Flask(__name__)

@app.route("/webhook", methods=["GET","POST"])
def webhook():
    if request.method == "GET":
        return "✅ TGIM Webhook is live", 200
    try:
        return jsonify({"ok": True, "echo": request.get_json(silent=True)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
