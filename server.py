"""Triage server — serves the job dashboard and handles status updates.

Run:
    python server.py

Then open http://localhost:5000 in your browser.
Status changes (Ignore / Applied / Back to Matched) are written
immediately to seen_jobs.json so the scraper preserves them on the next run.
They are also written to statuses.json and pushed to GitHub so the
GitHub Pages version stays in sync across devices.
"""

import json
import logging
import os
import subprocess
import threading

from flask import Flask, jsonify, request, send_file

import cache as job_cache

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

_DIR           = os.path.dirname(os.path.abspath(__file__))
HTML_PATH      = os.path.join(_DIR, "latest_jobs.html")
STATUSES_PATH  = os.path.join(_DIR, "statuses.json")

# Debounce timer so rapid clicks produce at most one git push per 3 s.
_push_timer: threading.Timer | None = None
_push_lock  = threading.Lock()


def _write_statuses() -> None:
    """Overwrite statuses.json with the current in-memory triage state."""
    try:
        with open(STATUSES_PATH, "w", encoding="utf-8") as fh:
            json.dump(job_cache.all_statuses(), fh, indent=2)
    except OSError as exc:
        logger.warning("Could not write statuses.json: %s", exc)


def _schedule_push() -> None:
    """Schedule a debounced git push of statuses.json (fires 3 s after last change)."""
    global _push_timer
    with _push_lock:
        if _push_timer is not None:
            _push_timer.cancel()
        _push_timer = threading.Timer(3.0, _do_push)
        _push_timer.daemon = True
        _push_timer.start()


def _do_push() -> None:
    try:
        subprocess.run(["git", "add", "statuses.json"], cwd=_DIR, capture_output=True)
        r = subprocess.run(
            ["git", "commit", "-m", "update statuses [skip ci]"],
            cwd=_DIR, capture_output=True,
        )
        if r.returncode == 0:
            subprocess.run(["git", "push"], cwd=_DIR, capture_output=True)
            logger.info("statuses.json pushed to GitHub")
    except Exception as exc:
        logger.warning("Could not push statuses.json: %s", exc)


@app.route("/")
def index():
    return send_file(HTML_PATH)


@app.route("/statuses.json")
def serve_statuses_json():
    """Serve live statuses at the same relative path the HTML fetches on GitHub Pages."""
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
    _write_statuses()
    _schedule_push()
    logger.info("Status updated: %s → %s", url, status)
    return jsonify({"ok": True})


if __name__ == "__main__":
    job_cache.load()
    logger.info("Dashboard available at http://localhost:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
