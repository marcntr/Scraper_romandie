"""Triage server — serves the job dashboard and handles status updates.

Run:
    python server.py

Then open http://localhost:5000 in your browser.
Status changes (Ignore / Applied / Back to Matched) are written
immediately to seen_jobs.json so the scraper preserves them on the next run.
Cross-device sync is handled by the GitHub Gist integration in the dashboard JS.
"""

import logging
import os

from flask import Flask, jsonify, request, send_file

import cache as job_cache

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

_DIR      = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(_DIR, "latest_jobs.html")


@app.route("/")
def index():
    return send_file(HTML_PATH)


@app.route("/api/status", methods=["POST"])
def update_status():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    status = data.get("status", "").strip()
    if not url or status not in ("matched", "ignored", "applied"):
        return jsonify({"error": "invalid request"}), 400
    job_cache.load()  # re-sync with disk before mutating
    job_cache.set_status(url, status)
    job_cache.save()
    logger.info("Status updated: %s → %s", url, status)
    return jsonify({"ok": True})


if __name__ == "__main__":
    job_cache.load()
    logger.info("Dashboard available at http://localhost:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
