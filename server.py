"""Triage server — serves the job dashboard and handles status updates.

Run:
    python server.py

Then open http://localhost:5000 in your browser.
Status changes (Ignore / Applied / Back to Matched) are written
immediately to seen_jobs.json so the scraper preserves them on the next run.
"""

import logging
import os

from flask import Flask, jsonify, request, send_file

import cache as job_cache

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

HTML_PATH = os.path.join(os.path.dirname(__file__), "latest_jobs.html")


@app.route("/")
def index():
    return send_file(HTML_PATH)


@app.route("/api/statuses", methods=["GET"])
def get_all_statuses():
    """Return all non-matched triage decisions so the dashboard can sync across devices."""
    job_cache.load()
    return jsonify(job_cache.all_statuses())


@app.route("/api/status", methods=["POST"])
def update_status():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    status = data.get("status", "").strip()
    if not url or status not in ("matched", "ignored", "applied"):
        return jsonify({"error": "invalid request"}), 400
    job_cache.load()  # re-sync with disk before mutating — scraper may have written new data since startup
    job_cache.set_status(url, status)
    job_cache.save()
    logger.info("Status updated: %s → %s", url, status)
    return jsonify({"ok": True})


if __name__ == "__main__":
    job_cache.load()
    logger.info("Dashboard available at http://localhost:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
