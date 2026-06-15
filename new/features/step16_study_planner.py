"""
╔══════════════════════════════════════════════════════════╗
║  Step 16 — Smart Study Planner                           ║
║  POST /api/planner/generate — exam_date + subjects দিলে  ║
║                                day-by-day plan বানায়     ║
║  GET  /api/planner/today     — আজকের পড়ার তালিকা        ║
║  GET  /api/planner/full      — পুরো routine               ║
║  DELETE /api/planner/clear   — routine মুছে ফেলা          ║
╚══════════════════════════════════════════════════════════╝

Logic:
  1. subject_chapters থেকে chapter list নেওয়া (per subject)
  2. mcq_bank থেকে accuracy (times_correct/times_shown) বের করা
     - attempt না করা chapter কে "medium-weak" (0.4) ধরা হয়
  3. সবচেয়ে দুর্বল chapter সবার আগে priority তে রাখা হয়
  4. exam_date পর্যন্ত দিন সংখ্যা অনুযায়ী chapter গুলো ভাগ করা হয়
     - দিন কম হলে → এক দিনে একাধিক chapter
     - দিন বেশি হলে → বাকি দিন দুর্বল chapter revision + শেষ ২ দিন full revision
  5. routine_json → student_routine টেবিলে save (class_id ভিত্তিক, পুরনোটা replace)
"""

from flask import Blueprint, request, jsonify
import sqlite3, os, json, logging, math
from datetime import datetime, date, timedelta

log = logging.getLogger(__name__)

# ── DB helper ─────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "study_ai.db")

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

# ── Blueprint ─────────────────────────────────────────────────
bp = Blueprint("study_planner", __name__)


def _init_tables():
    conn = get_db()
    # student_routine ইতিমধ্যে আছে, কিন্তু safety জন্য CREATE IF NOT EXISTS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS student_routine (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id     TEXT NOT NULL,
            exam_date    TEXT,
            routine_json TEXT NOT NULL,
            created_at   TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

_init_tables()


# ── Weakness calculation ────────────────────────────────────────
DEFAULT_WEAKNESS = 0.4  # attempt না করা chapter — medium-weak ধরা হয়

def _chapter_weakness_map(conn, class_id, subject_id):
    """chapter_num -> accuracy (0.0 - 1.0, কম মানে দুর্বল) """
    rows = conn.execute("""
        SELECT chapter_num,
               SUM(times_shown)  AS shown,
               SUM(times_correct) AS correct
        FROM mcq_bank
        WHERE class_id=? AND subject_id=?
        GROUP BY chapter_num
    """, (class_id, subject_id)).fetchall()

    result = {}
    for r in rows:
        shown = r["shown"] or 0
        correct = r["correct"] or 0
        if shown > 0:
            result[r["chapter_num"]] = correct / shown
        else:
            result[r["chapter_num"]] = DEFAULT_WEAKNESS
    return result


def _get_chapters(conn, class_id, subject_id):
    rows = conn.execute("""
        SELECT chapter_num, chapter_title, total_mcq, total_cq
        FROM subject_chapters
        WHERE class_id=? AND subject_id=?
        ORDER BY chapter_num ASC
    """, (class_id, subject_id)).fetchall()
    return [dict(r) for r in rows]


def _build_priority_tasks(conn, class_id, subjects):
    """
    সব subject এর chapter একসাথে নিয়ে weakness অনুযায়ী sort করে
    একটা flat task list বানায় (সবচেয়ে দুর্বল আগে)
    """
    tasks = []
    for subject_id in subjects:
        chapters = _get_chapters(conn, class_id, subject_id)
        if not chapters:
            continue
        weakness_map = _chapter_weakness_map(conn, class_id, subject_id)

        for ch in chapters:
            accuracy = weakness_map.get(ch["chapter_num"], DEFAULT_WEAKNESS)
            tasks.append({
                "subject_id":    subject_id,
                "chapter_num":   ch["chapter_num"],
                "chapter_title": ch["chapter_title"],
                "accuracy":      round(accuracy, 2),
            })

    # সবচেয়ে দুর্বল (accuracy কম) আগে
    tasks.sort(key=lambda t: t["accuracy"])
    return tasks


# ── Routine generation ──────────────────────────────────────────
def _generate_routine(conn, class_id, subjects, exam_date_str):
    today = date.today()
    try:
        exam_date = datetime.strptime(exam_date_str, "%Y-%m-%d").date()
    except ValueError:
        return None, "exam_date ফরম্যাট ভুল — YYYY-MM-DD দিন"

    days_left = (exam_date - today).days
    if days_left < 1:
        return None, "পরীক্ষার তারিখ আজকের পরে হতে হবে"

    tasks = _build_priority_tasks(conn, class_id, subjects)
    if not tasks:
        return None, "এই subject(গুলো)র জন্য কোনো chapter পাওয়া যায়নি — আগে DB Import করুন"

    total_tasks = len(tasks)

    # শেষের ২ দিন (বা days_left যদি কম থাকে) revision-এর জন্য রাখি
    revision_days = 2 if days_left > 3 else max(1, days_left // 3)
    study_days = max(1, days_left - revision_days)

    days_plan = []

    if total_tasks <= study_days:
        # দিন বেশি — প্রতিদিন ১টা chapter, বাকি দিন গুলো দুর্বল chapter-এর double-pass
        extra_days = study_days - total_tasks
        schedule = list(tasks)
        # extra দিনের জন্য সবচেয়ে দুর্বল chapter গুলো আবার repeat
        weakest_repeat = tasks[:max(1, math.ceil(total_tasks * 0.3))]
        i = 0
        while extra_days > 0:
            t = weakest_repeat[i % len(weakest_repeat)]
            schedule.append({**t, "is_revision": True})
            i += 1
            extra_days -= 1
        # weakest গুলো আগে থাকুক, কিন্তু repeat গুলো ছড়িয়ে দিই (interleave)
        schedule.sort(key=lambda t: (t["accuracy"], t.get("is_revision", False)))
        per_day_chunks = [[t] for t in schedule]
    else:
        # chapter বেশি, দিন কম — chunk করে ভাগ করি
        chunk_size = math.ceil(total_tasks / study_days)
        per_day_chunks = [tasks[i:i + chunk_size] for i in range(0, total_tasks, chunk_size)]

    # study days বসানো
    for idx, chunk in enumerate(per_day_chunks):
        d = today + timedelta(days=idx)
        days_plan.append({
            "date":  d.isoformat(),
            "day_num": idx + 1,
            "type":  "study",
            "tasks": [
                {
                    "subject_id":    c["subject_id"],
                    "chapter_num":   c["chapter_num"],
                    "chapter_title": c["chapter_title"],
                    "accuracy":      c["accuracy"],
                    "note": "দুর্বল chapter — মনোযোগ দিয়ে পড়ুন" if c["accuracy"] < 0.5 else
                            ("আগে একবার দেখা হয়েছে — দ্রুত revise করুন" if c.get("is_revision") else "নতুন chapter")
                }
                for c in chunk
            ]
        })

    # বাকি দিন গুলো (revision_days) — সব দুর্বল chapter এর সংক্ষিপ্ত revision + mock exam
    used_days = len(days_plan)
    remaining_days = days_left - used_days
    weakest_n = tasks[:max(1, math.ceil(total_tasks * 0.4))]

    for r in range(max(remaining_days, revision_days)):
        d = today + timedelta(days=used_days + r)
        if d > exam_date:
            break
        is_last_day = (d == exam_date - timedelta(days=1)) or (r == max(remaining_days, revision_days) - 1)
        days_plan.append({
            "date": d.isoformat(),
            "day_num": used_days + r + 1,
            "type": "revision",
            "tasks": [
                {
                    "subject_id":    c["subject_id"],
                    "chapter_num":   c["chapter_num"],
                    "chapter_title": c["chapter_title"],
                    "accuracy":      c["accuracy"],
                    "note": "শেষ revision — দুর্বল অধ্যায়"
                }
                for c in weakest_n
            ] + ([{"subject_id": None, "chapter_num": None,
                    "chapter_title": "📝 Mock Exam দিন (পুরো syllabus)",
                    "accuracy": None, "note": "পরীক্ষার আগে practice"}] if is_last_day else [])
        })

    return {
        "exam_date": exam_date.isoformat(),
        "days_left": days_left,
        "subjects": subjects,
        "total_chapters": total_tasks,
        "plan": days_plan,
    }, None


# ── Routes ────────────────────────────────────────────────────
@bp.route("/api/planner/generate", methods=["POST"])
def planner_generate():
    data = request.get_json(force=True) or {}
    class_id   = data.get("class_id")
    exam_date  = data.get("exam_date")
    subjects   = data.get("subjects") or []

    if not class_id or not exam_date or not subjects:
        return jsonify({"success": False, "error": "class_id, exam_date, subjects দরকার"}), 400

    conn = get_db()
    try:
        routine, err = _generate_routine(conn, class_id, subjects, exam_date)
        if err:
            return jsonify({"success": False, "error": err}), 400

        # পুরনো routine মুছে নতুনটা বসাই (class_id ভিত্তিক একটাই active routine)
        conn.execute("DELETE FROM student_routine WHERE class_id=?", (class_id,))
        conn.execute("""
            INSERT INTO student_routine (class_id, exam_date, routine_json)
            VALUES (?, ?, ?)
        """, (class_id, exam_date, json.dumps(routine, ensure_ascii=False)))
        conn.commit()

        return jsonify({"success": True, "routine": routine})
    except Exception as e:
        log.exception("planner_generate error")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()


@bp.route("/api/planner/today", methods=["GET"])
def planner_today():
    class_id = request.args.get("class_id")
    if not class_id:
        return jsonify({"success": False, "error": "class_id দরকার"}), 400

    conn = get_db()
    try:
        row = conn.execute("""
            SELECT routine_json, exam_date FROM student_routine
            WHERE class_id=? ORDER BY id DESC LIMIT 1
        """, (class_id,)).fetchone()

        if not row:
            return jsonify({"success": False, "error": "এখনো কোনো routine তৈরি হয়নি — /api/planner/generate কল করুন"}), 404

        routine = json.loads(row["routine_json"])
        today_str = date.today().isoformat()

        today_plan = next((d for d in routine["plan"] if d["date"] == today_str), None)

        exam_date = datetime.strptime(row["exam_date"], "%Y-%m-%d").date()
        days_left = (exam_date - date.today()).days

        if days_left < 0:
            return jsonify({"success": True, "finished": True,
                             "message": "পরীক্ষা শেষ! নতুন routine বানাতে চাইলে /api/planner/generate কল করুন"})

        if not today_plan:
            return jsonify({"success": True, "today": None, "days_left": days_left,
                             "message": "আজকের জন্য কোনো plan নেই (পরীক্ষার দিন বা routine সীমার বাইরে)"})

        return jsonify({"success": True, "today": today_plan, "days_left": days_left})
    except Exception as e:
        log.exception("planner_today error")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()


@bp.route("/api/planner/full", methods=["GET"])
def planner_full():
    class_id = request.args.get("class_id")
    if not class_id:
        return jsonify({"success": False, "error": "class_id দরকার"}), 400

    conn = get_db()
    try:
        row = conn.execute("""
            SELECT routine_json FROM student_routine
            WHERE class_id=? ORDER BY id DESC LIMIT 1
        """, (class_id,)).fetchone()

        if not row:
            return jsonify({"success": False, "error": "এখনো কোনো routine তৈরি হয়নি"}), 404

        return jsonify({"success": True, "routine": json.loads(row["routine_json"])})
    finally:
        conn.close()


@bp.route("/api/planner/clear", methods=["DELETE"])
def planner_clear():
    class_id = request.args.get("class_id")
    if not class_id:
        return jsonify({"success": False, "error": "class_id দরকার"}), 400

    conn = get_db()
    try:
        conn.execute("DELETE FROM student_routine WHERE class_id=?", (class_id,))
        conn.commit()
        return jsonify({"success": True, "message": "routine মুছে ফেলা হয়েছে"})
    finally:
        conn.close()
