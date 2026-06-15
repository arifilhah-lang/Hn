"""
╔══════════════════════════════════════════════════════════╗
║  Step 19 — Adaptive Difficulty                           ║
║                                                          ║
║  এই ফাইলে কোনো Blueprint নেই — শুধু helper functions    ║
║  যেগুলো step6_mock_exam.py import করে ব্যবহার করে।      ║
║                                                          ║
║  Logic:                                                  ║
║   ৮০%+  → level = 'hard'   (পরের exam-এ কঠিন প্রশ্ন)   ║
║   ৫০-৭৯% → level = 'medium' (mixed)                     ║
║   <৫০%  → level = 'easy'   (সহজ প্রশ্ন + concept hint)  ║
║                                                          ║
║  student_difficulty টেবিলে per (class_id, subject_id)   ║
║  level সেভ থাকে। পরের exam_start-এ এই level দেখে       ║
║  mcq_bank থেকে difficulty-weighted MCQ টানা হয়।         ║
╚══════════════════════════════════════════════════════════╝
"""

import sqlite3, os, json, logging

log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "study_ai.db")


def _get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_adaptive_table():
    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS student_difficulty (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id    TEXT NOT NULL,
            subject_id  TEXT NOT NULL,
            level       TEXT NOT NULL DEFAULT 'medium',
            last_pct    REAL,
            exam_count  INTEGER DEFAULT 0,
            updated_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(class_id, subject_id)
        )
    """)
    conn.commit()
    conn.close()


init_adaptive_table()


# ── Level read/write ────────────────────────────────────────
def get_student_level(class_id: str, subject_id: str) -> str:
    """বর্তমান difficulty level পড়ো — default 'medium'"""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT level FROM student_difficulty WHERE class_id=? AND subject_id=?",
            (class_id, subject_id)
        ).fetchone()
        return row["level"] if row else "medium"
    finally:
        conn.close()


def update_student_level(class_id: str, subject_id: str, percent: float):
    """
    exam শেষে score percentage দেখে level আপডেট করো।
    ৮০%+  → hard
    ৫০-৭৯% → medium
    <৫০%   → easy
    """
    if percent >= 80:
        new_level = "hard"
    elif percent >= 50:
        new_level = "medium"
    else:
        new_level = "easy"

    conn = _get_db()
    try:
        conn.execute("""
            INSERT INTO student_difficulty (class_id, subject_id, level, last_pct, exam_count, updated_at)
            VALUES (?, ?, ?, ?, 1, datetime('now'))
            ON CONFLICT(class_id, subject_id) DO UPDATE SET
                level      = excluded.level,
                last_pct   = excluded.last_pct,
                exam_count = exam_count + 1,
                updated_at = datetime('now')
        """, (class_id, subject_id, new_level, round(percent, 1)))
        conn.commit()
        log.info(f"Adaptive: {class_id}/{subject_id} → {new_level} ({percent:.1f}%)")
        return new_level
    finally:
        conn.close()


# ── Difficulty-weighted MCQ query ────────────────────────────
def get_mcqs_adaptive(class_id: str, subject_id: str, count: int = 30) -> list:
    """
    level অনুযায়ী difficulty-weighted MCQ টানো।
    - easy   → easy প্রশ্ন আগে, তারপর medium, hard সবশেষে
    - medium → random
    - hard   → hard প্রশ্ন আগে, তারপর medium, easy সবশেষে
    কোনো question exclude করা হয় না — শুধু priority বদলায়।
    """
    level = get_student_level(class_id, subject_id)

    if level == "easy":
        order_sql = """
            ORDER BY CASE difficulty
                WHEN 'easy'   THEN 0
                WHEN 'medium' THEN 1
                ELSE               2
            END, RANDOM()
        """
    elif level == "hard":
        order_sql = """
            ORDER BY CASE difficulty
                WHEN 'hard'   THEN 0
                WHEN 'medium' THEN 1
                ELSE               2
            END, RANDOM()
        """
    else:
        order_sql = "ORDER BY RANDOM()"

    conn = _get_db()
    try:
        rows = conn.execute(f"""
            SELECT id, chapter, chapter_num, question,
                   option_a, option_b, option_c, option_d,
                   answer, difficulty
            FROM mcq_bank
            WHERE class_id=? AND subject_id=?
            {order_sql}
            LIMIT ?
        """, (class_id, subject_id, count)).fetchall()
        return [dict(r) for r in rows], level
    finally:
        conn.close()


# ── Concept hints for weak chapters (<50%) ───────────────────
def get_concept_hints(wrong_chapters: list, class_id: str, subject_id: str) -> dict:
    """
    score < 50% হলে ভুল-বেশি chapter গুলোর জন্য Gemini দিয়ে
    brief concept hint তৈরি করো।
    Returns: { "chapter_name": "hint text", ... }
    """
    if not wrong_chapters:
        return {}

    try:
        from config import GEMINI_API_KEYS, DEFAULT_MODEL, CLASSES, get_subject_info
        from google import genai
        from google.genai import types

        client = None
        for key in GEMINI_API_KEYS:
            if key.strip():
                try:
                    client = genai.Client(
                        api_key=key,
                        http_options={'api_version': 'v1beta'}
                    )
                    break
                except Exception:
                    pass
        if not client:
            return {}

        cls        = CLASSES.get(class_id, {})
        class_label = cls.get("label", class_id)
        subj_info  = get_subject_info(class_id, subject_id)
        subject_bn = subj_info.get("bn", subject_id) if subj_info else subject_id

        chapters_str = "\n".join(f"- {ch}" for ch in wrong_chapters[:5])

        prompt = (
            f"তুমি {class_label} {subject_bn} বিষয়ের শিক্ষক।\n"
            f"নিচের অধ্যায়গুলোতে ছাত্র পরীক্ষায় বেশি ভুল করেছে:\n{chapters_str}\n\n"
            f"প্রতিটা অধ্যায়ের জন্য ২-৩ লাইনে সবচেয়ে গুরুত্বপূর্ণ concept reminder দাও "
            f"(মনে রাখার tip + common mistake)।\n\n"
            f"JSON format (শুধু JSON, কোনো markdown নয়):\n"
            f'{{ "অধ্যায়ের নাম": "hint text", ... }}'
        )

        response = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=600, temperature=0.3)
        )

        raw = (response.text or "{}").strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)

    except Exception as e:
        log.error(f"concept_hints error: {e}")
        return {}
