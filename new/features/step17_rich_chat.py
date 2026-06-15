"""
╔══════════════════════════════════════════════════════════╗
║  Step 17 — Rich Chat (লেসন মোড + থিংকিং মোড টগল)         ║
║  POST /api/rich-chat/message   — chat message পাঠাও      ║
║  GET  /api/rich-chat/settings  — session এর mode জানো    ║
║  POST /api/rich-chat/settings  — mode টগল করো (message    ║
║                                    ছাড়াই)                  ║
║  GET  /api/rich-chat/history   — পুরনো chat               ║
║  POST /api/rich-chat/clear     — session reset            ║
╚══════════════════════════════════════════════════════════╝

দুটো independent toggle:

1. lesson_mode (default: false)
   - ON হলে → AI Socratic পদ্ধতিতে পড়ায়। সরাসরি answer না দিয়ে
     ছোট ছোট প্রশ্ন করে ছাত্রকে নিজে ভাবতে সাহায্য করে, ধাপে ধাপে।
   - OFF হলে → normal direct Q&A tutor (যেমন আগের theory chat)।

2. thinking_mode (default: true)
   - ON হলে → _think_call() (extended thinking, বেশি accurate কিন্তু
     ধীর + বেশি token)।
   - OFF হলে → plain generate_content() (দ্রুত, কম token, simple
     প্রশ্নের জন্য যথেষ্ট)।

দুটো toggle session_id ভিত্তিক rich_chat_settings টেবিলে সেভ থাকে,
তাই পরের message-এ আবার না পাঠালেও আগের mode persist করে। কিন্তু
client প্রতিবার পাঠালে সেটাই priority পায় (override)।
"""

from flask import Blueprint, request, jsonify, Response
import sqlite3, os, json, logging, uuid

from features.step18_cq_lesson_guide import is_cq_question, cq_lesson_prompt

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
bp = Blueprint("rich_chat", __name__)


def _init_tables():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rich_chat_settings (
            session_id   TEXT PRIMARY KEY,
            class_id     TEXT,
            subject_id   TEXT,
            lesson_mode  INTEGER DEFAULT 0,
            thinking_mode INTEGER DEFAULT 0,
            is_cq_session INTEGER DEFAULT 0,
            updated_at   TEXT DEFAULT (datetime('now'))
        )
    """)
    try:
        conn.execute("ALTER TABLE rich_chat_settings ADD COLUMN is_cq_session INTEGER DEFAULT 0")
    except Exception:
        pass
    conn.commit()
    conn.close()

_init_tables()


# ── System prompts ───────────────────────────────────────────
def _lesson_mode_prompt(class_label, subject_bn):
    return (
        f"তুমি {class_label} শ্রেণীর {subject_bn} বিষয়ের একজন যত্নশীল শিক্ষক।"
        "\n\n⛔ সবচেয়ে গুরুত্বপূর্ণ নিয়ম:\n"
        "তোমাকে 'পাঠ্যবই থেকে তথ্য:' অংশে কিছু তথ্য দেওয়া হবে। "
        "তুমি শুধুমাত্র ওই তথ্য থেকে উত্তর দেবে। "
        "নিজের মাথা থেকে বা training data থেকে কিছু বলবে না। "
        "তথ্যে উত্তর না থাকলে বলো: 'দুঃখিত, পাঠ্যবইয়ের তথ্যে এটি পাওয়া যায়নি।'"
        "\n\nঅন্যান্য নিয়ম:\n"
        "- উত্তরের শুরুতে বলো কোন [তথ্য] থেকে উত্তর দিচ্ছো।\n"
        "- ছোট ছোট ধাপে পড়াও, একসাথে পুরো answer দিও না।\n"
        "- প্রতি ধাপে একটা সহজ প্রশ্ন করো যাতে ছাত্র চিন্তা করে।\n"
        "- ছাত্র ভুল করলে হিন্ট দাও, সঠিক করলে appreciate করো।\n"
        "- সহজ বাংলায়, ৩-৫ লাইনে reply দাও।"
    )



def _normal_mode_prompt(class_label, subject_bn):
    return (
        f"তুমি {class_label} শ্রেণীর {subject_bn} বিষয়ের সহায়ক।"
        "\n\n⛔ সবচেয়ে গুরুত্বপূর্ণ নিয়ম:\n"
        "তোমাকে 'পাঠ্যবই থেকে তথ্য:' অংশে কিছু তথ্য দেওয়া হবে। "
        "তুমি শুধুমাত্র ওই তথ্য থেকে উত্তর দেবে। "
        "নিজের মাথা থেকে বা training data থেকে একটা শব্দও যোগ করবে না। "
        "তথ্যে উত্তর না থাকলে বলো: 'দুঃখিত, পাঠ্যবইয়ের তথ্যে এটি পাওয়া যায়নি।'"
        "\n\nঅন্যান্য নিয়ম:\n"
        "- হাই/হ্যালো এর উত্তর দিতে পারো।\n"
        "- উত্তরের শুরুতে বলো কোন [তথ্য] থেকে উত্তর দিচ্ছো।\n"
        "- সরাসরি স্পষ্ট উত্তর দাও।\n"
        "- উদাহরণও প্রদত্ত তথ্য থেকেই নাও।\n"
        "- উত্তর সংক্ষিপ্ত রাখো।"
    )



# ── Settings helpers ─────────────────────────────────────────
def _get_settings(conn, session_id):
    row = conn.execute(
        "SELECT * FROM rich_chat_settings WHERE session_id=?", (session_id,)
    ).fetchone()
    if row:
        return {"lesson_mode": bool(row["lesson_mode"]), "thinking_mode": bool(row["thinking_mode"]),
                "class_id": row["class_id"], "subject_id": row["subject_id"],
                "is_cq_session": bool(row["is_cq_session"]) if "is_cq_session" in row.keys() else False}
    return None


def _save_settings(conn, session_id, class_id, subject_id, lesson_mode, thinking_mode, is_cq_session=False):
    conn.execute("""
        INSERT INTO rich_chat_settings (session_id, class_id, subject_id, lesson_mode, thinking_mode, is_cq_session, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(session_id) DO UPDATE SET
            class_id=excluded.class_id,
            subject_id=excluded.subject_id,
            lesson_mode=excluded.lesson_mode,
            thinking_mode=excluded.thinking_mode,
            is_cq_session=excluded.is_cq_session,
            updated_at=datetime('now')
    """, (session_id, class_id, subject_id, int(lesson_mode), int(thinking_mode), int(is_cq_session)))
    conn.commit()


# ── Routes ────────────────────────────────────────────────────
@bp.route("/api/rich-chat/stream", methods=["POST"])
def rich_chat_stream():
    # circular import এড়ানোর জন্য function-এর ভিতরে import
    from app import (
        _get_client, _think_call,
        _conv_save, _conv_load, _search_json_library, _build_context,
        _detect_source_types,
        CLASSES, get_subject_info,
        MAX_OUTPUT_SHORT, MAX_OUTPUT_LONG, DEFAULT_MODEL
    )
    from google.genai import types

    client = _get_client()
    if not client:
        return jsonify({"success": False, "error": "❌ API Key সেট করা হয়নি"}), 400

    data = request.get_json(force=True) or {}
    class_id   = (data.get("class_id") or "").strip()
    subject_id = (data.get("subject_id") or "").strip()
    message    = (data.get("message") or "").strip()
    session_id = (data.get("session_id") or "").strip()
    ai_model   = (data.get("ai_model") or "zolo_1").strip()

    if not class_id or not subject_id or not message:
        return jsonify({"success": False, "error": "❌ class_id, subject_id, message আবশ্যক"}), 400

    if not session_id:
        session_id = str(uuid.uuid4())[:12]

    conn = get_db()
    try:
        saved = _get_settings(conn, session_id)

        # client যদি toggle না পাঠায়, আগের session settings ব্যবহার হবে; না থাকলে default
        lesson_mode   = data.get("lesson_mode")
        thinking_mode = data.get("thinking_mode")

        if lesson_mode is None:
            lesson_mode = saved["lesson_mode"] if saved else False
        if thinking_mode is None:
            thinking_mode = saved["thinking_mode"] if saved else False

        lesson_mode   = bool(lesson_mode)
        thinking_mode = bool(thinking_mode)

        is_cq = False
        if saved:
            is_cq = saved.get("is_cq_session", False)
        if is_cq_question(message):
            is_cq = True

        _save_settings(conn, session_id, class_id, subject_id, lesson_mode, thinking_mode, is_cq)
    finally:
        conn.close()

    cls         = CLASSES.get(class_id, {})
    class_label = cls.get("label", class_id)
    subj_info   = get_subject_info(class_id, subject_id)
    subject_bn  = subj_info.get("bn", subject_id) if subj_info else subject_id

    # ✅ NEW (IM-10): প্রশ্নের ধরন বুঝে board_book/test_paper বা guide
    # থেকে chunk আনে — নির্দিষ্ট source এ কিছু না পেলে সব source থেকে খোঁজে।
    detected_source_types = _detect_source_types(message)

    # পাঠ্যবই থেকে context — বেশি chunk আনো
    chunks  = _search_json_library(class_id, subject_id, message, top_n=6, source_type=detected_source_types)
    if not chunks and detected_source_types:
        chunks = _search_json_library(class_id, subject_id, message, top_n=6)
    context = _build_context(chunks)

    # ✅ চ্যাংক রিট্রিভাল লগ — দেখাবে কতগুলো chunk পাওয়া গেছে
    chunk_chapters = [c.get("chapter", "?") for c in chunks] if chunks else []
    chunk_sources = list(set([c.get("source_type", "?") for c in chunks])) if chunks else []
    log.info(f"📖 Chunk search: query='{message[:50]}' | intent_source_type={detected_source_types} | found={len(chunks)} chunks | chapters={chunk_chapters} | sources={chunk_sources} | context_len={len(context)}")

    hist_limit = 12 if lesson_mode else 8
    history = _conv_load(session_id, limit=hist_limit)

    system_prompt = (
        (cq_lesson_prompt(class_label, subject_bn) if is_cq else _lesson_mode_prompt(class_label, subject_bn))
        if lesson_mode
        else _normal_mode_prompt(class_label, subject_bn)
    )

    contents = []
    for h in history:
        contents.append(types.Content(role=h["role"], parts=[types.Part(text=h["parts"][0])]))

    if context:
        user_text = (
            f"⛔ নিচের 'পাঠ্যবই থেকে তথ্য' অংশ তোমার একমাত্র তথ্যসূত্র। "
            f"শুধুমাত্র এই তথ্য ব্যবহার করে উত্তর দাও। "
            f"নিজের মাথা থেকে কিছু যোগ করবে না।\n\n"
            f"পাঠ্যবই থেকে তথ্য:\n{context}\n\n"
            f"ছাত্রের বার্তা: {message}"
        )
    else:
        user_text = message
        log.warning(f"⚠️ কোনো chunk পাওয়া যায়নি! query='{message[:50]}'")

    contents.append(types.Content(role="user", parts=[types.Part(text=user_text)]))

    def generate():
        # First yield the metadata — chunk info সহ
        meta = {
            'type': 'meta',
            'session_id': session_id,
            'from_library': bool(context),
            'chunks_found': len(chunks),
            'chunk_chapters': chunk_chapters[:5],
            'lesson_mode': lesson_mode,
            'thinking_mode': thinking_mode
        }
        yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"

        full_answer = ""
        try:
            from features.nvidia_models import is_nvidia_model, generate_nvidia_stream
            if is_nvidia_model(ai_model):
                try:
                    for kind, piece in generate_nvidia_stream(
                        model_alias=ai_model,
                        contents=contents,
                        system_instruction=system_prompt,
                        max_tokens=MAX_OUTPUT_LONG if thinking_mode else MAX_OUTPUT_SHORT,
                        temperature=0.7,
                        thinking_mode=thinking_mode
                    ):
                        if kind == "chunk":
                            full_answer += piece
                            yield f"data: {json.dumps({'type': 'chunk', 'text': piece}, ensure_ascii=False)}\n\n"
                except Exception as ne:
                    log.warning(f"⚠️ Nvidia rich stream failed: {ne}. Falling back to Gemini...")
                    model_name = "gemini-2.5-flash" if ai_model == "zolo_1_5" else DEFAULT_MODEL
                    config_args = {
                        "max_output_tokens": MAX_OUTPUT_LONG if thinking_mode else MAX_OUTPUT_SHORT,
                        "temperature": 0.7,
                        "system_instruction": system_prompt,
                    }
                    if thinking_mode:
                        config_args["thinking_config"] = types.ThinkingConfig(thinking_budget_tokens=1024)
                    
                    response_stream = client.models.generate_content_stream(
                        model=model_name,
                        contents=contents,
                        config=types.GenerateContentConfig(**config_args)
                    )
                    for chunk in response_stream:
                        if chunk.text:
                            full_answer += chunk.text
                            yield f"data: {json.dumps({'type': 'chunk', 'text': chunk.text}, ensure_ascii=False)}\n\n"
            else:
                model_name = "gemini-2.5-flash" if ai_model == "zolo_1_5" else DEFAULT_MODEL
                
                # We need to simulate _think_call but with streaming for gemini if thinking mode is ON
                # Actually, gemini thinking mode currently doesn't support streaming well via the python SDK,
                # but we can just use generate_content_stream and if thinking_config is passed it streams the thought blocks too
                # For simplicity, we just use generate_content_stream for normal calls
                
                config_args = {
                    "max_output_tokens": MAX_OUTPUT_LONG if thinking_mode else MAX_OUTPUT_SHORT,
                    "temperature": 0.7,
                    "system_instruction": system_prompt,
                }
                if thinking_mode:
                    config_args["thinking_config"] = types.ThinkingConfig(thinking_budget_tokens=1024)
                
                response_stream = client.models.generate_content_stream(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(**config_args)
                )
                
                for chunk in response_stream:
                    if chunk.text:
                        full_answer += chunk.text
                        yield f"data: {json.dumps({'type': 'chunk', 'text': chunk.text}, ensure_ascii=False)}\n\n"

        except Exception as e:
            log.error(f"❌ Rich chat stream ত্রুটি: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            return

        full_answer = full_answer.strip()
        _conv_save(session_id, class_id, subject_id, "user", message)
        _conv_save(session_id, class_id, subject_id, "model", full_answer)

        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )



@bp.route("/api/rich-chat/settings", methods=["GET"])
def rich_chat_get_settings():
    session_id = (request.args.get("session_id") or "").strip()
    if not session_id:
        return jsonify({"success": False, "error": "session_id দরকার"}), 400

    conn = get_db()
    try:
        saved = _get_settings(conn, session_id)
        if not saved:
            return jsonify({"success": True, "lesson_mode": False, "thinking_mode": False, "exists": False})
        return jsonify({"success": True, "exists": True, **saved})
    finally:
        conn.close()


@bp.route("/api/rich-chat/settings", methods=["POST"])
def rich_chat_set_settings():
    """চ্যাট না করেও শুধু toggle change করতে চাইলে এই endpoint ব্যবহার হবে"""
    data = request.get_json(force=True) or {}
    session_id = (data.get("session_id") or "").strip()
    if not session_id:
        session_id = str(uuid.uuid4())[:12]

    class_id   = (data.get("class_id") or "").strip()
    subject_id = (data.get("subject_id") or "").strip()

    conn = get_db()
    try:
        saved = _get_settings(conn, session_id)

        lesson_mode   = data.get("lesson_mode")
        thinking_mode = data.get("thinking_mode")

        if lesson_mode is None:
            lesson_mode = saved["lesson_mode"] if saved else False
        if thinking_mode is None:
            thinking_mode = saved["thinking_mode"] if saved else False

        if not class_id and saved:
            class_id = saved["class_id"]
        if not subject_id and saved:
            subject_id = saved["subject_id"]

        is_cq_session = saved["is_cq_session"] if saved else False
        _save_settings(conn, session_id, class_id, subject_id, bool(lesson_mode), bool(thinking_mode), bool(is_cq_session))

        return jsonify({
            "success": True,
            "session_id": session_id,
            "lesson_mode": bool(lesson_mode),
            "thinking_mode": bool(thinking_mode),
        })
    finally:
        conn.close()


@bp.route("/api/rich-chat/history", methods=["GET"])
def rich_chat_history():
    from app import _conv_load
    session_id = (request.args.get("session_id") or "").strip()
    if not session_id:
        return jsonify({"success": False, "error": "session_id দরকার"}), 400

    history = _conv_load(session_id, limit=50)
    return jsonify({"success": True, "session_id": session_id, "history": history})


@bp.route("/api/rich-chat/clear", methods=["POST"])
def rich_chat_clear():
    from app import _conv_clear
    data = request.get_json(force=True) or {}
    session_id = (data.get("session_id") or "").strip()
    if not session_id:
        return jsonify({"success": False, "error": "session_id দরকার"}), 400

    _conv_clear(session_id)

    conn = get_db()
    try:
        conn.execute("DELETE FROM rich_chat_settings WHERE session_id=?", (session_id,))
        conn.commit()
    finally:
        conn.close()

    return jsonify({"success": True, "message": "Session reset হয়েছে"})



@bp.route("/api/rich-chat/sessions", methods=["GET"])
def rich_chat_sessions():
    conn = get_db()
    try:
        rows = conn.execute('''
            SELECT s.session_id, s.subject_id, s.updated_at,
                   (SELECT message FROM conversation_history h 
                    WHERE h.session_id = s.session_id AND role = 'user' 
                    ORDER BY id ASC LIMIT 1) as title
            FROM rich_chat_settings s
            ORDER BY s.updated_at DESC
            LIMIT 50
        ''').fetchall()
        
        sessions = []
        for r in rows:
            sessions.append({
                "session_id": r["session_id"],
                "subject_id": r["subject_id"],
                "updated_at": r["updated_at"],
                "title": r["title"] if r["title"] else "নতুন চ্যাট"
            })
        return jsonify({"success": True, "sessions": sessions})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()

@bp.route("/api/rich-chat/history/delete", methods=["POST"])
def rich_chat_delete_session():
    data = request.get_json(force=True) or {}
    session_id = (data.get("session_id") or "").strip()
    if not session_id:
        return jsonify({"success": False, "error": "session_id দরকার"}), 400

    conn = get_db()
    try:
        conn.execute("DELETE FROM conversation_history WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM rich_chat_settings WHERE session_id=?", (session_id,))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()
