"""
╔══════════════════════════════════════════════════════════╗
║  Step 6 — Mock Exam Mode                                 ║
║  POST /api/exam/start   — পরীক্ষা শুরু করো             ║
║  POST /api/exam/submit  — উত্তর জমা দাও, score পাও     ║
║  GET  /api/exam/history — পুরনো পরীক্ষার তালিকা        ║
╚══════════════════════════════════════════════════════════╝
"""

from flask import Blueprint, request, jsonify
import sqlite3, os, json, uuid, logging, re

log = logging.getLogger(__name__)

# ── DB helper ─────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "study_ai.db")

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

# ── Adaptive Difficulty ────────────────────────────────────────
from features.step19_adaptive import (
    get_mcqs_adaptive, update_student_level,
    get_concept_hints, get_student_level
)

# ── Spaced Repetition ──────────────────────────────────────────
from features.step20_spaced_rep import build_exam_mcqs, update_mcq_stats

# ── Gemini + Config ───────────────────────────────────────────
from config import GEMINI_API_KEYS, DEFAULT_MODEL, CLASSES, get_subject_info
from google import genai
from google.genai import types

_exam_client = None
def _get_client():
    global _exam_client
    if _exam_client is None:
        for key in GEMINI_API_KEYS:
            if key.strip():
                try:
                    _exam_client = genai.Client(
                        api_key=key,
                        http_options={'api_version': 'v1beta'}
                    )
                    break
                except Exception:
                    pass
    return _exam_client

# ── Blueprint ─────────────────────────────────────────────────
bp = Blueprint("mock_exam", __name__)

# ── Table init ────────────────────────────────────────────────
def _init_tables():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS exam_sessions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id     TEXT UNIQUE NOT NULL,
            class_id       TEXT NOT NULL,
            subject_id     TEXT NOT NULL,
            questions_json TEXT NOT NULL,
            answers_json   TEXT,
            score          REAL,
            total          REAL,
            time_taken     INTEGER,
            completed_at   TEXT,
            created_at     TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

_init_tables()


# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════

def _get_mcqs_from_bank(class_id, subject_id, count=30):
    """mcq_bank থেকে random MCQ টানো"""
    conn = get_db()
    rows = conn.execute("""
        SELECT id, chapter, chapter_num, question,
               option_a, option_b, option_c, option_d,
               answer, difficulty
        FROM mcq_bank
        WHERE class_id=? AND subject_id=?
        ORDER BY RANDOM() LIMIT ?
    """, (class_id, subject_id, count)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _generate_cqs(class_id, subject_id, count=8):
    """Gemini দিয়ে CQ generate করো"""
    client = _get_client()
    if not client:
        return []

    cls        = CLASSES.get(class_id, {})
    class_label = cls.get("label", class_id)
    subj_info  = get_subject_info(class_id, subject_id)
    subject_bn = subj_info.get("bn", subject_id) if subj_info else subject_id

    prompt = (
        f"তুমি {class_label} {subject_bn} বোর্ড পরীক্ষার CQ বিশেষজ্ঞ।\n"
        f"বোর্ড পরীক্ষার ধাঁচে {count}টি সৃজনশীল প্রশ্ন তৈরি করো।\n"
        f"প্রতিটিতে বাস্তবসম্মত উদ্দীপক এবং ক খ গ ঘ অংশ থাকবে।\n\n"
        f"JSON array format (শুধু array, কোনো markdown নয়):\n"
        f'[{{"stimulus": "উদ্দীপকের লেখা", "chapter": "অধ্যায়ের নাম", '
        f'"parts": [{{"label": "ক", "text": "প্রশ্ন", "marks": 1}}, '
        f'{{"label": "খ", "text": "প্রশ্ন", "marks": 2}}, '
        f'{{"label": "গ", "text": "প্রশ্ন", "marks": 3}}, '
        f'{{"label": "ঘ", "text": "প্রশ্ন", "marks": 4}}]}}]'
    )

    try:
        response = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=2000, temperature=0.5
            )
        )
        raw = response.text.strip() if response.text else "[]"
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r'\[.*\]', raw, re.DOTALL)
            return json.loads(m.group()) if m else []
    except Exception as e:
        log.error(f"CQ generate error: {e}")
        return []


def _get_grade(score, total):
    """Score থেকে grade বের করো (Bangladesh system)"""
    if not total:
        return "N/A"
    pct = (score / total) * 100
    if pct >= 80: return "A+"
    if pct >= 70: return "A"
    if pct >= 60: return "A-"
    if pct >= 50: return "B"
    if pct >= 40: return "C"
    if pct >= 33: return "D"
    return "F"


# ══════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════

@bp.route("/api/exam/start", methods=["POST"])
def exam_start():
    """
    পরীক্ষা শুরু করো।
    Body: { class_id, subject_id, mcq_count (default 30), cq_count (default 8) }
    Returns: session_id + questions
    """
    data       = request.get_json() or {}
    class_id   = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()
    mcq_count  = min(int(data.get("mcq_count", 30)), 50)
    cq_count   = min(int(data.get("cq_count", 8)),   12)

    if not class_id or not subject_id:
        return jsonify({"success": False,
                        "error": "❌ class_id ও subject_id আবশ্যক"}), 400

    # ── MCQ bank থেকে টানো (spaced rep + adaptive mix) ────────
    mcqs, current_level, review_count = build_exam_mcqs(
        class_id, subject_id, mcq_count, get_mcqs_adaptive
    )
    if len(mcqs) < 5:
        return jsonify({
            "success":   False,
            "error":     f"❌ MCQ Bank এ পর্যাপ্ত MCQ নেই ({len(mcqs)}টি)। "
                         f"Admin panel থেকে import করুন।",
            "mcq_count": len(mcqs)
        }), 400

    # ── CQ generate করো ───────────────────────────────────────
    cqs = _generate_cqs(class_id, subject_id, cq_count)

    # ── Session তৈরি করো ──────────────────────────────────────
    session_id = str(uuid.uuid4())
    questions  = {
        "mcq":          mcqs,
        "cq":           cqs,
        "mcq_count":    len(mcqs),
        "cq_count":     len(cqs),
        "cq_to_answer": 3,
    }

    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO exam_sessions (session_id, class_id, subject_id, questions_json)
            VALUES (?, ?, ?, ?)
        """, (session_id, class_id, subject_id,
              json.dumps(questions, ensure_ascii=False)))
        conn.commit()
        conn.close()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    subj_info  = get_subject_info(class_id, subject_id)
    subject_bn = subj_info.get("bn", subject_id) if subj_info else subject_id

    return jsonify({
        "success":          True,
        "session_id":       session_id,
        "subject":          subject_bn,
        "difficulty_level": current_level,
        "review_mcq_count": review_count,
        "questions":        questions,
        "instructions": {
            "mcq":  f"{len(mcqs)}টি MCQ ({review_count}টি পুনরাবৃত্তি) — সঠিক উত্তরে +১, ভুল উত্তরে -০.২৫",
            "cq":   f"{len(cqs)}টি CQ এর মধ্যে যেকোনো ৩টি উত্তর দাও",
            "time": "মোট সময়: ৩ ঘণ্টা ৩০ মিনিট",
        }
    })


@bp.route("/api/exam/submit", methods=["POST"])
def exam_submit():
    """
    উত্তর জমা দাও, MCQ score পাও।
    Body: {
      session_id,
      mcq_answers: [{ mcq_id, selected_answer }],
      cq_answers:  [{ stimulus, parts_answered }],
      time_taken:  seconds (integer)
    }
    MCQ: auto-score (+1 / -0.25)
    CQ:  answers সেভ হয়, /api/cq/evaluate দিয়ে পরে evaluate করো
    """
    data        = request.get_json() or {}
    session_id  = data.get("session_id", "").strip()
    mcq_answers = data.get("mcq_answers", [])
    cq_answers  = data.get("cq_answers", [])
    time_taken  = int(data.get("time_taken", 0))

    if not session_id:
        return jsonify({"success": False, "error": "❌ session_id আবশ্যক"}), 400

    try:
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM exam_sessions WHERE session_id=?", (session_id,)
        ).fetchone()

        if not row:
            conn.close()
            return jsonify({"success": False,
                            "error": "❌ Session পাওয়া যায়নি"}), 404

        if row["completed_at"]:
            conn.close()
            return jsonify({"success": False,
                            "error": "❌ এই পরীক্ষা আগেই submit হয়েছে"}), 400

        questions = json.loads(row["questions_json"])
        mcqs      = questions.get("mcq", [])

        # ── MCQ Scoring ───────────────────────────────────────
        mcq_correct = mcq_wrong = mcq_skipped = 0
        mcq_results = []
        answered_map = {
            str(a.get("mcq_id")): a.get("selected_answer", "")
            for a in mcq_answers
        }

        for mcq in mcqs:
            mid      = str(mcq["id"])
            correct  = mcq["answer"].strip()
            selected = answered_map.get(mid, "").strip()

            if not selected:
                mcq_skipped += 1
                status = "skipped"
            elif selected == correct:
                mcq_correct += 1
                status = "correct"
            else:
                mcq_wrong += 1
                status = "wrong"

            mcq_results.append({
                "mcq_id":   mcq["id"],
                "question": mcq["question"],
                "selected": selected,
                "correct":  correct,
                "status":   status,
                "chapter":  mcq.get("chapter", ""),
            })

        # +1 সঠিক, -0.25 ভুল
        mcq_score = max(0, round(mcq_correct - mcq_wrong * 0.25, 2))
        mcq_total = len(mcqs)

        # Chapter-wise breakdown
        chapter_stats = {}
        for r in mcq_results:
            ch = r["chapter"] or "অজানা"
            if ch not in chapter_stats:
                chapter_stats[ch] = {"correct": 0, "wrong": 0, "skipped": 0}
            chapter_stats[ch][r["status"]] += 1

        # ── Save to DB ────────────────────────────────────────
        answers_payload = {
            "mcq_answers": mcq_answers,
            "cq_answers":  cq_answers,
        }
        conn.execute("""
            UPDATE exam_sessions
            SET answers_json=?, score=?, total=?,
                time_taken=?, completed_at=datetime('now')
            WHERE session_id=?
        """, (json.dumps(answers_payload, ensure_ascii=False),
              mcq_score, mcq_total, time_taken, session_id))
        conn.commit()
        conn.close()

        # ── Spaced Repetition: mcq_bank stats আপডেট ──────────
        update_mcq_stats(mcq_results)

        # Time format
        m, s = divmod(time_taken, 60)
        h, m = divmod(m, 60)
        time_str = (f"{h}ঘ {m}মি {s}সে" if h else f"{m}মি {s}সে")

        # ── Adaptive Difficulty update ─────────────────────────
        mcq_percent = round(mcq_score / mcq_total * 100, 1) if mcq_total else 0
        class_id_val = row["class_id"]
        subject_id_val = row["subject_id"]
        new_level = update_student_level(class_id_val, subject_id_val, mcq_percent)

        # ── Concept hints (শুধু <50% হলে) ─────────────────────
        concept_hints = {}
        adaptive_msg = ""
        if mcq_percent >= 80:
            adaptive_msg = f"🎉 দারুণ! {mcq_percent:.1f}% পেয়েছ — পরের exam-এ কঠিন প্রশ্ন আসবে।"
        elif mcq_percent < 50:
            adaptive_msg = f"😔 {mcq_percent:.1f}% — চিন্তা নেই, পরের exam-এ সহজ থেকে শুরু হবে।"
            weak_chapters = [
                ch for ch, st in chapter_stats.items()
                if st.get("wrong", 0) > st.get("correct", 0)
            ]
            concept_hints = get_concept_hints(weak_chapters, class_id_val, subject_id_val)
        else:
            adaptive_msg = f"✅ {mcq_percent:.1f}% — ভালো! পরের exam-এ similar কঠিনতার প্রশ্ন থাকবে।"

        return jsonify({
            "success":    True,
            "session_id": session_id,
            "score": {
                "mcq_correct":  mcq_correct,
                "mcq_wrong":    mcq_wrong,
                "mcq_skipped":  mcq_skipped,
                "mcq_score":    mcq_score,
                "mcq_total":    mcq_total,
                "mcq_percent":  mcq_percent,
                "cq_attempted": len([a for a in cq_answers if a.get("parts_answered")]),
                "cq_note":      "CQ evaluate করতে /api/cq/evaluate ব্যবহার করো",
            },
            "grade":           _get_grade(mcq_score, mcq_total),
            "time_taken":      time_str,
            "chapter_stats":   chapter_stats,
            "mcq_results":     mcq_results,
            "adaptive": {
                "new_level":     new_level,
                "message":       adaptive_msg,
                "concept_hints": concept_hints,
            },
        })

    except Exception as e:
        log.error(f"Exam submit error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/api/exam/history", methods=["GET"])
def exam_history():
    """
    GET /api/exam/history?class_id=ssc&subject_id=physics&limit=10
    পুরনো সম্পন্ন পরীক্ষার তালিকা।
    """
    class_id   = request.args.get("class_id", "").strip()
    subject_id = request.args.get("subject_id", "").strip()
    limit      = int(request.args.get("limit", 10))

    try:
        conn   = get_db()
        where  = ["completed_at IS NOT NULL"]
        params = []
        if class_id:
            where.append("class_id=?")
            params.append(class_id)
        if subject_id:
            where.append("subject_id=?")
            params.append(subject_id)
        params.append(limit)

        rows = conn.execute(f"""
            SELECT session_id, class_id, subject_id,
                   score, total, time_taken, completed_at
            FROM exam_sessions
            WHERE {" AND ".join(where)}
            ORDER BY completed_at DESC LIMIT ?
        """, params).fetchall()
        conn.close()

        history = []
        for r in rows:
            pct = round(r["score"] / r["total"] * 100, 1) if r["total"] else 0
            m, s = divmod(r["time_taken"] or 0, 60)
            h, m = divmod(m, 60)
            history.append({
                "session_id":   r["session_id"],
                "class_id":     r["class_id"],
                "subject_id":   r["subject_id"],
                "score":        r["score"],
                "total":        r["total"],
                "percent":      pct,
                "grade":        _get_grade(r["score"], r["total"]),
                "time_taken":   (f"{h}ঘ {m}মি {s}সে" if h else f"{m}মি {s}সে"),
                "completed_at": r["completed_at"],
            })

        return jsonify({
            "success": True,
            "history": history,
            "total":   len(history),
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
