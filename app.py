"""
Phase 4 - Web Dashboard (Flask backend)

Full-screen live video + detection history sidebar (past day / week / month / year).
History is stored in SQLite, so it survives restarts.

Other phases plug in through these hooks:

    from app import start_dashboard, set_frame, set_motion, log_event, is_armed

    start_dashboard()                          # once at startup (background thread)
    set_frame(jpeg_bytes)                      # every loop: cv2.imencode('.jpg', frame)[1].tobytes()
    if is_armed() and motion_found:
        set_motion(True)                       # live status -> ALERT
        log_event("Motion detected", media=jpeg_bytes)       # snapshot saved + shown in history
        # or: log_event("Motion detected", media="/path/clip.mp4")   # video footage
    else:
        set_motion(False)
"""
import os
import shutil
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime

from flask import (Flask, Response, abort, jsonify, render_template, request,
                   send_from_directory)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
MEDIA_DIR = os.path.join(DATA_DIR, "media")      # snapshots / clips live here
DB_PATH = os.path.join(DATA_DIR, "events.db")
RETENTION_DAYS = 400                              # older events + media are pruned at startup
os.makedirs(MEDIA_DIR, exist_ok=True)

app = Flask(__name__)

_lock = threading.Lock()
_state = {"armed": True, "motion": False, "last_motion": None}
_frame = None  # latest JPEG bytes

RANGES = {"day": 86400, "week": 7 * 86400, "month": 30 * 86400, "year": 365 * 86400}


# ------------------------------------------------------------------
# Database helpers
# ------------------------------------------------------------------
def _query(sql, args=()):
    with closing(sqlite3.connect(DB_PATH, timeout=10)) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def _exec(sql, args=()):
    with closing(sqlite3.connect(DB_PATH, timeout=10)) as c:
        c.execute(sql, args)
        c.commit()


def _init_db():
    _exec("""CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                media TEXT)""")
    _exec("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")


def prune(days=RETENTION_DAYS):
    cutoff = time.time() - days * 86400
    for row in _query("SELECT media FROM events WHERE ts < ? AND media IS NOT NULL", (cutoff,)):
        try:
            os.remove(os.path.join(MEDIA_DIR, row["media"]))
        except OSError:
            pass
    _exec("DELETE FROM events WHERE ts < ?", (cutoff,))


_init_db()
prune()


# ------------------------------------------------------------------
# Hooks for other phases
# ------------------------------------------------------------------
def set_frame(jpeg_bytes: bytes):
    """Push the latest JPEG frame for the live view."""
    global _frame
    with _lock:
        _frame = jpeg_bytes


def set_motion(detected: bool):
    """Update the live status (call every loop with True/False)."""
    with _lock:
        _state["motion"] = bool(detected)
        if detected:
            _state["last_motion"] = time.time()


def log_event(message: str, level: str = "alert", media=None):
    """
    Save an event to history.
      level: "alert" (detection) or "info" (system message)
      media: JPEG bytes (snapshot)  OR  path to a video/image file (copied into data/media)
    """
    ts = time.time()
    name = None
    if isinstance(media, (bytes, bytearray)):
        name = datetime.fromtimestamp(ts).strftime("%Y%m%d_%H%M%S_%f") + ".jpg"
        with open(os.path.join(MEDIA_DIR, name), "wb") as f:
            f.write(media)
    elif isinstance(media, str) and os.path.isfile(media):
        name = os.path.basename(media)
        dest = os.path.join(MEDIA_DIR, name)
        if os.path.abspath(media) != os.path.abspath(dest):
            shutil.copy2(media, dest)
    _exec("INSERT INTO events (ts, level, message, media) VALUES (?,?,?,?)",
          (ts, level, message, name))


def is_armed() -> bool:
    """Check before triggering LED / LCD / relay."""
    with _lock:
        return _state["armed"]


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    with _lock:
        data = dict(_state)
        data["has_frame"] = _frame is not None
    today = _query("SELECT COUNT(*) AS n FROM events WHERE level='alert' AND ts > ?",
                   (time.time() - 86400,))
    data["alerts_24h"] = today[0]["n"]
    return jsonify(data)


@app.route("/api/events")
def api_events():
    """?range=day|week|month|year|all  &footage=1 (only events with media)  &limit=500"""
    rng = request.args.get("range", "week")
    limit = min(int(request.args.get("limit", 500)), 2000)
    sql, args = "SELECT id, ts, level, message, media FROM events WHERE 1=1", []
    if rng in RANGES:
        sql += " AND ts > ?"
        args.append(time.time() - RANGES[rng])
    if request.args.get("footage") == "1":
        sql += " AND media IS NOT NULL"
    sql += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    return jsonify(_query(sql, args))


@app.route("/api/arm", methods=["POST"])
def api_arm():
    with _lock:
        _state["armed"] = not _state["armed"]
        armed = _state["armed"]
    log_event("System ARMED" if armed else "System DISARMED", level="info")
    return jsonify({"armed": armed})


@app.route("/media/<path:name>")
def media(name):
    if not os.path.isfile(os.path.join(MEDIA_DIR, name)):
        abort(404)
    return send_from_directory(MEDIA_DIR, name)


def _mjpeg():
    while True:
        with _lock:
            frame = _frame
        if frame is None:
            time.sleep(0.5)
            continue
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        time.sleep(0.05)  # ~20 fps cap


@app.route("/video_feed")
def video_feed():
    return Response(_mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")


# ------------------------------------------------------------------
# Start helper
# ------------------------------------------------------------------
def start_dashboard(host="0.0.0.0", port=5000):
    """Run Flask in a background thread so the detection loop keeps running."""
    t = threading.Thread(
        target=lambda: app.run(host=host, port=port, threaded=True, use_reloader=False),
        daemon=True,
    )
    t.start()
    return t


if __name__ == "__main__":
    # Standalone test run
    app.run(host="0.0.0.0", port=5000, threaded=True)
