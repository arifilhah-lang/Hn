"""
╔══════════════════════════════════════════════════════════╗
║  Step 15 — Gemini Context Caching                        ║
║                                                          ║
║  একবার subject এর content cache করো → পরে 0 token!      ║
║  Model: gemini-3.1-flash-lite (context cache সাপোর্ট)   ║
║                                                          ║
║  POST   /api/cache/warm          — subject cache তৈরি    ║
║  GET    /api/cache/status        — কোনটা cached আছে      ║
║  DELETE /api/cache/clear         — cache মুছো            ║
║  GET    /api/cache/savings       — কত token বাঁচলো       ║
╚══════════════════════════════════════════════════════════╝
"""

from flask import Blueprint, request, jsonify
import sqlite3, os, json, logging, time, threading

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════

# Free tier check — some models have 0 cached content limit on free tier
# Set ENABLE_CONTEXT_CACHE=False in .env if hitting free tier limits
import os
ENABLE_CONTEXT_CACHE = os.getenv("ENABLE_CONTEXT_CACHE", "true").lower() == "true"

CACHE_TTL      = "3600s"
CACHE_MODEL    = "gemini-3.1-flash-lite"
MAX_CACHE_CHARS = 80_000

# ── Paths ─────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "study_ai.db")

# ── DB helper ─────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

# ── Gemini client ─────────────────────────────────────────
from config import GEMINI_API_KEYS, DEFAULT_MODEL
from google import genai
from google.genai import types

_cache_client = None
def _get_client():
    global _cache_client
    if _cache_client is None:
        for key in GEMINI_API_KEYS:
            if key.strip():
                try:
                    _cache_client = genai.Client(
                        api_key=key,
                        http_options={'api_version': 'v1beta'}
                    )
                    break
                except Exception:
                    pass
    return _cache_client

# ── Blueprint ─────────────────────────────────────────────
bp = Blueprint("context_cache", __name__)

# ══════════════════════════════════════════════════════════
#  TABLE INIT
# ══════════════════════════════════════════════════════════
def _init_tables():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subject_caches (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id    TEXT    NOT NULL,
            subject_id  TEXT    NOT NULL,
            cache_name  TEXT    NOT NULL,
            expires_at  TEXT,
            token_count INTEGER DEFAULT 0,
            hit_count   INTEGER DEFAULT 0,
            tokens_saved INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(class_id, subject_id)
        )
    """)
    conn.commit()
    conn.close()
    log.info("[Step15] subject_caches table ready")

_init_tables()

# ══════════════════════════════════════════════════════════
#  CORE HELPERS
# ══════════════════════════════════════════════════════════

def _build_subject_context(class_id: str, subject_id: str) -> str:
    """DB থেকে subject এর সব content একসাথে নাও"""
    conn = get_db()
    rows = conn.execute("""
        SELECT chapter, chapter_num, content, source_type
        FROM pdf_content
        WHERE class_id   = ?
          AND subject_id = ?
          AND content    IS NOT NULL
          AND length(content) > 20
        ORDER BY chapter_num, page
    """, (class_id, subject_id)).fetchall()
    conn.close()

    if not rows:
        return ""

    # Chapter দিয়ে group করো
    chapters = {}
    for r in rows:
        ch = r["chapter"] or "অধ্যায় অজানা"
        if ch not in chapters:
            chapters[ch] = []
        chapters[ch].append(r["content"])

    parts = [f"# {class_id.upper()} — {subject_id} পাঠ্যবই\n"]
    total = 0
    for ch, contents in chapters.items():
        chunk = f"\n## {ch}\n" + "\n".join(contents[:5])  # per-chapter max 5 chunks
        parts.append(chunk)
        total += len(chunk)
        if total >= MAX_CACHE_CHARS:
            parts.append("\n[... বাকি অধ্যায় ...]\n")
            break

    return "\n".join(parts)


def get_cached_content(class_id: str, subject_id: str):
    """
    app.py থেকে call করো — cache থাকলে cache_name দেবে, নাহলে None।
    hit_count + tokens_saved update করে।
    """
    conn = get_db()
    row = conn.execute("""
        SELECT cache_name, token_count, expires_at
        FROM subject_caches
        WHERE class_id = ? AND subject_id = ?
    """, (class_id, subject_id)).fetchone()
    conn.close()

    if not row:
        return None

    # Expiry চেক
    if row["expires_at"]:
        from datetime import datetime
        try:
            exp = datetime.fromisoformat(row["expires_at"])
            if datetime.utcnow() > exp:
                # Expired — delete
                conn = get_db()
                conn.execute(
                    "DELETE FROM subject_caches WHERE class_id=? AND subject_id=?",
                    (class_id, subject_id)
                )
                conn.commit()
                conn.close()
                log.info(f"[Step15] Cache expired: {class_id}/{subject_id}")
                return None
        except Exception:
            pass

    # hit_count + tokens_saved update
    conn = get_db()
    conn.execute("""
        UPDATE subject_caches
        SET hit_count    = hit_count + 1,
            tokens_saved = tokens_saved + token_count
        WHERE class_id = ? AND subject_id = ?
    """, (class_id, subject_id))
    conn.commit()
    conn.close()

    return row["cache_name"]


def _create_gemini_cache(class_id: str, subject_id: str) -> dict:
    """Gemini API তে cache তৈরি করো"""
    if not ENABLE_CONTEXT_CACHE:
        return {"success": False, "error": "Context cache disabled (ENABLE_CONTEXT_CACHE=false)"}
    
    client = _get_client()
    if not client:
        return {"success": False, "error": "Gemini client init হয়নি"}

    context_text = _build_subject_context(class_id, subject_id)
    if not context_text or len(context_text) < 500:
        return {"success": False, "error": "এই subject এর content DB তে নেই বা অনেক কম"}

    # Gemini cache minimum ~32k tokens — content কম হলে warn করো
    if len(context_text) < 10_000:
        log.warning(f"[Step15] Content মাত্র {len(context_text)} chars — cache এ কম token, হয়তো reject হবে")

    try:
        cache = client.caches.create(
            model=CACHE_MODEL,
            config=types.CreateCachedContentConfig(
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part(text=context_text)]
                    )
                ],
                ttl=CACHE_TTL,
                system_instruction=(
                    f"তুমি {class_id.upper()} {subject_id} বিষয়ের একজন বিশেষজ্ঞ শিক্ষক। "
                    "উপরের পাঠ্যবই এর content ব্যবহার করে বাংলায় উত্তর দাও।"
                ),
            ),
        )

        # DB তে save করো
        from datetime import datetime, timedelta
        expires_at = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        approx_tokens = len(context_text) // 4  # rough estimate

        conn = get_db()
        conn.execute("""
            INSERT OR REPLACE INTO subject_caches
                (class_id, subject_id, cache_name, expires_at, token_count)
            VALUES (?, ?, ?, ?, ?)
        """, (class_id, subject_id, cache.name, expires_at, approx_tokens))
        conn.commit()
        conn.close()

        log.info(f"[Step15] Cache created: {cache.name} for {class_id}/{subject_id}")
        return {
            "success":       True,
            "cache_name":    cache.name,
            "approx_tokens": approx_tokens,
            "content_chars": len(context_text),
            "expires_at":    expires_at,
        }

    except Exception as e:
        log.error(f"[Step15] Cache create error: {e}")
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════

@bp.route("/api/cache/warm", methods=["POST"])
def warm_cache():
    """
    Subject এর context cache তৈরি করো।
    Body: { class_id, subject_id, force? }
    force=true হলে পুরনো cache মুছে নতুন বানাবে।
    """
    if not ENABLE_CONTEXT_CACHE:
        return jsonify({"success": False, "error": "Context cache disabled (ENABLE_CONTEXT_CACHE=false)"}), 503
    
    data       = request.get_json(force=True) or {}
    class_id   = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()
    force      = data.get("force", False)

    if not class_id or not subject_id:
        return jsonify({"success": False, "error": "class_id আর subject_id দাও"}), 400

    # Already cached?
    existing = get_cached_content(class_id, subject_id)
    if existing and not force:
        return jsonify({
            "success":    True,
            "cached":     True,
            "cache_name": existing,
            "message":    "ইতিমধ্যে cached আছে। force=true দিলে নতুন করে বানাবে।",
        })

    # Force হলে DB record মুছো (Gemini cache আলাদা expire হবে)
    if force and existing:
        conn = get_db()
        conn.execute(
            "DELETE FROM subject_caches WHERE class_id=? AND subject_id=?",
            (class_id, subject_id)
        )
        conn.commit()
        conn.close()

    result = _create_gemini_cache(class_id, subject_id)
    return jsonify(result), (200 if result["success"] else 500)


@bp.route("/api/cache/status", methods=["GET"])
def cache_status():
    """কোন কোন subject cached আছে"""
    conn = get_db()
    rows = conn.execute("""
        SELECT class_id, subject_id, cache_name,
               token_count, hit_count, tokens_saved,
               expires_at, created_at
        FROM subject_caches
        ORDER BY class_id, subject_id
    """).fetchall()
    conn.close()

    caches = []
    for r in rows:
        caches.append({
            "class_id":     r["class_id"],
            "subject_id":   r["subject_id"],
            "cache_name":   r["cache_name"],
            "token_count":  r["token_count"],
            "hit_count":    r["hit_count"],
            "tokens_saved": r["tokens_saved"],
            "expires_at":   r["expires_at"],
            "created_at":   r["created_at"],
        })

    total_saved = sum(c["tokens_saved"] for c in caches)
    return jsonify({
        "success":        True,
        "cached_subjects": len(caches),
        "total_tokens_saved": total_saved,
        "caches":         caches,
        "model":          CACHE_MODEL,
    })


@bp.route("/api/cache/clear", methods=["DELETE"])
def clear_cache():
    """
    Cache মুছো।
    Body: { class_id?, subject_id? } — না দিলে সব মুছবে
    """
    data       = request.get_json(force=True) or {}
    class_id   = data.get("class_id")
    subject_id = data.get("subject_id")

    conn = get_db()
    if class_id and subject_id:
        conn.execute(
            "DELETE FROM subject_caches WHERE class_id=? AND subject_id=?",
            (class_id, subject_id)
        )
        msg = f"{class_id}/{subject_id} cache মুছা হয়েছে"
    elif class_id:
        conn.execute("DELETE FROM subject_caches WHERE class_id=?", (class_id,))
        msg = f"{class_id} এর সব cache মুছা হয়েছে"
    else:
        conn.execute("DELETE FROM subject_caches")
        msg = "সব cache মুছা হয়েছে"

    conn.commit()
    deleted = conn.total_changes
    conn.close()

    return jsonify({"success": True, "message": msg, "deleted": deleted})


# ══════════════════════════════════════════════════════════
#  AUTO-WARM — Startup এ popular subjects cache করো
# ══════════════════════════════════════════════════════════

def auto_warm_popular_subjects(top_n: int = 5, delay_seconds: int = 30):
    """
    Server start হওয়ার পর background এ চলে।
    DB তে সবচেয়ে বেশি content আছে এমন top_n subject auto-cache করে।
    Already cached থাকলে skip করে — token নষ্ট হয় না।
    """
    if not ENABLE_CONTEXT_CACHE:
        log.info("[Step15] Auto-warm skipped (ENABLE_CONTEXT_CACHE=false)")
        return

    time.sleep(delay_seconds)  # Server পুরো ready হওয়ার জন্য অপেক্ষা

    log.info(f"[Step15] Auto-warm শুরু — top {top_n} subjects...")

    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT class_id, subject_id,
                   COUNT(*) as chunk_count,
                   SUM(length(content)) as total_chars
            FROM pdf_content
            WHERE content IS NOT NULL AND length(content) > 20
            GROUP BY class_id, subject_id
            HAVING total_chars > 10000
            ORDER BY total_chars DESC
            LIMIT ?
        """, (top_n,)).fetchall()
        conn.close()
    except Exception as e:
        log.error(f"[Step15] Auto-warm DB error: {e}")
        return

    if not rows:
        log.info("[Step15] Auto-warm: DB তে কোনো subject নেই, skip।")
        return

    warmed, skipped, failed = 0, 0, 0

    for row in rows:
        class_id   = row["class_id"]
        subject_id = row["subject_id"]

        # Already cached? → skip, token বাঁচাও
        existing = get_cached_content(class_id, subject_id)
        if existing:
            log.info(f"[Step15] Auto-warm skip (already cached): {class_id}/{subject_id}")
            skipped += 1
            continue

        result = _create_gemini_cache(class_id, subject_id)
        if result["success"]:
            log.info(f"[Step15] Auto-warmed: {class_id}/{subject_id} "
                     f"(~{result['approx_tokens']} tokens cached)")
            warmed += 1
        else:
            log.warning(f"[Step15] Auto-warm failed: {class_id}/{subject_id} — {result['error']}")
            failed += 1

        time.sleep(2)  # Rate limit এড়াতে ছোট্ট বিরতি

    log.info(f"[Step15] Auto-warm done — warmed:{warmed} skipped:{skipped} failed:{failed}")


@bp.route("/api/cache/auto-warm", methods=["POST"])
def trigger_auto_warm():
    """Admin থেকে manually auto-warm trigger করো"""
    if not ENABLE_CONTEXT_CACHE:
        return jsonify({"success": False, "error": "Context cache disabled (ENABLE_CONTEXT_CACHE=false)"}), 503
    
    data  = request.get_json(force=True) or {}
    top_n = int(data.get("top_n", 5))
    thread = threading.Thread(
        target=auto_warm_popular_subjects,
        kwargs={"top_n": top_n, "delay_seconds": 0},
        daemon=True
    )
    thread.start()
    return jsonify({"success": True, "message": f"Auto-warm background এ চলছে (top {top_n} subjects)..."})


# ── Startup hook — module load হলেই background thread শুরু ──
if ENABLE_CONTEXT_CACHE:
    threading.Thread(
        target=auto_warm_popular_subjects,
        kwargs={"top_n": 5, "delay_seconds": 30},
        daemon=True
    ).start()
else:
    log.info("[Step15] Startup auto-warm skipped (ENABLE_CONTEXT_CACHE=false)")


@bp.route("/api/cache/savings", methods=["GET"])
def cache_savings():
    """কত token বাঁচলো — stats"""
    conn = get_db()
    row = conn.execute("""
        SELECT
            SUM(hit_count)    as total_hits,
            SUM(tokens_saved) as total_tokens_saved,
            COUNT(*)          as cached_subjects
        FROM subject_caches
    """).fetchone()
    conn.close()

    hits   = row["total_hits"]   or 0
    saved  = row["total_tokens_saved"] or 0
    # Gemini 3.1 Flash Lite: $0.025 per 1M input tokens (approx)
    cost_saved_usd = saved / 1_000_000 * 0.025

    return jsonify({
        "success":           True,
        "total_cache_hits":  hits,
        "total_tokens_saved": saved,
        "approx_cost_saved_usd": round(cost_saved_usd, 5),
        "cached_subjects":   row["cached_subjects"] or 0,
    })
