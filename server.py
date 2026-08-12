"""Local dashboard preview server.

Run:
    python server.py

Then open http://localhost:5000 in your browser to preview latest_jobs.html
before it's pushed. Status changes (Ignore / Applied / Back to Matched) sync
via the GitHub Gist integration in the dashboard JS, not through this server.
"""

import logging
import os

from flask import Flask, send_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

_DIR      = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(_DIR, "latest_jobs.html")


@app.route("/")
def index():
    return send_file(HTML_PATH)


if __name__ == "__main__":
    logger.info("Dashboard available at http://localhost:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
