from flask import Flask, render_template, jsonify
from match_analyzer import get_analysis

app = Flask(__name__)


@app.route("/")
def index():
    data = get_analysis()
    return render_template("index.html", data=data)


@app.route("/api/matches")
def api_matches():
    return jsonify(get_analysis())


if __name__ == "__main__":
    # 0.0.0.0 -> VPS'in dışarıya açık IP'sinden erişilebilir olsun
    app.run(host="0.0.0.0", port=8080)
