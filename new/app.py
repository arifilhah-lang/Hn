"""
╔══════════════════════════════════════════════════════════╗
║          Study AI — Main Flask API                       ║
║   SSC + HSC শিক্ষার্থীদের জন্য AI Study Assistant        ║
╚══════════════════════════════════════════════════════════╝
"""

from flask import Flask, request, jsonify, render_template, Response
from flask_cors import CORS
import os, json, re, hashlib, logging, time, sqlite3, datetime, threading, glob, importlib
from difflib import SequenceMatcher
from google import genai
from google.genai import types
from config import *

# ══════════════════════════════════════════════════════
#  THINKING HELPER — Gemini thinking mode for accuracy
# ══════════════════════════════════════════════════════
def _think_call(client, prompt, system_instruction=None,
                max_tokens=None, cached_content=None, ai_model="zolo_1"):
    """
    Gemini thinking mode call or Nvidia model call.
    Thinking budget চালু থাকলে model নিজে step-by-step reason করে
    তারপর final answer দেয় → MCQ/CQ accuracy অনেক বেড়ে যায়।
    """
    try:
        from features.nvidia_models import is_nvidia_model, generate_nvidia_content
        if is_nvidia_model(ai_model):
            return generate_nvidia_content(
                model_alias=ai_model,
                contents=prompt,
                system_instruction=system_instruction,
                max_tokens=max_tokens or MAX_OUTPUT_LONG,
                temperature=THINKING_TEMPERATURE,
                thinking_mode=True
            )
    except Exception as e:
        log.error(f"Nvidia fallback error: {e}")
    if max_tokens is None:
        max_tokens = MAX_OUTPUT_LONG

    cfg_args = dict(
        max_output_tokens = max_tokens,
        temperature       = THINKING_TEMPERATURE,
        thinking_config   = types.ThinkingConfig(thinking_level=THINKING_LEVEL),
    )
    if system_instruction:
        cfg_args['system_instruction'] = system_instruction

    model_name = "gemini-2.5-flash" if ai_model == "zolo_1_5" else DEFAULT_MODEL

    call_args = dict(
        model   = model_name,
        contents= prompt,
        config  = types.GenerateContentConfig(**cfg_args),
    )
    if cached_content:
        call_args['cached_content'] = cached_content

    return client.models.generate_content(**call_args)


def _parse_json_response(raw_text):
    """JSON response safely parse করো — ```json``` strip সহ।"""
    text = (raw_text or '').strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'\[.*\]', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        m = re.search(r'\[.*?\]', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        m2 = re.search(r'\{.*\}', text, re.DOTALL)
        if m2:
            try:
                return json.loads(m2.group())
            except json.JSONDecodeError:
                pass
        m2 = re.search(r'\{.*?\}', text, re.DOTALL)
        if m2:
            try:
                return json.loads(m2.group())
            except json.JSONDecodeError:
                pass
        return None


# ══════════════════════════════════════════════════════════
#  LOGGING SETUP
# ══════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
#  FLASK APP SETUP
# ══════════════════════════════════════════════════════════
app = Flask(__name__)
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 1536 * 1024 * 1024  # 1.5 GB

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CQ_DIR   = os.path.join(BASE_DIR, "cq_data")
DB_PATH  = os.path.join(BASE_DIR, "study_ai.db")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CQ_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════
#  GEMINI CLIENT POOL — 4 API Key Round-Robin Rotation
# ══════════════════════════════════════════════════════════
_clients = []
_pool_lock = threading.Lock()
_pool_index = 0


def _init_clients():
    """env থেকে সব API key দিয়ে Gemini client pool তৈরি করো"""
    global _clients
    _clients = []
    for i, key in enumerate(GEMINI_API_KEYS):
        if key.strip():
            try:
                c = genai.Client(api_key=key, http_options={'api_version': 'v1beta'})
                _clients.append(c)
                log.info(f"✅ API Key {i+1} সেট: {key[:6]}...")
            except Exception as e:
                log.warning(f"⚠️ API Key {i+1} সমস্যা: {e}")
    log.info(f"✅ মোট {len(_clients)}টি Gemini client রেডি")


def _get_client():
    """পরের client নাও — round-robin"""
    global _pool_index
    if not _clients:
        return None
    with _pool_lock:
        c = _clients[_pool_index % len(_clients)]
        _pool_index += 1
    return c


# Startup-এ client pool তৈরি করো
_init_clients()

# ══════════════════════════════════════════════════════════
#  বাংলা STOPWORDS
# ══════════════════════════════════════════════════════════
BENGALI_STOPWORDS = {
    "এবং", "ও", "এর", "তার", "যে", "এই", "সেই", "কি", "কী", "না",
    "হয়", "করে", "থেকে", "দিয়ে", "নিয়ে", "সাথে", "মধ্যে", "জন্য",
    "পর্যন্ত", "প্রতি", "অথবা", "কিন্তু", "তবে", "যদি", "তাহলে",
    "আর", "বা", "হলে", "করা", "হওয়া", "যায়", "দেওয়া", "নেওয়া",
    "আমি", "তুমি", "সে", "আমরা", "তোমরা", "তারা", "তিনি",
    "একটি", "একটা", "সব", "কিছু", "আছে", "ছিল", "হবে", "হয়েছে",
    "the", "is", "a", "an", "of", "in", "to", "for", "and", "or",
    "on", "at", "by", "it", "be", "as", "do", "has", "had", "was",
    "are", "not", "but", "from", "this", "that", "with", "what",
    "which", "who", "how", "where", "when", "why", "can", "will",
}

# ══════════════════════════════════════════════════════════
#  SQLite DATABASE SETUP
# ══════════════════════════════════════════════════════════
# _response_cache (in-memory) সরানো হয়েছে — শুধু SQLite DB cache (IM-5)


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS pdf_content (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id    TEXT NOT NULL,
                subject_id  TEXT NOT NULL,
                subject_bn  TEXT,
                page        INTEGER DEFAULT 0,
                chapter     TEXT DEFAULT '',
                chapter_num INTEGER,
                content     TEXT NOT NULL,
                content_type TEXT DEFAULT 'text',
                source_type  TEXT DEFAULT 'board_book',
                board_name   TEXT DEFAULT '',
                board_year   TEXT DEFAULT '',
                created_at  TEXT DEFAULT (datetime('now'))
            )""")
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS pdf_content_fts
            USING fts5(content, content_rowid=id, tokenize='unicode61')""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS response_cache (
                hash        TEXT PRIMARY KEY,
                question    TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at  TEXT DEFAULT (datetime('now'))
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS student_progress (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id    TEXT NOT NULL,
                subject_id  TEXT NOT NULL,
                type        TEXT NOT NULL,
                topic       TEXT,
                score       REAL NOT NULL DEFAULT 0,
                total       REAL NOT NULL DEFAULT 10,
                date        TEXT DEFAULT (date('now')),
                created_at  TEXT DEFAULT (datetime('now'))
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS student_routine (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id    TEXT NOT NULL,
                exam_date   TEXT,
                routine_json TEXT NOT NULL,
                created_at  TEXT DEFAULT (datetime('now'))
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS conversation_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                class_id    TEXT NOT NULL,
                subject_id  TEXT NOT NULL,
                role        TEXT NOT NULL,
                message     TEXT NOT NULL,
                created_at  TEXT DEFAULT (datetime('now'))
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_conv_session ON conversation_history(session_id)")

        # ── নতুন table: subject_chapters (Step 3) ─────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS subject_chapters (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id     TEXT NOT NULL,
                subject_id   TEXT NOT NULL,
                chapter_num  INTEGER,
                chapter_title TEXT NOT NULL,
                total_pages  INTEGER DEFAULT 0,
                total_mcq    INTEGER DEFAULT 0,
                total_cq     INTEGER DEFAULT 0,
                created_at   TEXT DEFAULT (datetime('now')),
                UNIQUE(class_id, subject_id, chapter_num)
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_chapters_subj ON subject_chapters(class_id, subject_id)")

        # ── নতুন table: mcq_bank (Step 2) ────────────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS mcq_bank (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id    TEXT NOT NULL,
                subject_id  TEXT NOT NULL,
                chapter     TEXT DEFAULT '',
                chapter_num INTEGER,
                question    TEXT NOT NULL,
                option_a    TEXT NOT NULL,
                option_b    TEXT NOT NULL,
                option_c    TEXT NOT NULL,
                option_d    TEXT NOT NULL,
                answer      TEXT NOT NULL,
                explanation TEXT DEFAULT '',
                difficulty  TEXT DEFAULT 'medium',
                source_type TEXT DEFAULT 'board_book',
                board_name  TEXT DEFAULT '',
                board_year  TEXT DEFAULT '',
                times_shown INTEGER DEFAULT 0,
                times_correct INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now'))
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_mcqbank_subj ON mcq_bank(class_id, subject_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_mcqbank_ch ON mcq_bank(class_id, subject_id, chapter_num)")

        # ── নতুন table: chapter_summaries (Step 5) ──────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS chapter_summaries (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id     TEXT NOT NULL,
                subject_id   TEXT NOT NULL,
                chapter      TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                created_at   TEXT DEFAULT (datetime('now')),
                UNIQUE(class_id, subject_id, chapter)
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_summary_subj ON chapter_summaries(class_id, subject_id)")

        # ── নতুন table: training_feedback (Step 13) ─────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS training_feedback (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id         TEXT,
                subject_id       TEXT,
                input_text       TEXT NOT NULL,
                output_text      TEXT NOT NULL,
                feedback         TEXT DEFAULT 'neutral',
                score            REAL,
                source           TEXT,
                used_in_training INTEGER DEFAULT 0,
                created_at       TEXT DEFAULT (datetime('now'))
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_feedback_class ON training_feedback(class_id, subject_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_feedback_source ON training_feedback(source)")

        # ── নতুন table: cq_model_answers (IM-3) ────────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS cq_model_answers (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id     TEXT NOT NULL,
                subject_id   TEXT NOT NULL,
                chapter      TEXT DEFAULT '',
                chapter_num  INTEGER,
                stimulus     TEXT,
                question_ka  TEXT,
                question_kha TEXT,
                question_ga  TEXT,
                question_gha TEXT,
                answer_ka    TEXT,
                answer_kha   TEXT,
                answer_ga    TEXT,
                answer_gha   TEXT,
                source_type  TEXT DEFAULT 'guide',
                board_name   TEXT DEFAULT '',
                board_year   TEXT DEFAULT '',
                created_at   TEXT DEFAULT (datetime('now'))
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_cq_model_subj ON cq_model_answers(class_id, subject_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_cq_model_ch ON cq_model_answers(class_id, subject_id, chapter_num)")

        # ── নতুন table: mcq_review_schedule (S-2) ────────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS mcq_review_schedule (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id        TEXT NOT NULL,
                subject_id      TEXT NOT NULL,
                mcq_id          INTEGER NOT NULL,
                next_review     TEXT NOT NULL,
                interval_days   INTEGER DEFAULT 1,
                ease_factor     REAL DEFAULT 2.5,
                repetitions     INTEGER DEFAULT 0,
                last_reviewed   TEXT,
                created_at      TEXT DEFAULT (datetime('now')),
                FOREIGN KEY(mcq_id) REFERENCES mcq_bank(id)
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_mcq_review_subj ON mcq_review_schedule(class_id, subject_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_mcq_review_next ON mcq_review_schedule(next_review)")

        # ── নতুন table: flashcards (S-3) ────────────────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS flashcards (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id        TEXT NOT NULL,
                subject_id      TEXT NOT NULL,
                chapter         TEXT DEFAULT '',
                chapter_num     INTEGER,
                question        TEXT NOT NULL,
                answer          TEXT NOT NULL,
                source_type     TEXT DEFAULT 'board_book',
                difficulty      TEXT DEFAULT 'medium',
                created_at      TEXT DEFAULT (datetime('now'))
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_flashcards_subj ON flashcards(class_id, subject_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_flashcards_ch ON flashcards(class_id, subject_id, chapter_num)")

        # পুরনো DB এ নতুন column না থাকলে যোগ করো
        for col, definition in [
            ("chapter",      "TEXT DEFAULT ''"),
            ("chapter_num",  "INTEGER"),
            ("content_type", "TEXT DEFAULT 'text'"),
            ("source_type",  "TEXT DEFAULT 'board_book'"),
            ("board_name",   "TEXT DEFAULT ''"),
            ("board_year",   "TEXT DEFAULT ''"),
        ]:
            try:
                c.execute(f"ALTER TABLE pdf_content ADD COLUMN {col} {definition}")
            except Exception:
                pass  # already exists

        # mcq_bank এ cross-board pattern tracking columns যোগ করো
        for col, definition in [
            ("frequency_score",   "INTEGER DEFAULT 1"),
            ("appeared_boards",   "TEXT DEFAULT '[]'"),   # JSON array
            ("appeared_years",    "TEXT DEFAULT '[]'"),   # JSON array
            ("cross_board_score", "INTEGER DEFAULT 1"),   # কতগুলো আলাদা board এ এসেছে
            ("last_appeared_year","INTEGER DEFAULT 0"),
            ("canonical_id",      "INTEGER DEFAULT 0"),   # 0 = নিজেই canonical
            ("is_canonical",      "INTEGER DEFAULT 1"),   # 0 = duplicate
        ]:
            try:
                c.execute(f"ALTER TABLE mcq_bank ADD COLUMN {col} {definition}")
            except Exception:
                pass  # already exists
        conn.commit()
        log.info("✅ SQLite ডাটাবেজ রেডি: %s", DB_PATH)
    except Exception as e:
        log.error("❌ SQLite init ত্রুটি: %s", e)
    finally:
        conn.close()


def _db_find_cache(question_key):
    h = hashlib.md5(question_key.encode('utf-8')).hexdigest()
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT result_json FROM response_cache WHERE hash=?", (h,)
        ).fetchone()
        conn.close()
        if row:
            return json.loads(row["result_json"])
    except Exception as e:
        log.warning("DB cache read error: %s", e)
    return None


def _db_save_cache(question_key, result):
    h = hashlib.md5(question_key.encode('utf-8')).hexdigest()
    try:
        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO response_cache (hash, question, result_json) VALUES (?,?,?)",
            (h, question_key, json.dumps(result, ensure_ascii=False))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("DB cache write error: %s", e)


def _count_db_cache():
    """response_cache table এর row count — stats endpoint এ ব্যবহার।"""
    try:
        conn = get_db()
        n = conn.execute("SELECT COUNT(*) FROM response_cache").fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


def _conv_save(session_id, class_id, subject_id, role, message):
    """conversation history তে একটা message সেভ করো"""
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO conversation_history (session_id, class_id, subject_id, role, message) VALUES (?,?,?,?,?)",
            (session_id, class_id, subject_id, role, message)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("Conversation save error: %s", e)


def _conv_load(session_id, limit=10):
    """একটা session এর শেষ N টা message লোড করো"""
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT role, message FROM conversation_history WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit)
        ).fetchall()
        conn.close()
        # Reverse করো (newest last)
        return [{"role": r["role"], "parts": [r["message"]]} for r in reversed(rows)]
    except Exception as e:
        log.warning("Conversation load error: %s", e)
        return []


def _conv_clear(session_id):
    """একটা session এর history মুছো"""
    try:
        conn = get_db()
        conn.execute("DELETE FROM conversation_history WHERE session_id=?", (session_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("Conversation clear error: %s", e)


def _save_feedback(class_id, subject_id, input_text, output_text,
                   feedback="neutral", score=None, source="manual"):
    """
    training_feedback table এ একটা entry সেভ করো।
    feedback: 'positive' | 'negative' | 'neutral'
    source:   'mcq_result' | 'cq_eval' | 'thumb_up' | 'thumb_down'

    ✅ Negative feedback হলে DB cache থেকে ঐ answer invalidate করা হয় —
    so that পরের বার নতুন করে Gemini call হয়।
    """
    try:
        conn = get_db()
        conn.execute(
            """INSERT INTO training_feedback
               (class_id, subject_id, input_text, output_text, feedback, score, source)
               VALUES (?,?,?,?,?,?,?)""",
            (class_id, subject_id,
             input_text[:2000],   # context টা বড় হলে trim করো
             output_text[:2000],
             feedback, score, source)
        )
        conn.commit()
        conn.close()

        # ✅ Cache invalidation on negative feedback
        if feedback == "negative" and input_text:
            _invalidate_cache_for_question(input_text)

    except Exception as e:
        log.warning("Feedback save error: %s", e)


def _invalidate_cache_for_question(question_key: str):
    """
    Negative feedback পেলে DB cache থেকে সংশ্লিষ্ট response_cache row delete করো।
    পরের request এ নতুন করে Gemini call হবে।
    """
    try:
        h = hashlib.md5(question_key.encode('utf-8')).hexdigest()
        conn = get_db()
        conn.execute("DELETE FROM response_cache WHERE hash=?", (h,))
        conn.commit()
        conn.close()
        log.info(f"🗑️ Cache invalidated for hash={h[:8]}...")
    except Exception as e:
        log.warning(f"Cache invalidate error: {e}")


def _db_search_fts(class_id, subject_id, query, top_n=3, content_type=None,
                   chapter=None, chapter_num=None, source_type=None,
                   board_name=None, board_year=None):
    """
    FTS5 search with multiple filters.
    ✅ Added: chapter_num integer filter — exact chapter match।
    ✅ Added: board_name/board_year filter — board & year specific search।
    """
    try:
        fts_query = " OR ".join(
            re.findall(r'[\u0980-\u09FF]+|[a-zA-Z]{3,}', query)
        )
        if not fts_query:
            return []
        conn = get_db()

        # Dynamic WHERE clause
        filters = ["pdf_content_fts MATCH ?", "pc.class_id = ?", "pc.subject_id = ?"]
        params  = [fts_query, class_id, subject_id]

        if content_type:
            filters.append("pc.content_type = ?")
            params.append(content_type)

        # chapter string match + chapter_num integer match — দুটোই support
        if chapter:
            filters.append("pc.chapter = ?")
            params.append(chapter)
        if chapter_num is not None:
            filters.append("pc.chapter_num = ?")
            params.append(int(chapter_num))

        # source_type: string বা list
        if source_type and source_type != "all":
            if isinstance(source_type, list):
                placeholders = ",".join("?" * len(source_type))
                filters.append(f"pc.source_type IN ({placeholders})")
                params.extend(source_type)
            else:
                filters.append("pc.source_type = ?")
                params.append(source_type)

        # board_name / board_year filter
        if board_name:
            filters.append("pc.board_name = ?")
            params.append(board_name)
        if board_year:
            filters.append("pc.board_year = ?")
            params.append(board_year)

        params.append(top_n)

        sql = f"""
            SELECT pc.content, pc.page, pc.chapter, pc.chapter_num,
                   pc.content_type, pc.source_type, pc.board_name, pc.board_year,
                   bm25(pdf_content_fts) AS rank
            FROM pdf_content_fts
            JOIN pdf_content pc ON pc.id = pdf_content_fts.rowid
            WHERE {" AND ".join(filters)}
            ORDER BY rank
            LIMIT ?
        """
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [{
            "text":         r["content"],
            "page":         r["page"],
            "chapter":      r["chapter"],
            "chapter_num":  r["chapter_num"],
            "content_type": r["content_type"],
            "source_type":  r["source_type"],
            "board_name":   r["board_name"],
            "board_year":   r["board_year"],
            "score":        abs(r["rank"]),
            "source":       f"{class_id}_{subject_id}.db"
        } for r in rows]
    except Exception as e:
        log.warning("FTS5 search error: %s", e)
        return []


# ══════════════════════════════════════════════════════════
#  DB CONTEXT MANAGER — connection leak proof  (IM-6)
# ══════════════════════════════════════════════════════════
from contextlib import contextmanager

@contextmanager
def _db_conn():
    """Connection leak ছাড়া DB access — সব নতুন code এটা use করবে।"""
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
#  CHUNK PARSER — IM-1  (page → typed chunks)
# ══════════════════════════════════════════════════════════

def _split_text_into_paragraphs(text):
    """বড় text block কে paragraph এ ভাগ করো।"""
    results = []
    lines   = text.split('\n')
    buffer  = []

    def flush():
        combined = '\n'.join(buffer).strip()
        if combined and len(combined) > 10:
            results.append({"content": combined, "content_type": "text"})
        buffer.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if buffer:
                flush()
            continue

        if stripped.startswith('[DEFINITION:'):
            flush()
            results.append({"content": stripped, "content_type": "definition"})
        elif stripped.startswith('[FORMULA:') or stripped.startswith('[EQUATION:'):
            flush()
            results.append({"content": stripped, "content_type": "formula"})
        elif stripped.startswith('[CHAPTER:'):
            pass  # chapter info already in metadata
        else:
            buffer.append(stripped)
            # 600 char এ পৌঁছালে flush
            if sum(len(l) for l in buffer) > 600:
                flush()

    flush()
    return results


def _parse_page_into_chunks(text, page, chapter, chapter_num, source_type):
    """
    একটা page content → list of typed chunk dicts.
    প্রতিটা chunk: {content, content_type, page, chapter, chapter_num, source_type, board_name, board_year}
    """
    if not text or text.strip() in ("[EMPTY_PAGE]", ""):
        return []

    board_name, board_year = "", ""
    m = re.search(r'\[SOURCE:[^\]]*board=([^,\]]+)', text)
    if m:
        board_name = m.group(1).strip()
    m = re.search(r'\[SOURCE:[^\]]*year=([^,\]]+)', text)
    if m:
        board_year = m.group(1).strip()

    mcq_blocks  = re.findall(r'\[MCQ\](.*?)\[/MCQ\]',         text, re.DOTALL)
    cq_blocks   = re.findall(r'\[CQ\](.*?)\[/CQ\]',           text, re.DOTALL)
    saq_blocks  = re.findall(r'\[SAQ\](.*?)\[/SAQ\]',         text, re.DOTALL)
    ex_blocks   = re.findall(r'\[EXERCISE\](.*?)\[/EXERCISE\]',text, re.DOTALL)

    remaining = text
    for pat in [r'\[MCQ\].*?\[/MCQ\]', r'\[CQ\].*?\[/CQ\]',
                r'\[SAQ\].*?\[/SAQ\]', r'\[EXERCISE\].*?\[/EXERCISE\]',
                r'\[SOURCE:[^\]]*\]',  r'\[EMPTY_PAGE\]']:
        remaining = re.sub(pat, '', remaining, flags=re.DOTALL)

    base = {"page": page, "chapter": chapter or "",
            "chapter_num": chapter_num, "source_type": source_type,
            "board_name": board_name, "board_year": board_year}

    chunks = []
    for b in mcq_blocks:
        b = b.strip()
        if b:
            chunks.append({**base, "content": b, "content_type": "mcq"})
    for b in cq_blocks:
        b = b.strip()
        if b:
            chunks.append({**base, "content": b, "content_type": "cq"})
    for b in saq_blocks:
        b = b.strip()
        if b:
            chunks.append({**base, "content": b, "content_type": "saq"})
    for b in ex_blocks:
        b = b.strip()
        if b:
            chunks.append({**base, "content": b, "content_type": "exercise"})
    for seg in _split_text_into_paragraphs(remaining):
        if seg["content"]:
            chunks.append({**base, **seg})

    return chunks


# ══════════════════════════════════════════════════════════
#  MCQ PARSER — IM-2  (MCQ chunk → mcq_bank row)
# ══════════════════════════════════════════════════════════

def _parse_mcq_for_bank(block, class_id, subject_id, chapter, chapter_num,
                         source_type, board_name, board_year):
    """
    [MCQ] block text → mcq_bank এ insert করার জন্য dict।
    Parse না হলে None।
    """
    q = re.search(r'প্রশ্ন:\s*(.+?)(?=\n\(ক\)|\n\(খ\)|$)', block, re.DOTALL)
    if not q:
        return None
    question = q.group(1).strip()

    ka  = re.search(r'\(ক\)\s*(.+?)(?=\(খ\)|উত্তর:|কঠিনতা:|$)', block, re.DOTALL)
    kha = re.search(r'\(খ\)\s*(.+?)(?=\(গ\)|উত্তর:|কঠিনতা:|$)', block, re.DOTALL)
    ga  = re.search(r'\(গ\)\s*(.+?)(?=\(ঘ\)|উত্তর:|কঠিনতা:|$)', block, re.DOTALL)
    gha = re.search(r'\(ঘ\)\s*(.+?)(?=উত্তর:|কঠিনতা:|$)',        block, re.DOTALL)

    option_a = ka.group(1).strip()  if ka  else ""
    option_b = kha.group(1).strip() if kha else ""
    option_c = ga.group(1).strip()  if ga  else ""
    option_d = gha.group(1).strip() if gha else ""

    if not all([option_a, option_b, option_c, option_d]):
        return None   # ৪টা option না থাকলে skip

    ans  = re.search(r'উত্তর:\s*\(([কখগঘ])\)', block)
    diff = re.search(r'কঠিনতা:\s*(easy|medium|hard)', block)
    exp  = re.search(r'ব্যাখ্যা:\s*(.+?)(?:\n\n|$)', block, re.DOTALL)

    return {
        "class_id":    class_id,
        "subject_id":  subject_id,
        "chapter":     chapter or "",
        "chapter_num": chapter_num,
        "question":    question,
        "option_a":    option_a,
        "option_b":    option_b,
        "option_c":    option_c,
        "option_d":    option_d,
        "answer":      ans.group(1)  if ans  else "N/A",
        "difficulty":  diff.group(1) if diff else "medium",
        "explanation": exp.group(1).strip() if exp else "",
        "source_type": source_type,
        "board_name":  board_name or "",
        "board_year":  board_year or "",
    }


# ══════════════════════════════════════════════════════════
#  CQ PARSER — guide CQ block → cq_model_answers row
# ══════════════════════════════════════════════════════════

def _parse_cq_for_model_answers(block, class_id, subject_id, chapter, chapter_num,
                                 source_type, board_name, board_year):
    """
    [CQ]...[/CQ] block → cq_model_answers এ insert করার dict।
    guide বই থেকে extract হলে model answer সহ থাকে।
    Parse না হলে None।
    """
    # উদ্দীপক
    stim = re.search(r'উদ্দীপক[:\s]*(.+?)(?=\(ক\)|\n\n|প্রশ্ন:|$)', block, re.DOTALL)
    stimulus = stim.group(1).strip() if stim else ""

    # প্রশ্ন (ক), (খ), (গ), (ঘ)
    ka  = re.search(r'\(ক\)[^\n]*প্রশ্ন[:\s]*(.+?)(?=\(খ\)|\(ক\).*উত্তর|উত্তর.*ক|$)', block, re.DOTALL)
    kha = re.search(r'\(খ\)[^\n]*প্রশ্ন[:\s]*(.+?)(?=\(গ\)|\(খ\).*উত্তর|উত্তর.*খ|$)', block, re.DOTALL)
    ga  = re.search(r'\(গ\)[^\n]*প্রশ্ন[:\s]*(.+?)(?=\(ঘ\)|\(গ\).*উত্তর|উত্তর.*গ|$)', block, re.DOTALL)
    gha = re.search(r'\(ঘ\)[^\n]*প্রশ্ন[:\s]*(.+?)(?=উত্তর|$)', block, re.DOTALL)

    q_ka  = ka.group(1).strip()  if ka  else ""
    q_kha = kha.group(1).strip() if kha else ""
    q_ga  = ga.group(1).strip()  if ga  else ""
    q_gha = gha.group(1).strip() if gha else ""

    # কমপক্ষে উদ্দীপক বা একটা প্রশ্ন থাকতে হবে
    if not stimulus and not any([q_ka, q_kha, q_ga, q_gha]):
        return None

    # মডেল উত্তর (guide এ থাকে)
    a_ka  = re.search(r'উত্তর.*?\(ক\)[:\s]*(.+?)(?=উত্তর.*?\(খ\)|$)', block, re.DOTALL)
    a_kha = re.search(r'উত্তর.*?\(খ\)[:\s]*(.+?)(?=উত্তর.*?\(গ\)|$)', block, re.DOTALL)
    a_ga  = re.search(r'উত্তর.*?\(গ\)[:\s]*(.+?)(?=উত্তর.*?\(ঘ\)|$)', block, re.DOTALL)
    a_gha = re.search(r'উত্তর.*?\(ঘ\)[:\s]*(.+?)$', block, re.DOTALL)

    return {
        "class_id":    class_id,
        "subject_id":  subject_id,
        "chapter":     chapter or "",
        "chapter_num": chapter_num,
        "stimulus":    stimulus,
        "question_ka":  q_ka,
        "question_kha": q_kha,
        "question_ga":  q_ga,
        "question_gha": q_gha,
        "answer_ka":   a_ka.group(1).strip()  if a_ka  else "",
        "answer_kha":  a_kha.group(1).strip() if a_kha else "",
        "answer_ga":   a_ga.group(1).strip()  if a_ga  else "",
        "answer_gha":  a_gha.group(1).strip() if a_gha else "",
        "source_type": source_type,
        "board_name":  board_name or "",
        "board_year":  board_year or "",
    }

def _is_prechunked_format(items):
    """
    TRUE pre-chunked format detect: items already parsed fields আছে
    (question/stimulus/answer_ka) — re-parse ছাড়াই directly insert করা যায়।
    """
    if not items or not isinstance(items, list):
        return False

    # প্রথম item না, প্রথম কয়েকটা (max 5) sample দেখো —
    # যদি batch এর শুরুতে plain text chunk আর পরে structured MCQ/CQ থাকে।
    samples = items[:5]
    return any(
        isinstance(sample, dict) and any(
            field in sample for field in
            ("question", "stimulus", "options", "answer_ka", "q_ka")
        )
        for sample in samples
    )


def _get_import_progress_filepath(filepath, class_id, subject_id, source_type):
    """Resume file location — JSON এ save হয় last_index।"""
    base = os.path.basename(filepath).replace(".json", "")
    return os.path.join(
        DATA_DIR,
        f".import_progress_{class_id}_{subject_id}_{source_type}_{base}.json"
    )


def _save_import_progress(progress_path, last_index, items_done, session_id):
    """Disk এ progress save করো — interrupted হলে resume এ লাগবে।"""
    try:
        with open(progress_path, "w", encoding="utf-8") as f:
            json.dump({
                "last_index":     last_index,
                "items_done":     items_done,
                "session_id":     session_id,
                "updated_at":     datetime.datetime.now().isoformat(),
                "status":         "in_progress"
            }, f, ensure_ascii=False)
    except Exception as e:
        log.warning(f"Progress save failed: {e}")


def _load_import_progress(progress_path):
    """আগের interrupted progress load করো — None if no progress।"""
    if not os.path.exists(progress_path):
        return None
    try:
        with open(progress_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("status") == "completed":
            return None  # Already done — start fresh
        return data
    except Exception:
        return None


def _clear_import_progress(progress_path):
    """শেষ হলে progress file delete করো।"""
    try:
        if os.path.exists(progress_path):
            os.remove(progress_path)
    except Exception:
        pass


def _import_precunked_item(item, class_id, subject_id, subject_bn, source_type, conn):
    """
    TRUE pre-chunked item (already parsed Q/A fields সহ) কে সরাসরি DB তে insert।
    অন্যথায় legacy parser-এর উপর rely করে।
    """
    content_type = item.get("content_type") or item.get("type") or "text"
    content      = item.get("content") or item.get("text") or ""
    page         = item.get("page", 0)
    chapter      = item.get("chapter", "") or ""
    chapter_num  = item.get("chapter_num")
    item_src     = item.get("source_type", source_type)
    item_board   = item.get("board_name", "") or ""
    item_year    = item.get("board_year", "") or ""

    # Question/Answer fields (direct from item if already extracted)
    question     = item.get("question", "")
    options      = item.get("options", [])
    answer       = item.get("answer", "")
    explanation  = item.get("explanation", "")
    stimulus     = item.get("stimulus", "")
    q_ka         = item.get("question_ka", "")
    q_kha        = item.get("question_kha", "")
    q_ga         = item.get("question_ga", "")
    q_gha        = item.get("question_gha", "")
    a_ka         = item.get("answer_ka", "")
    a_kha        = item.get("answer_kha", "")
    a_ga         = item.get("answer_ga", "")
    a_gha        = item.get("answer_gha", "")

    if not content or not str(content).strip():
        return 0

    try:
        cur = conn.execute(
            """INSERT INTO pdf_content
               (class_id, subject_id, subject_bn, page, chapter, chapter_num,
                content, content_type, source_type, board_name, board_year)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (class_id, subject_id, subject_bn, page, chapter, chapter_num,
             content, content_type, item_src, item_board, item_year)
        )
        conn.execute(
            "INSERT INTO pdf_content_fts(rowid, content) VALUES (?,?)",
            (cur.lastrowid, content)
        )

        rows_affected = 1

        # MCQ items → mcq_bank table
        if content_type == "mcq":
            if question:  # তাহলে পুরোপুরি parsed আছে
                options_a = options[0] if len(options) > 0 else ""
                options_b = options[1] if len(options) > 1 else ""
                options_c = options[2] if len(options) > 2 else ""
                options_d = options[3] if len(options) > 3 else ""
                exists = conn.execute(
                    "SELECT 1 FROM mcq_bank WHERE class_id=? AND subject_id=? AND question=?",
                    (class_id, subject_id, question)
                ).fetchone()
                if not exists:
                    conn.execute(
                        """INSERT INTO mcq_bank
                           (class_id, subject_id, chapter, chapter_num,
                            question, option_a, option_b, option_c, option_d,
                            answer, explanation, difficulty,
                            source_type, board_name, board_year, last_appeared_year)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (class_id, subject_id, chapter, chapter_num,
                         question, options_a, options_b, options_c, options_d,
                         answer or "N/A", explanation, "medium",
                         item_src, item_board, item_year, _year_int(item_year))
                    )
            else:
                # question field নেই — content থেকে legacy parser দিয়ে extract করো
                mcq_row = _parse_mcq_for_bank(
                    content, class_id, subject_id,
                    chapter, chapter_num, item_src, item_board, item_year
                )
                if mcq_row:
                    exists = conn.execute(
                        "SELECT 1 FROM mcq_bank WHERE class_id=? AND subject_id=? AND question=?",
                        (class_id, subject_id, mcq_row["question"])
                    ).fetchone()
                    if not exists:
                        conn.execute(
                            """INSERT INTO mcq_bank
                               (class_id, subject_id, chapter, chapter_num,
                                question, option_a, option_b, option_c, option_d,
                                answer, explanation, difficulty,
                                source_type, board_name, board_year, last_appeared_year)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (mcq_row["class_id"], mcq_row["subject_id"],
                             mcq_row["chapter"], mcq_row["chapter_num"],
                             mcq_row["question"], mcq_row["option_a"],
                             mcq_row["option_b"], mcq_row["option_c"],
                             mcq_row["option_d"], mcq_row["answer"],
                             mcq_row["explanation"], mcq_row["difficulty"],
                             mcq_row["source_type"], mcq_row["board_name"],
                             mcq_row["board_year"], _year_int(mcq_row["board_year"]))
                        )

        # CQ items → cq_model_answers table
        elif content_type == "cq":
            if stimulus or a_ka:  # পুরোপুরি parsed আছে
                exists = conn.execute(
                    "SELECT 1 FROM cq_model_answers WHERE class_id=? AND subject_id=? AND stimulus=?",
                    (class_id, subject_id, (stimulus or "")[:200])
                ).fetchone()
                if not exists and stimulus:
                    conn.execute(
                        """INSERT INTO cq_model_answers
                           (class_id, subject_id, chapter, chapter_num,
                            stimulus, question_ka, question_kha, question_ga, question_gha,
                            answer_ka, answer_kha, answer_ga, answer_gha,
                            source_type, board_name, board_year)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (class_id, subject_id, chapter, chapter_num,
                         stimulus[:500], q_ka, q_kha, q_ga, q_gha,
                         a_ka, a_kha, a_ga, a_gha,
                         item_src, item_board, item_year)
                    )
            else:
                # stimulus field নেই — content এর [CQ] block থেকে legacy parser দিয়ে parse
                cq_row = _parse_cq_for_model_answers(
                    content, class_id, subject_id,
                    chapter, chapter_num, item_src, item_board, item_year
                )
                if cq_row and cq_row["stimulus"]:
                    exists = conn.execute(
                        "SELECT 1 FROM cq_model_answers WHERE class_id=? AND subject_id=? AND stimulus=?",
                        (class_id, subject_id, cq_row["stimulus"][:200])
                    ).fetchone()
                    if not exists:
                        conn.execute(
                            """INSERT INTO cq_model_answers
                               (class_id, subject_id, chapter, chapter_num,
                                stimulus, question_ka, question_kha, question_ga, question_gha,
                                answer_ka, answer_kha, answer_ga, answer_gha,
                                source_type, board_name, board_year)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (cq_row["class_id"], cq_row["subject_id"],
                             cq_row["chapter"], cq_row["chapter_num"],
                             cq_row["stimulus"][:500],
                             cq_row["question_ka"], cq_row["question_kha"],
                             cq_row["question_ga"], cq_row["question_gha"],
                             cq_row["answer_ka"], cq_row["answer_kha"],
                             cq_row["answer_ga"], cq_row["answer_gha"],
                             cq_row["source_type"], cq_row["board_name"],
                             cq_row["board_year"])
                        )

        return rows_affected
    except Exception as e:
        log.warning(f"Prechunked insert error: {e}")
        return 0


def _year_int(y):
    """board_year string → int। Invalid/empty হলে 0।"""
    s = str(y or "").strip()
    return int(s) if s.isdigit() and len(s) == 4 else 0


def _db_import_json_to_fts(class_id, subject_id, force=False, on_progress=None, specific_files=None):
    """
    JSON → DB import with RESUME support।

    ✅ Pre-chunked JSON detect করলে re-parse ছাড়া directly insert করে
       (এটা user এর 960-item guide.json এর মতো case এ অনেক fast)।
    ✅ Interrupted হলে `.import_progress_*.json` file থেকে resume হয়।
    ✅ প্রতি 100 items এ disk-এ progress save হয়।
    ✅ on_progress callback দিয়ে real-time % জানানো যায় (UI এর জন্য)।

    Returns: dict with {total_inserted, items_done, was_resumed, files: [...]}
    """
    # Bug3 fix: specific_files দিলে শুধু ওটাই import করো (upload-and-import flow)
    if specific_files is not None:
        all_files = specific_files
    else:
        from config import find_all_data_files
        all_files = find_all_data_files(class_id, subject_id, DATA_DIR)

        if not all_files:
            legacy = find_data_file(class_id, subject_id, DATA_DIR)
            if legacy:
                all_files = [("board_book", legacy)]

    if not all_files:
        return {"total_inserted": 0, "files": [], "was_resumed": False}

    subj_info  = get_subject_info(class_id, subject_id)
    subject_bn = subj_info.get("bn", subject_id) if subj_info else subject_id

    grand_total    = 0
    grand_mcq      = 0
    grand_cq       = 0
    file_results   = []
    was_resumed    = False

    for source_type, filepath in all_files:
        progress_path = _get_import_progress_filepath(filepath, class_id, subject_id, source_type)
        session_id    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        try:
            with _db_conn() as conn:
                # ইতিমধ্যে import আছে কিনা check (except when force=True)
                if not force:
                    already = conn.execute(
                        "SELECT COUNT(*) FROM pdf_content WHERE class_id=? AND subject_id=? AND source_type=?",
                        (class_id, subject_id, source_type)
                    ).fetchone()[0]
                    if already > 0:
                        log.info(f"⏭️ {source_type}/{class_id}/{subject_id} ইতিমধ্যে imported ({already} chunks)")
                        file_results.append({
                            "source_type": source_type,
                            "filepath":    filepath,
                            "inserted":    0,
                            "skipped":     True,
                            "already":     already
                        })
                        grand_total += already
                        continue

                # Force mode হলে আগের data মুছে দাও
                if force:
                    log.info(f"🗑️ Force mode: clearing old data for {source_type}/{class_id}/{subject_id}")
                    old_ids = conn.execute(
                        "SELECT id FROM pdf_content WHERE class_id=? AND subject_id=? AND source_type=?",
                        (class_id, subject_id, source_type)
                    ).fetchall()
                    for r in old_ids:
                        try:
                            conn.execute("DELETE FROM pdf_content_fts WHERE rowid=?", (r["id"],))
                        except Exception:
                            pass
                    conn.execute(
                        "DELETE FROM pdf_content WHERE class_id=? AND subject_id=? AND source_type=?",
                        (class_id, subject_id, source_type)
                    )
                    conn.execute(
                        "DELETE FROM mcq_bank WHERE class_id=? AND subject_id=? AND source_type=?",
                        (class_id, subject_id, source_type)
                    )
                    conn.execute(
                        "DELETE FROM cq_model_answers WHERE class_id=? AND subject_id=? AND source_type=?",
                        (class_id, subject_id, source_type)
                    )
                    conn.commit()
                    _clear_import_progress(progress_path)

                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Pre-chunked detect: items আগে থেকেই class_id+content_type সহ
                if _is_prechunked_format(data):
                    log.info(f"⚡ Pre-chunked JSON detected: {filepath}")
                    items = data
                else:
                    # legacy raw page format → _parse_page_into_chunks() দিয়ে chunk করো
                    items = data if isinstance(data, list) else data.get("pages", data.get("content", [data]))
                    if isinstance(items, dict):
                        items = [items]

                total_items = len(items)

                # ── Resume check ───────────────────────────────────
                start_index = 0
                progress = _load_import_progress(progress_path)
                if progress and not force:
                    saved_index = progress.get("last_index", 0)
                    if saved_index < total_items:
                        start_index = saved_index
                        was_resumed = True
                        log.info(f"♻️ Resuming from index {start_index}/{total_items} (interrupted earlier)")

                # ── Import loop ────────────────────────────────────
                inserted   = 0
                mcq_insert = 0
                cq_insert  = 0
                last_save  = 0

                if on_progress:
                    try:
                        on_progress(0, total_items, source_type, "started")
                    except Exception:
                        pass

                for i in range(start_index, total_items):
                    item = items[i]

                    # Pre-chunked case: items[i] already has class_id, content_type
                    if _is_prechunked_format([item]):
                        ok = _import_precunked_item(
                            item, class_id, subject_id, subject_bn,
                            source_type, conn
                        )
                        if ok:
                            inserted += 1
                            ct = item.get("content_type", "text")
                            if ct == "mcq" and item.get("question"):
                                mcq_insert += 1
                            elif ct == "cq":
                                cq_insert += 1
                    else:
                        # Legacy raw page
                        if isinstance(item, dict):
                            raw_text    = item.get("text", item.get("content", ""))
                            page        = item.get("page", i)
                            chapter     = item.get("chapter", "") or ""
                            chapter_num = item.get("chapter_num")
                            src         = item.get("source_type", source_type)
                        else:
                            raw_text    = str(item)
                            page        = i
                            chapter     = ""
                            chapter_num = None
                            src         = source_type

                        if not raw_text or not raw_text.strip():
                            continue

                        chunks = _parse_page_into_chunks(raw_text, page, chapter, chapter_num, src)

                        for chunk in chunks:
                            content = chunk["content"]
                            if not content:
                                continue

                            cur = conn.execute(
                                """INSERT INTO pdf_content
                                   (class_id, subject_id, subject_bn, page, chapter, chapter_num,
                                    content, content_type, source_type, board_name, board_year)
                                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                                (class_id, subject_id, subject_bn,
                                 chunk["page"], chunk["chapter"], chunk["chapter_num"],
                                 content, chunk["content_type"], chunk["source_type"],
                                 chunk["board_name"], chunk["board_year"])
                            )
                            conn.execute(
                                "INSERT INTO pdf_content_fts(rowid, content) VALUES (?,?)",
                                (cur.lastrowid, content)
                            )
                            inserted += 1

                            if chunk["content_type"] == "mcq":
                                mcq_row = _parse_mcq_for_bank(
                                    content, class_id, subject_id,
                                    chunk["chapter"], chunk["chapter_num"],
                                    chunk["source_type"], chunk["board_name"], chunk["board_year"]
                                )
                                if mcq_row:
                                    exists = conn.execute(
                                        "SELECT 1 FROM mcq_bank WHERE class_id=? AND subject_id=? AND question=?",
                                        (class_id, subject_id, mcq_row["question"])
                                    ).fetchone()
                                    if not exists:
                                        conn.execute(
                                            """INSERT INTO mcq_bank
                                               (class_id, subject_id, chapter, chapter_num,
                                                question, option_a, option_b, option_c, option_d,
                                                answer, explanation, difficulty,
                                                source_type, board_name, board_year, last_appeared_year)
                                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                            (mcq_row["class_id"], mcq_row["subject_id"],
                                             mcq_row["chapter"], mcq_row["chapter_num"],
                                             mcq_row["question"], mcq_row["option_a"],
                                             mcq_row["option_b"], mcq_row["option_c"],
                                             mcq_row["option_d"], mcq_row["answer"],
                                             mcq_row["explanation"], mcq_row["difficulty"],
                                             mcq_row["source_type"], mcq_row["board_name"],
                                             mcq_row["board_year"], _year_int(mcq_row["board_year"]))
                                        )
                                        mcq_insert += 1

                            elif chunk["content_type"] == "cq":
                                cq_row = _parse_cq_for_model_answers(
                                    content, class_id, subject_id,
                                    chunk["chapter"], chunk["chapter_num"],
                                    chunk["source_type"], chunk["board_name"], chunk["board_year"]
                                )
                                if cq_row and cq_row["stimulus"]:
                                    exists = conn.execute(
                                        "SELECT 1 FROM cq_model_answers WHERE class_id=? AND subject_id=? AND stimulus=?",
                                        (class_id, subject_id, cq_row["stimulus"][:200])
                                    ).fetchone()
                                    if not exists:
                                        conn.execute(
                                            """INSERT INTO cq_model_answers
                                               (class_id, subject_id, chapter, chapter_num,
                                                stimulus, question_ka, question_kha, question_ga, question_gha,
                                                answer_ka, answer_kha, answer_ga, answer_gha,
                                                source_type, board_name, board_year)
                                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                            (cq_row["class_id"], cq_row["subject_id"],
                                             cq_row["chapter"], cq_row["chapter_num"],
                                             cq_row["stimulus"][:500],
                                             cq_row["question_ka"], cq_row["question_kha"],
                                             cq_row["question_ga"], cq_row["question_gha"],
                                             cq_row["answer_ka"], cq_row["answer_kha"],
                                             cq_row["answer_ga"], cq_row["answer_gha"],
                                             cq_row["source_type"], cq_row["board_name"],
                                             cq_row["board_year"])
                                        )
                                        cq_insert += 1

                    # ── প্রতি 100 items এ progress save করো ────────
                    if (i + 1) - last_save >= 100:
                        # হয়তো 100 insert এর পর check
                        _save_import_progress(progress_path, i + 1, inserted, session_id)
                        last_save = i + 1
                        if on_progress:
                            try:
                                on_progress(i + 1, total_items, source_type, "in_progress")
                            except Exception:
                                pass

                # Complete: progress file remove
                _clear_import_progress(progress_path)

                if on_progress:
                    try:
                        on_progress(total_items, total_items, source_type, "completed")
                    except Exception:
                        pass

                log.info(f"✅ Import [{source_type}]: {class_id}/{subject_id} → "
                         f"{inserted} chunks ({mcq_insert} MCQ, {cq_insert} CQ)")
                grand_total += inserted
                grand_mcq   += mcq_insert
                grand_cq    += cq_insert
                file_results.append({
                    "source_type":  source_type,
                    "filepath":     filepath,
                    "inserted":     inserted,
                    "mcq_inserted": mcq_insert,
                    "cq_inserted":  cq_insert,
                    "skipped":      False,
                    "total_items":  total_items,
                    "skipped_resume": start_index  # কতগুলো আগেই done ছিল
                })

        except Exception as e:
            log.error(f"Import error [{source_type}] {class_id}/{subject_id}: {e}")
            file_results.append({
                "source_type": source_type,
                "filepath":    filepath,
                "error":       str(e)
            })

    return {
        "total_inserted": grand_total,
        "mcq_inserted":   grand_mcq,
        "cq_inserted":    grand_cq,
        "files":          file_results,
        "was_resumed":    was_resumed
    }


# ══════════════════════════════════════════════════════════
#  CONTEXT CACHE
# ══════════════════════════════════════════════════════════
_context_cache = {}


def _try_cache_context_on_startup():
    cached_count = 0
    if not os.path.isdir(DATA_DIR):
        return
    for root, dirs, files in os.walk(DATA_DIR):
        for filename in files:
            if filename.endswith(".json") and not filename.startswith("."):
                filepath = os.path.join(root, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    rel = os.path.relpath(filepath, DATA_DIR)
                    parts = rel.replace("\\", "/").split("/")
                    src_type = filename.replace(".json", "")
                    if len(parts) >= 3:
                        # new structure: data/<class_id>/<group>/<subject_id>/<source_type>.json
                        class_id   = parts[0]
                        subject_id = parts[-2]
                        cache_key  = f"{class_id}/{subject_id}/{src_type}"
                    else:
                        # legacy: data/<class_id>_<subject_id>.json (একটাই ফাইলে সব)
                        cache_key = src_type

                    # ✅ usage-time lookup যেভাবে normalize করে (list of dicts), একইভাবে এখানেও normalize করো
                    items = raw if isinstance(raw, list) else raw.get("pages", raw.get("content", [raw]))
                    if isinstance(items, dict):
                        items = [items]

                    _context_cache[cache_key] = items
                    cached_count += 1
                except Exception as e:
                    log.warning(f"⚠️ ক্যাশ ব্যর্থ: {filename} → {e}")
    log.info(f"✅ স্টার্টআপে {cached_count}টি ডেটা ফাইল ক্যাশ করা হয়েছে")


init_db()
_try_cache_context_on_startup()


# ══════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════

def _extract_keywords(text):
    if not text:
        return []
    words = re.findall(r'[\u0980-\u09FF]+|[a-zA-Z]+', text.lower() if text.isascii() else text)
    return [w for w in words if w not in BENGALI_STOPWORDS and len(w) > 1]


# ══════════════════════════════════════════════════════════
#  QUESTION INTENT → SOURCE_TYPE ROUTING (IM-10)
#  বোর্ড প্রশ্ন হলে board_book/test_paper থেকে, আর কনসেপ্ট/টপিক
#  না-বোঝা প্রশ্ন হলে guide/board_book থেকে chunk আনে।
#  কিছু match না করলে None ফেরত দেয় — তখন আগের মতোই সব
#  source_type একসাথে search হবে।
# ══════════════════════════════════════════════════════════
_BOARD_INTENT_PATTERNS = [
    r'বোর্ড', r'board', r'প্রশ্নপত্র', r'গত\s*বছরের', r'পরীক্ষায়',
    r'এক্সাম', r'exam', r'mcq\s*bank',
    r'\b(19|20)\d{2}\b',          # ইংরেজি সাল: 2023
    r'[১-৯][০-৯]{3}\s*সালের',     # বাংলা সাল: ২০২৩ সালের
]

_DOUBT_INTENT_PATTERNS = [
    r'বুঝিনি', r'বুঝতে\s*পারছি\s*না', r'বুঝিয়ে\s*দাও', r'বুঝাও',
    r'ব্যাখ্যা', r'explain', r'উদাহরণ\s*দিয়ে', r'কেন\s', r'কীভাবে',
    r'কিভাবে', r'সংজ্ঞা', r'definition', r'মানে\s*কী', r'অর্থ\s*কী',
]


def _detect_source_types(question):
    """প্রশ্নের লেখা দেখে কোন source_type (board_book/test_paper/guide)
    থেকে chunk খোঁজা হবে সেটা ঠিক করো।"""
    if not question:
        return None

    q = question.lower()

    for pat in _BOARD_INTENT_PATTERNS:
        if re.search(pat, q, re.IGNORECASE):
            return ["test_paper", "board_book"]

    for pat in _DOUBT_INTENT_PATTERNS:
        if re.search(pat, q, re.IGNORECASE):
            return ["guide", "board_book"]

    return None



# ── Banglish → Bengali keyword mapping (common education/accounting terms) ──
_BANGLISH_MAP = {
    # হিসাববিজ্ঞান
    "jabeda": "জাবেদা", "journal": "জাবেদা",
    "khatiyan": "খতিয়ান", "ledger": "খতিয়ান",
    "rewamil": "রেওয়ামিল", "trial": "রেওয়ামিল",
    "artho": "আর্থিক", "financial": "আর্থিক",
    "hishab": "হিসাব", "hisab": "হিসাব", "accounting": "হিসাববিজ্ঞান",
    "lenaden": "লেনদেন", "transaction": "লেনদেন",
    "debit": "ডেবিট", "credit": "ক্রেডিট",
    "capital": "মূলধন", "muladhan": "মূলধন",
    "nagad": "নগদ", "cash": "নগদ",
    "bank": "ব্যাংক",
    "munafa": "মুনাফা", "profit": "মুনাফা", "loss": "ক্ষতি",
    "asset": "সম্পদ", "sampod": "সম্পদ",
    "liability": "দায়", "day": "দায়",
    "income": "আয়", "expense": "ব্যয়", "byay": "ব্যয়",
    # সাধারণ
    "shikhao": "শিখাও", "shekho": "শেখো", "bojhao": "বোঝাও",
    "ki": "কী", "keno": "কেন", "kivabe": "কীভাবে",
    "shuru": "শুরু", "prothom": "প্রথম", "shesh": "শেষ",
    "odhyay": "অধ্যায়", "chapter": "অধ্যায়",
    "niyom": "নিয়ম", "rule": "নিয়ম",
    "udaharon": "উদাহরণ", "example": "উদাহরণ",
    "somikaron": "সমীকরণ", "equation": "সমীকরণ",
    # পদার্থবিজ্ঞান
    "physics": "পদার্থবিজ্ঞান", "podartho": "পদার্থ",
    "chemistry": "রসায়ন", "rashayon": "রসায়ন",
    "biology": "জীববিজ্ঞান", "jib": "জীব",
    "math": "গণিত", "gonit": "গণিত",
    # ইতিহাস/সমাজ
    "etihas": "ইতিহাস", "history": "ইতিহাস",
    "geography": "ভূগোল", "bhugol": "ভূগোল",
    "civics": "পৌরনীতি", "pouroneeti": "পৌরনীতি",
}

def _expand_banglish_query(question):
    """Roman/Banglish words → Bengali equivalents যোগ করো FTS query এ।"""
    latin_words = re.findall(r'[a-zA-Z]+', question.lower())
    extras = []
    for w in latin_words:
        if w in _BANGLISH_MAP:
            extras.append(_BANGLISH_MAP[w])
    return extras  # list of Bengali terms to add to FTS


def _is_banglish_query(question):
    """True যদি query তে Bengali character না থেকে mostly Roman থাকে।"""
    bn_chars = len(re.findall(r'[\u0980-\u09FF]', question))
    en_chars = len(re.findall(r'[a-zA-Z]', question))
    return bn_chars == 0 and en_chars > 0


# ══════════════════════════════════════════════════════════════════════
#  FUNCTION CALLING — Smart 2-step RAG
#  Step-1 (HTTP-1): Gemini বলে কোন Bengali keywords দিয়ে search করতে হবে
#  Step-2 (HTTP-2): সেই chunks দিয়ে Gemini accurate answer দেয়
# ══════════════════════════════════════════════════════════════════════

# search_textbook tool definition — Gemini এই function "call" করবে
_SEARCH_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_textbook",
            description=(
                "পাঠ্যবইয়ের FTS database থেকে relevant chunk খোঁজো। "
                "user এর প্রশ্ন যেভাবেই লেখা থাকুক (Banglish/Bengali/English), "
                "তুমি সঠিক বাংলা keywords বের করে এই function call করবে।"
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "keywords": types.Schema(
                        type=types.Type.ARRAY,
                        items=types.Schema(type=types.Type.STRING),
                        description=(
                            "পাঠ্যবইয়ের ভাষায় বাংলা search keywords। "
                            "যতবেশি specific এবং varied হবে, তত ভালো chunk পাওয়া যাবে। "
                            "topic এর সংজ্ঞা, বৈশিষ্ট্য, নিয়ম, উদাহরণ — সব কিছুর keyword দাও।"
                        ),
                    ),
                    "top_n": types.Schema(
                        type=types.Type.INTEGER,
                        description=(
                            "কতটা chunk দরকার। সহজ সংজ্ঞা হলে 5, "
                            "বিস্তারিত ব্যাখ্যা বা উদাহরণ চাইলে 10, "
                            "তুলনা/পার্থক্য বা সম্পূর্ণ topic হলে 12।"
                        ),
                    ),
                },
                required=["keywords", "top_n"],
            ),
        )
    ]
)

# Step-1 system prompt — শুধু keyword extraction এর জন্য, ছোট ও focused
_FC_STEP1_PROMPT = """তুমি বাংলাদেশের SSC/HSC পাঠ্যবইয়ের একজন বিশেষজ্ঞ।

তোমার কাজ: শিক্ষার্থীর প্রশ্ন বিশ্লেষণ করে `search_textbook` function call করো।

keyword বাছাইয়ের নিয়ম:
1. প্রশ্ন Banglish হলে (jabeda, khotiyan, rewamil) → বাংলায় convert করো (জাবেদা, খতিয়ান, রেওয়ামিল)
2. topic এর মূল শব্দ + সংজ্ঞার শব্দ + বৈশিষ্ট্যের শব্দ — সব দাও
3. শুধু ১টা keyword নয় — ৫-৮টা varied keyword দাও যাতে বেশি chunk আসে
4. পাঠ্যবইয়ের formal বাংলা ভাষায় লেখো

উদাহরণ:
প্রশ্ন "jabeda ki" → keywords: ["জাবেদা", "প্রাথমিক জাবেদা", "লেনদেন লিপিবদ্ধ", "হিসাবের বই", "ডেবিট ক্রেডিট বিশ্লেষণ"]
প্রশ্ন "মূলধন কী" → keywords: ["মূলধন", "মালিকানা স্বত্ব", "প্রারম্ভিক মূলধন", "মূলধন বৃদ্ধি হ্রাস"]

top_n নির্ধারণ:
- "কী / সংজ্ঞা" প্রশ্ন → 6
- "কীভাবে / নিয়ম / শেখাও" → 10
- "পার্থক্য / তুলনা / উদাহরণ সহ" → 12
- "সম্পূর্ণ topic / অধ্যায়" → 15

বিষয়: {subject_bn}
শ্রেণি: {class_label}"""


def _fc_search_and_answer(
    question: str,
    class_id: str,
    subject_id: str,
    history: list = None,
    chapter_num=None,
    source_type=None,
) -> dict:
    """
    Function Calling দিয়ে 2-step smart RAG।

    HTTP-1 (fast, ~0.5s):
        Gemini question বিশ্লেষণ করে → search_textbook(keywords=[...], top_n=N) call করে

    FTS Search (local, instant):
        সেই keywords দিয়ে SQLite FTS → accurate Bengali chunks পাওয়া যায়

    HTTP-2 (main answer):
        chunks + question → Gemini full answer দেয়

    Return: {"answer": str, "from_library": bool, "chunks_found": int}
    """
    client = _get_client()
    if not client:
        return {"error": "❌ API Key সেট করা হয়নি"}

    has_history = bool(history)

    cls       = CLASSES.get(class_id, {})
    class_label = cls.get("label", class_id)
    subj_info = get_subject_info(class_id, subject_id)
    subject_bn = subj_info.get("bn", subject_id) if subj_info else subject_id

    # ── HTTP Request 1: keyword extraction ───────────────────────────
    step1_system = _FC_STEP1_PROMPT.format(
        subject_bn=subject_bn,
        class_label=class_label,
    )

    try:
        step1_resp = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=question,
            config=types.GenerateContentConfig(
                system_instruction=step1_system,
                tools=[_SEARCH_TOOL],
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="ANY",  # function call বাধ্যতামূলক — text reply নয়
                        allowed_function_names=["search_textbook"],
                    )
                ),
                max_output_tokens=300,
                temperature=0.1,
            ),
        )

        # function call parse করো
        fc = None
        for part in (step1_resp.candidates[0].content.parts if step1_resp.candidates else []):
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                break

        if fc and fc.name == "search_textbook":
            args     = dict(fc.args)
            keywords = args.get("keywords", [])
            top_n    = int(args.get("top_n", 8))
            top_n    = max(5, min(top_n, 15))  # 5-15 এর মধ্যে রাখো
            log.info(f"🔧 FC keywords={keywords} top_n={top_n}")
        else:
            # Fallback: static map
            log.warning("⚠️ FC: no function_call found, using static map fallback")
            keywords = _expand_banglish_query(question) or []
            top_n    = 8

    except Exception as e:
        log.error(f"❌ FC Step-1 error: {e}")
        keywords = _expand_banglish_query(question) or []
        top_n    = 8

    # ── FTS Search (local, no API call) ──────────────────────────────
    if keywords:
        # AI-extracted keywords দিয়ে FTS query বানাও
        fts_query = " OR ".join(f'"{kw}"' if " " in kw else kw for kw in keywords)
        # direct FTS search with these exact Bengali keywords
        chunks = _db_search_fts(
            class_id, subject_id,
            fts_query,
            top_n=top_n,
            source_type=source_type,
        )
        # কম পেলে original question দিয়েও চেষ্টা করো
        if len(chunks) < 3:
            extra = _db_search_fts(class_id, subject_id, question, top_n=top_n,
                                   source_type=source_type)
            seen = {c["text"] for c in chunks}
            chunks += [c for c in extra if c["text"] not in seen]
            chunks = chunks[:top_n]
    else:
        chunks = _search_json_library(class_id, subject_id, question,
                                      top_n=top_n, source_type=source_type,
                                      chapter_num=chapter_num)

    # DB তে কিছু না পেলে auto-import চেষ্টা
    if not chunks:
        imported = _db_import_json_to_fts(class_id, subject_id)
        if imported and keywords:
            fts_query = " OR ".join(f'"{kw}"' if " " in kw else kw for kw in keywords)
            chunks = _db_search_fts(class_id, subject_id, fts_query, top_n=top_n)

    context = _build_context(chunks)
    log.info(f"📚 FC: {len(chunks)} chunks found for answer")

    # ── HTTP Request 2: final answer ──────────────────────────────────
    answer_system = get_answer_prompt(subject_id, class_label, subject_bn)
    if has_history:
        answer_system += _CONTINUITY_INSTRUCTIONS

    if context:
        user_prompt = (
            f"⛔ নিচের 'পাঠ্যবই থেকে তথ্য' অংশ তোমার একমাত্র তথ্যসূত্র। "
            f"শুধুমাত্র এই তথ্য ব্যবহার করে উত্তর দাও।\n\n"
            f"পাঠ্যবই থেকে তথ্য:\n{context}\n\n"
            f"প্রশ্ন: {question}"
        )
    else:
        user_prompt = (
            f"প্রশ্ন: {question}\n\n"
            f"(নোট: পাঠ্যবইয়ে এই বিষয়ে কোনো তথ্য পাওয়া যায়নি।)"
        )

    is_short = _is_short_question(question)

    if has_history:
        contents = []
        for h in history:
            role = "user" if h.get("role") == "user" else "model"
            text = h.get("parts", [""])[0]
            if text:
                contents.append(types.Content(role=role, parts=[types.Part(text=text)]))
        contents.append(types.Content(role="user", parts=[types.Part(text=user_prompt)]))
    else:
        contents = user_prompt

    try:
        # Step15 context cache (optional)
        gemini_cache_name = None
        try:
            from features.step15_cache import get_cached_content
            gemini_cache_name = get_cached_content(class_id, subject_id)
        except Exception:
            pass

        gen_config = types.GenerateContentConfig(
            system_instruction=answer_system,
            max_output_tokens=MAX_OUTPUT_SHORT if is_short else MAX_OUTPUT_LONG,
            temperature=0.3,
        )

        call_kwargs = dict(model=DEFAULT_MODEL, contents=contents, config=gen_config)
        if gemini_cache_name:
            call_kwargs["cached_content"] = gemini_cache_name

        response   = client.models.generate_content(**call_kwargs)
        answer_txt = response.text if response.text else "উত্তর তৈরি করা যায়নি।"

        return {
            "answer":       answer_txt,
            "from_library": bool(context),
            "chunks_found": len(chunks),
        }

    except Exception as e:
        log.error(f"❌ FC Step-2 answer error: {e}")
        return {"error": f"AI সমস্যা: {str(e)}"}



def _fc_get_chunks(
    question: str,
    class_id: str,
    subject_id: str,
    chapter_num=None,
    source_type=None,
) -> list:
    """
    FC Step-1 only: Gemini keyword বের করে FTS search করে chunks return করে।
    Stream version এ ব্যবহার হয় — answer step আলাদা (build_answer_stream করে)।
    """
    client = _get_client()
    cls        = CLASSES.get(class_id, {})
    class_label = cls.get("label", class_id)
    subj_info  = get_subject_info(class_id, subject_id)
    subject_bn = subj_info.get("bn", subject_id) if subj_info else subject_id

    step1_system = _FC_STEP1_PROMPT.format(subject_bn=subject_bn, class_label=class_label)

    keywords = []
    top_n    = 8

    if client:
        try:
            resp = client.models.generate_content(
                model=DEFAULT_MODEL,
                contents=question,
                config=types.GenerateContentConfig(
                    system_instruction=step1_system,
                    tools=[_SEARCH_TOOL],
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode="ANY",
                            allowed_function_names=["search_textbook"],
                        )
                    ),
                    max_output_tokens=300,
                    temperature=0.1,
                ),
            )
            for part in (resp.candidates[0].content.parts if resp.candidates else []):
                if hasattr(part, "function_call") and part.function_call and part.function_call.name == "search_textbook":
                    args     = dict(part.function_call.args)
                    keywords = args.get("keywords", [])
                    top_n    = max(5, min(int(args.get("top_n", 8)), 15))
                    log.info(f"\U0001f527 FC chunks: keywords={keywords} top_n={top_n}")
                    break
        except Exception as e:
            log.warning(f"\u26a0\ufe0f FC get_chunks step-1 error: {e}")

    if not keywords:
        keywords = _expand_banglish_query(question)

    if keywords:
        fts_query = " OR ".join(f'"{kw}"' if " " in kw else kw for kw in keywords)
        chunks = _db_search_fts(class_id, subject_id, fts_query, top_n=top_n, source_type=source_type)
        if len(chunks) < 3:
            extra = _db_search_fts(class_id, subject_id, question, top_n=top_n, source_type=source_type)
            seen  = {c["text"] for c in chunks}
            chunks += [c for c in extra if c["text"] not in seen]
            chunks = chunks[:top_n]
    else:
        chunks = _search_json_library(class_id, subject_id, question, top_n=top_n,
                                      source_type=source_type, chapter_num=chapter_num)

    if not chunks:
        imported = _db_import_json_to_fts(class_id, subject_id)
        if imported and keywords:
            fts_query = " OR ".join(f'"{kw}"' if " " in kw else kw for kw in keywords)
            chunks = _db_search_fts(class_id, subject_id, fts_query, top_n=top_n)

    return chunks


def _search_json_library(class_id, subject_id, question, top_n=None, content_type=None, chapter=None, chapter_num=None, source_type=None, board_name=None, board_year=None):
    if top_n is None:
        top_n = TOP_N_CHUNKS

    # ✅ Banglish detection: Roman query হলে Bengali equivalent যোগ করো (static map — no extra API call)
    banglish = _is_banglish_query(question)
    fts_question = question
    if banglish:
        extras = _expand_banglish_query(question)
        if extras:
            fts_question = question + " " + " ".join(extras)
            log.info(f"🔤 Banglish → static map expanded: '{fts_question[:80]}'")

    # ✅ chapter_num পাস করা হচ্ছে — exact chapter match
    fts_results = _db_search_fts(class_id, subject_id, fts_question, top_n,
                                 content_type, chapter, chapter_num, source_type,
                                 board_name, board_year)

    # ── Step14 hybrid search integrate (IM-7) ─────────────────────────
    # FTS results কম হলে semantic search দিয়ে supplement করো
    if len(fts_results) < top_n:
        try:
            from features.step14_semantic import hybrid_search
            sem_results = hybrid_search(class_id, subject_id, question, top_n=top_n)
            existing_content = {r["text"] for r in fts_results}
            for sr in sem_results:
                content = sr.get("content", "")
                if content and content not in existing_content:
                    fts_results.append({
                        "text":         content,
                        "score":        sr.get("combined", 0.5),
                        "content_type": "text",
                        "chapter":      sr.get("chapter", ""),
                        "source_type":  source_type or "board_book",
                        "source":       f"{class_id}_{subject_id}_semantic",
                    })
                    existing_content.add(content)
                    if len(fts_results) >= top_n:
                        break
        except Exception as e:
            log.debug("Hybrid search skip: %s", e)

    if fts_results:
        return fts_results[:top_n]

    imported = _db_import_json_to_fts(class_id, subject_id)
    if imported:
        fts_results = _db_search_fts(class_id, subject_id, question, top_n,
                                     content_type, chapter, chapter_num, source_type,
                                     board_name, board_year)
        if fts_results:
            return fts_results

    # ── Last resort: JSON keyword fallback (সব source_type একসাথে) ──
    from config import find_all_data_files
    all_files = find_all_data_files(class_id, subject_id, DATA_DIR)
    if not all_files:
        legacy = find_data_file(class_id, subject_id, DATA_DIR)
        if legacy:
            all_files = [("board_book", legacy)]

    if not all_files:
        return []

    # সব source_type এর data merge করো
    all_items = []
    for src_type, filepath in all_files:
        cache_key = f"{class_id}/{subject_id}/{src_type}"
        if cache_key in _context_cache:
            items = _context_cache[cache_key]
        else:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                items = raw if isinstance(raw, list) else raw.get("pages", raw.get("content", [raw]))
                if isinstance(items, dict):
                    items = [items]
                _context_cache[cache_key] = items
            except Exception as e:
                log.error("Fallback read error [%s]: %s", filepath, e)
                continue
        all_items.extend(items)

    if not all_items:
        return []

    keywords = _extract_keywords(question)
    # Banglish হলে static map থেকে Bengali keywords যোগ করো (no extra API call)
    if banglish:
        extra_bn = _expand_banglish_query(question)
        keywords = list(set(keywords + extra_bn))
    if not keywords:
        # কোনো keyword নেই কিন্তু Banglish হলে কিছু general context দাও
        if banglish and all_items:
            text_items = [it for it in all_items if isinstance(it, dict) and it.get("content_type","text") == "text"]
            return [{
                "text":         it.get("content", ""),
                "score":        0.1,
                "content_type": "text",
                "chapter":      it.get("chapter", ""),
                "source_type":  it.get("source_type", "board_book"),
                "source":       f"{class_id}_{subject_id}.json"
            } for it in text_items[:top_n]]
        return []

    scored_chunks = []
    for item in all_items:
        if isinstance(item, dict):
            # content_type filter (JSON fallback)
            if content_type and item.get("content_type", "text") != content_type:
                continue
            if chapter and item.get("chapter", "") != chapter:
                continue
            # source_type filter (JSON fallback)
            if source_type and source_type != "all":
                item_src = item.get("source_type", "board_book")
                if isinstance(source_type, list):
                    if item_src not in source_type:
                        continue
                elif item_src != source_type:
                    continue
            text = item.get("text", item.get("content",
                            json.dumps(item, ensure_ascii=False)))
        else:
            text = str(item)
        item_keywords = _extract_keywords(text)
        if not item_keywords:
            continue
        overlap = sum(1 for kw in keywords if kw in item_keywords)
        if overlap > 0:
            score = overlap / len(keywords)
            scored_chunks.append({
                "text":         text,
                "score":        score,
                "content_type": item.get("content_type", "text") if isinstance(item, dict) else "text",
                "chapter":      item.get("chapter", "") if isinstance(item, dict) else "",
                "source_type":  item.get("source_type", "board_book") if isinstance(item, dict) else "board_book",
                "source":       f"{class_id}_{subject_id}.json"
            })

    scored_chunks.sort(key=lambda x: x["score"], reverse=True)
    if scored_chunks:
        return scored_chunks[:top_n]

    # ── Banglish শেষ চেষ্টা: কোনো keyword match না হলে general text chunks দাও ──
    if banglish and all_items:
        log.info(f"⚡ Banglish fallback: returning general context for '{question[:40]}'")
        text_items = [it for it in all_items
                      if isinstance(it, dict)
                      and it.get("content_type", "text") == "text"
                      and len(str(it.get("content", ""))) > 50]
        return [{
            "text":         it.get("content", ""),
            "score":        0.1,
            "content_type": "text",
            "chapter":      it.get("chapter", ""),
            "source_type":  it.get("source_type", "board_book"),
            "source":       f"{class_id}_{subject_id}.json"
        } for it in text_items[:top_n]]

    return []


def _clean_accounting_tags(text):
    """
    [JOURNAL]/[LEDGER: name]/[TRIAL_BALANCE] ইত্যাদি tag রিমুভ করে
    শুধু clean Markdown table রাখো — যাতে Gemini ঠিকভাবে render করতে পারে।
    """
    if not text:
        return text

    # [JOURNAL] ... [/JOURNAL] → just the inner content
    text = re.sub(r'\[/?JOURNAL\]', '', text, flags=re.IGNORECASE)

    # [LEDGER: হিসাবের নাম] ... [/LEDGER] → "**হিসাবের নাম:**" + content
    text = re.sub(
        r'\[LEDGER:\s*([^\]]+)\](.*?)\[/LEDGER\]',
        lambda m: f"**{m.group(1).strip()}:**\n{m.group(2).strip()}",
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    # Simple [LEDGER] ... [/LEDGER] (no name)
    text = re.sub(r'\[LEDGER\](.*?)\[/LEDGER\]', r'\1', text, flags=re.IGNORECASE | re.DOTALL)

    # [TRIAL_BALANCE] ... [/TRIAL_BALANCE] → "**ট্রায়াল ব্যালেন্স:**" + content
    text = re.sub(
        r'\[TRIAL_BALANCE\](.*?)\[/TRIAL_BALANCE\]',
        lambda m: f"**ট্রায়াল ব্যালেন্স:**\n{m.group(1).strip()}",
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    return text


def _build_context(chunks):
    if not chunks:
        return ""
    parts = []
    for i, chunk in enumerate(chunks):
        text = chunk.get("text", "")
        text = _clean_accounting_tags(text)
        if len(text) > MAX_CHARS_PER_PAGE:
            text = text[:MAX_CHARS_PER_PAGE] + "..."
        parts.append(f"[তথ্য {i+1}]\n{text}")
    return "\n\n".join(parts)


def _find_in_cache(question):
    """DB cache থেকে খোঁজো — in-memory cache সরানো হয়েছে (IM-5)."""
    return _db_find_cache(question)


def _save_to_cache(question, result):
    """DB cache এ save করো — in-memory cache সরানো হয়েছে (IM-5)."""
    _db_save_cache(question, result)


def _is_short_question(question):
    return len(question.split()) < SHORT_Q_WORD_LIMIT


# ✅ NEW (IM-8): Conversation continuity — history থাকলে এই instruction
# system_prompt এর সাথে জুড়ে দেওয়া হয়, যাতে Gemini আগের কথোপকথন বুঝে
# পুনরাবৃত্তি না করে এগিয়ে যায়।
_CONTINUITY_INSTRUCTIONS = """

📌 কথোপকথন প্রসঙ্গ (Conversation Continuity):
এই প্রম্পটের আগে student-এর সাথে তোমার আগের কথোপকথন (পূর্ববর্তী turn গুলো) দেওয়া আছে।
- প্রথমে সেগুলো পড়ে বুঝে নাও student-কে আগে কী বলা হয়েছে / কতদূর পড়ানো হয়েছে।
- আগে যা ব্যাখ্যা করেছ, তা হুবহু বা প্রায় একইভাবে আবার বলো না — এটা একটা গুরুতর ভুল।
- student যদি "শিখাও", "বুঝিয়ে দাও", "continue করো", "আরো বলো" এর মতো কিছু বলে, তাহলে আগের জায়গা থেকে পরের অংশে এগিয়ে যাও, অথবা নতুন উদাহরণ/সহজ ভাষায়/প্রশ্ন-উত্তর আকারে একই বিষয় ভিন্নভাবে উপস্থাপন করো।
- "প্রদত্ত তথ্য" ব্লকে যদি আগের মতোই একই content থাকে, সেটাকে raw আকারে কপি-পেস্ট না করে — student এর অগ্রগতি অনুযায়ী নতুন কোণ থেকে (উদাহরণ, ব্যায়াম, ছোট প্রশ্ন) ব্যবহার করো।
"""




# ══════════════════════════════════════════════════════════
#  MCQ DEDUPLICATION + CROSS-BOARD PATTERN ANALYSIS
# ══════════════════════════════════════════════════════════

def _deduplicate_mcqs(class_id: str, subject_id: str, similarity_threshold: float = 0.85) -> dict:
    """
    একই subject এর MCQ গুলো scan করো।
    85%+ similar হলে → duplicate mark করো, canonical এ merge করো।

    Returns:
      { total_scanned, duplicates_found, merged_count }
    """
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT id, question, board_name, board_year
               FROM mcq_bank
               WHERE class_id=? AND subject_id=? AND is_canonical=1
               ORDER BY id""",
            (class_id, subject_id)
        ).fetchall()

        total      = len(rows)
        dup_count  = 0
        merge_count = 0

        # প্রতিটা pair compare করো  O(n²) — কিন্তু subject-level তাই manageable
        for i, row_a in enumerate(rows):
            if not row_a:
                continue
            id_a  = row_a["id"]
            q_a   = (row_a["question"] or "").strip()

            for j in range(i + 1, len(rows)):
                row_b = rows[j]
                if not row_b:
                    continue
                id_b = row_b["id"]
                q_b  = (row_b["question"] or "").strip()

                # similarity check
                ratio = SequenceMatcher(None, q_a, q_b).ratio()
                if ratio < similarity_threshold:
                    continue

                # ── Duplicate পাওয়া গেছে ──
                dup_count += 1

                # canonical (id_a) এর appeared data পড়ো
                canon = conn.execute(
                    "SELECT appeared_boards, appeared_years, frequency_score, board_name, board_year FROM mcq_bank WHERE id=?",
                    (id_a,)
                ).fetchone()
                if not canon:
                    continue

                boards = json.loads(canon["appeared_boards"] or "[]")
                years  = json.loads(canon["appeared_years"]  or "[]")

                # canonical নিজের board/year যোগ করো (প্রথমবার)
                if canon["board_name"] and canon["board_name"] not in boards:
                    boards.insert(0, canon["board_name"])
                if canon["board_year"] and canon["board_year"] not in years:
                    years.insert(0, canon["board_year"])

                # duplicate (id_b) এর board/year merge করো
                b_board = row_b["board_name"] or ""
                b_year  = row_b["board_year"]  or ""
                if b_board and b_board not in boards:
                    boards.append(b_board)
                if b_year and b_year not in years:
                    years.append(b_year)

                freq  = len(years) if years else (canon["frequency_score"] or 1) + 1
                cross = len(set(boards))
                last  = max((int(y) for y in years if str(y).isdigit()), default=0)

                # canonical update করো
                conn.execute(
                    """UPDATE mcq_bank
                       SET appeared_boards=?, appeared_years=?,
                           frequency_score=?, cross_board_score=?,
                           last_appeared_year=?
                       WHERE id=?""",
                    (json.dumps(boards, ensure_ascii=False),
                     json.dumps(years,  ensure_ascii=False),
                     freq, cross, last, id_a)
                )

                # duplicate mark করো
                conn.execute(
                    "UPDATE mcq_bank SET is_canonical=0, canonical_id=? WHERE id=?",
                    (id_a, id_b)
                )
                rows[j] = None   # আর process করবে না
                merge_count += 1

        conn.commit()
        log.info(f"✅ Deduplicate done: {total} scanned, {dup_count} duplicates, {merge_count} merged")
        return {
            "total_scanned":   total,
            "duplicates_found": dup_count,
            "merged_count":    merge_count,
        }
    finally:
        conn.close()


def _mcq_frequency_analysis(class_id: str, subject_id: str, board: str = None) -> dict:
    """
    Chapter-wise MCQ frequency analysis।
    board দিলে শুধু ওই board এর data।

    Returns:
      {
        chapter_frequency: [...],
        top_repeated: [...],
        not_appeared_recently: [...],
        prediction_hints: [...]
      }
    """
    import datetime
    current_year = datetime.datetime.now().year
    conn = get_db()
    try:
        # ── Chapter Frequency ──────────────────────────────────
        if board:
            ch_rows = conn.execute(
                """SELECT chapter, COUNT(*) as mcq_count,
                          MAX(last_appeared_year) as last_year,
                          AVG(frequency_score) as avg_freq
                   FROM mcq_bank
                   WHERE class_id=? AND subject_id=? AND is_canonical=1
                     AND (appeared_boards LIKE ? OR board_name=?)
                   GROUP BY chapter
                   ORDER BY mcq_count DESC""",
                (class_id, subject_id, f'%{board}%', board)
            ).fetchall()
        else:
            ch_rows = conn.execute(
                """SELECT chapter, COUNT(*) as mcq_count,
                          MAX(last_appeared_year) as last_year,
                          AVG(frequency_score) as avg_freq
                   FROM mcq_bank
                   WHERE class_id=? AND subject_id=? AND is_canonical=1
                   GROUP BY chapter
                   ORDER BY mcq_count DESC""",
                (class_id, subject_id)
            ).fetchall()

        chapter_frequency = []
        not_appeared_recently = []
        for r in ch_rows:
            last = r["last_year"] or 0
            gap  = current_year - int(last) if last else 99
            entry = {
                "chapter":    r["chapter"],
                "mcq_count":  r["mcq_count"],
                "last_year":  last,
                "gap_years":  gap,
                "avg_freq":   round(r["avg_freq"] or 1, 1),
            }
            chapter_frequency.append(entry)
            if gap >= 3 and r["chapter"]:
                not_appeared_recently.append(entry)

        # ── Top Repeated MCQ (৩+ board/year) ──────────────────
        top_rows = conn.execute(
            """SELECT question, option_a, option_b, option_c, option_d,
                      answer, chapter, frequency_score,
                      cross_board_score, appeared_boards, appeared_years,
                      last_appeared_year
               FROM mcq_bank
               WHERE class_id=? AND subject_id=? AND is_canonical=1
                 AND frequency_score >= 2
               ORDER BY cross_board_score DESC, frequency_score DESC
               LIMIT 20""",
            (class_id, subject_id)
        ).fetchall()

        top_repeated = []
        for r in top_rows:
            boards = json.loads(r["appeared_boards"] or "[]")
            years  = json.loads(r["appeared_years"]  or "[]")
            if not boards and r["appeared_boards"] is None:
                boards = [r.get("board_name", "")] if r.get("board_name") else []
            top_repeated.append({
                "question":          r["question"],
                "answer":            r["answer"],
                "chapter":           r["chapter"],
                "frequency_score":   r["frequency_score"],
                "cross_board_score": r["cross_board_score"],
                "appeared_boards":   boards,
                "appeared_years":    years,
                "last_year":         r["last_appeared_year"],
            })

        # ── Prediction Hints (rule-based) ──────────────────────
        prediction_hints = []
        for entry in chapter_frequency:
            if entry["avg_freq"] >= 5:
                prediction_hints.append({
                    "type":    "certain",
                    "chapter": entry["chapter"],
                    "reason":  f"প্রতি বছর গড়ে {entry['avg_freq']}টা MCQ আসে — নিশ্চিত আসবে",
                })
            elif entry["gap_years"] >= 3:
                prediction_hints.append({
                    "type":    "gap_year",
                    "chapter": entry["chapter"],
                    "reason":  f"{entry['gap_years']} বছর ধরে আসেনি (শেষ {entry['last_year']}) — এবার আসার সম্ভাবনা আছে",
                })

        for mcq in top_repeated:
            if mcq["cross_board_score"] >= 3:
                prediction_hints.append({
                    "type":     "cross_board",
                    "question": mcq["question"][:80] + "...",
                    "chapter":  mcq["chapter"],
                    "reason":   f"{mcq['cross_board_score']}টা বোর্ডে এসেছে — common question",
                })

        return {
            "chapter_frequency":     chapter_frequency,
            "top_repeated":          top_repeated,
            "not_appeared_recently": not_appeared_recently,
            "prediction_hints":      prediction_hints[:15],   # top 15
        }
    finally:
        conn.close()


def build_answer(question, context, class_id, subject_id, history=None):
    """Gemini API দিয়ে উত্তর তৈরি করো — key pool থেকে client নাও

    history: _conv_load() থেকে পাওয়া [{"role": "user"/"model"/"assistant", "parts": [text]}, ...]
             দিলে role-based conversation contents পাঠানো হবে (continuity ঠিক রাখার জন্য)।
    """
    client = _get_client()
    if not client:
        return {"error": "❌ কোনো Gemini API Key সেট করা হয়নি। Railway এ GEMINI_API_KEY_1 variable সেট করুন।"}

    has_history = bool(history)

    cache_key = f"{class_id}_{subject_id}_{question}"
    # ✅ Conversation চলাকালীন (history আছে) cache ব্যবহার করা হবে না —
    # নাহলে আগের session এর generic উত্তর ফিরে আসতে পারে এবং continuity ভেঙে যায়।
    if not has_history:
        cached = _find_in_cache(cache_key)
        if cached:
            return cached

    cls = CLASSES.get(class_id, {})
    class_label = cls.get("label", class_id)
    subj_info = get_subject_info(class_id, subject_id)
    subject_bn = subj_info.get("bn", subject_id) if subj_info else subject_id

    system_prompt = get_answer_prompt(subject_id, class_label, subject_bn)
    if has_history:
        system_prompt += _CONTINUITY_INSTRUCTIONS

    if context:
        user_prompt = (
            f"⛔ নিচের 'পাঠ্যবই থেকে তথ্য' অংশ তোমার একমাত্র তথ্যসূত্র। "
            f"শুধুমাত্র এই তথ্য ব্যবহার করে উত্তর দাও। "
            f"নিজের মাথা থেকে কিছু যোগ করবে না।\n\n"
            f"পাঠ্যবই থেকে তথ্য:\n{context}\n\n"
            f"প্রশ্ন: {question}"
        )
    else:
        user_prompt = f"প্রশ্ন: {question}\n\n(নোট: পাঠ্যবইয়ে এই বিষয়ে কোনো তথ্য পাওয়া যায়নি। ছাত্রকে জানাও যে এই প্রশ্নের উত্তর পাঠ্যবইয়ে নেই।)"

    is_short = _is_short_question(question)

    # ── Step15 context cache integrate (IM-7) ────────────────────────
    gemini_cache_name = None
    try:
        from features.step15_cache import get_cached_content
        gemini_cache_name = get_cached_content(class_id, subject_id)
    except Exception:
        pass

    # ✅ NEW (IM-8): history থাকলে role-based contents বানাও, যাতে Gemini
    # প্রতিটা আগের turn আলাদাভাবে দেখে — শুধু একটা flat text এর চেয়ে
    # এটা continuity-র জন্য বেশি reliable।
    if has_history:
        contents = []
        for h in history:
            role = h.get("role", "user")
            # পুরনো রো-গুলোতে "assistant" সেভ করা থাকতে পারে — Gemini শুধু
            # "user"/"model" রোল বোঝে
            role = "user" if role == "user" else "model"
            text = h.get("parts", [""])[0]
            if not text:
                continue
            contents.append(types.Content(role=role, parts=[types.Part(text=text)]))
        contents.append(types.Content(role="user", parts=[types.Part(text=user_prompt)]))
    else:
        contents = user_prompt

    try:
        model_name = DEFAULT_MODEL
        model_info = MODELS.get(model_name, {})

        gen_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=MAX_OUTPUT_SHORT if is_short else MAX_OUTPUT_LONG,
            temperature=0.3,
        )

        if gemini_cache_name:
            # Context cached — subject content আর পাঠাতে হবে না
            response = client.models.generate_content(
                model=model_name,
                cached_content=gemini_cache_name,
                contents=contents,
                config=gen_config
            )
        else:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=gen_config
            )

        answer_text = response.text if response.text else "উত্তর তৈরি করা যায়নি।"

        result = {
            "answer":       answer_text,
            "from_library": bool(context),
            "from_cache":   bool(gemini_cache_name),
        }

        # ✅ history-aware উত্তর cache করা হয় না (প্রতিটা conversation এর
        # প্রসঙ্গ আলাদা, generic cache ভুল উত্তর ফিরিয়ে দিতে পারে)
        if not has_history:
            _save_to_cache(cache_key, result)


        return result

    except Exception as e:
        log.error(f"❌ Gemini API ত্রুটি: {e}")
        return {"error": f"AI সমস্যা: {str(e)}"}


def build_answer_stream(question, context, class_id, subject_id, history=None, ai_model="zolo_1", thinking_mode=False):
    """
    ✅ NEW (IM-9): build_answer()-এর streaming ভার্সন।
    Gemini যেভাবে token/chunk পাঠায়, সেভাবেই yield করে — একবারে পুরো উত্তর
    জমা না করে frontend-এ পাঠানো যায় (real-time "টাইপ হচ্ছে" effect)।

    yield করে (kind, payload) tuple:
      ("chunk", text)        — একটা টেক্সট খণ্ড
      ("done",  result_dict) — শেষ হলে পুরো ফলাফল (answer/from_library ইত্যাদি)
      ("error", message)     — সমস্যা হলে
    """
    client = _get_client()
    if not client:
        yield ("error", "❌ কোনো Gemini API Key সেট করা হয়নি। Railway এ GEMINI_API_KEY_1 variable সেট করুন।")
        return

    has_history = bool(history)

    cls = CLASSES.get(class_id, {})
    class_label = cls.get("label", class_id)
    subj_info = get_subject_info(class_id, subject_id)
    subject_bn = subj_info.get("bn", subject_id) if subj_info else subject_id

    system_prompt = get_answer_prompt(subject_id, class_label, subject_bn)
    if has_history:
        system_prompt += _CONTINUITY_INSTRUCTIONS

    if context:
        user_prompt = (
            f"⛔ নিচের 'পাঠ্যবই থেকে তথ্য' অংশ তোমার একমাত্র তথ্যসূত্র। "
            f"শুধুমাত্র এই তথ্য ব্যবহার করে উত্তর দাও। "
            f"নিজের মাথা থেকে কিছু যোগ করবে না।\n\n"
            f"পাঠ্যবই থেকে তথ্য:\n{context}\n\n"
            f"প্রশ্ন: {question}"
        )
    else:
        user_prompt = f"প্রশ্ন: {question}\n\n(নোট: পাঠ্যবইয়ে এই বিষয়ে কোনো তথ্য পাওয়া যায়নি। ছাত্রকে জানাও যে এই প্রশ্নের উত্তর পাঠ্যবইয়ে নেই।)"

    is_short = _is_short_question(question)

    # ── Step15 context cache integrate (IM-7) ────────────────────────
    gemini_cache_name = None
    try:
        from features.step15_cache import get_cached_content
        gemini_cache_name = get_cached_content(class_id, subject_id)
    except Exception:
        pass

    if has_history:
        contents = []
        for h in history:
            role = h.get("role", "user")
            role = "user" if role == "user" else "model"
            text = h.get("parts", [""])[0]
            if not text:
                continue
            contents.append(types.Content(role=role, parts=[types.Part(text=text)]))
        contents.append(types.Content(role="user", parts=[types.Part(text=user_prompt)]))
    else:
        contents = user_prompt

    try:
        model_name = DEFAULT_MODEL
        model_info = MODELS.get(model_name, {})

        gen_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=MAX_OUTPUT_SHORT if is_short else MAX_OUTPUT_LONG,
            temperature=0.3,
        )

        stream_kwargs = dict(model=model_name, contents=contents, config=gen_config)
        if gemini_cache_name:
            stream_kwargs["cached_content"] = gemini_cache_name

        full_text = ""
        
        try:
            from features.nvidia_models import is_nvidia_model, generate_nvidia_stream
            
            if is_nvidia_model(ai_model):
                try:
                    for kind, piece in generate_nvidia_stream(
                        model_alias=ai_model,
                        contents=contents,
                        system_instruction=system_prompt,
                        max_tokens=MAX_OUTPUT_SHORT if is_short else MAX_OUTPUT_LONG,
                        temperature=0.3,
                        thinking_mode=thinking_mode
                    ):
                        if kind == "chunk" and piece:
                            full_text += piece
                            yield ("chunk", piece)
                except Exception as ne:
                    log.warning(f"⚠️ Nvidia stream failed: {ne}. Falling back to Gemini...")
                    for chunk in client.models.generate_content_stream(**stream_kwargs):
                        piece = getattr(chunk, "text", None)
                        if piece:
                            full_text += piece
                            yield ("chunk", piece)
            else:
                for chunk in client.models.generate_content_stream(**stream_kwargs):
                    piece = getattr(chunk, "text", None)
                    if piece:
                        full_text += piece
                        yield ("chunk", piece)
        except Exception as e:
            log.error(f"Stream API Error: {e}")
            yield ("error", f"Stream error: {str(e)}")
            return

        if not full_text:
            full_text = "উত্তর তৈরি করা যায়নি।"
            yield ("chunk", full_text)

        result = {
            "answer":       full_text,
            "from_library": bool(context),
            "from_cache":   bool(gemini_cache_name),
        }


        yield ("done", result)

    except Exception as e:
        log.error(f"❌ Gemini streaming ত্রুটি: {e}")
        yield ("error", f"AI সমস্যা: {str(e)}")


# ══════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/classes", methods=["GET"])
def get_classes():
    return jsonify({"success": True, "data": CLASSES})


@app.route("/api/mcq/generate", methods=["POST"])
def generate_mcq():
    client = _get_client()
    if not client:
        return jsonify({"success": False, "error": "❌ API Key সেট করা হয়নি"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "❌ JSON ডেটা পাওয়া যায়নি"}), 400

    class_id   = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()
    topic      = data.get("topic", "").strip()
    count      = data.get("count", 5)

    if not class_id or not subject_id or not topic:
        return jsonify({"success": False, "error": "❌ class_id, subject_id এবং topic আবশ্যক"}), 400

    count = max(1, min(int(count), 20))

    cache_key = f"mcq_{class_id}_{subject_id}_{topic}_{count}"
    cached = _find_in_cache(cache_key)
    if cached:
        return jsonify({"success": True, "data": cached, "from_cache": True})

    cls = CLASSES.get(class_id, {})
    class_label = cls.get("label", class_id)
    subj_info = get_subject_info(class_id, subject_id)
    if not subj_info:
        return jsonify({"success": False, "error": f"❌ '{subject_id}' বিষয় পাওয়া যায়নি"}), 404
    subject_bn = subj_info.get("bn", subject_id)

    chunks = _search_json_library(class_id, subject_id, topic)
    context = _build_context(chunks)
    from_library = bool(context)

    prompt = MCQ_GENERATE_PROMPT.format(
        class_label=class_label,
        subject_bn=subject_bn,
        topic=topic,
        count=count
    )
    full_prompt = f"তথ্য:\n{context}\n\n{prompt}" if context else \
                  f"{prompt}\n\n(নোট: লাইব্রেরিতে তথ্য নেই, নিজের জ্ঞান থেকে তৈরি করো)"

    try:
        model_name = DEFAULT_MODEL
        model_info = MODELS.get(model_name, {})

        response = client.models.generate_content(
            model=model_name,
            contents=full_prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=MAX_OUTPUT_LONG,
                temperature=0.5,
            )
        )

        raw_text = response.text if response.text else ""
        json_text = re.sub(r'^```(?:json)?\s*', '', raw_text.strip())
        json_text = re.sub(r'\s*```$', '', json_text)

        try:
            mcq_list = json.loads(json_text)
        except json.JSONDecodeError:
            match = re.search(r'\[.*\]', raw_text, re.DOTALL)
            if match:
                mcq_list = json.loads(match.group())
            else:
                return jsonify({"success": False, "error": "❌ MCQ ফরম্যাট পার্স করা যায়নি"}), 500

        note = "" if from_library else "⚠️ লাইব্রেরিতে ডেটা পাওয়া যায়নি — AI এর জ্ঞান থেকে তৈরি"
        result = {
            "questions": mcq_list,
            "mcqs": mcq_list,
            "topic": topic,
            "count": len(mcq_list),
            "from_library": from_library,
            "note": note
        }
        _save_to_cache(cache_key, result)


        return jsonify({"success": True, **result, "data": result})

    except Exception as e:
        log.error(f"❌ MCQ Generation ত্রুটি: {e}")
        return jsonify({"success": False, "error": f"MCQ তৈরিতে সমস্যা: {str(e)}"}), 500


@app.route("/api/mcq/deduplicate", methods=["POST"])
def api_deduplicate_mcqs():
    """
    POST /api/mcq/deduplicate
    Body: { class_id, subject_id }

    একই subject এর duplicate MCQ খুঁজে merge করো।
    DB import এর পরে call করো।
    """
    data       = request.get_json() or {}
    class_id   = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()

    if not class_id or not subject_id:
        return jsonify({"error": "class_id ও subject_id দরকার"}), 400

    try:
        result = _deduplicate_mcqs(class_id, subject_id)
        return jsonify({"success": True, **result})
    except Exception as e:
        log.error("deduplicate error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/mcq/frequency-analysis", methods=["GET"])
def api_frequency_analysis():
    """
    GET /api/mcq/frequency-analysis
      ?class_id=ssc&subject_id=physics&board=ঢাকা (optional)

    Chapter-wise MCQ frequency + repeated questions + prediction hints।
    """
    class_id   = request.args.get("class_id", "").strip()
    subject_id = request.args.get("subject_id", "").strip()
    board      = request.args.get("board", "").strip() or None

    if not class_id or not subject_id:
        return jsonify({"error": "class_id ও subject_id দরকার"}), 400

    try:
        result = _mcq_frequency_analysis(class_id, subject_id, board)
        return jsonify({"success": True, **result})
    except Exception as e:
        log.error("frequency analysis error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/mcq/smart", methods=["POST"])
def smart_mcq():
    """
    Smart MCQ — chapter + mode (board/unique/all) filter সহ।
    শুধু MCQ content_type chunk পাঠায় Gemini কে → token সাশ্রয়।
    """
    client = _get_client()
    if not client:
        return jsonify({"success": False, "error": "❌ API Key সেট করা হয়নি"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "❌ JSON ডেটা পাওয়া যায়নি"}), 400

    class_id   = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()
    chapter    = data.get("chapter", "").strip()   # "অধ্যায় ২" বা খালি = সব
    chapter_num = data.get("chapter_num")          # exact chapter match এর জন্য (integer, optional)
    mode       = data.get("mode", "board").strip() # board | unique | all
    count      = int(data.get("count", 10))
    count      = max(1, min(count, 30))
    # source_type: "all" | "board_book" | "test_paper" | "guide"
    # "board" mode এ test_paper ও board_book দুটোই আসে
    source_type = data.get("source_type", "all").strip()
    board_name  = data.get("board_name", "").strip()   # "ঢাকা", "চট্টগ্রাম" বা ""
    board_year  = data.get("board_year", "").strip()   # "2022", "2023" বা ""

    if not class_id or not subject_id:
        return jsonify({"success": False, "error": "❌ class_id, subject_id আবশ্যক"}), 400

    cls        = CLASSES.get(class_id, {})
    class_label = cls.get("label", class_id)
    subj_info  = get_subject_info(class_id, subject_id)
    subject_bn = subj_info.get("bn", subject_id) if subj_info else subject_id

    # source_type resolve — "all" মানে filter নেই
    src_filter = None if source_type == "all" else source_type

    # unique mode এ সব source থেকে খোঁজো (বেশি variety)
    if mode == "unique":
        src_filter = None

    # board/year filter — unique mode এ ignore করো
    bn_filter = board_name if mode != "unique" else None
    by_filter = board_year if mode != "unique" else None

    # শুধু MCQ content_type খোঁজো — token বাঁচে
    query = f"{subject_bn} {chapter} mcq বহুনির্বাচনী"
    chunks = _search_json_library(
        class_id, subject_id, query,
        top_n=15,
        content_type="mcq",
        chapter=chapter if chapter else None,
        chapter_num=chapter_num,
        source_type=src_filter,
        board_name=bn_filter,
        board_year=by_filter
    )
    context = _build_context(chunks)

    # mode অনুযায়ী prompt তৈরি
    if mode == "board":
        src_label = {
            "test_paper": "বোর্ড প্রশ্নপত্র থেকে",
            "guide":      "গাইড বই থেকে",
            "board_book": "পাঠ্যবই থেকে",
        }.get(source_type, "বোর্ড পরীক্ষায়")
        mode_instruction = (
            f"{src_label} বারবার আসা সবচেয়ে গুরুত্বপূর্ণ MCQ দাও। "
            "প্রতিটিতে উল্লেখ করো: কোন বোর্ড ও সালে এসেছিল (জানা থাকলে), "
            "কেন এটা গুরুত্বপূর্ণ, এবং explanation-এ concept টি ভালোভাবে বুঝিয়ে দাও। "
            "সবচেয়ে বেশিবার যে MCQ এসেছে সেগুলো আগে দাও।"
        )
    elif mode == "unique":
        mode_instruction = (
            "পূর্বে কোনো বোর্ড পরীক্ষায় আসেনি এমন সম্পূর্ণ নতুন MCQ তৈরি করো। "
            "প্রশ্নগুলো application-based ও conceptually deep হবে — শুধু সংজ্ঞা নয়, "
            "real-life scenario বা unusual angle থেকে বইয়ের concept test করবে। "
            "প্রতিটি option plausible কিন্তু শুধু একটিই সঠিক। "
            "explanation-এ বিস্তারিত কারণ দাও কেন সঠিক উত্তরটি সঠিক। "
            "যদি database এ যথেষ্ট data না থাকে, তাহলে পাঠ্যবইয়ের গভীর জ্ঞান থেকে তৈরি করো।"
        )
    else:
        mode_instruction = "গুরুত্বপূর্ণ ও বৈচিত্র্যময় MCQ দাও।"

    chapter_instruction = f"শুধু '{chapter}' থেকে দাও।" if chapter else "সব অধ্যায় থেকে দিতে পারো।"

    # unique mode এ context না থাকলে Gemini কে বলো নিজে তৈরি করতে
    if mode == "unique" and not context:
        gemini_note = (
            f"\n\n⚠️ Database এ পর্যাপ্ত প্রশ্ন নেই। তুমি {class_label} {subject_bn} এর "
            f"expert হিসেবে নিজের জ্ঞান থেকে {count}টি মৌলিক, চমকপ্রদ MCQ তৈরি করো। "
            f"প্রশ্নগুলো সঠিক ও পরীক্ষাযোগ্য হতে হবে।"
        )
    else:
        gemini_note = ""

    prompt = (
        f"তুমি {class_label} {subject_bn} পরীক্ষার একজন expert প্রশ্নকর্তা।\n"
        f"{chapter_instruction}\n"
        f"{mode_instruction}\n"
        f"মোট {count}টি high-quality MCQ দাও।\n\n"
        f"**অতি গুরুত্বপূর্ণ নির্দেশ:** প্রতিটি MCQ তৈরি করার সময় উত্তরের সঠিকতা প্রদত্ত তথ্যের সাথে ১০০% নিশ্চিত হয়ে তারপরই আউটপুট দেবে। কোনো ভুল বা সন্দেহজনক উত্তর দেওয়া যাবে না।\n\n"
        f"প্রতিটি MCQ এর JSON format (exactly এভাবে):\n"
        f"{{\n"
        f"  \"question\": \"স্পষ্ট ও নির্ভুল প্রশ্ন\",\n"
        f"  \"options\": [\"ক) ...\", \"খ) ...\", \"গ) ...\", \"ঘ) ...\"],\n"
        f"  \"answer\": \"ক\",\n"
        f"  \"explanation\": \"বিস্তারিত ব্যাখ্যা কেন সঠিক উত্তর সঠিক\",\n"
        f"  \"chapter\": \"অধ্যায়ের নাম\",\n"
        f"  \"difficulty\": \"easy/medium/hard\",\n"
        f"  \"board_note\": \"কোন বোর্ডে কত সালে এসেছে (না জানলে খালি string)\"\n"
        f"}}\n\n"
        f"নিয়ম:\n"
        f"- শুধু JSON array রিটার্ন করো, কোনো markdown বা extra text না\n"
        f"- প্রতিটি option unique ও plausible হবে\n"
        f"- explanation অবশ্যই বাংলায় ও বিস্তারিত হবে"
        f"{gemini_note}"
    )

    if context:
        full_prompt = f"পাঠ্যবই/গাইড থেকে MCQ তথ্য:\n{context}\n\n{prompt}"
    else:
        full_prompt = prompt

    # ── Step15 context cache (IM-7) ──────────────────────────────────
    gemini_cache_name = None
    try:
        from features.step15_cache import get_cached_content
        gemini_cache_name = get_cached_content(class_id, subject_id)
    except Exception:
        pass

    try:
        # ── Thinking mode: Gemini reason করে তারপর MCQ দেয় ──────────
        response = _think_call(
            client, full_prompt,
            cached_content=gemini_cache_name
        )
        raw = response.text.strip() if response.text else "[]"
        mcq_list = _parse_json_response(raw) or []

        return jsonify({
            "success":      True,
            "questions":    mcq_list,
            "count":        len(mcq_list),
            "mode":         mode,
            "source_type":  source_type,
            "chapter":      chapter or "সব অধ্যায়",
            "from_library": bool(context),
            "gemini_generated": not bool(context) and mode == "unique",
            "verified":     True,
        })
    except Exception as e:
        log.error(f"❌ Smart MCQ ত্রুটি: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/cq/smart", methods=["POST"])
def smart_cq():
    """
    Smart CQ — chapter filter + board/unique mode।
    শুধু CQ content_type chunk পাঠায় → token সাশ্রয়।
    """
    client = _get_client()
    if not client:
        return jsonify({"success": False, "error": "❌ API Key সেট করা হয়নি"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "❌ JSON ডেটা পাওয়া যায়নি"}), 400

    class_id   = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()
    chapter    = data.get("chapter", "").strip()
    mode       = data.get("mode", "board").strip()  # board | unique | practice
    count      = int(data.get("count", 3))
    count      = max(1, min(count, 10))
    # source_type: "all" | "board_book" | "test_paper" | "guide"
    source_type = data.get("source_type", "all").strip()
    board_name  = data.get("board_name", "").strip()   # "ঢাকা", "চট্টগ্রাম" বা ""
    board_year  = data.get("board_year", "").strip()   # "2022", "2023" বা ""

    if not class_id or not subject_id:
        return jsonify({"success": False, "error": "❌ class_id, subject_id আবশ্যক"}), 400

    cls        = CLASSES.get(class_id, {})
    class_label = cls.get("label", class_id)
    subj_info  = get_subject_info(class_id, subject_id)
    subject_bn = subj_info.get("bn", subject_id) if subj_info else subject_id

    # source_type resolve
    src_filter = None if source_type == "all" else source_type
    if mode == "unique":
        src_filter = None  # unique mode এ সব source থেকে খোঁজো

    # board/year filter — unique mode এ ignore করো
    bn_filter = board_name if mode != "unique" else None
    by_filter = board_year if mode != "unique" else None

    # শুধু CQ content_type খোঁজো
    query = f"{subject_bn} {chapter} সৃজনশীল উদ্দীপক"
    chunks = _search_json_library(
        class_id, subject_id, query,
        top_n=8,
        content_type="cq",
        chapter=chapter if chapter else None,
        source_type=src_filter,
        board_name=bn_filter,
        board_year=by_filter
    )
    context = _build_context(chunks)

    if mode == "board":
        src_label = {
            "test_paper": "বোর্ড প্রশ্নপত্র থেকে",
            "guide":      "গাইড বই থেকে",
            "board_book": "পাঠ্যবই থেকে",
        }.get(source_type, "বোর্ড পরীক্ষায়")
        mode_instruction = f"{src_label} আসা ধাঁচের CQ দাও। বাস্তব উদ্দীপক ব্যবহার করো।"
    elif mode == "unique":
        mode_instruction = (
            "নতুন ও চমকপ্রদ উদ্দীপক দিয়ে CQ তৈরি করো যা সাধারণত দেখা যায় না। "
            "যদি database এ যথেষ্ট CQ না থাকে, তাহলে তোমার নিজের জ্ঞান থেকে "
            "মৌলিক ও বাস্তবসম্মত উদ্দীপক দিয়ে CQ তৈরি করো।"
        )
    else:
        mode_instruction = "অনুশীলনের জন্য সহজ থেকে কঠিন ক্রমে CQ দাও।"

    chapter_instruction = f"'{chapter}' অধ্যায় থেকে।" if chapter else "যেকোনো গুরুত্বপূর্ণ অধ্যায় থেকে।"

    # unique mode এ context না থাকলে Gemini কে বলো নিজে তৈরি করতে
    if mode == "unique" and not context:
        gemini_note = (
            f"\n\n⚠️ Database এ পর্যাপ্ত CQ নেই। তুমি {class_label} {subject_bn} এর "
            f"expert হিসেবে নিজের জ্ঞান থেকে {count}টি মৌলিক সৃজনশীল প্রশ্ন তৈরি করো। "
            f"উদ্দীপক অবশ্যই বাস্তবসম্মত ও বিষয়ভিত্তিক হতে হবে।"
        )
    else:
        gemini_note = ""

    prompt = (
        f"তুমি {class_label} {subject_bn} এর CQ বিশেষজ্ঞ।\n"
        f"{chapter_instruction} {mode_instruction}\n"
        f"মোট {count}টি সৃজনশীল প্রশ্ন দাও।\n\n"
        f"প্রতিটি CQ format:\n"
        f"{{\"chapter\": \"অধ্যায়\", \"stimulus\": \"উদ্দীপক\", "
        f"\"parts\": [{{\"label\": \"ক\", \"text\": \"প্রশ্ন\", \"marks\": 1}}, "
        f"{{\"label\": \"খ\", \"text\": \"প্রশ্ন\", \"marks\": 2}}, "
        f"{{\"label\": \"গ\", \"text\": \"প্রশ্ন\", \"marks\": 3}}, "
        f"{{\"label\": \"ঘ\", \"text\": \"প্রশ্ন\", \"marks\": 4}}]}}\n\n"
        f"শুধু JSON array রিটার্ন করো।"
        f"{gemini_note}"
    )

    if context:
        full_prompt = f"পাঠ্যবই/গাইড থেকে CQ তথ্য:\n{context}\n\n{prompt}"
    else:
        full_prompt = prompt

    # ── Step15 context cache (IM-7) ──────────────────────────────────
    gemini_cache_name = None
    try:
        from features.step15_cache import get_cached_content
        gemini_cache_name = get_cached_content(class_id, subject_id)
    except Exception:
        pass

    try:
        # ── Thinking mode: CQ accuracy উন্নত করে ────────────────────
        response = _think_call(
            client, full_prompt,
            cached_content=gemini_cache_name
        )
        raw = response.text.strip() if response.text else "[]"
        cq_list = _parse_json_response(raw) or []

        return jsonify({
            "success":      True,
            "questions":    cq_list,
            "count":        len(cq_list),
            "mode":         mode,
            "source_type":  source_type,
            "chapter":      chapter or "সব অধ্যায়",
            "from_library": bool(context),
            "gemini_generated": not bool(context) and mode == "unique",
        })
    except Exception as e:
        log.error(f"❌ Smart CQ ত্রুটি: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/cq/list", methods=["GET"])
def list_cq():
    class_id   = request.args.get("class_id", "").strip()
    subject_id = request.args.get("subject_id", "").strip()
    chapter    = request.args.get("chapter", "").strip()
    source     = request.args.get("source", "all").strip()  # all | guide | test_paper | board_book
    board_name = request.args.get("board_name", "").strip()  # "ঢাকা" বা ""
    board_year = request.args.get("board_year", "").strip()  # "2022" বা ""

    if not class_id or not subject_id:
        return jsonify({"success": False, "error": "❌ class_id এবং subject_id আবশ্যক"}), 400

    cq_list = []

    try:
        conn = get_db()

        # ── ১. cq_model_answers থেকে (guide এর structured CQ) ──────────
        if source in ("all", "guide"):
            where = ["class_id=?", "subject_id=?"]
            params = [class_id, subject_id]
            if chapter:
                where.append("chapter=?")
                params.append(chapter)
            if board_name:
                where.append("board_name=?")
                params.append(board_name)
            if board_year:
                where.append("board_year=?")
                params.append(board_year)

            rows = conn.execute(
                f"SELECT * FROM cq_model_answers WHERE {' AND '.join(where)} ORDER BY chapter_num, id",
                params
            ).fetchall()

            LBL_MAP = {"ক": "ka", "খ": "kha", "গ": "ga", "ঘ": "gha"}
            for r in rows:
                parts = []
                for lbl, q, marks in [("ক", r["question_ka"], 1), ("খ", r["question_kha"], 2),
                                       ("গ", r["question_ga"], 3), ("ঘ", r["question_gha"], 4)]:
                    if q:
                        col = LBL_MAP[lbl]
                        parts.append({"label": lbl, "text": q, "marks": marks,
                                      "model_answer": r[f"answer_{col}"] or ""})
                cq_list.append({
                    "id":          r["id"],
                    "chapter":     r["chapter"],
                    "chapter_num": r["chapter_num"],
                    "stimulus":    r["stimulus"],
                    "parts":       parts,
                    "source_type": r["source_type"],
                    "board_name":  r["board_name"],
                    "board_year":  r["board_year"],
                    "has_model_answer": bool(r["answer_ka"] or r["answer_kha"]),
                })

        # ── ২. pdf_content থেকে (test_paper এর raw CQ) ─────────────────
        if source in ("all", "test_paper", "board_book"):
            src_filter = None if source == "all" else source
            chunks = _db_search_fts(class_id, subject_id, "সৃজনশীল উদ্দীপক",
                                    top_n=50, content_type="cq",
                                    chapter=chapter or None,
                                    source_type=src_filter,
                                    board_name=board_name or None,
                                    board_year=board_year or None)
            for chunk in chunks:
                cq_list.append({
                    "chapter":     chunk.get("chapter", ""),
                    "stimulus":    chunk.get("text", ""),
                    "parts":       [],
                    "source_type": chunk.get("source_type", ""),
                    "board_name":  chunk.get("board_name", ""),
                    "board_year":  chunk.get("board_year", ""),
                    "has_model_answer": False,
                })

        conn.close()

    except Exception as e:
        log.error(f"CQ list error for {class_id}/{subject_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({
        "success":   True,
        "questions": cq_list,
        "data":      cq_list,
        "total":     len(cq_list),
    })


@app.route("/api/cq/ask", methods=["POST"])
def ask_cq():
    client = _get_client()
    if not client:
        return jsonify({"success": False, "error": "❌ API Key সেট করা হয়নি"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "❌ JSON ডেটা পাওয়া যায়নি"}), 400

    class_id   = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()
    question   = data.get("question", "").strip()

    if not class_id or not subject_id or not question:
        return jsonify({"success": False, "error": "❌ class_id, subject_id এবং question আবশ্যক"}), 400

    chunks = _search_json_library(class_id, subject_id, question)
    context = _build_context(chunks)
    result = build_answer(question, context, class_id, subject_id)

    if "error" in result:
        return jsonify({"success": False, "error": result["error"]}), 500

    sources = [chunk.get("source", "") for chunk in chunks] if chunks else []
    return jsonify({
        "success": True,
        "answer": result.get("answer", ""),
        "from_library": result.get("from_library", False),
        "sources": sources,
        "data": {
            "answer": result.get("answer", ""),
            "from_library": result.get("from_library", False),
            "sources": sources,
        }
    })


@app.route("/api/cq/model-answer", methods=["POST"])
def cq_model_answer():
    """
    CQ মডেল উত্তর পাও — প্রথমে cq_model_answers table এ খোঁজো।
    পাওয়া না গেলে Gemini API কল করে জেনারেট করো।
    """
    client = _get_client()
    if not client:
        return jsonify({"success": False, "error": "❌ API Key সেট করা হয়নি"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "❌ JSON ডেটা পাওয়া যায়নি"}), 400

    class_id     = data.get("class_id", "").strip()
    subject_id   = data.get("subject_id", "").strip()
    stimulus     = data.get("stimulus", "").strip()
    question_ka  = data.get("question_ka", "").strip()
    question_kha = data.get("question_kha", "").strip()
    question_ga  = data.get("question_ga", "").strip()
    question_gha = data.get("question_gha", "").strip()
    chapter      = data.get("chapter", "").strip()
    chapter_num  = data.get("chapter_num")

    if not class_id or not subject_id:
        return jsonify({"success": False, "error": "❌ class_id এবং subject_id আবশ্যক"}), 400

    # ১. DB-তে মডেল উত্তর খোঁজো
    try:
        conn = get_db()
        where = ["class_id=?", "subject_id=?"]
        params = [class_id, subject_id]

        if stimulus:
            where.append("stimulus LIKE ?")
            params.append(f"%{stimulus[:100]}%")
        elif chapter:
            where.append("chapter=?")
            params.append(chapter)
        if chapter_num is not None:
            where.append("chapter_num=?")
            params.append(chapter_num)

        row = conn.execute(
            f"""SELECT * FROM cq_model_answers
                WHERE {' AND '.join(where)}
                ORDER BY id DESC LIMIT 1""",
            params
        ).fetchone()
        conn.close()

        if row and (row["answer_ka"] or row["answer_kha"] or row["answer_ga"] or row["answer_gha"]):
            LBL_BN = {"ka": "ক", "kha": "খ", "ga": "গ", "gha": "ঘ"}
            parts = []
            for lbl in ["ka", "kha", "ga", "gha"]:
                q = row[f"question_{lbl}"]
                a = row[f"answer_{lbl}"]
                if q or a:
                    parts.append({
                        "label": LBL_BN[lbl],
                        "question": q,
                        "model_answer": a
                    })
            return jsonify({
                "success": True,
                "from_db": True,
                "stimulus": row["stimulus"],
                "parts": parts,
                "source_type": row["source_type"],
                "board_name": row["board_name"],
                "board_year": row["board_year"],
                "tokens_used": 0
            })

    except Exception as e:
        log.warning("Model answer DB lookup failed: %s", e)

    # ২. DB-তে পাওয়া গেলে না — Gemini API কল করো
    prompt_parts = []
    if stimulus:
        prompt_parts.append(f"উদ্দীপক:\n{stimulus}")
    for lbl, q in [("ক", question_ka), ("খ", question_kha), ("গ", question_ga), ("ঘ", question_gha)]:
        if q:
            prompt_parts.append(f"({lbl}) {q}")

    full_question = "\n\n".join(prompt_parts)
    if not full_question:
        return jsonify({"success": False, "error": "❌ উদ্দীপক বা প্রশ্ন দেওয়া হয়নি"}), 400

    # Context search for better answer — chapter_num pass করা হচ্ছে exact match এর জন্য
    chunks = _search_json_library(
        class_id, subject_id, full_question,
        top_n=5,
        chapter=chapter or None,
        chapter_num=chapter_num
    )
    context = _build_context(chunks)

    cls = CLASSES.get(class_id, {})
    class_label = cls.get("label", class_id)
    subj_info = get_subject_info(class_id, subject_id)
    subject_bn = subj_info.get("bn", subject_id) if subj_info else subject_id

    system_prompt = f"""আপনি {class_label} - {subject_bn} বিষয়ের অভিজ্ঞ শিক্ষক।
প্রদত্ত উদ্দীপক ও প্রশ্নের ভিত্তিতে নির্ভুল, সংক্ষিপ্ত ও মানক মডেল উত্তর দিন।
উত্তর বাংলায় দিন। প্রতিটি প্রশ্নের জন্য পৃথক পৃথক উত্তর দিন।"""

    user_prompt = f"তথ্য:\n{context}\n\n{full_question}\n\nউপরোক্ত প্রশ্নের মডেল উত্তর দিন।"

    try:
        model_name = DEFAULT_MODEL
        model_info = MODELS.get(model_name, {})

        gen_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=MAX_OUTPUT_LONG,
            temperature=0.2,
        )

        response = client.models.generate_content(
            model=model_name,
            contents=user_prompt,
            config=gen_config
        )

        answer_text = response.text if response.text else "উত্তর তৈরি করা যায়নি।"

        # Parse the generated answer into parts
        LBL_MAP = {"ক": "ka", "খ": "kha", "গ": "ga", "ঘ": "gha"}
        q_vars = {"ka": question_ka, "kha": question_kha, "ga": question_ga, "gha": question_gha}
        parts = []
        for lbl in ["ক", "খ", "গ", "ঘ"]:
            pattern = rf'\(?{lbl}\)?\s*(.+?)(?=\(?[কখগঘ]\)?|$)'
            matches = re.findall(pattern, answer_text, re.DOTALL)
            if matches:
                parts.append({
                    "label": lbl,
                    "question": q_vars.get(LBL_MAP[lbl], ""),
                    "model_answer": matches[0].strip()
                })



        return jsonify({
            "success": True,
            "from_db": False,
            "stimulus": stimulus,
            "parts": parts,
            "tokens_used": "gemini",
            "raw_answer": answer_text
        })

    except Exception as e:
        log.error(f"❌ Model answer generation error: {e}")
        return jsonify({"success": False, "error": f"AI সমস্যা: {str(e)}"}), 500


# ═════════════════════════════════════════════════════════
#  MCQ REVIEW SCHEDULE (S-2) — Spaced Repetition APIs
#  SuperMemo-2 (SM-2) algorithm ব্যবহার করা হচ্ছে।
# ═════════════════════════════════════════════════════════

def _sm2_update(repetitions, ease_factor, interval_days, quality):
    """SuperMemo-2 algorithm — quality 0-5 (0=ভুল, 5=নিখুঁত)।"""
    if quality < 3:
        repetitions = 0
        interval_days = 1
    else:
        repetitions += 1
        if repetitions == 1:
            interval_days = 1
        elif repetitions == 2:
            interval_days = 6
        else:
            interval_days = int(interval_days * ease_factor)

    ease_factor = max(1.3, ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))

    next_review = (datetime.datetime.now() + datetime.timedelta(days=interval_days)).strftime("%Y-%m-%d")
    return repetitions, ease_factor, interval_days, next_review


@app.route("/api/mcq-review/schedule", methods=["POST"])
def schedule_mcq_review():
    """MCQ কে review schedule এ যোগ করো (S-2 feature)।"""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "❌ JSON ডেটা পাওয়া যায়নি"}), 400

    class_id   = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()
    mcq_id     = data.get("mcq_id")

    if not class_id or not subject_id or not mcq_id:
        return jsonify({"success": False, "error": "❌ class_id, subject_id এবং mcq_id আবশ্যক"}), 400

    try:
        with _db_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM mcq_review_schedule WHERE class_id=? AND subject_id=? AND mcq_id=?",
                (class_id, subject_id, mcq_id)
            ).fetchone()

            today = datetime.datetime.now().strftime("%Y-%m-%d")

            if existing:
                conn.execute(
                    """UPDATE mcq_review_schedule
                       SET next_review=?, interval_days=1, ease_factor=2.5,
                           repetitions=0, last_reviewed=NULL
                       WHERE id=?""",
                    (today, existing["id"])
                )
                return jsonify({
                    "success": True,
                    "action": "rescheduled",
                    "schedule_id": existing["id"],
                    "next_review": today
                })
            else:
                cur = conn.execute(
                    """INSERT INTO mcq_review_schedule
                       (class_id, subject_id, mcq_id, next_review,
                        interval_days, ease_factor, repetitions)
                       VALUES (?,?,?,?,?,?,?)""",
                    (class_id, subject_id, mcq_id, today, 1, 2.5, 0)
                )
                return jsonify({
                    "success": True,
                    "action": "created",
                    "schedule_id": cur.lastrowid,
                    "next_review": today
                })
    except Exception as e:
        log.error("Schedule MCQ error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/mcq-review/mark", methods=["POST"])
def mark_mcq_reviewed():
    """MCQ review সম্পন্ন — quality score সহ SM-2 update।"""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "❌ JSON ডেটা পাওয়া যায়নি"}), 400

    class_id = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()
    mcq_id = data.get("mcq_id")
    quality = int(data.get("quality", 3))   # 0-5 scale

    if not class_id or not subject_id or not mcq_id:
        return jsonify({"success": False, "error": "❌ class_id, subject_id, mcq_id দরকার"}), 400

    quality = max(0, min(5, quality))

    try:
        with _db_conn() as conn:
            row = conn.execute(
                """SELECT * FROM mcq_review_schedule
                   WHERE class_id=? AND subject_id=? AND mcq_id=?""",
                (class_id, subject_id, mcq_id)
            ).fetchone()

            if not row:
                return jsonify({"success": False, "error": "❌ schedule এ নেই, আগে schedule করুন"}), 404

            reps, ef, interval, next_rev = _sm2_update(
                row["repetitions"] or 0,
                row["ease_factor"] or 2.5,
                row["interval_days"] or 1,
                quality
            )

            today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """UPDATE mcq_review_schedule
                   SET repetitions=?, ease_factor=?, interval_days=?,
                       next_review=?, last_reviewed=?
                   WHERE id=?""",
                (reps, ef, interval, next_rev, today, row["id"])
            )

            # MCQ stats আপডেট
            is_correct = 1 if quality >= 3 else 0
            conn.execute(
                """UPDATE mcq_bank
                   SET times_shown=times_shown+1,
                       times_correct=times_correct+?
                   WHERE id=?""",
                (is_correct, mcq_id)
            )

            return jsonify({
                "success": True,
                "schedule": {
                    "interval_days": interval,
                    "ease_factor": round(ef, 2),
                    "repetitions": reps,
                    "next_review": next_rev,
                    "quality": quality
                }
            })
    except Exception as e:
        log.error("Mark MCQ reviewed error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/mcq-review/due", methods=["GET"])
def get_due_reviews():
    """আজ due আছে এমন MCQ list দাও।"""
    class_id   = request.args.get("class_id", "").strip()
    subject_id = request.args.get("subject_id", "").strip()
    limit = int(request.args.get("limit", 20))

    if not class_id or not subject_id:
        return jsonify({"success": False, "error": "❌ class_id এবং subject_id আবশ্যক"}), 400

    limit = max(1, min(limit, 100))

    try:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        with _db_conn() as conn:
            rows = conn.execute(
                """SELECT mrs.*, mb.question, mb.option_a, mb.option_b, mb.option_c, mb.option_d,
                          mb.answer, mb.explanation, mb.chapter, mb.chapter_num
                   FROM mcq_review_schedule mrs
                   JOIN mcq_bank mb ON mb.id = mrs.mcq_id
                   WHERE mrs.class_id=? AND mrs.subject_id=? AND mrs.next_review <= ?
                   ORDER BY mrs.next_review ASC, mrs.repetitions ASC
                   LIMIT ?""",
                (class_id, subject_id, today, limit)
            ).fetchall()

            return jsonify({
                "success": True,
                "due_count": len(rows),
                "items": [{
                    "schedule_id":    r["id"],
                    "mcq_id":         r["mcq_id"],
                    "question":       r["question"],
                    "options": [r["option_a"], r["option_b"], r["option_c"], r["option_d"]],
                    "answer":         r["answer"],
                    "explanation":    r["explanation"],
                    "chapter":        r["chapter"],
                    "chapter_num":    r["chapter_num"],
                    "interval_days":  r["interval_days"],
                    "repetitions":    r["repetitions"],
                    "ease_factor":    r["ease_factor"],
                    "next_review":    r["next_review"],
                    "last_reviewed":  r["last_reviewed"]
                } for r in rows]
            })
    except Exception as e:
        log.error("Get due reviews error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/mcq-review/stats", methods=["GET"])
def get_review_stats():
    """User এর total scheduled/due/overdue stats।"""
    class_id   = request.args.get("class_id", "").strip()
    subject_id = request.args.get("subject_id", "").strip()

    if not class_id or not subject_id:
        return jsonify({"success": False, "error": "❌ class_id এবং subject_id আবশ্যক"}), 400

    try:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        with _db_conn() as conn:
            total_row = conn.execute(
                """SELECT COUNT(*) as total,
                          SUM(CASE WHEN next_review <= ? THEN 1 ELSE 0 END) as due,
                          SUM(CASE WHEN last_reviewed IS NOT NULL THEN 1 ELSE 0 END) as reviewed
                   FROM mcq_review_schedule
                   WHERE class_id=? AND subject_id=?""",
                (today, class_id, subject_id)
            ).fetchone()

            return jsonify({
                "success": True,
                "class_id": class_id,
                "subject_id": subject_id,
                "total_scheduled": total_row["total"] or 0,
                "due_today":       total_row["due"] or 0,
                "total_reviewed":  total_row["reviewed"] or 0
            })
    except Exception as e:
        log.error("Review stats error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


# ═════════════════════════════════════════════════════════
#  FLASHCARDS (S-3) — Generation / Review APIs
#  AI দিয়ে context থেকে Q/A flashcard জোড়া তৈরি করা হয়।
# ═════════════════════════════════════════════════════════

_FLASH_CARD_PROMPT = """প্রদত্ত context থেকে {count}টি ফ্ল্যাশকার্ড তৈরি করো।

ফ্ল্যাশকার্ডের ফরম্যাট:
- প্রশ্ন (front): সংক্ষিপ্ত, পরিষ্কার, একটি মূল ধারণা পরীক্ষা করে
- উত্তর (back): ১-৩ বাক্যে সম্পূর্ণ উত্তর

নিয়ম:
- শুধু গুরুত্বপূর্ণ সংজ্ঞা, সূত্র, ধারণা, কারণ-ফলাফল নাও
- প্রশ্ন যেন ১০-১৫ সেকেন্ডে পড়া যায়
- উত্তর যেন মুখস্থ করার যোগ্য হয়
- কোনো extra text/ব্যাখ্যা নয় — শুধু JSON array

JSON format (অন্য কিছু লিখো না):
[
  {{"question": "Q1", "answer": "A1"}},
  {{"question": "Q2", "answer": "A2"}}
]"""


@app.route("/api/flashcards/generate", methods=["POST"])
def generate_flashcards():
    """
    AI দিয়ে context থেকে flashcard generate করো।
    Body: { class_id, subject_id, chapter?, chapter_num?, topic?, count? }
    """
    client = _get_client()
    if not client:
        return jsonify({"success": False, "error": "❌ API Key সেট করা হয়নি"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "❌ JSON ডেটা পাওয়া যায়নি"}), 400

    class_id   = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()
    chapter    = data.get("chapter", "").strip()
    chapter_num = data.get("chapter_num")
    topic      = data.get("topic", "").strip() or chapter
    count      = int(data.get("count", 10))
    save       = bool(data.get("save", True))   # DB তে save করবে কিনা

    if not class_id or not subject_id:
        return jsonify({"success": False, "error": "❌ class_id এবং subject_id আবশ্যক"}), 400

    count = max(1, min(count, 30))

    # Cache key — same params এর জন্য একই response
    cache_key = f"flashcard_{class_id}_{subject_id}_{chapter}_{chapter_num}_{topic}_{count}"
    cached = _find_in_cache(cache_key)
    if cached:
        return jsonify({"success": True, "data": cached, "from_cache": True})

    # Context retrieve
    chunks = _search_json_library(
        class_id, subject_id, topic,
        chapter=chapter or None
    )
    context = _build_context(chunks)
    if not context:
        return jsonify({"success": False, "error": "❌ Context পাওয়া যায়নি"}), 404

    cls = CLASSES.get(class_id, {})
    class_label = cls.get("label", class_id)
    subj_info = get_subject_info(class_id, subject_id)
    subject_bn = subj_info.get("bn", subject_id) if subj_info else subject_id

    prompt = _FLASH_CARD_PROMPT.format(count=count)

    try:
        model_name = DEFAULT_MODEL
        model_info = MODELS.get(model_name, {})

        gen_config = types.GenerateContentConfig(
            system_instruction=f"তুমি {class_label} - {subject_bn} বিষয়ের শিক্ষক। ছোট, মুখস্থযোগ্য ফ্ল্যাশকার্ড তৈরি করো।",
            max_output_tokens=MAX_OUTPUT_LONG,
            temperature=0.3,
        )

        response = client.models.generate_content(
            model=model_name,
            contents=f"Context:\n{context}\n\n{prompt}",
            config=gen_config
        )

        raw_text = response.text if response.text else "[]"

        # JSON parse — robust error handling (codebase pattern অনুযায়ী)
        json_text = re.sub(r'^```(?:json)?\s*', '', raw_text.strip())
        json_text = re.sub(r'\s*```$', '', json_text)
        try:
            cards = json.loads(json_text)
        except json.JSONDecodeError:
            # Fallback: প্রথম [...] block extract
            m = re.search(r'\[\s*\{.*\}\s*\]', json_text, re.DOTALL)
            if not m:
                return jsonify({"success": False, "error": "AI valid JSON দেয়নি"}), 500
            try:
                cards = json.loads(m.group(0))
            except Exception:
                return jsonify({"success": False, "error": "JSON parse failed"}), 500

        if not isinstance(cards, list):
            cards = []

        # DB তে save (optional)
        saved_count = 0
        if save and cards:
            try:
                with _db_conn() as conn:
                    for c in cards:
                        q = (c.get("question") or "").strip()
                        a = (c.get("answer") or "").strip()
                        if not q or not a:
                            continue
                        # Duplicate check
                        exists = conn.execute(
                            "SELECT id FROM flashcards WHERE class_id=? AND subject_id=? AND question=?",
                            (class_id, subject_id, q[:500])
                        ).fetchone()
                        if exists:
                            continue
                        conn.execute(
                            """INSERT INTO flashcards
                               (class_id, subject_id, chapter, chapter_num,
                                question, answer, source_type)
                               VALUES (?,?,?,?,?,?,?)""",
                            (class_id, subject_id, chapter or "",
                             chapter_num, q[:1000], a[:2000], "board_book")
                        )
                        saved_count += 1
            except Exception as se:
                log.warning(f"Flashcard save partial error: {se}")

        result = {
            "cards_generated": len(cards),
            "saved_to_db":     saved_count,
            "cards":           cards
        }
        _save_to_cache(cache_key, result)


        return jsonify({
            "success": True,
            "data":    result,
            "context_sources": len(chunks)
        })

    except Exception as e:
        log.error(f"❌ Flashcard generation error: {e}")
        return jsonify({"success": False, "error": f"AI সমস্যা: {str(e)}"}), 500


@app.route("/api/flashcards/list", methods=["GET"])
def list_flashcards():
    """
    Flashcard list দেখাও — review/study mode এর জন্য।
    Query: ?class_id=...&subject_id=...&chapter=...&limit=20&random=true
    """
    class_id   = request.args.get("class_id", "").strip()
    subject_id = request.args.get("subject_id", "").strip()
    chapter    = request.args.get("chapter", "").strip()
    limit      = int(request.args.get("limit", 20))
    randomize  = request.args.get("random", "false").lower() == "true"

    if not class_id or not subject_id:
        return jsonify({"success": False, "error": "❌ class_id এবং subject_id আবশ্যক"}), 400

    limit = max(1, min(limit, 100))

    try:
        with _db_conn() as conn:
            where = ["class_id=?", "subject_id=?"]
            params = [class_id, subject_id]
            if chapter:
                where.append("chapter=?")
                params.append(chapter)

            order = "RANDOM()" if randomize else "id DESC"
            rows = conn.execute(
                f"""SELECT * FROM flashcards
                    WHERE {' AND '.join(where)}
                    ORDER BY {order}
                    LIMIT ?""",
                params + [limit]
            ).fetchall()

            return jsonify({
                "success": True,
                "total":   len(rows),
                "cards":   [{
                    "id":         r["id"],
                    "question":   r["question"],
                    "answer":     r["answer"],
                    "chapter":    r["chapter"],
                    "chapter_num": r["chapter_num"],
                    "difficulty": r["difficulty"],
                    "created_at": r["created_at"]
                } for r in rows]
            })
    except Exception as e:
        log.error("Flashcard list error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/flashcards/<int:card_id>", methods=["DELETE"])
def delete_flashcard(card_id):
    """একটি flashcard delete করো।"""
    try:
        with _db_conn() as conn:
            result = conn.execute(
                "DELETE FROM flashcards WHERE id=?",
                (card_id,)
            )
            if result.rowcount == 0:
                return jsonify({"success": False, "error": "❌ Card পাওয়া যায়নি"}), 404
            return jsonify({"success": True, "deleted_id": card_id})
    except Exception as e:
        log.error("Delete flashcard error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/flashcards/stats", methods=["GET"])
def flashcard_stats():
    """কোন subject/chapter এ কত card আছে — quick overview।"""
    class_id   = request.args.get("class_id", "").strip()
    subject_id = request.args.get("subject_id", "").strip()

    if not class_id or not subject_id:
        return jsonify({"success": False, "error": "❌ class_id এবং subject_id আবশ্যক"}), 400

    try:
        with _db_conn() as conn:
            rows = conn.execute(
                """SELECT chapter, chapter_num, COUNT(*) as total,
                          MIN(created_at) as first_created,
                          MAX(created_at) as last_created
                   FROM flashcards
                   WHERE class_id=? AND subject_id=?
                   GROUP BY chapter
                   ORDER BY chapter_num, chapter""",
                (class_id, subject_id)
            ).fetchall()

            total = conn.execute(
                "SELECT COUNT(*) FROM flashcards WHERE class_id=? AND subject_id=?",
                (class_id, subject_id)
            ).fetchone()[0]

            return jsonify({
                "success":     True,
                "class_id":    class_id,
                "subject_id":  subject_id,
                "total_cards": total,
                "by_chapter":  [{
                    "chapter":       r["chapter"],
                    "chapter_num":   r["chapter_num"],
                    "count":         r["total"],
                    "first_created": r["first_created"],
                    "last_created":  r["last_created"]
                } for r in rows]
            })
    except Exception as e:
        log.error("Flashcard stats error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


# ═════════════════════════════════════════════════════════
#  STUDENT FEEDBACK — RLHF Loop
#  ✅ Negative feedback automatically DB cache invalidate করে
# ═════════════════════════════════════════════════════════

@app.route("/api/feedback", methods=["POST"])
def student_feedback():
    """
    Student feedback নাও — positive/negative/neutral।
    Negative হলে cached answer invalidate হয়।
    Body: { class_id, subject_id, question, answer, feedback, score?, source? }
    """
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "❌ JSON ডেটা পাওয়া যায়নি"}), 400

    class_id   = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()
    question   = data.get("question", "").strip()
    answer     = data.get("answer", "").strip()
    feedback   = data.get("feedback", "neutral").strip()
    score      = data.get("score")
    source     = data.get("source", "thumb_btn").strip()

    if not question or not answer:
        return jsonify({"success": False, "error": "❌ question এবং answer দরকার"}), 400

    if feedback not in ("positive", "negative", "neutral"):
        return jsonify({"success": False, "error": "❌ feedback: positive | negative | neutral"}), 400

    _save_feedback(class_id, subject_id, question, answer, feedback, score, source)

    cache_invalidated = (feedback == "negative")

    return jsonify({
        "success":           True,
        "feedback":          feedback,
        "cache_invalidated": cache_invalidated,
        "message":           "ধন্যবাদ! আপনার মতামত আমাদের AI কে আরো ভালো করবে।"
    })


@app.route("/api/overall/ask", methods=["POST"])
def overall_ask():
    """
    যেকোনো প্রশ্ন করো — Subject select করা থাকলে সেটা ব্যবহার করো,
    না থাকলে LOCAL keyword matching দিয়ে detect করো।
    ✅ Gemini API call ছাড়াই subject detect — 50% token ও ~4 সেকেন্ড বাঁচে।
    ✅ Conversation history (session_id) ব্যবহার করে step-by-step context।
    """
    client = _get_client()
    if not client:
        return jsonify({"success": False, "error": "❌ API Key সেট করা হয়নি"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "❌ JSON ডেটা পাওয়া যায়নি"}), 400

    class_id = (data.get("class_id") or "").strip()
    group_id = (data.get("group_id") or "").strip()
    subject_id = (data.get("subject_id") or "").strip()
    question = (data.get("question") or "").strip()
    session_id = (data.get("session_id") or "").strip()  # ✅ NEW: Conversation history

    if not class_id or not question:
        return jsonify({"success": False, "error": "❌ class_id এবং question আবশ্যক"}), 400

    # ✅ FIX: chapter_num আগে undefined ছিল (NameError) — overall_ask_stream এর
    # মতো প্রশ্ন থেকে chapter number extract করো (অধ্যায়/chapter N)
    chapter_num = None
    m = re.search(r'(?:chapter|chap|অধ্যায়|অধ্যায়)\s*(\d+)', question.lower())
    if m:
        chapter_num = m.group(1)

    cache_key = f"overall_{class_id}_{group_id}_{subject_id}_{question}"
    # ✅ session_id থাকলে এটা চলমান কথোপকথনের অংশ — generic cache skip করো,
    # নাহলে আগের অন্য session এর উত্তর ফিরে এসে continuity ভাঙবে।
    if not session_id:
        cached = _find_in_cache(cache_key)
        if cached:
            return jsonify({"success": True, "data": cached, "from_cache": True})

    # ─── Subject決定 ─────────────────────────────────────────
    if subject_id:
        detected_subject = subject_id
        log.info(f"✅ Subject from UI: {detected_subject}")
    else:
        if group_id:
            cls = CLASSES.get(class_id, {})
            group = cls.get("groups", {}).get(group_id, {})
            filtered_subjects = {}
            for sid, sinfo in group.get("subjects", {}).items():
                filtered_subjects[sid] = sinfo
            for sid, sinfo in group.get("4th_subjects", {}).items():
                filtered_subjects[sid] = sinfo
            common = cls.get("groups", {}).get("common", {})
            for sid, sinfo in common.get("subjects", {}).items():
                filtered_subjects[sid] = sinfo
            subject_keys = list(filtered_subjects.keys())
        else:
            subject_keys = list(get_all_subjects(class_id).keys())

        detected_subject = detect_subject_locally(question, subject_keys)

        if not detected_subject:
            detected_subject = subject_keys[0] if subject_keys else "bangla_1"
            log.info(f"⚠️ Subject detect হয়নি, default: {detected_subject}")
        else:
            log.info(f"✅ Subject detected locally: {detected_subject}")

    # ─── Conversation History Load ──────────────────────────
    # ✅ history_context কে আর প্লেইন টেক্সট হিসেবে context-এর সাথে মেশানো হচ্ছে না।
    # বরং role-based history সরাসরি build_answer-কে দেওয়া হবে, যাতে Gemini
    # প্রতিটা আগের turn ঠিকভাবে বুঝতে পারে এবং পুনরাবৃত্তি না করে এগিয়ে যায়।
    history = []
    if session_id:
        history = _conv_load(session_id, limit=6)  # Last 6 messages
        if history:
            log.info(f"📜 Loaded {len(history)} history messages for session {session_id}")

    # ─── Smart RAG: Function Calling দিয়ে search + answer ────────────
    # HTTP-1: Gemini keyword বের করে → FTS search → HTTP-2: answer
    detected_source_types = _detect_source_types(question)
    result = _fc_search_and_answer(
        question       = question,
        class_id       = class_id,
        subject_id     = detected_subject,
        history        = history,
        chapter_num    = chapter_num,
        source_type    = detected_source_types,
    )
    chunks = []  # FC internally handles chunks

    if "error" in result:
        return jsonify({"success": False, "error": result["error"]}), 500

    # Save to conversation history (Gemini role: "user" / "model")
    if session_id:
        _conv_save(session_id, class_id, detected_subject, "user", question)
        _conv_save(session_id, class_id, detected_subject, "model", result.get("answer", ""))

    subj_info = get_subject_info(class_id, detected_subject)
    sources = list(set([chunk.get("source", "") for chunk in chunks])) if chunks else []

    final_result = {
        "answer": result.get("answer", ""),
        "detected_subject": detected_subject,
        "detected_subject_bn": subj_info.get("bn", detected_subject) if subj_info else detected_subject,
        "from_library": result.get("from_library", False),
        "sources": sources,
    }

    if not session_id:
        _save_to_cache(cache_key, final_result)

    return jsonify({
        "success": True,
        **final_result,
        "data": final_result
    })


@app.route("/api/overall/ask/stream", methods=["POST"])
def overall_ask_stream():
    """
    ✅ NEW (IM-9): overall_ask এর streaming ভার্সন।
    Gemini যেভাবে token পাঠায় সেভাবেই Server-Sent Events (SSE) দিয়ে
    frontend-কে পাঠানো হয় — real "টাইপ হচ্ছে" effect।

    Event ফরম্যাট (প্রতিটা "data: {...}\\n\\n"):
      {"type":"meta",  detected_subject, detected_subject_bn, sources, from_library}
      {"type":"chunk", "text": "..."}      -- বারবার আসবে
      {"type":"done"}
      {"type":"error", "message": "..."}
    """
    client = _get_client()
    if not client:
        return jsonify({"success": False, "error": "❌ API Key সেট করা হয়নি"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "❌ JSON ডেটা পাওয়া যায়নি"}), 400

    class_id   = (data.get("class_id") or "").strip()
    group_id   = (data.get("group_id") or "").strip()
    subject_id = (data.get("subject_id") or "").strip()
    question   = (data.get("question") or "").strip()
    session_id = (data.get("session_id") or "").strip()
    ai_model   = (data.get("ai_model") or "zolo_1").strip()
    thinking_mode = bool(data.get("thinking_mode", False))

    if not class_id or not question:
        return jsonify({"success": False, "error": "❌ class_id এবং question আবশ্যক"}), 400

    # Extract chapter number from query
    chapter_num = None
    m = re.search(r'(?:chapter|chap|অধ্যায়|অধ্যায়)\s*(\d+)', question.lower())
    if m:
        chapter_num = m.group(1)

    # ─── Subject নির্ধারণ (overall_ask এর মতোই) ─────────────────
    if subject_id:
        detected_subject = subject_id
        log.info(f"✅ Subject from UI: {detected_subject}")
    else:
        if group_id:
            cls = CLASSES.get(class_id, {})
            group = cls.get("groups", {}).get(group_id, {})
            filtered_subjects = {}
            for sid, sinfo in group.get("subjects", {}).items():
                filtered_subjects[sid] = sinfo
            for sid, sinfo in group.get("4th_subjects", {}).items():
                filtered_subjects[sid] = sinfo
            common = cls.get("groups", {}).get("common", {})
            for sid, sinfo in common.get("subjects", {}).items():
                filtered_subjects[sid] = sinfo
            subject_keys = list(filtered_subjects.keys())
        else:
            subject_keys = list(get_all_subjects(class_id).keys())

        detected_subject = detect_subject_locally(question, subject_keys)
        if not detected_subject:
            detected_subject = subject_keys[0] if subject_keys else "bangla_1"
            log.info(f"⚠️ Subject detect হয়নি, default: {detected_subject}")
        else:
            log.info(f"✅ Subject detected locally: {detected_subject}")

    # ─── Conversation History Load ──────────────────────────
    history = []
    if session_id:
        history = _conv_load(session_id, limit=6)
        if history:
            log.info(f"📜 Loaded {len(history)} history messages for session {session_id}")

    # ─── Smart RAG: FC দিয়ে keyword বের করো → FTS search ──────────────
    detected_source_types = _detect_source_types(question)
    chunks = _fc_get_chunks(
        question    = question,
        class_id    = class_id,
        subject_id  = detected_subject,
        chapter_num = chapter_num,
        source_type = detected_source_types,
    )
    context = _build_context(chunks)

    # log
    chunk_chapters = [c.get("chapter", "?") for c in chunks] if chunks else []
    chunk_sources_list = list(set([c.get("source_type", "?") for c in chunks])) if chunks else []
    log.info(f"📖 FC Chunk search: query='{question[:50]}' | found={len(chunks)} | chapters={chunk_chapters}")
    if not chunks:
        log.warning(f"⚠️ কোনো chunk পাওয়া যায়নি! query='{question[:50]}'")

    subj_info = get_subject_info(class_id, detected_subject)
    sources = list(set([c.get("source", "") for c in chunks])) if chunks else []

    meta = {
        "type":                "meta",
        "detected_subject":    detected_subject,
        "detected_subject_bn": subj_info.get("bn", detected_subject) if subj_info else detected_subject,
        "from_library":        bool(context),
        "chunks_found":        len(chunks),
        "chunk_chapters":      chunk_chapters[:5],
        "sources":             sources,
    }

    def generate():
        yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"

        full_answer = ""
        try:
            for kind, payload in build_answer_stream(
                question, context, class_id, detected_subject, 
                history=history, ai_model=ai_model, thinking_mode=thinking_mode
            ):
                if kind == "chunk":
                    full_answer += payload
                    yield f"data: {json.dumps({'type': 'chunk', 'text': payload}, ensure_ascii=False)}\n\n"
                elif kind == "error":
                    yield f"data: {json.dumps({'type': 'error', 'message': payload}, ensure_ascii=False)}\n\n"
                    return
                elif kind == "done":
                    full_answer = payload.get("answer", full_answer)
                    break
        except Exception as e:
            log.error(f"❌ Stream generate ত্রুটি: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            return

        # Conversation history-তে সেভ করো (Gemini role: "user" / "model")
        if session_id:
            _conv_save(session_id, class_id, detected_subject, "user", question)
            _conv_save(session_id, class_id, detected_subject, "model", full_answer)

        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # প্রক্সি buffering বন্ধ — Railway এ চাঙ্ক সাথে সাথে যাবে
        }
    )


@app.route("/api/theory/chat", methods=["POST"])
def theory_chat():
    """
    Theory/Concept শেখানো — conversation history সহ।
    Student বলবে 'chapter 1 থেকে বোঝাও' বা follow-up প্রশ্ন করবে।
    """
    client = _get_client()
    if not client:
        return jsonify({"success": False, "error": "❌ API Key সেট করা হয়নি"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "❌ JSON ডেটা পাওয়া যায়নি"}), 400

    class_id   = (data.get("class_id") or "").strip()
    subject_id = (data.get("subject_id") or "").strip()
    message    = (data.get("message") or "").strip()
    session_id = (data.get("session_id") or "").strip()

    if not class_id or not subject_id or not message:
        return jsonify({"success": False, "error": "❌ class_id, subject_id, message আবশ্যক"}), 400

    # session_id না থাকলে নতুন তৈরি করো
    if not session_id:
        import uuid
        session_id = str(uuid.uuid4())[:12]

    cls        = CLASSES.get(class_id, {})
    class_label = cls.get("label", class_id)
    subj_info  = get_subject_info(class_id, subject_id)
    subject_bn = subj_info.get("bn", subject_id) if subj_info else subject_id

    # পাঠ্যবই থেকে context খোঁজো
    chunks  = _search_json_library(class_id, subject_id, message, top_n=4)
    context = _build_context(chunks)

    # পুরনো conversation history লোড করো
    history = _conv_load(session_id, limit=8)

    # Theory chat system prompt
    system_prompt = (
        f"তুমি {class_label} শ্রেণীর {subject_bn} বিষয়ের একজন বিশেষজ্ঞ শিক্ষক।\n"
        f"তোমার কাজ হলো ছাত্রকে সহজ বাংলায় concept বোঝানো।\n\n"
        f"নিয়মাবলি:\n"
        f"- সহজ ভাষায় ধাপে ধাপে বোঝাও\n"
        f"- উদাহরণ দিয়ে explain করো\n"
        f"- 'আগে বলেছিলাম' বলে আগের কথা reference দাও (conversation history দেখে)\n"
        f"- 'chapter 1 থেকে বোঝাও' বললে সেই chapter এর শুরু থেকে শেখাও\n"
        f"- সংখ্যা বা তালিকা দিয়ে বোঝালে সহজ হয়\n"
        f"- একবারে বেশি না বলে, ছোট ছোট অংশে বোঝাও"
    )

    # Gemini contents তৈরি করো (history + context + current message)
    contents = []

    # আগের conversation থাকলে যোগ করো
    for h in history:
        role = h.get("role", "user")
        role = "user" if role == "user" else "model"
        contents.append(types.Content(
            role=role,
            parts=[types.Part(text=h["parts"][0])]
        ))

    # Current message (context সহ)
    if context:
        user_text = f"পাঠ্যবই থেকে তথ্য:\n{context}\n\nপ্রশ্ন/অনুরোধ: {message}"
    else:
        user_text = message

    contents.append(types.Content(
        role="user",
        parts=[types.Part(text=user_text)]
    ))

    try:
        # ── Thinking mode: শিক্ষকের মতো step-by-step বোঝায় ─────────
        response = _think_call(
            client, contents,
            system_instruction=system_prompt,
        )
        answer = response.text.strip() if response.text else "উত্তর তৈরি করা যায়নি।"

        # History সেভ করো
        _conv_save(session_id, class_id, subject_id, "user", message)
        _conv_save(session_id, class_id, subject_id, "model", answer)

        return jsonify({
            "success":      True,
            "answer":       answer,
            "session_id":   session_id,
            "from_library": bool(context),
        })

    except Exception as e:
        log.error(f"❌ Theory chat ত্রুটি: {e}")
        return jsonify({"success": False, "error": f"AI সমস্যা: {str(e)}"}), 500


@app.route("/api/theory/history", methods=["GET"])
def theory_history():
    """একটা session এর পুরো conversation দেখো"""
    session_id = request.args.get("session_id", "").strip()
    if not session_id:
        return jsonify({"success": False, "error": "session_id দরকার"}), 400
    history = _conv_load(session_id, limit=50)
    return jsonify({"success": True, "history": history, "count": len(history)})


@app.route("/api/theory/clear", methods=["POST"])
def theory_clear():
    """একটা session এর history মুছো"""
    data = request.get_json()
    session_id = data.get("session_id", "").strip() if data else ""
    if not session_id:
        return jsonify({"success": False, "error": "session_id দরকার"}), 400
    _conv_clear(session_id)
    return jsonify({"success": True, "message": "✅ Conversation মুছে গেছে"})


@app.route("/api/stats", methods=["GET"])
def get_stats():
    # নতুন folder structure এ সব JSON গুণো (walk করো)
    data_files = []
    if os.path.isdir(DATA_DIR):
        for root, _, files in os.walk(DATA_DIR):
            data_files.extend(f for f in files if f.endswith(".json") and not f.startswith("."))
    cq_files = [f for f in os.listdir(CQ_DIR) if f.endswith(".json")] if os.path.isdir(CQ_DIR) else []

    total_subjects = sum(len(get_all_subjects(cid)) for cid in CLASSES)
    active_keys    = len(_clients)

    return jsonify({
        "success": True,
        "data": {
            "classes": list(CLASSES.keys()),
            "total_classes": len(CLASSES),
            "total_subjects": total_subjects,
            "data_files": len(data_files),
            "cq_files": len(cq_files),
            "cached_data_files": len(_context_cache),
            "response_cache_size": _count_db_cache(),
            "default_model": DEFAULT_MODEL,
            "api_keys_active": active_keys,
            "api_key_set": active_keys > 0,
            "config": {
                "max_chars_per_page": MAX_CHARS_PER_PAGE,
                "max_output_long": MAX_OUTPUT_LONG,
                "top_n_chunks": TOP_N_CHUNKS,
                "cache_ttl": CACHE_TTL,
            }
        }
    })


@app.route("/api/key-status", methods=["GET"])
def key_status():
    return jsonify({
        "success": True,
        "is_set": len(_clients) > 0,
        "set": len(_clients) > 0,
        "active_keys": len(_clients),
    })


@app.route("/api/set-key", methods=["POST"])
def set_api_key():
    """Runtime-এ একটা নতুন API key pool এ যোগ করো"""
    data = request.get_json()
    if not data or not data.get("api_key"):
        return jsonify({"success": False, "error": "❌ api_key ফিল্ড আবশ্যক"}), 400

    new_key = data["api_key"].strip()
    if len(new_key) < 10:
        return jsonify({"success": False, "error": "❌ API Key খুবই ছোট"}), 400

    try:
        new_client = genai.Client(api_key=new_key, http_options={'api_version': 'v1beta'})
        _clients.append(new_client)
        log.info("✅ নতুন API Key pool এ যোগ হয়েছে")
        return jsonify({
            "success": True,
            "message": f"✅ API Key যোগ হয়েছে। এখন মোট {len(_clients)}টি key সক্রিয়।",
            "model": DEFAULT_MODEL,
            "active_keys": len(_clients),
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"API Key সেটে সমস্যা: {str(e)}"}), 500


@app.route("/api/cq/evaluate", methods=["POST"])
def evaluate_cq_answer():
    client = _get_client()
    if not client:
        return jsonify({"success": False, "error": "❌ API Key সেট করা হয়নি"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "❌ JSON ডেটা পাওয়া যায়নি"}), 400

    class_id       = data.get("class_id", "").strip()
    subject_id     = data.get("subject_id", "").strip()
    question       = data.get("question", "").strip()
    student_answer = data.get("student_answer", "").strip()

    if not all([class_id, subject_id, question, student_answer]):
        return jsonify({"success": False, "error": "❌ সব ফিল্ড আবশ্যক"}), 400

    cls = CLASSES.get(class_id, {})
    class_label = cls.get("label", class_id)
    subj_info = get_subject_info(class_id, subject_id)
    subject_bn = subj_info.get("bn", subject_id) if subj_info else subject_id

    chunks = _search_json_library(class_id, subject_id, question, top_n=2)
    context_text = ""
    if chunks:
        context_text = "সহায়ক তথ্য (পাঠ্যবই থেকে):\n" + _build_context(chunks)

    prompt = ANSWER_EVALUATION_PROMPT.format(
        class_label=class_label,
        subject_bn=subject_bn,
        question=question,
        student_answer=student_answer,
        context_text=context_text
    )

    try:
        model_name = DEFAULT_MODEL
        model_info = MODELS.get(model_name, {})
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=600, temperature=0.3)
        )
        raw_text = response.text.strip() if response.text else ""
        json_text = re.sub(r'^```(?:json)?\s*', '', raw_text)
        json_text = re.sub(r'\s*```$', '', json_text)

        try:
            eval_result = json.loads(json_text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            eval_result = json.loads(match.group()) if match else {}

        score = eval_result.get("score", 0)
        try:
            conn = get_db()
            conn.execute(
                "INSERT INTO student_progress (class_id, subject_id, type, topic, score, total) VALUES (?,?,?,?,?,?)",
                (class_id, subject_id, "cq", question[:100], score, 10)
            )
            conn.commit()
            conn.close()
        except Exception as db_err:
            log.warning("Progress save error: %s", db_err)

        # ── Feedback auto-collect (Step 13) ──────────────────────────────
        try:
            cq_feedback = "positive" if score >= 7 else ("negative" if score <= 3 else "neutral")
            _save_feedback(
                class_id    = class_id,
                subject_id  = subject_id,
                input_text  = f"CQ প্রশ্ন: {question}\n\nশিক্ষার্থীর উত্তর: {student_answer}",
                output_text = json.dumps(eval_result, ensure_ascii=False),
                feedback    = cq_feedback,
                score       = float(score),
                source      = "cq_eval"
            )
        except Exception:
            pass


        return jsonify({"success": True, "evaluation": eval_result, "data": eval_result})

    except Exception as e:
        return jsonify({"success": False, "error": f"মূল্যায়নে সমস্যা: {str(e)}"}), 500


@app.route("/api/routine/generate", methods=["POST"])
def generate_routine():
    client = _get_client()
    if not client:
        return jsonify({"success": False, "error": "❌ API Key সেট করা হয়নি"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "❌ JSON ডেটা পাওয়া যায়নি"}), 400

    class_id      = data.get("class_id", "").strip()
    exam_date     = data.get("exam_date", "").strip()
    weak_subjects = data.get("weak_subjects", [])
    daily_hours   = data.get("daily_hours", 4)

    if not class_id or not exam_date:
        return jsonify({"success": False, "error": "❌ class_id এবং exam_date আবশ্যক"}), 400

    cls = CLASSES.get(class_id, {})
    class_label = cls.get("label", class_id)
    today = datetime.date.today().strftime("%Y-%m-%d")
    weak_subjects_str = ", ".join(weak_subjects) if isinstance(weak_subjects, list) and weak_subjects \
                        else str(weak_subjects) if weak_subjects else "কোনো নির্দিষ্ট বিষয় নেই"

    prompt = ROUTINE_GENERATOR_PROMPT.format(
        class_label=class_label,
        exam_date=exam_date,
        weak_subjects=weak_subjects_str,
        daily_hours=daily_hours,
        today=today
    )

    try:
        model_name = DEFAULT_MODEL
        model_info = MODELS.get(model_name, {})
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=1200, temperature=0.5)
        )
        raw_text = response.text.strip() if response.text else ""
        json_text = re.sub(r'^```(?:json)?\s*', '', raw_text)
        json_text = re.sub(r'\s*```$', '', json_text)

        try:
            routine = json.loads(json_text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            routine = json.loads(match.group()) if match else {}

        try:
            conn = get_db()
            conn.execute(
                "INSERT INTO student_routine (class_id, exam_date, routine_json) VALUES (?,?,?)",
                (class_id, exam_date, json.dumps(routine, ensure_ascii=False))
            )
            conn.commit()
            conn.close()
        except Exception as db_err:
            log.warning("Routine save error: %s", db_err)


        return jsonify({"success": True, "routine": routine, "data": routine})

    except Exception as e:
        return jsonify({"success": False, "error": f"রুটিন তৈরিতে সমস্যা: {str(e)}"}), 500


@app.route("/api/progress/save", methods=["POST"])
def save_progress():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "❌ JSON ডেটা পাওয়া যায়নি"}), 400

    class_id   = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()
    ptype      = data.get("type", "mcq").strip()
    topic      = data.get("topic", "").strip()
    score      = float(data.get("score", 0))
    total      = float(data.get("total", 10))

    if not class_id or not subject_id:
        return jsonify({"success": False, "error": "❌ class_id এবং subject_id আবশ্যক"}), 400

    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO student_progress (class_id, subject_id, type, topic, score, total) VALUES (?,?,?,?,?,?)",
            (class_id, subject_id, ptype, topic, score, total)
        )
        conn.commit()
        conn.close()

        # ── Feedback auto-collect (Step 13) ──────────────────────────────
        if ptype == "mcq":
            try:
                percentage   = (score / total * 100) if total > 0 else 0
                mcq_feedback = "positive" if percentage >= 70 else ("negative" if percentage < 40 else "neutral")
                _save_feedback(
                    class_id   = class_id,
                    subject_id = subject_id,
                    input_text = f"MCQ topic: {topic}",
                    output_text= f"score: {score}/{total} ({round(percentage,1)}%)",
                    feedback   = mcq_feedback,
                    score      = score,
                    source     = "mcq_result"
                )
            except Exception:
                pass

        return jsonify({"success": True, "message": "✅ প্রগ্রেস সেভ হয়েছে"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/progress/stats", methods=["GET"])
def get_progress_stats():
    class_id = request.args.get("class_id", "").strip()
    try:
        conn = get_db()
        if class_id:
            rows = conn.execute("""
                SELECT subject_id, type, COUNT(*) as attempts,
                       AVG(score) as avg_score, MAX(score) as best_score,
                       SUM(score) as total_score, SUM(total) as total_possible
                FROM student_progress WHERE class_id = ?
                GROUP BY subject_id, type ORDER BY subject_id, type
            """, (class_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT class_id, subject_id, type, COUNT(*) as attempts,
                       AVG(score) as avg_score, MAX(score) as best_score,
                       SUM(score) as total_score, SUM(total) as total_possible
                FROM student_progress
                GROUP BY class_id, subject_id, type ORDER BY class_id, subject_id, type
            """).fetchall()

        recent_rows = conn.execute("""
            SELECT class_id, subject_id, type, topic, score, total, date
            FROM student_progress ORDER BY created_at DESC LIMIT 10
        """).fetchall()

        subject_stats = []
        for r in rows:
            d = dict(r)
            pct = round((d["total_score"] / d["total_possible"]) * 100, 1) if d.get("total_possible") else 0
            d["percentage"] = pct
            d["avg_score"] = round(d.get("avg_score", 0), 1)
            if class_id:
                si = get_subject_info(class_id, d["subject_id"])
                d["subject_bn"] = si.get("bn", d["subject_id"]) if si else d["subject_id"]
            subject_stats.append(d)

        conn.close()
        return jsonify({
            "success": True,
            "subject_stats": subject_stats,
            "recent": [dict(r) for r in recent_rows],
            "total_records": len(subject_stats)
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════
#  MCQ YEARS — mcq_bank-এ থাকা distinct board_year গুলো
# ══════════════════════════════════════════════════════════
@app.route("/api/mcq/years", methods=["GET"])
def mcq_years():
    """
    GET /api/mcq/years?class_id=ssc&subject_id=accounting
    mcq_bank-এ থাকা distinct board_year values return করে (empty বাদে)।
    """
    class_id   = request.args.get("class_id", "").strip()
    subject_id = request.args.get("subject_id", "").strip()
    if not class_id or not subject_id:
        return jsonify({"success": False, "error": "class_id ও subject_id দরকার"}), 400
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT DISTINCT board_year FROM mcq_bank
            WHERE class_id=? AND subject_id=?
              AND board_year IS NOT NULL AND board_year != ''
            ORDER BY board_year DESC
        """, (class_id, subject_id)).fetchall()
        conn.close()
        return jsonify({"success": True, "years": [r["board_year"] for r in rows]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════
#  CHAPTER LIST — subject_chapters থেকে অথবা pdf_content থেকে live
# ══════════════════════════════════════════════════════════
@app.route("/api/chapter/list", methods=["GET"])
def chapter_list():
    """
    GET /api/chapter/list?class_id=ssc&subject_id=physics

    subject_chapters table এ data থাকলে সেখান থেকে দেয় (fast).
    না থাকলে pdf_content থেকে live aggregate করে দেয় + subject_chapters এ cache করে।
    """
    class_id   = request.args.get("class_id", "").strip()
    subject_id = request.args.get("subject_id", "").strip()
    if not class_id or not subject_id:
        return jsonify({"success": False, "error": "class_id ও subject_id দরকার"}), 400

    try:
        conn = get_db()

        # ── subject_chapters এ আছে কিনা দেখো ──────────────────────────
        cached = conn.execute("""
            SELECT chapter_num, chapter_title, total_pages, total_mcq, total_cq
            FROM subject_chapters
            WHERE class_id = ? AND subject_id = ?
            ORDER BY COALESCE(chapter_num, 9999), chapter_title
        """, (class_id, subject_id)).fetchall()

        if cached:
            chapters = [dict(r) for r in cached]
            conn.close()
            return jsonify({"success": True, "chapters": chapters,
                            "total": len(chapters), "source": "cache"})

        # ── cache নেই → pdf_content থেকে live aggregate করো ────────────
        rows = conn.execute("""
            SELECT chapter, chapter_num,
                   COUNT(*) as total_pages,
                   SUM(CASE WHEN content_type = 'mcq' THEN 1 ELSE 0 END) as total_mcq,
                   SUM(CASE WHEN content_type = 'cq'  THEN 1 ELSE 0 END) as total_cq
            FROM pdf_content
            WHERE class_id = ? AND subject_id = ?
              AND chapter IS NOT NULL AND chapter != ''
            GROUP BY chapter, chapter_num
            ORDER BY COALESCE(chapter_num, 9999), chapter
        """, (class_id, subject_id)).fetchall()

        chapters = []
        for r in rows:
            d = dict(r)
            # subject_chapters এ save করো (cache হিসেবে)
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO subject_chapters
                        (class_id, subject_id, chapter_num, chapter_title, total_pages, total_mcq, total_cq)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (class_id, subject_id,
                      d.get("chapter_num"), d.get("chapter"),
                      d.get("total_pages", 0), d.get("total_mcq", 0), d.get("total_cq", 0)))
            except Exception:
                pass
            chapters.append({
                "chapter_num":   d.get("chapter_num"),
                "chapter_title": d.get("chapter"),
                "total_pages":   d.get("total_pages", 0),
                "total_mcq":     d.get("total_mcq", 0),
                "total_cq":      d.get("total_cq", 0),
            })

        conn.commit()
        conn.close()

        if not chapters:
            return jsonify({"success": True, "chapters": [],
                            "total": 0, "note": "এখনো chapter tag করা হয়নি"})

        return jsonify({"success": True, "chapters": chapters,
                        "total": len(chapters), "source": "live"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════
#  MCQ BANK — DB থেকে সরাসরি MCQ (0 Gemini token)
# ══════════════════════════════════════════════════════════
@app.route("/api/mcq/from-bank", methods=["POST"])
def mcq_from_bank():
    """
    POST /api/mcq/from-bank
    Body: { class_id, subject_id, chapter_num (optional), count (default 10) }

    mcq_bank table থেকে সরাসরি MCQ দেয় — Gemini call নেই, token শূন্য।
    chapter_num দিলে সেই chapter থেকে, না দিলে random।
    """
    data = request.get_json() or {}
    class_id    = data.get("class_id", "").strip()
    subject_id  = data.get("subject_id", "").strip()
    chapter_num = data.get("chapter_num")
    count       = min(int(data.get("count", 10)), 50)
    # নতুন optional filter
    difficulty  = data.get("difficulty", "").strip()   # easy | medium | hard | "" = সব
    board_name  = data.get("board_name", "").strip()   # "ঢাকা" বা ""
    board_year  = data.get("board_year", "").strip()   # "2023" বা ""

    if not class_id or not subject_id:
        return jsonify({"success": False, "error": "class_id ও subject_id দরকার"}), 400

    try:
        conn = get_db()

        # Dynamic WHERE clause
        # Bug1 fix: is_canonical=1 — duplicate MCQ student দেখবে না
        where = ["class_id = ?", "subject_id = ?", "is_canonical = 1"]
        params = [class_id, subject_id]

        if chapter_num is not None:
            where.append("chapter_num = ?")
            params.append(chapter_num)
        if difficulty:
            where.append("difficulty = ?")
            params.append(difficulty)
        if board_name:
            # Bug2 fix: dedup এর পরে board চলে যায় appeared_boards JSON এ
            where.append("(board_name = ? OR appeared_boards LIKE ?)")
            params.append(board_name)
            params.append(f'%"{board_name}"%')
        if board_year:
            # Bug2 fix: same for year
            where.append("(board_year = ? OR appeared_years LIKE ?)")
            params.append(board_year)
            params.append(f'%"{board_year}"%')

        params.append(count)
        sql = f"""
            SELECT id, chapter, chapter_num, question,
                   option_a, option_b, option_c, option_d,
                   answer, explanation, difficulty, source_type, board_name, board_year
            FROM mcq_bank
            WHERE {" AND ".join(where)}
            ORDER BY RANDOM() LIMIT ?
        """
        rows = conn.execute(sql, params).fetchall()

        if not rows:
            total = conn.execute(
                "SELECT COUNT(*) FROM mcq_bank WHERE class_id=? AND subject_id=?",
                (class_id, subject_id)
            ).fetchone()[0]
            conn.close()
            msg = "MCQ Bank এ এখনো কোনো MCQ নেই। Admin panel থেকে import করুন।" \
                  if total == 0 else \
                  f"এই chapter এ MCQ নেই (মোট bank এ {total}টি আছে)"
            return jsonify({"success": False, "error": msg, "bank_total": total}), 404

        # times_shown update করো
        ids = [r["id"] for r in rows]
        conn.execute(
            f"UPDATE mcq_bank SET times_shown = times_shown + 1 WHERE id IN ({','.join('?'*len(ids))})",
            ids
        )
        conn.commit()

        mcqs = []
        for r in rows:
            mcqs.append({
                "id":          r["id"],
                "question":    r["question"],
                "options":     [r["option_a"], r["option_b"], r["option_c"], r["option_d"]],
                "answer":      r["answer"],
                "explanation": r["explanation"],
                "chapter":     r["chapter"],
                "chapter_num": r["chapter_num"],
                "difficulty":  r["difficulty"],
                "source_type": r["source_type"],
                "board_name":  r["board_name"],
                "board_year":  r["board_year"],
            })

        conn.close()
        return jsonify({
            "success":    True,
            "questions":  mcqs,
            "count":      len(mcqs),
            "from_bank":  True,
            "token_cost": 0,
            "filters": {
                "difficulty": difficulty or "all",
                "board_name": board_name or "all",
                "board_year": board_year or "all",
            }
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500




# ══════════════════════════════════════════════════════════
#  MCQ BOARD STATS — available boards/years/chapters
# ══════════════════════════════════════════════════════════
@app.route("/api/mcq/board-stats", methods=["GET"])
def mcq_board_stats():
    """
    GET /api/mcq/board-stats?class_id=ssc&subject_id=accounting
    Returns: available boards, years, chapters from mcq_bank
    """
    class_id   = request.args.get("class_id", "").strip()
    subject_id = request.args.get("subject_id", "").strip()
    if not class_id or not subject_id:
        return jsonify({"success": False, "error": "class_id ও subject_id দরকার"}), 400
    try:
        conn = get_db()
        # Unique boards
        boards = [r[0] for r in conn.execute(
            "SELECT DISTINCT board_name FROM mcq_bank WHERE class_id=? AND subject_id=? AND board_name != '' ORDER BY board_name",
            (class_id, subject_id)
        ).fetchall()]
        # Unique years
        years = [r[0] for r in conn.execute(
            "SELECT DISTINCT board_year FROM mcq_bank WHERE class_id=? AND subject_id=? AND board_year != '' ORDER BY board_year DESC",
            (class_id, subject_id)
        ).fetchall()]
        # Chapters with MCQ count
        chapters = [dict(r) for r in conn.execute(
            """SELECT chapter, chapter_num, COUNT(*) as count
               FROM mcq_bank WHERE class_id=? AND subject_id=?
               GROUP BY chapter, chapter_num
               ORDER BY COALESCE(chapter_num, 999), chapter""",
            (class_id, subject_id)
        ).fetchall()]
        total = conn.execute(
            "SELECT COUNT(*) FROM mcq_bank WHERE class_id=? AND subject_id=?",
            (class_id, subject_id)
        ).fetchone()[0]
        conn.close()
        return jsonify({
            "success": True,
            "boards": boards,
            "years": years,
            "chapters": chapters,
            "total": total
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════
#  CHAPTER SUMMARY — একবার generate + DB cache
# ══════════════════════════════════════════════════════════
@app.route("/api/chapter/summary", methods=["POST"])
def chapter_summary():
    """
    POST /api/chapter/summary
    Body: { class_id, subject_id, chapter, force_refresh (optional, default false) }

    chapter_summaries table এ আগে থেকে থাকলে সরাসরি দেয় (0 token)।
    না থাকলে pdf_content থেকে context তৈরি করে Gemini দিয়ে generate করে,
    তারপর DB তে save করে রাখে — পরের request এ আর Gemini call লাগবে না।

    ✅ Long chapter হলে chunked summary বানায় — token limit overshoot হয় না।
    """
    client = _get_client()
    if not client:
        return jsonify({"success": False, "error": "❌ API Key সেট করা হয়নি"}), 400

    data = request.get_json() or {}
    class_id      = data.get("class_id", "").strip()
    subject_id    = data.get("subject_id", "").strip()
    chapter       = data.get("chapter", "").strip()
    force_refresh = bool(data.get("force_refresh", False))

    if not class_id or not subject_id or not chapter:
        return jsonify({"success": False, "error": "❌ class_id, subject_id এবং chapter আবশ্যক"}), 400

    cls        = CLASSES.get(class_id, {})
    class_label = cls.get("label", class_id)
    subj_info  = get_subject_info(class_id, subject_id)
    subject_bn = subj_info.get("bn", subject_id) if subj_info else subject_id

    try:
        conn = get_db()

        # ── DB তে cached summary আছে কিনা দেখো ───────────────────────
        if not force_refresh:
            row = conn.execute(
                "SELECT summary_json, created_at FROM chapter_summaries WHERE class_id=? AND subject_id=? AND chapter=?",
                (class_id, subject_id, chapter)
            ).fetchone()
            if row:
                summary = json.loads(row["summary_json"])
                conn.close()
                return jsonify({
                    "success":    True,
                    "summary":    summary,
                    "from_cache": True,
                    "cached_at":  row["created_at"],
                    "token_cost": 0,
                })

        conn.close()

        # ── Cache নেই — context তৈরি করো ────────────────────────────
        query = f"{subject_bn} {chapter}"

        text_chunks = _search_json_library(
            class_id, subject_id, query,
            top_n=10, content_type="text", chapter=chapter
        )
        mcq_chunks = _search_json_library(
            class_id, subject_id, query,
            top_n=5, content_type="mcq", chapter=chapter
        )

        all_chunks = text_chunks + mcq_chunks

        if not all_chunks:
            all_chunks = _search_json_library(class_id, subject_id, query, top_n=10)

        # ── Chunked Summary logic ───────────────────────────────
        # Long chapter হলে context ভাগ করে generate করো
        CHUNK_CHAR_LIMIT = 16000  # ~4k tokens যা Gemini safely handle করে
        combined_context_text = ""
        contexts = []
        for c in all_chunks:
            txt = _clean_accounting_tags(c.get("text", ""))
            chunk_text = txt[:MAX_CHARS_PER_PAGE]
            if not combined_context_text:
                combined_context_text = chunk_text
                contexts.append([combined_context_text])
            elif len(combined_context_text) + len(chunk_text) < CHUNK_CHAR_LIMIT:
                combined_context_text += "\n\n" + chunk_text
                contexts[-1].append(chunk_text)
            else:
                # নতুন context group শুরু
                combined_context_text = chunk_text
                contexts.append([chunk_text])

        if not contexts:
            contexts = [[""]]

        log.info("chapter_summary: %s/%s/%s → %d chunks, %d context group(s)",
                 class_id, subject_id, chapter, len(all_chunks), len(contexts))

        # প্রতিটা context group এর জন্য আলাদা summary generate
        cls_label = class_label
        partial_summaries = []
        total_tokens = 0
        model_info = MODELS.get(DEFAULT_MODEL, {})
        for idx, ctx_group in enumerate(contexts):
            ctx_text = "\n\n".join(ctx_group)
            if not ctx_text.strip():
                continue
            part_prompt = CHAPTER_SUMMARY_PROMPT.format(
                class_label=cls_label,
                subject_bn=subject_bn,
                chapter=chapter,
            )
            full_prompt = (
                f"পাঠ্যবই থেকে তথ্য (অংশ {idx+1}/{len(contexts)}):\n{ctx_text}\n\n{part_prompt}"
                if ctx_text else part_prompt
            )
            try:
                response = client.models.generate_content(
                    model=DEFAULT_MODEL,
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        max_output_tokens=MAX_OUTPUT_LONG,
                        temperature=0.3,
                    )
                )
                raw = response.text.strip() if response.text else "{}"
                raw = re.sub(r'^```(?:json)?\s*', '', raw)
                raw = re.sub(r'\s*```$', '', raw)
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    m = re.search(r'\{.*\}', raw, re.DOTALL)
                    parsed = json.loads(m.group()) if m else {"chapter": chapter, "summary": raw}

                partial_summaries.append(parsed)
                total_tokens += 1  # approximate cost
                # rate limit guard
                pass
            except Exception as gen_err:
                log.error(f"Chapter summary chunk {idx} error: {gen_err}")
                # Continue পরের chunks দিয়ে — partial summary এ save হবে
                partial_summaries.append({"chapter": chapter, "_error": str(gen_err)})

        # ── Combine partials ──────────────────────────────
        if len(partial_summaries) == 1:
            summary = partial_summaries[0]
        else:
            # একাধিক chunk থেকে merge — sections যুক্ত করে
            summary = _merge_chunked_summaries(partial_summaries, class_label, subject_bn, chapter, client)

        # ── DB তে save করো ───────────────────────────────────────────
        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO chapter_summaries (class_id, subject_id, chapter, summary_json) VALUES (?,?,?,?)",
            (class_id, subject_id, chapter, json.dumps(summary, ensure_ascii=False))
        )
        conn.commit()
        conn.close()

        return jsonify({
            "success":       True,
            "summary":       summary,
            "from_cache":    False,
            "from_library":  bool(all_chunks),
            "token_cost":    total_tokens,
            "chunks_used":   len(contexts),
            "chunked":       len(contexts) > 1,
        })

    except Exception as e:
        log.error(f"❌ Chapter summary ত্রুটি: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


def _merge_chunked_summaries(partials, class_label, subject_bn, chapter, client):
    """
    একাধিক partial summaries কে একটা coherent merged summary তে convert করো।
    Gemini ব্যবহার করে sections গুলোকে logically join করে।
    Fallback: simple string concatenation।
    """
    if not partials:
        return {"chapter": chapter, "summary": ""}

    try:
        # Gemini দিয়ে merge — বুদ্ধিমানের মতো sections যুক্ত করবে
        combined_input = "\n\n=========\n".join(
            json.dumps(p, ensure_ascii=False) for p in partials
        )
        merge_prompt = f"""তুমি {class_label} - {subject_bn} বিষয়ের শিক্ষক।
নিচে একটি অধ্যায়ের বিভিন্ন অংশের summary দেওয়া হলো।
একটি সুসংগত, সম্পূর্ণ summary-তে merge করো (JSON format এ, বাংলায়)।

আউটপুট শুধু JSON:
{{
  "chapter": "{chapter}",
  "short_intro": "...",
  "key_concepts": [...],
  "important_points": [...],
  "common_questions": [...]
}}

Department summaries to merge:
{combined_input}
"""
        response = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=merge_prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=MAX_OUTPUT_LONG,
                temperature=0.2,
            )
        )
        raw = response.text.strip() if response.text else ""
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        return json.loads(raw)
    except Exception:
        # Fallback: simple concat
        parts_text = []
        for p in partials:
            if isinstance(p, dict):
                if "summary" in p:
                    parts_text.append(str(p["summary"]))
                elif "important_points" in p:
                    parts_text.append(" • " + "\n • ".join(p["important_points"]))
            else:
                parts_text.append(str(p))
        return {
            "chapter": chapter,
            "summary": "\n\n".join(parts_text)
        }


@app.route("/api/chapter/summary/list", methods=["GET"])
def chapter_summary_list():
    """
    GET /api/chapter/summary/list?class_id=ssc&subject_id=physics
    কোন কোন chapter এর summary আছে সেটার তালিকা দেয়।
    """
    class_id   = request.args.get("class_id", "").strip()
    subject_id = request.args.get("subject_id", "").strip()
    if not class_id or not subject_id:
        return jsonify({"success": False, "error": "class_id ও subject_id দরকার"}), 400
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT chapter, created_at FROM chapter_summaries WHERE class_id=? AND subject_id=? ORDER BY chapter",
            (class_id, subject_id)
        ).fetchall()
        conn.close()
        return jsonify({
            "success":  True,
            "chapters": [{"chapter": r["chapter"], "cached_at": r["created_at"]} for r in rows],
            "total":    len(rows),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



# ══════════════════════════════════════════════════════════
#  FEEDBACK COLLECTION — Step 13 (AI Self-Improvement)
# ══════════════════════════════════════════════════════════

@app.route("/api/feedback/submit", methods=["POST"])
def submit_feedback():
    """
    POST /api/feedback/submit
    Manual 👍👎 feedback — theory chat বা যেকোনো AI response এর জন্য।
    Body: {
      class_id, subject_id,
      input_text,    -- প্রশ্ন / context
      output_text,   -- AI এর দেওয়া উত্তর
      feedback,      -- 'positive' | 'negative' | 'neutral'
      source         -- 'thumb_up' | 'thumb_down' | 'manual'
    }
    """
    data = request.get_json() or {}

    class_id    = data.get("class_id", "").strip()
    subject_id  = data.get("subject_id", "").strip()
    input_text  = data.get("input_text", "").strip()
    output_text = data.get("output_text", "").strip()
    feedback    = data.get("feedback", "neutral").strip()
    source      = data.get("source", "manual").strip()

    if not input_text or not output_text:
        return jsonify({"success": False, "error": "❌ input_text ও output_text আবশ্যক"}), 400

    if feedback not in ("positive", "negative", "neutral"):
        feedback = "neutral"

    _save_feedback(
        class_id   = class_id,
        subject_id = subject_id,
        input_text = input_text,
        output_text= output_text,
        feedback   = feedback,
        score      = None,
        source     = source
    )
    return jsonify({"success": True, "message": "✅ Feedback সেভ হয়েছে"})


@app.route("/api/feedback/stats", methods=["GET"])
def feedback_stats():
    """
    GET /api/feedback/stats?class_id=ssc&subject_id=physics  (optional filters)
    Training data কতটুকু জমেছে তার summary।
    """
    class_id   = request.args.get("class_id", "").strip()
    subject_id = request.args.get("subject_id", "").strip()

    try:
        conn   = get_db()
        params = []
        where  = []
        if class_id:
            where.append("class_id = ?")
            params.append(class_id)
        if subject_id:
            where.append("subject_id = ?")
            params.append(subject_id)

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        total_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM training_feedback {where_sql}", params
        ).fetchone()
        total = total_row["cnt"] if total_row else 0

        breakdown = conn.execute(f"""
            SELECT feedback, source, COUNT(*) as cnt
            FROM training_feedback {where_sql}
            GROUP BY feedback, source
            ORDER BY feedback, source
        """, params).fetchall()

        unused = conn.execute(
            f"SELECT COUNT(*) as cnt FROM training_feedback {where_sql + (' AND ' if where_sql else 'WHERE ')}used_in_training = 0",
            params
        ).fetchone()
        unused_cnt = unused["cnt"] if unused else 0

        conn.close()
        return jsonify({
            "success":       True,
            "total":         total,
            "unused":        unused_cnt,
            "ready_percent": round((unused_cnt / 500) * 100, 1) if unused_cnt <= 500 else 100,
            "target":        500,
            "breakdown":     [dict(r) for r in breakdown],
            "message":       f"Fine-tuning এর জন্য {total}/500 examples জমেছে"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


from admin_app import admin_bp
app.register_blueprint(admin_bp)


# ══════════════════════════════════════════════════════════
#  FEATURES AUTO-LOADER
#  features/ ফোল্ডারে যেকোনো .py ফাইল রাখো,
#  bp = Blueprint(...) থাকলে automatically load হয়ে যাবে।
#  app.py আর touch করতে হবে না।
# ══════════════════════════════════════════════════════════
_features_dir = os.path.join(BASE_DIR, "features")
os.makedirs(_features_dir, exist_ok=True)

_init_file = os.path.join(_features_dir, "__init__.py")
if not os.path.exists(_init_file):
    open(_init_file, "w").close()

for _fpath in sorted(glob.glob(os.path.join(_features_dir, "[!_]*.py"))):
    _fname = os.path.basename(_fpath)[:-3]
    try:
        _mod = importlib.import_module(f"features.{_fname}")
        if hasattr(_mod, "bp"):
            app.register_blueprint(_mod.bp)
            log.info(f"✅ Feature loaded: {_fname}")
        else:
            log.warning(f"⚠️ {_fname}.py তে 'bp' নেই — skip")
    except Exception as _e:
        log.error(f"❌ Feature load failed ({_fname}): {_e}")


# ══════════════════════════════════════════════════════════
#  ERROR HANDLERS
# ══════════════════════════════════════════════════════════
@app.errorhandler(404)
def not_found(e):
    return jsonify({"success": False, "error": "❌ এই রাউটটি পাওয়া যায়নি"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"success": False, "error": "❌ সার্ভারে সমস্যা হয়েছে"}), 500


# ══════════════════════════════════════════════════════════
#  RUN SERVER
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    log.info("=" * 50)
    log.info("🚀 Study AI সার্ভার চালু হচ্ছে...")
    log.info(f"🤖 মডেল: {DEFAULT_MODEL}")
    log.info(f"🔑 সক্রিয় API Key: {len(_clients)}টি")
    log.info(f"🌐 Port: {port}")
    log.info("=" * 50)
    app.run(host="0.0.0.0", port=port, debug=False)
