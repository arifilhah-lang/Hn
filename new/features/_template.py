"""
╔══════════════════════════════════════════════════════════╗
║  FEATURE TEMPLATE — এই ফাইলটা copy করে নতুন feature করো ║
║  ফাইলের নাম: step6_mock_exam.py, step7_weakness.py ...   ║
╚══════════════════════════════════════════════════════════╝

নিয়ম:
  1. bp = Blueprint(...) থাকতেই হবে — এটাই auto-loader খোঁজে
  2. get_db() ব্যবহার করতে হলে নিচের import uncomment করো
  3. Gemini client দরকার হলে _get_client() import করো
"""

from flask import Blueprint, request, jsonify
import sqlite3, os, json, logging

log = logging.getLogger(__name__)

# ── Shared utilities import ────────────────────────────────────
# app.py তে যা defined আছে সেগুলো এভাবে আনো:
# (circular import এড়াতে function এর ভেতরে import করো)

def get_db():
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DB_PATH  = os.path.join(BASE_DIR, "study_ai.db")
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ── Blueprint define করো ──────────────────────────────────────
bp = Blueprint("template", __name__)   # ← নাম বদলাও প্রতিটা feature এ


# ── Table migration (নতুন table লাগলে এখানে লেখো) ─────────────
def init_tables():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS example_table (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id   TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

init_tables()  # server start এ একবার চলবে


# ── Routes ────────────────────────────────────────────────────
@bp.route("/api/example/hello", methods=["GET"])
def hello():
    return jsonify({"success": True, "message": "Feature কাজ করছে!"})
