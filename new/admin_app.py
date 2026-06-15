"""
╔══════════════════════════════════════════════════════════╗
║          Study AI — Admin Blueprint                      ║
║   PDF আপলোড, Gemini এক্সট্রাকশন, JSON ম্যানেজমেন্ট     ║
╚══════════════════════════════════════════════════════════╝
"""

from flask import Blueprint, request, jsonify, render_template, send_file
import os, json, time, threading, math, uuid, logging, sqlite3 as _sqlite3
import fitz  # PyMuPDF
from google import genai
from google.genai import types
from config import MODELS, DEFAULT_MODEL, EXTRACT_PROMPT, EXTRACT_PROMPTS, EXTRACT_PROMPT_LABELS, CLASSES, get_all_subjects, get_data_filename, get_data_filepath, find_data_file, get_extract_prompt, GEMINI_API_KEYS

# ══════════════════════════════════════════════════════════
#  Blueprint — সব admin route /admin prefix এ থাকবে
# ══════════════════════════════════════════════════════════
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
log = logging.getLogger(__name__)

# ── ডিরেক্টরি পাথ ────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
SPLIT_DIR  = os.path.join(BASE_DIR, "split_pdfs")
DATA_DIR   = os.path.join(BASE_DIR, "data")
CQ_DIR     = os.path.join(BASE_DIR, "cq_data")

for d in [UPLOAD_DIR, SPLIT_DIR, DATA_DIR, CQ_DIR]:
    os.makedirs(d, exist_ok=True)

# ── গ্লোবাল স্টেট ────────────────────────────────────────
# .env থেকে GEMINI_API_KEYS auto-load — UI তে manual input দরকার নাই
gemini_client  = None
gemini_api_key = None

def _auto_init_client():
    """startup এ .env / config.py থেকে Gemini client auto-initialize করো"""
    global gemini_client, gemini_api_key
    for key in GEMINI_API_KEYS:
        if key and key.strip():
            try:
                gemini_client = genai.Client(api_key=key.strip())
                gemini_api_key = key.strip()
                break
            except Exception:
                pass

_auto_init_client()

jobs = {}

# parallel group tracking: group_id → { job_ids, class_id, subject_id, status, ... }
parallel_groups = {}
_merge_lock = threading.Lock()

# ── Async DB-import task tracking ─────────────────────────
_import_tasks = {}   # task_id → { status, message, total_chunks, ... }

# ══════════════════════════════════════════════════════════
#  SQLite Job Persistence  (restart এ jobs হারায় না)
# ══════════════════════════════════════════════════════════
DB_PATH = os.path.join(BASE_DIR, "study_ai.db")

def _admin_db():
    conn = _sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = _sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def _init_jobs_table():
    try:
        conn = _admin_db()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS extraction_jobs (
                job_id        TEXT PRIMARY KEY,
                group_id      TEXT,
                part_num      INTEGER,
                class_id      TEXT,
                subject_id    TEXT,
                subject_bn    TEXT,
                source        TEXT,
                model         TEXT,
                prompt_type   TEXT,
                status        TEXT DEFAULT 'starting',
                progress      REAL DEFAULT 0,
                current_page  INTEGER DEFAULT 0,
                total_pages   INTEGER DEFAULT 0,
                total_entries INTEGER DEFAULT 0,
                errors_count  INTEGER DEFAULT 0,
                message       TEXT DEFAULT '',
                started_at    REAL,
                completed_at  REAL
            )""")
        conn.commit()
        conn.close()
    except Exception as e:
        log.error("extraction_jobs table init error: %s", e)

_init_jobs_table()

def _save_job(job_dict):
    """Job dict → SQLite তে INSERT OR REPLACE"""
    try:
        conn = _admin_db()
        conn.execute("""
            INSERT OR REPLACE INTO extraction_jobs
            (job_id, group_id, part_num, class_id, subject_id, subject_bn,
             source, model, prompt_type, status, progress, current_page,
             total_pages, total_entries, errors_count, message, started_at, completed_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            job_dict.get("job_id"),        job_dict.get("group_id"),
            job_dict.get("part_num"),      job_dict.get("class_id"),
            job_dict.get("subject_id"),    job_dict.get("subject_bn"),
            job_dict.get("source"),        job_dict.get("model"),
            job_dict.get("prompt_type"),   job_dict.get("status"),
            job_dict.get("progress", 0),   job_dict.get("current_page", 0),
            job_dict.get("total_pages", 0),job_dict.get("total_entries", 0),
            job_dict.get("errors", 0),     job_dict.get("message", ""),
            job_dict.get("started_at"),    job_dict.get("completed_at"),
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        log.error("_save_job error: %s", e)

def _load_jobs_from_db(limit=100):
    """DB থেকে শেষ N টা job load করো"""
    try:
        conn = _admin_db()
        rows = conn.execute(
            "SELECT * FROM extraction_jobs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error("_load_jobs_from_db error: %s", e)
        return []


# ══════════════════════════════════════════════════════════
#  হেল্পার ফাংশন
# ══════════════════════════════════════════════════════════

def detect_content_type(content):
    """
    Content type detect করো।
    ⚠️ FIX: simple substring match এ false positive হতো —
    Gemini যদি explanation এ "[MCQ]" লিখত (যেমন "কোনো [MCQ] নেই"),
    সেটাও mcq হিসেবে count হয়ে যেত।
    এখন regex দিয়ে real tag check: tag এর পরে whitespace/newline থাকলেই real।
    """
    import re
    if not content:
        return "text"
    if re.search(r'\[BOARD_QUESTION[^\]]*\]\s*\n', content):
        return "board_question"
    if re.search(r'\[MCQ\]\s*\n', content):
        return "mcq"
    if re.search(r'\[CQ\]\s*\n', content):
        return "cq"
    # Accounting-specific
    if (re.search(r'\[JOURNAL\]\s*\n', content)
            or re.search(r'\[LEDGER[^\]]*\]\s*\n', content)
            or re.search(r'\[TRIAL_BALANCE\]\s*\n', content)):
        return "accounting_table"
    # Math/Physics-specific
    if re.search(r'\[SOLUTION\]\s*\n', content):
        return "solution"
    # Biology-specific
    if re.search(r'\[FIGURE_LABELS[^\]]*\]', content):
        return "figure"
    return "text"


def parse_chapter_from_content(content):
    """
    Extracted content থেকে [CHAPTER: ...] tag parse করে chapter info বের করে।
    Returns: (chapter_str, chapter_num)
      - chapter_str: যেমন "অধ্যায় ৩ — পরিবেশ দূষণ"
      - chapter_num: integer যেমন 3, অথবা None যদি না পাওয়া যায়
    """
    import re
    if not content:
        return None, None

    # [CHAPTER: অধ্যায় ৩ — নাম] বা [CHAPTER: ৩. নাম] যেকোনো format match করে
    match = re.search(r'\[CHAPTER:\s*(.+?)\]', content, re.IGNORECASE)
    if not match:
        return None, None

    chapter_text = match.group(1).strip()

    # Bengali digits → Arabic digits convert করো
    bengali_to_arabic = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')
    normalized = chapter_text.translate(bengali_to_arabic)

    # Chapter number বের করো (যেমন "অধ্যায় 3", "Chapter 3", "3.", "৩য় অধ্যায়")
    # সরাসরি প্রথম digit group খোঁজো — \b দিয়ে Bengali suffix ধরা যায় না
    num_match = re.search(r'(\d+)', normalized)
    chapter_num = int(num_match.group(1)) if num_match else None

    return chapter_text, chapter_num


def get_subject_bn(class_id, subject_id):
    subjects = get_all_subjects(class_id)
    return subjects.get(subject_id, {}).get("bn", subject_id)


def load_json_file(filepath):
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_json_file(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════
#  রাউটস
# ══════════════════════════════════════════════════════════

@admin_bp.route("/")
def index():
    return render_template("admin.html")


@admin_bp.route("/api/set-key", methods=["POST"])
def set_key():
    global gemini_client, gemini_api_key
    data = request.get_json()
    key = data.get("key", "").strip()
    if not key:
        return jsonify({"error": "API key দেওয়া হয়নি"}), 400
    try:
        gemini_client = genai.Client(api_key=key)
        gemini_api_key = key
        return jsonify({"success": True, "message": "API key সেট হয়েছে ✅"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/api/key-status", methods=["GET"])
def key_status():
    try:
        from app import _clients, GEMINI_API_KEYS
        active_count = len(_clients)
        total_count  = len([k for k in GEMINI_API_KEYS if k.strip()])
        # প্রতিটা configured key এর status (active না failed)
        key_details = []
        for i, key in enumerate(GEMINI_API_KEYS):
            key = key.strip()
            if not key:
                continue
            # _clients এ এই key আছে কিনা check করো (prefix দিয়ে)
            is_active = any(
                getattr(c, '_api_key', None) == key or
                (hasattr(c, '_api_key') and str(c._api_key) == key)
                for c in _clients
            )
            # fallback: active_count == total_count মানে সব key কাজ করছে
            if active_count == total_count:
                is_active = True
            key_details.append({
                "index":   i + 1,
                "masked":  f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "••••••••",
                "active":  is_active
            })
    except Exception as e:
        key_details  = []
        active_count = 1 if gemini_api_key else 0
        total_count  = active_count

    return jsonify({
        "is_set":       active_count > 0,
        "set":          active_count > 0,
        "active_keys":  active_count,
        "total_keys":   total_count,
        "keys":         key_details,
        "masked":       f"{gemini_api_key[:6]}...{gemini_api_key[-4:]}" if gemini_api_key else None
    })


@admin_bp.route("/api/upload", methods=["POST"])
def upload_pdf():
    if "file" not in request.files:
        return jsonify({"error": "কোনো ফাইল নেই"}), 400

    file       = request.files["file"]
    class_id   = request.form.get("class_id", "").strip()
    subject_id = request.form.get("subject_id", "").strip()

    if not class_id or not subject_id:
        return jsonify({"error": "class_id ও subject_id দরকার"}), 400
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "শুধু PDF ফাইল গ্রহণযোগ্য"}), 400

    filename = f"{class_id}_{subject_id}.pdf"
    filepath = os.path.join(UPLOAD_DIR, filename)
    file.save(filepath)

    doc = fitz.open(filepath)
    page_count = len(doc)
    doc.close()

    return jsonify({
        "success": True,
        "filename": filename,
        "pages": page_count,
        "message": f"আপলোড সফল ✅ ({page_count} পেজ)"
    })


@admin_bp.route("/api/split", methods=["POST"])
def split_pdf():
    data       = request.get_json()
    class_id   = data.get("class_id", "")
    subject_id = data.get("subject_id", "")
    parts      = data.get("parts", 4)

    filename = f"{class_id}_{subject_id}.pdf"
    filepath = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": f"ফাইল পাওয়া যায়নি: {filename}"}), 404

    doc = fitz.open(filepath)
    total_pages    = len(doc)
    pages_per_part = math.ceil(total_pages / parts)
    created_files  = []

    for i in range(parts):
        start = i * pages_per_part
        end   = min(start + pages_per_part, total_pages)
        if start >= total_pages:
            break
        part_doc = fitz.open()
        part_doc.insert_pdf(doc, from_page=start, to_page=end - 1)
        part_filename = f"{class_id}_{subject_id}_part{i+1}.pdf"
        part_path     = os.path.join(SPLIT_DIR, part_filename)
        part_doc.save(part_path)
        part_doc.close()
        created_files.append({"filename": part_filename, "pages": end - start, "range": f"{start+1}-{end}"})

    doc.close()
    return jsonify({
        "success": True,
        "total_pages": total_pages,
        "parts": len(created_files),
        "files": created_files,
        "message": f"PDF {len(created_files)} ভাগে ভাগ হয়েছে ✅"
    })


# ══════════════════════════════════════════════════════════
#  Extraction Worker (Background Thread)
# ══════════════════════════════════════════════════════════

def extraction_worker(job_id, source_path, model_name, class_id, subject_id,
                      prompt_type='board_book', client_override=None,
                      group_id=None, part_num=None, page_offset=0):
    """
    Single extraction worker.
    - client_override: নির্দিষ্ট Gemini client (parallel mode এ)
    - group_id / part_num: parallel group এর অংশ হলে দেওয়া হয়
    - page_offset: actual page number (0-based) যেখান থেকে এই part শুরু হয়েছে
    """
    global gemini_client
    client = client_override or gemini_client
    job = jobs[job_id]
    try:
        doc         = fitz.open(source_path)
        total_pages = len(doc)
        job["total_pages"] = total_pages

        model_info  = MODELS.get(model_name, MODELS.get(DEFAULT_MODEL, {}))
        sleep_time  = model_info.get("sleep", 4.0)
        subject_bn  = get_subject_bn(class_id, subject_id)

        # parallel mode এ progress file আলাদা রাখো
        progress_suffix = f"_p{part_num}" if part_num is not None else ""
        progress_file = os.path.join(DATA_DIR, f".progress_{class_id}_{subject_id}{progress_suffix}.json")
        results    = []
        start_page = 0

        if os.path.exists(progress_file):
            progress_data = load_json_file(progress_file)
            results    = progress_data.get("results", [])
            start_page = progress_data.get("last_page", 0)
            job["message"] = f"পেজ {start_page} থেকে রিজিউম হচ্ছে..."

        job["status"] = "running"
        _save_job(job)
        selected_prompt = get_extract_prompt(prompt_type, subject_id)

        # ── Chapter tracking: resume হলে শেষ chapter carry করো
        current_chapter     = None   # যেমন "অধ্যায় ৩ — পরিবেশ দূষণ"
        current_chapter_num = None   # integer যেমন 3
        if results:
            # ইতোমধ্যে কিছু result আছে (resume) — শেষেরটা থেকে chapter নাও
            for prev in reversed(results):
                if prev.get("chapter"):
                    current_chapter     = prev["chapter"]
                    current_chapter_num = prev.get("chapter_num")
                    break

        for page_num in range(start_page, total_pages):
            if job.get("cancelled"):
                job["status"]  = "cancelled"
                job["message"] = "জব বাতিল হয়েছে"
                _save_job(job)
                # parallel group কে জানাও
                if group_id and group_id in parallel_groups:
                    parallel_groups[group_id]["cancelled"] = True
                doc.close()
                return

            job["current_page"] = page_num + 1
            job["progress"]     = round((page_num + 1) / total_pages * 100, 1)
            actual_page         = page_offset + page_num + 1
            job["message"]      = f"পেজ {page_num+1}/{total_pages} (বইয়ের পেজ {actual_page}) প্রসেস হচ্ছে..."

            try:
                page      = doc[page_num]
                pix       = page.get_pixmap(dpi=300)
                img_bytes = pix.tobytes("png")

                response = client.models.generate_content(
                    model=model_name,
                    contents=[
                        types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                        selected_prompt
                    ]
                )

                content      = response.text.strip() if response.text else "[EMPTY_PAGE]"
                content_type = detect_content_type(content)

                # ── Chapter auto-detection ──────────────────────────────
                # এই page এ নতুন [CHAPTER: ...] tag আছে কিনা দেখো
                detected_chapter, detected_num = parse_chapter_from_content(content)
                if detected_chapter:
                    # নতুন chapter শুরু হয়েছে — update করো
                    current_chapter     = detected_chapter
                    current_chapter_num = detected_num
                    job["message"] = (
                        f"পেজ {page_num+1}/{total_pages} — "
                        f"নতুন অধ্যায় পাওয়া গেছে: {current_chapter} ✅"
                    )
                # ───────────────────────────────────────────────────────

                results.append({
                    "class_id":    class_id,
                    "subject_id":  subject_id,
                    "subject_bn":  subject_bn,
                    "page":        actual_page,   # বইয়ের actual page number
                    "chapter":     current_chapter,      # NEW: যেমন "অধ্যায় ৩ — পরিবেশ দূষণ"
                    "chapter_num": current_chapter_num,  # NEW: integer যেমন 3
                    "content":     content,
                    "content_type": content_type,
                    "source_type": prompt_type
                })

                if (page_num + 1) % 10 == 0:
                    save_json_file(progress_file, {"last_page": page_num + 1, "results": results})
                    job["message"] = f"পেজ {page_num+1}/{total_pages} — প্রোগ্রেস সেভ ✅"

                time.sleep(sleep_time)

            except Exception as e:
                error_msg = str(e)
                job["errors"] = job.get("errors", 0) + 1

                # ── 429 Rate Limit: ৬০ সেকেন্ড অপেক্ষা, retry ──────────
                if "429" in error_msg or "rate" in error_msg.lower():
                    job["message"] = f"পেজ {page_num+1} — রেট লিমিট, ৬০ সেকেন্ড অপেক্ষা, retry হবে..."
                    time.sleep(60)
                    try:
                        response = client.models.generate_content(
                            model=model_name,
                            contents=[
                                types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                                selected_prompt
                            ]
                        )
                        content      = response.text.strip() if response.text else "[EMPTY_PAGE]"
                        content_type = detect_content_type(content)
                        detected_chapter, detected_num = parse_chapter_from_content(content)
                        if detected_chapter:
                            current_chapter     = detected_chapter
                            current_chapter_num = detected_num
                        results.append({
                            "class_id":    class_id, "subject_id":  subject_id,
                            "subject_bn":  subject_bn, "page": actual_page,
                            "chapter":     current_chapter, "chapter_num": current_chapter_num,
                            "content":     content, "content_type": content_type,
                            "source_type": prompt_type
                        })
                        job["errors"] -= 1  # retry সফল — error কমাও
                        time.sleep(sleep_time)
                        continue
                    except Exception:
                        pass  # retry ও fail → নিচে error entry যোগ হবে

                # ── 503 Unavailable: ৩০ সেকেন্ড অপেক্ষা, retry ─────────
                elif "503" in error_msg or "UNAVAILABLE" in error_msg or "unavailable" in error_msg.lower():
                    job["message"] = f"পেজ {page_num+1} — সার্ভার ব্যস্ত (503), ৩০ সেকেন্ড অপেক্ষা, retry হবে..."
                    time.sleep(30)
                    try:
                        response = client.models.generate_content(
                            model=model_name,
                            contents=[
                                types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                                selected_prompt
                            ]
                        )
                        content      = response.text.strip() if response.text else "[EMPTY_PAGE]"
                        content_type = detect_content_type(content)
                        detected_chapter, detected_num = parse_chapter_from_content(content)
                        if detected_chapter:
                            current_chapter     = detected_chapter
                            current_chapter_num = detected_num
                        results.append({
                            "class_id":    class_id, "subject_id":  subject_id,
                            "subject_bn":  subject_bn, "page": actual_page,
                            "chapter":     current_chapter, "chapter_num": current_chapter_num,
                            "content":     content, "content_type": content_type,
                            "source_type": prompt_type
                        })
                        job["errors"] -= 1  # retry সফল — error কমাও
                        time.sleep(sleep_time)
                        continue
                    except Exception:
                        pass  # retry ও fail → নিচে error entry যোগ হবে

                # ── অন্য error: log করে skip ──────────────────────────
                results.append({
                    "class_id":    class_id,
                    "subject_id":  subject_id,
                    "subject_bn":  subject_bn,
                    "page":        actual_page,
                    "chapter":     current_chapter,
                    "chapter_num": current_chapter_num,
                    "content":     f"[ERROR: {error_msg}]",
                    "content_type": "error",
                    "source_type": prompt_type
                })
                time.sleep(sleep_time)

        doc.close()

        # ── Parallel mode: temp file এ সেভ করো, group monitor merge করবে
        if group_id and part_num is not None:
            temp_path = os.path.join(DATA_DIR, f".part_{class_id}_{subject_id}_p{part_num}.json")
            save_json_file(temp_path, results)
            job["status"]        = "completed"
            job["progress"]      = 100
            job["total_entries"] = len(results)
            job["message"]       = f"Part {part_num} সম্পন্ন ✅ ({len(results)} এন্ট্রি) — merge অপেক্ষায়..."
            job["completed_at"]  = time.time()
            _save_job(job)  # ← DB persist
            if os.path.exists(progress_file):
                os.remove(progress_file)
            # group monitor কে trigger করো
            _check_group_complete(group_id)
            return

        # ── Single mode: সরাসরি final file এ merge করো
        output_path = get_data_filepath(class_id, subject_id, DATA_DIR, source_type=prompt_type)
        existing = []
        if os.path.exists(output_path):
            try:
                existing = load_json_file(output_path)
            except Exception:
                existing = []
        merged_results = existing + results
        save_json_file(output_path, merged_results)

        if os.path.exists(progress_file):
            os.remove(progress_file)

        job["status"]        = "completed"
        job["progress"]      = 100
        job["output_file"]   = get_data_filename(class_id, subject_id)
        job["total_entries"] = len(results)
        job["message"]       = f"এক্সট্রাকশন সম্পন্ন ✅ ({len(results)} এন্ট্রি)"
        job["completed_at"]  = time.time()
        _save_job(job)  # ← DB persist

    except Exception as e:
        job["status"]  = "error"
        job["message"] = f"এরর: {str(e)}"
        _save_job(job)  # ← DB persist
        if group_id and group_id in parallel_groups:
            parallel_groups[group_id]["error"] = str(e)


def _check_group_complete(group_id):
    """সব part শেষ হলে auto-merge করো। Thread-safe।"""
    with _merge_lock:
        group = parallel_groups.get(group_id)
        if not group or group.get("merged"):
            return

        job_ids    = group["job_ids"]
        all_done   = all(jobs.get(jid, {}).get("status") in ("completed", "error", "cancelled")
                        for jid in job_ids)
        if not all_done:
            return  # এখনো বাকি আছে

        # সব শেষ — merge শুরু
        group["status"]    = "merging"
        group["merged"]    = True
        class_id   = group["class_id"]
        subject_id = group["subject_id"]
        num_parts  = len(job_ids)

        log.info(f"[GROUP {group_id}] সব {num_parts}টা part শেষ — auto-merge শুরু...")

        # page number অনুযায়ী সব results এক করো
        all_results = []
        for i in range(1, num_parts + 1):
            temp_path = os.path.join(DATA_DIR, f".part_{class_id}_{subject_id}_p{i}.json")
            if os.path.exists(temp_path):
                try:
                    part_data = load_json_file(temp_path)
                    all_results.extend(part_data)
                    os.remove(temp_path)  # temp file মুছো
                    log.info(f"[GROUP {group_id}] Part {i}: {len(part_data)} এন্ট্রি merge হয়েছে")
                except Exception as ex:
                    log.warning(f"[GROUP {group_id}] Part {i} পড়তে সমস্যা: {ex}")

        # page number অনুযায়ী sort করো
        all_results.sort(key=lambda x: x.get("page", 0))

        # final file এ save করো (existing এর সাথে merge)
        group_prompt_type = group.get("prompt_type", "board_book")
        output_path = get_data_filepath(class_id, subject_id, DATA_DIR, source_type=group_prompt_type)
        existing = []
        if os.path.exists(output_path):
            try:
                existing = load_json_file(output_path)
            except Exception:
                existing = []
        final_results = existing + all_results
        save_json_file(output_path, final_results)

        group["status"]        = "completed"
        group["total_entries"] = len(all_results)
        group["output_file"]   = get_data_filename(class_id, subject_id)
        group["completed_at"]  = time.time()
        group["message"]       = f"✅ Auto-merge সম্পন্ন! {len(all_results)} এন্ট্রি → {get_data_filename(class_id, subject_id)}"
        log.info(f"[GROUP {group_id}] Merge সম্পন্ন — {len(all_results)} এন্ট্রি")


@admin_bp.route("/api/start-extract", methods=["POST"])
def start_extract():
    if not gemini_client:
        return jsonify({"error": "আগে API key সেট করো"}), 400

    data       = request.get_json()
    source      = data.get("source", "")
    model       = data.get("model", DEFAULT_MODEL)
    class_id    = data.get("class_id", "")
    subject_id  = data.get("subject_id", "")
    prompt_type = data.get("prompt_type", "board_book")
    if prompt_type not in EXTRACT_PROMPTS:
        prompt_type = "board_book"

    if not source or not class_id or not subject_id:
        return jsonify({"error": "source, class_id, subject_id দরকার"}), 400

    source_path = os.path.join(UPLOAD_DIR, source)
    if not os.path.exists(source_path):
        source_path = os.path.join(SPLIT_DIR, source)
    if not os.path.exists(source_path):
        return jsonify({"error": f"সোর্স ফাইল পাওয়া যায়নি: {source}"}), 404

    if model not in MODELS:
        return jsonify({"error": f"অজানা মডেল: {model}"}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "job_id":      job_id,
        "source":      source,
        "model":       model,
        "prompt_type": prompt_type,
        "class_id":    class_id,
        "subject_id":  subject_id,
        "subject_bn":  get_subject_bn(class_id, subject_id),
        "status":      "starting",
        "progress":    0,
        "current_page": 0,
        "total_pages": 0,
        "errors":      0,
        "message":     "জব শুরু হচ্ছে...",
        "started_at":  time.time(),
        "completed_at": None,
        "cancelled":   False
    }
    _save_job(jobs[job_id])  # ← DB তে persist

    threading.Thread(
        target=extraction_worker,
        args=(job_id, source_path, model, class_id, subject_id, prompt_type),
        daemon=True
    ).start()

    return jsonify({"success": True, "job_id": job_id, "message": "এক্সট্রাকশন শুরু হয়েছে ✅"})


@admin_bp.route("/api/start-parallel", methods=["POST"])
def start_parallel():
    """
    4টা split part একসাথে 4টা API key দিয়ে চালাও।
    auto-merge হবে সব শেষ হলে।
    """
    from app import _clients  # app.py এর client pool থেকে নাও

    data       = request.get_json()
    class_id   = data.get("class_id", "")
    subject_id = data.get("subject_id", "")
    model      = data.get("model", DEFAULT_MODEL)
    prompt_type = data.get("prompt_type", "board_book")
    if prompt_type not in EXTRACT_PROMPTS:
        prompt_type = "board_book"

    if not class_id or not subject_id:
        return jsonify({"error": "class_id ও subject_id দরকার"}), 400

    # split_pdfs folder থেকে এই subject এর part files খোঁজো
    base_name = f"{class_id}_{subject_id}"
    part_files = sorted([
        f for f in os.listdir(SPLIT_DIR)
        if f.startswith(base_name + "_part") and f.endswith(".pdf")
    ])

    if not part_files:
        return jsonify({"error": f"কোনো split part পাওয়া যায়নি। আগে PDF split করো।"}), 404

    if model not in MODELS:
        return jsonify({"error": f"অজানা মডেল: {model}"}), 400

    # কতটা page offset আছে প্রতিটা part এর জন্য বের করো
    page_offsets = []
    offset = 0
    for fname in part_files:
        fpath = os.path.join(SPLIT_DIR, fname)
        try:
            doc = fitz.open(fpath)
            page_offsets.append(offset)
            offset += len(doc)
            doc.close()
        except Exception:
            page_offsets.append(offset)

    # group তৈরি করো
    group_id  = str(uuid.uuid4())[:8]
    job_ids   = []
    num_parts = len(part_files)

    # client pool — যতটা part ততটা client cycle করো
    clients_available = _clients if _clients else ([gemini_client] if gemini_client else [])
    if not clients_available:
        return jsonify({"error": "কোনো Gemini client নেই। API key সেট করো।"}), 400

    for i, fname in enumerate(part_files):
        part_num    = i + 1
        source_path = os.path.join(SPLIT_DIR, fname)
        client_for_part = clients_available[i % len(clients_available)]
        page_offset = page_offsets[i]

        job_id = str(uuid.uuid4())[:8]
        jobs[job_id] = {
            "job_id":       job_id,
            "group_id":     group_id,
            "part_num":     part_num,
            "source":       fname,
            "model":        model,
            "prompt_type":  prompt_type,
            "class_id":     class_id,
            "subject_id":   subject_id,
            "subject_bn":   get_subject_bn(class_id, subject_id),
            "status":       "starting",
            "progress":     0,
            "current_page": 0,
            "total_pages":  0,
            "errors":       0,
            "message":      f"Part {part_num} শুরু হচ্ছে...",
            "started_at":   time.time(),
            "completed_at": None,
            "cancelled":    False
        }
        _save_job(jobs[job_id])  # ← DB তে persist
        job_ids.append(job_id)

        threading.Thread(
            target=extraction_worker,
            args=(job_id, source_path, model, class_id, subject_id, prompt_type,
                  client_for_part, group_id, part_num, page_offset),
            daemon=True
        ).start()

    # group রেকর্ড করো
    parallel_groups[group_id] = {
        "group_id":   group_id,
        "class_id":   class_id,
        "subject_id": subject_id,
        "subject_bn": get_subject_bn(class_id, subject_id),
        "job_ids":    job_ids,
        "num_parts":  num_parts,
        "model":      model,
        "prompt_type": prompt_type,
        "status":     "running",
        "merged":     False,
        "started_at": time.time(),
        "completed_at": None,
        "message":    f"{num_parts}টা worker চলছে...",
    }

    return jsonify({
        "success":    True,
        "group_id":   group_id,
        "job_ids":    job_ids,
        "num_parts":  num_parts,
        "message":    f"{num_parts}টা parallel worker শুরু হয়েছে ✅ — শেষ হলে auto-merge হবে"
    })


@admin_bp.route("/api/group/<group_id>", methods=["GET"])
def get_group(group_id):
    """Parallel group এর status দেখো"""
    group = parallel_groups.get(group_id)
    if not group:
        return jsonify({"error": "Group পাওয়া যায়নি"}), 404
    # job details যোগ করো
    group_copy = dict(group)
    group_copy["jobs"] = [jobs.get(jid, {"job_id": jid, "status": "unknown"})
                          for jid in group["job_ids"]]
    return jsonify(group_copy)


@admin_bp.route("/api/groups", methods=["GET"])
def get_all_groups():
    """সব parallel group দেখো"""
    result = []
    for g in sorted(parallel_groups.values(), key=lambda x: x.get("started_at", 0), reverse=True):
        g_copy = dict(g)
        g_copy["jobs"] = [jobs.get(jid, {"job_id": jid, "status": "unknown"})
                          for jid in g["job_ids"]]
        result.append(g_copy)
    return jsonify(result)


@admin_bp.route("/api/job/<job_id>", methods=["GET"])
def get_job(job_id):
    job = jobs.get(job_id)
    if not job:
        # memory তে নেই — DB থেকে চেষ্টা করো
        try:
            conn = _admin_db()
            row = conn.execute("SELECT * FROM extraction_jobs WHERE job_id=?", (job_id,)).fetchone()
            conn.close()
            if row:
                return jsonify(dict(row))
        except Exception:
            pass
        return jsonify({"error": "জব পাওয়া যায়নি"}), 404
    return jsonify(job)


@admin_bp.route("/api/jobs", methods=["GET"])
def get_all_jobs():
    # memory jobs (চলমান) + DB jobs (ইতিহাস) merge করো
    mem_jobs = {j["job_id"]: j for j in jobs.values()}
    db_jobs  = {j["job_id"]: j for j in _load_jobs_from_db(200)}
    # memory সবসময় priority পায় (বেশি fresh)
    merged = {**db_jobs, **mem_jobs}
    result = sorted(merged.values(), key=lambda j: j.get("started_at") or 0, reverse=True)
    return jsonify(result)


@admin_bp.route("/api/data-files", methods=["GET"])
def list_data_files():
    files = []
    # Walk the entire DATA_DIR tree (supports data/ssc/science/physics.json style)
    for root, dirs, fnames in os.walk(DATA_DIR):
        # skip hidden temp dirs
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in fnames:
            if not fname.endswith(".json") or fname.startswith("."):
                continue
            fpath = os.path.join(root, fname)
            stat  = os.stat(fpath)
            # Derive class_id and subject_id from path
            rel = os.path.relpath(fpath, DATA_DIR)  # e.g. "ssc/science/physics.json"
            parts = rel.replace("\\", "/").split("/")
            if len(parts) == 1:
                # legacy flat: ssc_physics.json
                name_parts = fname.replace(".json", "").split("_", 1)
                cid = name_parts[0] if len(name_parts) > 0 else ""
                sid = name_parts[1] if len(name_parts) > 1 else ""
                group_folder = ""
                source_type  = ""
            elif len(parts) == 4:
                # new with source_type: ssc/business/accounting/board_book.json
                cid          = parts[0]
                group_folder = parts[1]
                sid          = parts[2]
                source_type  = parts[3].replace(".json", "")
            elif len(parts) == 3:
                # ssc/science/physics.json (old format without source_type)
                cid          = parts[0]
                group_folder = parts[1]
                sid          = parts[2].replace(".json", "")
                source_type  = ""
            elif len(parts) == 2:
                # ssc/physics.json
                cid          = parts[0]
                group_folder = ""
                sid          = parts[1].replace(".json", "")
                source_type  = ""
            else:
                cid = sid = group_folder = source_type = ""

            try:
                data = load_json_file(fpath)
                entry_count = len(data) if isinstance(data, list) else 0
            except Exception:
                entry_count = 0

            files.append({
                "filename":     os.path.basename(fpath),
                "filepath":     rel,
                "class_id":     cid,
                "group_folder": group_folder,
                "subject_id":   sid,
                "source_type":  source_type,
                "subject_bn":   get_subject_bn(cid, sid) if cid and sid else "",
                "size_kb":      round(stat.st_size / 1024, 1),
                "entries":      entry_count,
                "modified":     stat.st_mtime
            })
    files.sort(key=lambda f: f["modified"], reverse=True)
    return jsonify(files)


@admin_bp.route("/api/upload-json", methods=["POST"])
def upload_json():
    if "file" not in request.files:
        return jsonify({"error": "কোনো ফাইল নেই"}), 400
    file = request.files["file"]
    if not file.filename.lower().endswith(".json"):
        return jsonify({"error": "শুধু JSON ফাইল গ্রহণযোগ্য"}), 400
    filename = file.filename
    filepath = os.path.join(DATA_DIR, filename)
    file.save(filepath)
    try:
        data  = load_json_file(filepath)
        count = len(data) if isinstance(data, list) else 1
    except json.JSONDecodeError:
        os.remove(filepath)
        return jsonify({"error": "ইনভ্যালিড JSON ফাইল"}), 400
    return jsonify({"success": True, "filename": filename, "entries": count,
                    "message": f"JSON আপলোড সফল ✅ ({count} এন্ট্রি)"})


@admin_bp.route("/api/upload-and-import", methods=["POST"])
def upload_and_import():
    """
    JSON ফাইল আপলোড করো + সাথে সাথে সঠিক folder এ save করো + DB import করো।

    Form fields:
      file       → JSON ফাইল
      class_id   → ssc / hsc
      subject_id → physics / accounting / etc.
      source_type → board_book / test_paper / guide
      force      → true/false (আগের data মুছে নতুন করে import)
    """
    from app import get_db, _db_import_json_to_fts
    from config import get_data_filepath

    # ── Input Validation ─────────────────────────────────
    if "file" not in request.files:
        return jsonify({"error": "JSON ফাইল দরকার"}), 400

    file        = request.files["file"]
    class_id    = request.form.get("class_id", "").strip()
    subject_id  = request.form.get("subject_id", "").strip()
    source_type = request.form.get("source_type", "guide").strip()
    force       = request.form.get("force", "false").lower() == "true"

    if not file.filename.lower().endswith(".json"):
        return jsonify({"error": "শুধু .json ফাইল গ্রহণযোগ্য"}), 400
    if not class_id or not subject_id:
        return jsonify({"error": "class_id ও subject_id দরকার"}), 400
    if source_type not in ("board_book", "test_paper", "guide"):
        return jsonify({"error": "source_type হবে: board_book / test_paper / guide"}), 400

    # ── Correct Path এ Save করো ──────────────────────────
    # e.g. data/ssc/business/accounting/guide.json
    save_path = get_data_filepath(class_id, subject_id, DATA_DIR, source_type)
    try:
        file.save(save_path)
    except Exception as e:
        return jsonify({"error": f"ফাইল save করতে সমস্যা: {e}"}), 500

    # ── JSON Valid কিনা চেক করো ──────────────────────────
    try:
        data  = load_json_file(save_path)
        count = len(data) if isinstance(data, list) else 1
    except Exception:
        os.remove(save_path)
        return jsonify({"error": "ইনভ্যালিড JSON ফাইল — ফাইল delete করা হয়েছে"}), 400

    # ── Background এ DB Import শুরু করো ──────────────────
    task_id = str(uuid.uuid4())[:8]
    _import_tasks[task_id] = {
        "status":      "running",
        "message":     f"'{source_type}' DB import শুরু হচ্ছে... ({count} entries)",
        "class_id":    class_id,
        "subject_id":  subject_id,
        "source_type": source_type,
        "started_at":  time.time(),
        "file_entries": count,
        "saved_path":  save_path,
    }

    def _run():
        try:
            conn = get_db()
            try:
                if force:
                    # আগের data এই source_type এর জন্য মুছো
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
                    _import_tasks[task_id]["message"] = "আগের data মুছে নতুন import শুরু..."
            finally:
                conn.close()

            def _update_progress(done, total, src, status):
                pct = int(done * 100 / total) if total else 0
                _import_tasks[task_id].update({
                    "status":   status,
                    "message":  f"[{src}] {done}/{total} ({pct}%)",
                    "progress": pct,
                })

            # Bug3 fix: শুধু এইমাত্র upload হওয়া file টাই import করো
            result = _db_import_json_to_fts(
                class_id, subject_id,
                force=False,           # আমরা উপরে manually force করেছি
                on_progress=_update_progress,
                specific_files=[(source_type, save_path)]
            )

            chunks = result.get("total_inserted", 0)
            mcqs   = result.get("mcq_inserted", 0)
            cqs    = result.get("cq_inserted", 0)

            _import_tasks[task_id].update({
                "status":         "done",
                "message":        f"✅ Import সফল! {chunks} chunk, {mcqs} MCQ, {cqs} CQ",
                "progress":       100,
                "chunks_inserted": chunks,
                "mcq_inserted":   mcqs,
                "cq_inserted":    cqs,
            })
        except Exception as e:
            log.error("upload_and_import background error: %s", e)
            _import_tasks[task_id].update({
                "status":  "error",
                "message": f"❌ Import এ সমস্যা: {e}",
            })

    threading.Thread(target=_run, daemon=True).start()

    return jsonify({
        "success":     True,
        "task_id":     task_id,
        "saved_path":  save_path,
        "file_entries": count,
        "message":     f"✅ ফাইল save হয়েছে ({count} entries) — DB import চলছে background এ",
        "poll_url":    f"/admin/api/db-import-status/{task_id}",
    })


@admin_bp.route("/api/merge", methods=["POST"])
def merge_json():
    data      = request.get_json()
    filenames = data.get("filenames", [])
    output    = data.get("output", "")
    if len(filenames) < 2:
        return jsonify({"error": "মার্জ করতে কমপক্ষে ২টা ফাইল দরকার"}), 400
    if not output:
        return jsonify({"error": "আউটপুট ফাইলের নাম দরকার"}), 400
    if not output.endswith(".json"):
        output += ".json"
    merged = []
    for fname in filenames:
        fpath = os.path.join(DATA_DIR, fname)
        if not os.path.exists(fpath):
            return jsonify({"error": f"ফাইল পাওয়া যায়নি: {fname}"}), 404
        fd = load_json_file(fpath)
        merged.extend(fd if isinstance(fd, list) else [fd])
    save_json_file(os.path.join(DATA_DIR, output), merged)
    return jsonify({"success": True, "output": output, "total_entries": len(merged),
                    "message": f"মার্জ সফল ✅ ({len(merged)} এন্ট্রি)"})


@admin_bp.route("/api/download-json/<filename>", methods=["GET"])
def download_json(filename):
    filepath = os.path.join(DATA_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "ফাইল পাওয়া যায়নি"}), 404
    return send_file(filepath, as_attachment=True)


@admin_bp.route("/api/delete-json", methods=["POST"])
def delete_json():
    data     = request.get_json()
    filename = data.get("filename", "")
    if not filename:
        return jsonify({"error": "ফাইলের নাম দরকার"}), 400
    filepath = os.path.join(DATA_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "ফাইল পাওয়া যায়নি"}), 404
    os.remove(filepath)
    return jsonify({"success": True, "message": f"{filename} মুছে ফেলা হয়েছে ✅"})


@admin_bp.route("/api/models", methods=["GET"])
def list_models():
    return jsonify([
        {"id": mid, "label": info.get("label", mid),
         "rpm": info.get("rpm"), "rpd": info.get("rpd"), "sleep": info.get("sleep")}
        for mid, info in MODELS.items()
    ])


@admin_bp.route("/api/classes", methods=["GET"])
def list_classes():
    result = {}
    for class_id, cls in CLASSES.items():
        groups_out = {}
        for grp_id, grp in cls.get("groups", {}).items():
            groups_out[grp_id] = {
                "label":        grp.get("label", grp_id),
                "subjects":     grp.get("subjects", {}),
                "4th_subjects": grp.get("4th_subjects", {}),
            }
        result[class_id] = {
            "label":  cls.get("label", class_id),
            "icon":   cls.get("icon", "🎓"),
            "groups": groups_out,
        }
    return jsonify(result)


@admin_bp.route("/api/split-files", methods=["GET"])
def list_split_files():
    files = []
    for fname in os.listdir(SPLIT_DIR):
        if fname.endswith(".pdf"):
            fpath = os.path.join(SPLIT_DIR, fname)
            stat  = os.stat(fpath)
            try:
                doc   = fitz.open(fpath)
                pages = len(doc)
                doc.close()
            except Exception:
                pages = 0
            files.append({"filename": fname, "size_kb": round(stat.st_size / 1024, 1),
                          "pages": pages, "modified": stat.st_mtime})
    files.sort(key=lambda f: f["filename"])
    return jsonify(files)


@admin_bp.route("/api/download-split/<filename>", methods=["GET"])
def download_split(filename):
    filepath = os.path.join(SPLIT_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "ফাইল পাওয়া যায়নি"}), 404
    return send_file(filepath, as_attachment=True)


def get_cq_filepath(class_id, subject_id):
    return os.path.join(CQ_DIR, f"{class_id}_{subject_id}_cq.json")


@admin_bp.route("/api/cq-files", methods=["GET"])
def list_cq_files():
    class_id   = request.args.get("class_id", "").strip()
    subject_id = request.args.get("subject_id", "").strip()

    if class_id and subject_id:
        filepath = get_cq_filepath(class_id, subject_id)
        if not os.path.exists(filepath):
            return jsonify([])
        cqs = load_json_file(filepath)
        for cq in cqs:
            q = cq.get("question_text", cq.get("question", cq.get("text", "")))
            cq["question"] = q
            cq["text"]     = q
            cq["question_text"] = q
        return jsonify(cqs)

    files = []
    for fname in os.listdir(CQ_DIR):
        if fname.endswith("_cq.json"):
            fpath = os.path.join(CQ_DIR, fname)
            stat  = os.stat(fpath)
            try:
                count = len(load_json_file(fpath))
            except Exception:
                count = 0
            base  = fname.replace("_cq.json", "")
            parts = base.split("_", 1)
            cid   = parts[0] if len(parts) > 0 else ""
            sid   = parts[1] if len(parts) > 1 else ""
            files.append({
                "filename": fname, "class_id": cid, "subject_id": sid,
                "subject_bn": get_subject_bn(cid, sid) if cid and sid else "",
                "count": count, "size_kb": round(stat.st_size / 1024, 1),
                "modified": stat.st_mtime
            })
    files.sort(key=lambda f: f["modified"], reverse=True)
    return jsonify(files)


@admin_bp.route("/api/cq/add", methods=["POST"])
def add_cq():
    data          = request.get_json()
    class_id      = data.get("class_id", "")
    subject_id    = data.get("subject_id", "")
    chapter       = data.get("chapter", "")
    question_text = data.get("question_text", "")
    parts         = data.get("parts", [])

    if not class_id or not subject_id or not question_text:
        return jsonify({"error": "class_id, subject_id, question_text দরকার"}), 400

    filepath = get_cq_filepath(class_id, subject_id)
    cq_list  = load_json_file(filepath)
    new_cq   = {
        "id":           str(uuid.uuid4())[:8],
        "class_id":     class_id,
        "subject_id":   subject_id,
        "subject_bn":   get_subject_bn(class_id, subject_id),
        "chapter":      chapter,
        "question":     question_text,
        "text":         question_text,
        "question_text": question_text,
        "parts":        parts,
        "created_at":   time.time()
    }
    cq_list.append(new_cq)
    save_json_file(filepath, cq_list)
    return jsonify({"success": True, "cq": new_cq, "total": len(cq_list),
                    "message": "CQ যোগ হয়েছে ✅"})


@admin_bp.route("/api/cq/delete", methods=["POST"])
def delete_cq():
    data       = request.get_json()
    cq_id      = data.get("id", "")
    class_id   = data.get("class_id", "")
    subject_id = data.get("subject_id", "")
    if not all([cq_id, class_id, subject_id]):
        return jsonify({"error": "id, class_id, subject_id দরকার"}), 400
    filepath = get_cq_filepath(class_id, subject_id)
    cq_list  = load_json_file(filepath)
    original = len(cq_list)
    cq_list  = [cq for cq in cq_list if cq.get("id") != cq_id]
    if len(cq_list) == original:
        return jsonify({"error": "CQ পাওয়া যায়নি"}), 404
    save_json_file(filepath, cq_list)
    return jsonify({"success": True, "remaining": len(cq_list), "message": "CQ মুছে ফেলা হয়েছে ✅"})


@admin_bp.route("/api/download-data/<path:filename>", methods=["GET"])
def download_data_file(filename):
    # নতুন folder structure: ssc/business/accounting/board_book.json
    full_path = os.path.normpath(os.path.join(DATA_DIR, filename))
    # Path traversal protection
    if not full_path.startswith(DATA_DIR):
        return jsonify({"error": "Invalid path"}), 400
    if os.path.exists(full_path) and full_path.endswith(".json"):
        return send_file(full_path, as_attachment=True,
                         download_name=os.path.basename(full_path),
                         mimetype="application/json")
    # Fallback: legacy flat file
    safe = os.path.basename(filename)
    for folder in [DATA_DIR, CQ_DIR]:
        p = os.path.join(folder, safe)
        if os.path.exists(p) and safe.endswith(".json"):
            return send_file(p, as_attachment=True, download_name=safe,
                             mimetype="application/json")
    return jsonify({"error": "ফাইল পাওয়া যায়নি"}), 404


@admin_bp.route("/api/delete-data", methods=["POST"])
def delete_data_file():
    data     = request.get_json()
    filename = data.get("filename", "").strip()
    if not filename or not filename.endswith(".json"):
        return jsonify({"error": "ফাইলের নাম দরকার"}), 400
    # নতুন folder structure: ssc/business/accounting/board_book.json
    full_path = os.path.normpath(os.path.join(DATA_DIR, filename))
    if not full_path.startswith(DATA_DIR):
        return jsonify({"error": "Invalid path"}), 400
    if os.path.exists(full_path):
        os.remove(full_path)
        return jsonify({"success": True, "message": f"✅ ফাইল মুছে ফেলা হয়েছে"})
    # Fallback: legacy flat
    flat = os.path.join(DATA_DIR, os.path.basename(filename))
    if os.path.exists(flat):
        os.remove(flat)
    prog = os.path.join(DATA_DIR, f".progress_{filename.replace('.json','')}.json")
    if os.path.exists(prog):
        os.remove(prog)
    return jsonify({"success": True, "message": f"✅ '{filename}' ডিলিট হয়েছে"})


@admin_bp.route("/api/delete-cq", methods=["POST"])
def delete_cq_file():
    data     = request.get_json()
    filename = os.path.basename(data.get("filename", ""))
    if not filename or not filename.endswith("_cq.json"):
        return jsonify({"error": "সঠিক CQ ফাইলের নাম দরকার"}), 400
    filepath = os.path.join(CQ_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": f"'{filename}' পাওয়া যায়নি"}), 404
    os.remove(filepath)
    return jsonify({"success": True, "message": f"✅ '{filename}' ডিলিট হয়েছে"})


@admin_bp.route("/api/delete-upload", methods=["POST"])
def delete_upload():
    data     = request.get_json()
    filename = os.path.basename(data.get("filename", ""))
    if not filename or not filename.endswith(".pdf"):
        return jsonify({"error": "ফাইলের নাম দরকার"}), 400
    deleted = []
    up = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(up):
        os.remove(up)
        deleted.append(up)
    base = filename.replace(".pdf", "")
    for f in os.listdir(SPLIT_DIR):
        if f.startswith(base) and f.endswith(".pdf"):
            try:
                os.remove(os.path.join(SPLIT_DIR, f))
                deleted.append(f)
            except Exception:
                pass
    if not deleted:
        return jsonify({"error": f"'{filename}' পাওয়া যায়নি"}), 404
    return jsonify({"success": True, "deleted": deleted,
                    "message": f"✅ '{filename}' ডিলিট হয়েছে"})


@admin_bp.route("/api/files-summary", methods=["GET"])
def files_summary():
    summary = {"data_files": [], "cq_files": [], "upload_files": []}

    for fname in sorted(os.listdir(DATA_DIR)):
        if fname.endswith(".json") and not fname.startswith(".progress"):
            fpath = os.path.join(DATA_DIR, fname)
            stat  = os.stat(fpath)
            try:
                count = len(load_json_file(fpath))
            except Exception:
                count = 0
            summary["data_files"].append({
                "filename": fname, "count": count,
                "size_kb": round(stat.st_size / 1024, 1), "modified": stat.st_mtime
            })

    for fname in sorted(os.listdir(CQ_DIR)):
        if fname.endswith("_cq.json"):
            fpath = os.path.join(CQ_DIR, fname)
            stat  = os.stat(fpath)
            try:
                count = len(load_json_file(fpath))
            except Exception:
                count = 0
            base  = fname.replace("_cq.json", "").split("_", 1)
            cid   = base[0] if len(base) > 0 else ""
            sid   = base[1] if len(base) > 1 else ""
            summary["cq_files"].append({
                "filename": fname, "class_id": cid, "subject_id": sid,
                "subject_bn": get_subject_bn(cid, sid) if cid and sid else "",
                "count": count, "size_kb": round(stat.st_size / 1024, 1)
            })

    for fname in sorted(os.listdir(UPLOAD_DIR)):
        if fname.endswith(".pdf"):
            fpath = os.path.join(UPLOAD_DIR, fname)
            stat  = os.stat(fpath)
            try:
                doc   = fitz.open(fpath)
                pages = len(doc)
                doc.close()
            except Exception:
                pages = 0
            summary["upload_files"].append({
                "filename": fname, "pages": pages,
                "size_kb": round(stat.st_size / 1024, 1)
            })

    return jsonify(summary)


@admin_bp.route("/api/prompt-types", methods=["GET"])
def list_prompt_types():
    return jsonify([
        {"id": k, "label": v}
        for k, v in EXTRACT_PROMPT_LABELS.items()
    ])


# ══════════════════════════════════════════════════════════
#  MCQ BANK IMPORT — JSON ফাইল থেকে MCQ parse করে DB তে ঢোকাও
# ══════════════════════════════════════════════════════════
import re as _re
import sqlite3 as _sqlite3

def _parse_mcqs_from_entries(entries):
    """
    JSON data entries থেকে [MCQ]...[/MCQ] block parse করে structured list বানায়।
    Returns: list of dicts { question, option_a..d, answer, chapter, chapter_num, source_type, board_name, board_year }
    """
    mcq_pattern = _re.compile(
        r'\[MCQ\](.*?)\[/MCQ\]',
        _re.DOTALL | _re.IGNORECASE
    )
    answer_map = {'ক': 'ক', 'খ': 'খ', 'গ': 'গ', 'ঘ': 'ঘ',
                  'a': 'ক', 'b': 'খ', 'c': 'গ', 'd': 'ঘ'}

    results = []
    for entry in entries:
        content = entry.get("content", "")
        if "[MCQ]" not in content:
            continue

        chapter     = entry.get("chapter", "")
        chapter_num = entry.get("chapter_num")
        source_type = entry.get("source_type", "board_book")

        # board info from [SOURCE: ...] tag if present
        board_name, board_year = "", ""
        src_match = _re.search(r'\[SOURCE:([^\]]+)\]', content)
        if src_match:
            src_text = src_match.group(1)
            bm = _re.search(r'board=([^,\]]+)', src_text)
            ym = _re.search(r'year=([^,\]]+)', src_text)
            if bm: board_name = bm.group(1).strip()
            if ym: board_year = ym.group(1).strip()

        difficulty_map = {
            "easy": "easy", "সহজ": "easy",
            "medium": "medium", "মাঝারি": "medium",
            "hard": "hard", "কঠিন": "hard",
        }

        for mcq_block in mcq_pattern.finditer(content):
            block = mcq_block.group(1).strip()
            lines = [l.strip() for l in block.splitlines() if l.strip()]

            question    = ""
            options     = []
            answer      = "N/A"
            explanation = ""
            difficulty  = "medium"  # default

            for line in lines:
                if line.startswith("প্রশ্ন:"):
                    question = line[len("প্রশ্ন:"):].strip()
                elif _re.match(r'^\((ক|খ|গ|ঘ|a|b|c|d)\)', line, _re.IGNORECASE):
                    options.append(_re.sub(r'^\([^)]+\)\s*', '', line).strip())
                elif line.startswith("উত্তর:"):
                    raw_ans = line[len("উত্তর:"):].strip()
                    raw_ans = _re.sub(r'[()（）]', '', raw_ans).strip()
                    answer = answer_map.get(raw_ans.lower(), raw_ans)
                elif line.startswith("ব্যাখ্যা:"):
                    expl = line[len("ব্যাখ্যা:"):].strip()
                    if expl.lower() != "n/a":
                        explanation = expl
                elif line.startswith("কঠিনতা:"):
                    raw_diff = line[len("কঠিনতা:"):].strip().lower()
                    difficulty = difficulty_map.get(raw_diff, "medium")

            if not question or len(options) < 4:
                continue

            results.append({
                "question":    question,
                "option_a":    options[0],
                "option_b":    options[1],
                "option_c":    options[2],
                "option_d":    options[3],
                "answer":      answer,
                "explanation": explanation,
                "difficulty":  difficulty,
                "chapter":     chapter,
                "chapter_num": chapter_num,
                "source_type": source_type,
                "board_name":  board_name,
                "board_year":  board_year,
            })

    return results


@admin_bp.route("/api/mcq-bank/import", methods=["POST"])
def mcq_bank_import():
    """
    POST /admin/api/mcq-bank/import
    Body: { class_id, subject_id, overwrite (bool, default false) }

    ওই subject এর JSON ফাইল থেকে সব MCQ parse করে mcq_bank table এ import করে।
    """
    from app import get_db, DB_PATH

    data       = request.get_json() or {}
    class_id   = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()
    overwrite  = data.get("overwrite", False)

    if not class_id or not subject_id:
        return jsonify({"error": "class_id ও subject_id দরকার"}), 400

    data_path = find_data_file(class_id, subject_id, DATA_DIR)
    if not data_path or not os.path.exists(data_path):
        return jsonify({"error": f"ডেটা ফাইল পাওয়া যায়নি ({class_id}/{subject_id})"}), 404

    try:
        entries = load_json_file(data_path)
    except Exception as e:
        return jsonify({"error": f"JSON পড়তে সমস্যা: {e}"}), 500

    mcqs = _parse_mcqs_from_entries(entries)
    if not mcqs:
        return jsonify({
            "success": False,
            "message": "কোনো [MCQ] block পাওয়া যায়নি",
            "total_entries": len(entries)
        }), 200

    try:
        conn = get_db()

        if overwrite:
            conn.execute(
                "DELETE FROM mcq_bank WHERE class_id = ? AND subject_id = ?",
                (class_id, subject_id)
            )

        inserted = 0
        skipped  = 0
        for m in mcqs:
            # duplicate check (same question + subject)
            exists = conn.execute(
                "SELECT 1 FROM mcq_bank WHERE class_id=? AND subject_id=? AND question=?",
                (class_id, subject_id, m["question"])
            ).fetchone()
            if exists and not overwrite:
                skipped += 1
                continue
            conn.execute("""
                INSERT INTO mcq_bank
                    (class_id, subject_id, chapter, chapter_num,
                     question, option_a, option_b, option_c, option_d,
                     answer, explanation, difficulty, source_type, board_name, board_year)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                class_id, subject_id,
                m["chapter"], m["chapter_num"],
                m["question"], m["option_a"], m["option_b"], m["option_c"], m["option_d"],
                m["answer"], m.get("explanation", ""), m.get("difficulty", "medium"),
                m["source_type"], m["board_name"], m["board_year"]
            ))
            inserted += 1

        conn.commit()
        total_in_bank = conn.execute(
            "SELECT COUNT(*) FROM mcq_bank WHERE class_id=? AND subject_id=?",
            (class_id, subject_id)
        ).fetchone()[0]
        conn.close()

        return jsonify({
            "success":      True,
            "inserted":     inserted,
            "skipped":      skipped,
            "total_parsed": len(mcqs),
            "bank_total":   total_in_bank,
            "message":      f"✅ {inserted}টি MCQ import হয়েছে (skip: {skipped}) — Bank এ মোট: {total_in_bank}টি"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════
#  CHAPTER CACHE CLEAR — subject_chapters ফ্রেশ করো
# ══════════════════════════════════════════════════════════
@admin_bp.route("/api/sync-chapters", methods=["POST"])
def sync_chapters():
    """
    POST /admin/api/sync-chapters
    Body: { class_id, subject_id }

    subject_chapters table refresh করে pdf_content থেকে।
    নতুন extraction এর পরে call করো।
    """
    from app import get_db

    data       = request.get_json() or {}
    class_id   = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()
    if not class_id or not subject_id:
        return jsonify({"error": "class_id ও subject_id দরকার"}), 400

    try:
        conn = get_db()
        # পুরনো cache মুছে ফেলো
        conn.execute(
            "DELETE FROM subject_chapters WHERE class_id=? AND subject_id=?",
            (class_id, subject_id)
        )
        # pdf_content থেকে fresh aggregate
        rows = conn.execute("""
            SELECT chapter, chapter_num,
                   COUNT(*) as total_pages,
                   SUM(CASE WHEN content_type='mcq' THEN 1 ELSE 0 END) as total_mcq,
                   SUM(CASE WHEN content_type='cq'  THEN 1 ELSE 0 END) as total_cq
            FROM pdf_content
            WHERE class_id=? AND subject_id=?
              AND chapter IS NOT NULL AND chapter != ''
            GROUP BY chapter, chapter_num
        """, (class_id, subject_id)).fetchall()

        for r in rows:
            conn.execute("""
                INSERT OR REPLACE INTO subject_chapters
                    (class_id, subject_id, chapter_num, chapter_title, total_pages, total_mcq, total_cq)
                VALUES (?,?,?,?,?,?,?)
            """, (class_id, subject_id, r["chapter_num"], r["chapter"],
                  r["total_pages"], r["total_mcq"], r["total_cq"]))

        conn.commit()
        conn.close()
        return jsonify({
            "success": True,
            "synced_chapters": len(rows),
            "message": f"✅ {len(rows)}টি chapter sync হয়েছে"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════
#  DB IMPORT — JSON → FTS5 + MCQ Bank + CQ Model Answers
#  (IM-1 + IM-2 + IM-3 একসাথে trigger করে)
# ══════════════════════════════════════════════════════════
@admin_bp.route("/api/db-import", methods=["POST"])
def db_import():
    """
    POST /admin/api/db-import
    Body: { class_id, subject_id, force (bool) }

    Background thread এ চালায় — বড় JSON (7MB+) timeout করবে না।
    Returns: { task_id } → /api/db-import-status/<task_id> দিয়ে poll করো।
    """
    from app import get_db, _db_import_json_to_fts
    from config import find_all_data_files, find_data_file

    data       = request.get_json() or {}
    class_id   = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()
    force      = data.get("force", False)

    if not class_id or not subject_id:
        return jsonify({"error": "class_id ও subject_id দরকার"}), 400

    # ── আগে check করো JSON file আছে কিনা ─────────────────
    all_files = find_all_data_files(class_id, subject_id, DATA_DIR)
    if not all_files:
        # legacy flat path চেষ্টা করো
        legacy = find_data_file(class_id, subject_id, DATA_DIR)
        if not legacy:
            return jsonify({
                "error": (
                    f"JSON ফাইল পাওয়া যায়নি।\n"
                    f"Expected: data/{class_id}/.../{ subject_id}/guide.json\n"
                    f"Extraction সম্পন্ন হয়েছে কিনা check করুন।"
                )
            }), 404

    task_id = str(uuid.uuid4())[:8]
    _import_tasks[task_id] = {
        "status":  "running",
        "message": "Import শুরু হচ্ছে...",
        "class_id": class_id,
        "subject_id": subject_id,
        "started_at": time.time(),
    }

    def _run():
        try:
            conn = get_db()
            try:
                if force:
                    fts_ids = conn.execute(
                        "SELECT id FROM pdf_content WHERE class_id=? AND subject_id=?",
                        (class_id, subject_id)
                    ).fetchall()
                    for row in fts_ids:
                        try:
                            conn.execute("DELETE FROM pdf_content_fts WHERE rowid=?", (row[0],))
                        except Exception:
                            pass
                    conn.execute("DELETE FROM pdf_content WHERE class_id=? AND subject_id=?", (class_id, subject_id))
                    conn.execute("DELETE FROM mcq_bank WHERE class_id=? AND subject_id=?", (class_id, subject_id))
                    conn.execute("DELETE FROM cq_model_answers WHERE class_id=? AND subject_id=?", (class_id, subject_id))
                    conn.commit()
                    _import_tasks[task_id]["message"] = "আগের data মুছে নতুন import শুরু..."
            finally:
                conn.close()

            _import_tasks[task_id]["message"] = "JSON parse ও DB insert চলছে... (বড় ফাইলে কয়েক মিনিট লাগতে পারে)"

            # progress callback — UI তে real-time % দেখানোর জন্য
            def _update_progress(done, total, src, status):
                pct = int(done * 100 / total) if total else 0
                _import_tasks[task_id].update({
                    "status":     status,
                    "message":    f"[{src}] {done}/{total} ({pct}%)",
                    "progress":   pct,
                    "current_source": src
                })

            result = _db_import_json_to_fts(class_id, subject_id, force=force, on_progress=_update_progress)

            total_chunks = result.get("total_inserted", 0)
            mcq_count    = result.get("mcq_inserted", 0)
            cq_count     = result.get("cq_inserted", 0)
            was_resumed  = result.get("was_resumed", False)

            conn2 = get_db()
            try:
                # Total counts in DB (আগের + নতুন)
                total_db_mcq = conn2.execute(
                    "SELECT COUNT(*) FROM mcq_bank WHERE class_id=? AND subject_id=?",
                    (class_id, subject_id)
                ).fetchone()[0]
                total_db_cq = conn2.execute(
                    "SELECT COUNT(*) FROM cq_model_answers WHERE class_id=? AND subject_id=?",
                    (class_id, subject_id)
                ).fetchone()[0]
                rows = conn2.execute(
                    "SELECT content_type, COUNT(*) as cnt FROM pdf_content WHERE class_id=? AND subject_id=? GROUP BY content_type ORDER BY cnt DESC",
                    (class_id, subject_id)
                ).fetchall()
                breakdown = {r["content_type"]: r["cnt"] for r in rows}
            finally:
                conn2.close()

            resume_note = " — ♻️ interrupted থেকে resume হয়েছে!" if was_resumed else ""
            _import_tasks[task_id].update({
                "status":        "completed",
                "total_chunks":  total_chunks,
                "mcq_count":     total_db_mcq,    # DB-র actual total
                "cq_count":      total_db_cq,
                "breakdown":     breakdown,
                "new_inserted":  mcq_count if isinstance(mcq_count, int) else 0,  # শুধু নতুন
                "was_resumed":   was_resumed,
                "files":         result.get("files", []),
                "message":       f"✅ {total_chunks}টি নতুন chunk import হয়েছে | MCQ Bank: {total_db_mcq}টি | CQ Model: {total_db_cq}টি{resume_note}",
                "completed_at":  time.time(),
            })

        except Exception as e:
            _import_tasks[task_id].update({
                "status":         "error",
                "message":        f"এরর: {str(e)}",
                "resumable_hint": "আবার POST /api/db-import call করুন — interrupted index থেকে resume হবে",
            })
            log.error("db_import background error: %s", e)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"success": True, "task_id": task_id, "message": "Import background এ শুরু হয়েছে ✅"})


@admin_bp.route("/api/db-import-status/<task_id>", methods=["GET"])
def db_import_status(task_id):
    """Poll endpoint — /api/db-import থেকে পাওয়া task_id দিয়ে call করো"""
    task = _import_tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task পাওয়া যায়নি"}), 404
    return jsonify(task)


@admin_bp.route("/api/progress-files", methods=["GET"])
def list_progress_files():
    """
    Resume করার জন্য — disk এ .progress_*.json files খোঁজো।
    Returns: [ { class_id, subject_id, last_page, entries_done, filename } ]
    """
    found = []
    try:
        for fname in os.listdir(DATA_DIR):
            if fname.startswith(".progress_") and fname.endswith(".json"):
                fpath = os.path.join(DATA_DIR, fname)
                try:
                    pdata   = load_json_file(fpath)
                    # filename format: .progress_{class_id}_{subject_id}.json
                    # বা .progress_{class_id}_{subject_id}_p{N}.json
                    inner   = fname[len(".progress_"):-len(".json")]
                    parts   = inner.split("_")
                    class_id   = parts[0] if parts else ""
                    subject_id = "_".join(parts[1:]) if len(parts) > 1 else ""
                    found.append({
                        "filename":     fname,
                        "class_id":     class_id,
                        "subject_id":   subject_id,
                        "last_page":    pdata.get("last_page", 0),
                        "entries_done": len(pdata.get("results", [])),
                    })
                except Exception:
                    pass
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(found)


@admin_bp.route("/api/import-progress", methods=["GET"])
def list_import_progress_files():
    """
    JSON → DB import এ interrupted হওয়া progress files দেখাও।
    Resume করতে: POST /api/db-import with same {class_id, subject_id} — interrupted index থেকে শুরু হবে।
    """
    found = []
    try:
        for fname in os.listdir(DATA_DIR):
            if not fname.startswith(".import_progress_") or not fname.endswith(".json"):
                continue
            fpath = os.path.join(DATA_DIR, fname)
            try:
                pdata = load_json_file(fpath)
                # filename format: .import_progress_{class}_{subj}_{src}_{base}.json
                inner = fname[len(".import_progress_"):-len(".json")]
                parts = inner.split("_")
                # parts: [class_id, subject_id, source_type, base]
                # source_type হলো board_book / test_paper / guide
                class_id    = parts[0] if len(parts) > 0 else ""
                subject_id  = parts[1] if len(parts) > 1 else ""
                source_type = parts[2] if len(parts) > 2 else ""
                found.append({
                    "filename":     fname,
                    "class_id":     class_id,
                    "subject_id":   subject_id,
                    "source_type":  source_type,
                    "last_index":   pdata.get("last_index", 0),
                    "items_done":   pdata.get("items_done", 0),
                    "updated_at":   pdata.get("updated_at", ""),
                    "session_id":   pdata.get("session_id", ""),
                    "status":       pdata.get("status", "in_progress"),
                    "resumable":    pdata.get("status") == "in_progress"
                })
            except Exception:
                pass
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "importable_resume_files":  found,
        "any_resumable":            any(x["resumable"] for x in found),
        "total_pending":            sum(1 for x in found if x["resumable"])
    })


@admin_bp.route("/api/import-progress/clear", methods=["POST"])
def clear_import_progress():
    """Resume files manually clear করো — 'completed' state force করতে।"""
    cleared = 0
    try:
        for fname in os.listdir(DATA_DIR):
            if fname.startswith(".import_progress_") and fname.endswith(".json"):
                os.remove(os.path.join(DATA_DIR, fname))
                cleared += 1
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"success": True, "cleared": cleared})


# ══════════════════════════════════════════════════════════
#  DB STATS — সব table এর row count একসাথে
# ══════════════════════════════════════════════════════════
@admin_bp.route("/api/db-stats", methods=["GET"])
def db_stats():
    """
    GET /admin/api/db-stats
    সব main table এর row count + DB size।
    """
    from app import get_db, DB_PATH
    import os

    tables = [
        "pdf_content", "mcq_bank", "cq_model_answers",
        "response_cache", "subject_chapters", "chapter_summaries",
        "pdf_embeddings", "student_progress", "conversation_history",
        "training_feedback", "exam_sessions", "student_routine",
    ]

    try:
        conn = get_db()
        try:
            stats = {}
            for tbl in tables:
                try:
                    n = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                    stats[tbl] = n
                except Exception:
                    stats[tbl] = None  # table নেই বা error

            # content_type breakdown for pdf_content
            breakdown = {}
            try:
                rows = conn.execute(
                    "SELECT content_type, COUNT(*) as cnt FROM pdf_content GROUP BY content_type"
                ).fetchall()
                breakdown = {r["content_type"]: r["cnt"] for r in rows}
            except Exception:
                pass

        finally:
            conn.close()

        # DB file size
        db_size_bytes = 0
        try:
            db_size_bytes = os.path.getsize(DB_PATH)
        except Exception:
            pass

        db_size_mb = round(db_size_bytes / (1024 * 1024), 2)

        return jsonify({
            "success":         True,
            "tables":          stats,
            "chunk_breakdown": breakdown,
            "db_size_mb":      db_size_mb,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════
#  CACHE CLEAR — response_cache table খালি করো
# ══════════════════════════════════════════════════════════
@admin_bp.route("/api/cache/clear", methods=["POST"])
def cache_clear():
    """
    POST /admin/api/cache/clear
    Body: { scope: "all" | "subject", class_id, subject_id }

    scope="all"     → পুরো response_cache মুছে দাও
    scope="subject" → শুধু ওই subject এর cache মুছে দাও
    """
    from app import get_db

    data       = request.get_json() or {}
    scope      = data.get("scope", "all")
    class_id   = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()

    try:
        conn = get_db()
        try:
            if scope == "subject" and class_id and subject_id:
                # question column এ class_id/subject_id থাকলে filter করো
                # (hash-based cache তাই approximate match)
                conn.execute(
                    "DELETE FROM response_cache WHERE question LIKE ?",
                    (f"%{class_id}%{subject_id}%",)
                )
                deleted_label = f"{class_id}/{subject_id} cache"
            else:
                conn.execute("DELETE FROM response_cache")
                deleted_label = "সম্পূর্ণ response cache"

            remaining = conn.execute("SELECT COUNT(*) FROM response_cache").fetchone()[0]
            conn.commit()
        finally:
            conn.close()

        return jsonify({
            "success":   True,
            "remaining": remaining,
            "message":   f"✅ {deleted_label} clear হয়েছে — বাকি: {remaining}টি entry"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════
#  CQ MODEL ANSWERS — browse + delete
# ══════════════════════════════════════════════════════════
@admin_bp.route("/api/cq-model-list", methods=["GET"])
def cq_model_list():
    """
    GET /admin/api/cq-model-list?class_id=ssc&subject_id=physics&limit=50&offset=0
    cq_model_answers table থেকে list করো।
    """
    from app import get_db

    class_id   = request.args.get("class_id", "").strip()
    subject_id = request.args.get("subject_id", "").strip()
    chapter    = request.args.get("chapter", "").strip()
    limit      = int(request.args.get("limit", 50))
    offset     = int(request.args.get("offset", 0))

    where  = []
    params = []
    if class_id:
        where.append("class_id=?");   params.append(class_id)
    if subject_id:
        where.append("subject_id=?"); params.append(subject_id)
    if chapter:
        where.append("chapter LIKE ?"); params.append(f"%{chapter}%")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    try:
        conn = get_db()
        try:
            total = conn.execute(
                f"SELECT COUNT(*) FROM cq_model_answers {where_sql}", params
            ).fetchone()[0]

            rows = conn.execute(
                f"""SELECT id, class_id, subject_id, chapter, chapter_num,
                           stimulus, question_ka, question_kha, question_ga, question_gha,
                           answer_ka, answer_kha, answer_ga, answer_gha,
                           source_type, board_name, board_year, created_at
                    FROM cq_model_answers {where_sql}
                    ORDER BY class_id, subject_id, chapter_num, id
                    LIMIT ? OFFSET ?""",
                params + [limit, offset]
            ).fetchall()

        finally:
            conn.close()

        items = []
        for r in rows:
            items.append({
                "id":           r["id"],
                "class_id":     r["class_id"],
                "subject_id":   r["subject_id"],
                "chapter":      r["chapter"],
                "chapter_num":  r["chapter_num"],
                "stimulus":     (r["stimulus"] or "")[:200],
                "question_ka":  r["question_ka"],
                "question_kha": r["question_kha"],
                "question_ga":  r["question_ga"],
                "question_gha": r["question_gha"],
                "answer_ka":    (r["answer_ka"]  or "")[:100],
                "answer_kha":   (r["answer_kha"] or "")[:100],
                "answer_ga":    (r["answer_ga"]  or "")[:100],
                "answer_gha":   (r["answer_gha"] or "")[:100],
                "source_type":  r["source_type"],
                "board_name":   r["board_name"],
                "board_year":   r["board_year"],
            })

        return jsonify({"success": True, "total": total, "items": items})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/api/cq-model-delete", methods=["POST"])
def cq_model_delete():
    """
    POST /admin/api/cq-model-delete
    Body: { id: <integer> }   অথবা  { class_id, subject_id }  → সব মুছে দাও
    """
    from app import get_db

    data       = request.get_json() or {}
    record_id  = data.get("id")
    class_id   = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()

    try:
        conn = get_db()
        try:
            if record_id:
                conn.execute("DELETE FROM cq_model_answers WHERE id=?", (record_id,))
                msg = f"✅ CQ #{record_id} মুছে গেছে"
            elif class_id and subject_id:
                conn.execute(
                    "DELETE FROM cq_model_answers WHERE class_id=? AND subject_id=?",
                    (class_id, subject_id)
                )
                msg = f"✅ {class_id}/{subject_id} এর সব CQ model answers মুছে গেছে"
            else:
                return jsonify({"error": "id অথবা class_id+subject_id দিতে হবে"}), 400

            conn.commit()
        finally:
            conn.close()

        return jsonify({"success": True, "message": msg})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════
#  MCQ BANK STATS — subject অনুযায়ী count দেখাও
# ══════════════════════════════════════════════════════════
@admin_bp.route("/api/mcq-bank/stats", methods=["GET"])
def mcq_bank_stats():
    """
    GET /admin/api/mcq-bank/stats?class_id=ssc&subject_id=physics
    MCQ bank এ ওই subject এর কতটা MCQ আছে দেখায়।
    class_id/subject_id না দিলে সব subject এর summary দেয়।
    """
    from app import get_db

    class_id   = request.args.get("class_id", "").strip()
    subject_id = request.args.get("subject_id", "").strip()

    try:
        conn = get_db()
        try:
            if class_id and subject_id:
                total = conn.execute(
                    "SELECT COUNT(*) FROM mcq_bank WHERE class_id=? AND subject_id=?",
                    (class_id, subject_id)
                ).fetchone()[0]

                by_chapter = conn.execute(
                    """SELECT chapter, chapter_num, COUNT(*) as cnt,
                              SUM(CASE WHEN source_type='test_paper' THEN 1 ELSE 0 END) as from_paper,
                              SUM(CASE WHEN source_type='board_book' THEN 1 ELSE 0 END) as from_book
                       FROM mcq_bank WHERE class_id=? AND subject_id=?
                       GROUP BY chapter, chapter_num ORDER BY chapter_num""",
                    (class_id, subject_id)
                ).fetchall()

                chapters = [
                    {"chapter": r["chapter"], "chapter_num": r["chapter_num"],
                     "total": r["cnt"], "from_paper": r["from_paper"], "from_book": r["from_book"]}
                    for r in by_chapter
                ]

                return jsonify({
                    "success": True, "total": total,
                    "class_id": class_id, "subject_id": subject_id,
                    "chapters": chapters
                })
            else:
                # সব subject এর summary
                rows = conn.execute(
                    """SELECT class_id, subject_id, COUNT(*) as cnt
                       FROM mcq_bank GROUP BY class_id, subject_id
                       ORDER BY class_id, cnt DESC"""
                ).fetchall()
                summary = [
                    {"class_id": r["class_id"], "subject_id": r["subject_id"], "total": r["cnt"]}
                    for r in rows
                ]
                grand_total = sum(r["total"] for r in summary)
                return jsonify({"success": True, "grand_total": grand_total, "subjects": summary})

        finally:
            conn.close()

    except Exception as e:
        return jsonify({"error": str(e)}), 500
