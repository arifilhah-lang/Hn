"""
╔══════════════════════════════════════════════════════════╗
║  Step 20 — Spaced Repetition                             ║
║                                                          ║
║  Blueprint নেই — শুধু helper functions।                 ║
║  step6_mock_exam.py এটা import করে।                     ║
║                                                          ║
║  Logic:                                                  ║
║   exam_submit হলে → mcq_bank-এর times_shown /            ║
║     times_correct আপডেট হয়।                            ║
║                                                          ║
║   exam_start হলে → "review batch" তৈরি হয়:             ║
║     mcq_bank থেকে times_shown > 0 AND accuracy < 0.6    ║
║     এমন MCQ গুলো (সবচেয়ে বেশি ভুল হওয়া আগে) নিয়ে      ║
║     exam-এর ৩০% slot পূরণ করা হয়।                      ║
║     বাকি ৭০% adaptive MCQ দিয়ে fill হয় (dup ছাড়া)।    ║
╚══════════════════════════════════════════════════════════╝
"""

import sqlite3, os, logging

log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "study_ai.db")


def _get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ── 1. exam_submit এর পরে stats আপডেট ───────────────────────
def update_mcq_stats(mcq_results: list):
    """
    mcq_results: exam_submit থেকে আসা list —
      [{ mcq_id, status: 'correct'|'wrong'|'skipped' }, ...]
    times_shown++ সব attempt করা MCQ-তে।
    times_correct++ শুধু correct MCQ-তে।
    skipped MCQ touch করা হয় না।
    """
    if not mcq_results:
        return

    conn = _get_db()
    try:
        for r in mcq_results:
            if r.get("status") == "skipped":
                continue
            mcq_id  = r.get("mcq_id")
            correct = r.get("status") == "correct"
            conn.execute("""
                UPDATE mcq_bank
                SET times_shown   = times_shown + 1,
                    times_correct = times_correct + ?
                WHERE id = ?
            """, (1 if correct else 0, mcq_id))
        conn.commit()
    except Exception as e:
        log.error(f"update_mcq_stats error: {e}")
    finally:
        conn.close()


# ── 2. exam_start এ review batch তৈরি ───────────────────────
REVIEW_ACCURACY_THRESHOLD = 0.6   # এর নিচে হলে review-এ আসে
REVIEW_MIN_SHOWN          = 1     # অন্তত একবার দেখানো হয়েছে এমন MCQ

def get_review_mcqs(class_id: str, subject_id: str, count: int) -> list:
    """
    ভুল-ভারী MCQ টানো — সবচেয়ে কম accuracy আগে।
    count = exam-এর কতটা slot review-এর জন্য বরাদ্দ (মোটের ৩০%)।
    """
    if count < 1:
        return []

    conn = _get_db()
    try:
        rows = conn.execute("""
            SELECT id, chapter, chapter_num, question,
                   option_a, option_b, option_c, option_d,
                   answer, difficulty,
                   times_shown, times_correct,
                   CAST(times_correct AS REAL) / times_shown AS accuracy
            FROM mcq_bank
            WHERE class_id=? AND subject_id=?
              AND times_shown >= ?
              AND (CAST(times_correct AS REAL) / times_shown) < ?
            ORDER BY accuracy ASC
            LIMIT ?
        """, (class_id, subject_id,
              REVIEW_MIN_SHOWN, REVIEW_ACCURACY_THRESHOLD,
              count)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error(f"get_review_mcqs error: {e}")
        return []
    finally:
        conn.close()


# ── 3. review + adaptive mix করা ────────────────────────────
def build_exam_mcqs(
    class_id: str,
    subject_id: str,
    total_count: int,
    adaptive_fn,          # get_mcqs_adaptive(class_id, subject_id, count) → (list, level)
    review_ratio: float = 0.30,
) -> tuple:
    """
    Review MCQ (৩০%) + Adaptive MCQ (৭০%) মিলিয়ে exam MCQ list বানাও।
    duplicate id এড়ানো হয়।
    Returns: (mcq_list, level, review_count)
    """
    review_slots   = max(0, round(total_count * review_ratio))
    adaptive_slots = total_count - review_slots

    # review batch
    review_mcqs = get_review_mcqs(class_id, subject_id, review_slots)
    review_ids  = {r["id"] for r in review_mcqs}

    # adaptive batch — duplicate বাদ দিয়ে
    adaptive_raw, level = adaptive_fn(class_id, subject_id, adaptive_slots + review_slots)
    adaptive_mcqs = [m for m in adaptive_raw if m["id"] not in review_ids][:adaptive_slots]

    final = review_mcqs + adaptive_mcqs

    # যদি review কম এলে (নতুন user), adaptive দিয়ে fill
    if len(final) < total_count:
        extra_ids = review_ids | {m["id"] for m in adaptive_mcqs}
        extra_raw, _ = adaptive_fn(class_id, subject_id, total_count * 2)
        extras = [m for m in extra_raw if m["id"] not in extra_ids]
        final += extras[: total_count - len(final)]

    return final, level, len(review_mcqs)
