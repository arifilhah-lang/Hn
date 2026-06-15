"""
╔══════════════════════════════════════════════════════════╗
║  Step 14 — Semantic Search / Vector Embedding            ║
║                                                          ║
║  Model: gemini-embedding-2 (text-embedding-004 shutdown) ║
║  Dim:   3072                                             ║
║                                                          ║
║  POST /api/search/semantic        — hybrid search        ║
║  POST /admin/api/embeddings/generate — embed content     ║
║  GET  /admin/api/embeddings/status   — কতটুকু done       ║
╚══════════════════════════════════════════════════════════╝
"""

from flask import Blueprint, request, jsonify
import sqlite3, os, json, logging, struct, time
import math

log = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "study_ai.db")

EMBEDDING_MODEL = "gemini-embedding-2"   # text-embedding-004 শাটডাউন হয়েছে
EMBED_DIM       = 3072                   # gemini-embedding-2 output dimension
EMBED_BATCH     = 20                     # প্রতি batch এ কতটা content embed করবো
EMBED_SLEEP     = 0.7                    # rate-limit sleep (100 RPM = 0.6s)

# ── Hybrid Search Tuning Constants ─────────────────────────
# Google best practice (Vertex AI / Gemini docs অনুযায়ী):
# - Reciprocal Rank Fusion (RRF) FTS+semantic combine করার recommended পদ্ধতি
# - Min cosine similarity threshold: 0.5 এর নিচে result unreliable
# - Weight balance: FTS-এ exact keyword match গুরুত্বপূর্ণ, semantic context এর জন্য

MIN_SEMANTIC_SCORE    = 0.50   # cosine similarity এর নিচে discard
MIN_FTS_SCORE         = 0.10   # normalized FTS rank এর নিচে discard
RRF_K                 = 60     # RRF formula এর K constant (প্রমাণিত optimal value)
WEIGHT_SEMANTIC       = 0.6    # semantic score এর weight
WEIGHT_FTS            = 0.4    # FTS score এর weight
DIVERSITY_THRESHOLD   = 0.92   # একই chapter/page থেকে repeat results কমাতে

# ── DB helper ─────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

# ── Gemini client ─────────────────────────────────────────
from config import GEMINI_API_KEYS, DEFAULT_MODEL
from google import genai

_sem_client = None
def _get_client():
    global _sem_client
    if _sem_client is None:
        for key in GEMINI_API_KEYS:
            if key.strip():
                try:
                    _sem_client = genai.Client(
                        api_key=key,
                        http_options={'api_version': 'v1beta'}
                    )
                    break
                except Exception:
                    pass
    return _sem_client

# ── Blueprint ─────────────────────────────────────────────
bp = Blueprint("semantic_search", __name__)

# ══════════════════════════════════════════════════════════
#  TABLE INIT
# ══════════════════════════════════════════════════════════
def _init_tables():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pdf_embeddings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id INTEGER NOT NULL REFERENCES pdf_content(id) ON DELETE CASCADE,
            embedding  BLOB NOT NULL,
            model      TEXT DEFAULT 'gemini-embedding-2',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(content_id)
        )
    """)
    conn.commit()
    conn.close()
    log.info("[Step14] pdf_embeddings table ready")

_init_tables()

# ══════════════════════════════════════════════════════════
#  EMBEDDING HELPERS
# ══════════════════════════════════════════════════════════

def _vec_to_blob(vec: list) -> bytes:
    """float list → binary BLOB (little-endian float32)"""
    return struct.pack(f"{len(vec)}f", *vec)

def _blob_to_vec(blob: bytes) -> list:
    """BLOB → float list"""
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))

def _cosine(a: list, b: list) -> float:
    """cosine similarity"""
    dot  = sum(x*y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x*x for x in a))
    mag_b = math.sqrt(sum(x*x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)

def _embed_text(text: str) -> list | None:
    """একটা text কে embedding vector এ convert করো"""
    client = _get_client()
    if not client:
        return None
    try:
        result = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
        )
        # genai SDK v2: result.embeddings[0].values
        return result.embeddings[0].values
    except Exception as e:
        log.error(f"[Step14] embed_text error: {e}")
        return None

# ══════════════════════════════════════════════════════════
#  HYBRID SEARCH (FTS5 + Semantic)
# ══════════════════════════════════════════════════════════
def _fts_search(conn, query: str, class_id: str, subject_id: str, top_n=10, min_score=MIN_FTS_SCORE, chapter_num=None) -> list:
    """FTS5 দিয়ে শব্দ-ভিত্তিক search — relevance threshold সহ"""
    try:
        sql = """
            SELECT pc.id, pc.content, pc.chapter, pc.page,
                   bm25(pdf_content_fts) AS raw_score
            FROM pdf_content_fts
            JOIN pdf_content pc ON pc.rowid = pdf_content_fts.rowid
            WHERE pdf_content_fts MATCH ?
              AND pc.class_id   = ?
              AND pc.subject_id = ?
        """
        params = [query, class_id, subject_id]
        if chapter_num:
            sql += " AND pc.chapter_num = ?"
            params.append(str(chapter_num))
            
        sql += " ORDER BY raw_score LIMIT ?"
        params.append(max(top_n * 2, 20))
        
        rows = conn.execute(sql, tuple(params)).fetchall()

        # bm25 score negative ছোট = better match
        # Normalize করো: 1.0 (best) → 0.0 (worst) স্কেলে
        results = []
        for i, r in enumerate(rows):
            normalized = 1.0 / (1 + abs(r["raw_score"]))  # 0..1, higher=better
            if normalized >= min_score:
                results.append({
                    "id":              r["id"],
                    "content":         r["content"],
                    "chapter":         r["chapter"],
                    "page":            r["page"],
                    "score":           normalized,
                    "raw_score":       r["raw_score"],
                })
        return results[:top_n]
    except Exception as e:
        log.warning(f"[Step14] FTS error: {e}")
        return []


def _semantic_search(conn, query_vec: list, class_id: str, subject_id: str,
                     top_n=10, min_sim=MIN_SEMANTIC_SCORE, chapter_num=None) -> list:
    """Embedding-based semantic search — threshold সহ"""
    sql = """
        SELECT pe.content_id, pe.embedding,
               pc.content, pc.chapter, pc.page
        FROM pdf_embeddings pe
        JOIN pdf_content pc ON pc.id = pe.content_id
        WHERE pc.class_id   = ?
          AND pc.subject_id = ?
    """
    params = [class_id, subject_id]
    if chapter_num:
        sql += " AND pc.chapter_num = ?"
        params.append(str(chapter_num))
        
    rows = conn.execute(sql, tuple(params)).fetchall()

    if not rows:
        return []

    scored = []
    for row in rows:
        vec = _blob_to_vec(row["embedding"])
        sim = _cosine(query_vec, vec)
        # Min similarity threshold — অপ্রাসঙ্গিক results বাদ
        if sim >= min_sim:
            scored.append({
                "id":      row["content_id"],
                "content": row["content"],
                "chapter": row["chapter"],
                "page":    row["page"],
                "score":   sim,
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


def _reciprocal_rank_fusion(fused: dict, fts_rank: int, sem_rank: int | None,
                            fts_score: float, sem_score: float) -> None:
    """
    Reciprocal Rank Fusion (RRF) — Google/Vector AI recommended method।
    Formula: RRF_score = Σ (weight / (k + rank))
    """
    # FTS contribution (rank-based)
    rrf_fts = WEIGHT_FTS / (RRF_K + fts_rank + 1) if fts_rank is not None else 0

    # Semantic contribution (rank-based)
    rrf_sem = WEIGHT_SEMANTIC / (RRF_K + sem_rank + 1) if sem_rank is not None else 0

    fused["rrf"] = fused.get("rrf", 0) + rrf_fts + rrf_sem

    # Raw signals retain করো debug/inspection এর জন্য
    fused["fts_score"] = max(fused.get("fts_score", 0), fts_score)
    fused["sem_score"] = max(fused.get("sem_score", 0), sem_score)


def _deduplicate_results(results: list, threshold: float = DIVERSITY_THRESHOLD) -> list:
    """
    একই chapter + page এর results deduplicate করো।
    অতিরিক্ত redundant results context কমায়।
    """
    seen_keys = set()
    unique = []
    for r in results:
        key = (r.get("chapter", ""), r.get("page", 0))
        if key in seen_keys:
            continue
        # Content similarity check (Jaccard-like)
        is_dup = False
        for existing in unique[-5:]:  # শেষ ৫টার সাথে compare
            existing_words = set(existing["content"][:500].split())
            current_words  = set(r["content"][:500].split())
            if existing_words and current_words:
                overlap = len(existing_words & current_words)
                similarity = overlap / min(len(existing_words), len(current_words))
                if similarity >= threshold:
                    is_dup = True
                    break
        if not is_dup:
            seen_keys.add(key)
            unique.append(r)
    return unique


def hybrid_search(class_id: str, subject_id: str, query: str, top_n=5,
                  min_semantic_score: float = MIN_SEMANTIC_SCORE,
                  return_debug: bool = False, chapter_num=None) -> list:
    """
    Hybrid search: FTS5 + Semantic + RRF re-ranking
    ✅ Google Vertex AI best practice অনুযায়ী Reciprocal Rank Fusion ব্যবহার করা হচ্ছে।

    Args:
        class_id, subject_id: subject filter
        query: search query
        top_n: কতটা result চাই
        min_semantic_score: cosine similarity threshold (default 0.50)
        return_debug: True হলে score breakdown সহ দেখায় (admin/dev use)
    """
    conn = get_db()

    # 1. FTS search (keyword-based)
    fts_results = _fts_search(conn, query, class_id, subject_id, top_n=15, chapter_num=chapter_num)

    # 2. Semantic search (embedding-based)
    sem_results = []
    query_vec = _embed_text(query)
    if query_vec:
        sem_results = _semantic_search(
            conn, query_vec, class_id, subject_id,
            top_n=15, min_sim=min_semantic_score, chapter_num=chapter_num
        )

    conn.close()

    # 3. Reciprocal Rank Fusion (RRF) re-ranking
    fused = {}

    # FTS-only or both-appearing results
    for rank, r in enumerate(fts_results):
        cid = r["id"]
        if cid not in fused:
            fused[cid] = {
                "content": r["content"],
                "chapter": r.get("chapter"),
                "page":    r.get("page"),
                "fts_score": 0,
                "sem_score": 0,
                "rrf":       0,
            }
        _reciprocal_rank_fusion(
            fused[cid],
            fts_rank=rank,
            sem_rank=None,
            fts_score=r["score"],
            sem_score=0
        )

    # Semantic results merge
    for rank, r in enumerate(sem_results):
        cid = r["id"]
        if cid not in fused:
            fused[cid] = {
                "content": r["content"],
                "chapter": r.get("chapter"),
                "page":    r.get("page"),
                "fts_score": 0,
                "sem_score": 0,
                "rrf":       0,
            }
        prev_fts_rank = next(
            (i for i, fr in enumerate(fts_results) if fr["id"] == cid),
            None
        )
        _reciprocal_rank_fusion(
            fused[cid],
            fts_rank=prev_fts_rank,
            sem_rank=rank,
            fts_score=0,
            sem_score=r["score"]
        )

    # 4. Sort by RRF score + dedupe near-identical results
    results = []
    for cid, d in fused.items():
        entry = {
            "id":      cid,
            "content": d["content"],
            "chapter": d["chapter"],
            "page":    d["page"],
            "combined": d["rrf"],
        }
        if return_debug:
            entry["debug"] = {
                "fts_score": round(d["fts_score"], 3),
                "sem_score": round(d["sem_score"], 3),
                "rrf":       round(d["rrf"], 6),
            }
        results.append(entry)

    results.sort(key=lambda x: x["combined"], reverse=True)
    results = _deduplicate_results(results)
    return results[:top_n]
# ══════════════════════════════════════════════════════════
#  ROUTES — Search
# ══════════════════════════════════════════════════════════

@bp.route("/api/search/semantic", methods=["POST"])
def semantic_search_endpoint():
    """
    Hybrid semantic search endpoint (RRF-ব্যবহার করে)
    Body: { class_id, subject_id, query, top_n?, min_semantic_score?, debug? }
    """
    data       = request.get_json(force=True) or {}
    class_id   = data.get("class_id", "").strip()
    subject_id = data.get("subject_id", "").strip()
    query      = data.get("query", "").strip()
    top_n      = int(data.get("top_n", 5))
    min_score  = float(data.get("min_semantic_score", MIN_SEMANTIC_SCORE))
    debug      = bool(data.get("debug", False))

    if not all([class_id, subject_id, query]):
        return jsonify({"success": False, "error": "class_id, subject_id, query দাও"}), 400

    top_n = max(1, min(top_n, 30))
    min_score = max(0.0, min(min_score, 1.0))

    try:
        results = hybrid_search(
            class_id, subject_id, query,
            top_n=top_n,
            min_semantic_score=min_score,
            return_debug=debug
        )
        return jsonify({
            "success":         True,
            "query":           query,
            "results":         results,
            "count":           len(results),
            "fusion_method":   "RRF",
            "min_semantic":    min_score,
            "embedding_model": EMBEDDING_MODEL,
        })
    except Exception as e:
        log.error(f"[Step14] search error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ══════════════════════════════════════════════════════════
#  ROUTES — Admin: Embedding Generation
# ══════════════════════════════════════════════════════════

@bp.route("/admin/api/embeddings/generate", methods=["POST"])
def generate_embeddings():
    """
    সব content এর embedding তৈরি করো।
    Body: { class_id?, subject_id?, limit? }
    limit দিলে শুধু ঐটুকু করবে (বড় DB হলে batch করো)
    """
    data       = request.get_json(force=True) or {}
    class_id   = data.get("class_id")
    subject_id = data.get("subject_id")
    limit      = int(data.get("limit", 100))

    conn = get_db()

    # embedding নেই এমন content খোঁজো
    where_parts = ["pe.id IS NULL"]
    params      = []
    if class_id:
        where_parts.append("pc.class_id = ?")
        params.append(class_id)
    if subject_id:
        where_parts.append("pc.subject_id = ?")
        params.append(subject_id)
    params.append(limit)

    rows = conn.execute(f"""
        SELECT pc.id, pc.content
        FROM pdf_content pc
        LEFT JOIN pdf_embeddings pe ON pe.content_id = pc.id
        WHERE {' AND '.join(where_parts)}
          AND pc.content IS NOT NULL
          AND length(pc.content) > 10
        LIMIT ?
    """, params).fetchall()
    conn.close()

    if not rows:
        return jsonify({"success": True, "message": "সব content এর embedding আছে", "done": 0})

    done    = 0
    errors  = 0
    client  = _get_client()

    if not client:
        return jsonify({"success": False, "error": "Gemini client init হয়নি"}), 500

    for row in rows:
        try:
            vec = _embed_text(row["content"])
            if vec:
                conn = get_db()
                conn.execute(
                    "INSERT OR REPLACE INTO pdf_embeddings (content_id, embedding) VALUES (?, ?)",
                    (row["id"], _vec_to_blob(vec))
                )
                conn.commit()
                conn.close()
                done += 1
            else:
                errors += 1

            time.sleep(EMBED_SLEEP)  # rate limit

        except Exception as e:
            log.error(f"[Step14] embed error content_id={row['id']}: {e}")
            errors += 1
            time.sleep(2)

    total_remaining = 0
    conn = get_db()
    row_count = conn.execute("""
        SELECT COUNT(*) as cnt FROM pdf_content pc
        LEFT JOIN pdf_embeddings pe ON pe.content_id = pc.id
        WHERE pe.id IS NULL AND length(pc.content) > 10
    """).fetchone()
    total_remaining = row_count["cnt"] if row_count else 0
    conn.close()

    return jsonify({
        "success":         True,
        "embedded":        done,
        "errors":          errors,
        "still_remaining": total_remaining,
        "model":           EMBEDDING_MODEL,
        "tip":             f"আরো {total_remaining} টা বাকি। আবার call করো।" if total_remaining > 0 else "সব শেষ! ✅",
    })


@bp.route("/admin/api/embeddings/status", methods=["GET"])
def embedding_status():
    """কতটুকু content embed হয়েছে"""
    conn = get_db()

    total = conn.execute(
        "SELECT COUNT(*) as c FROM pdf_content WHERE length(content) > 10"
    ).fetchone()["c"]

    embedded = conn.execute(
        "SELECT COUNT(*) as c FROM pdf_embeddings"
    ).fetchone()["c"]

    # per-subject breakdown
    by_subject = conn.execute("""
        SELECT pc.class_id, pc.subject_id,
               COUNT(pc.id)   as total,
               COUNT(pe.id)   as embedded
        FROM pdf_content pc
        LEFT JOIN pdf_embeddings pe ON pe.content_id = pc.id
        WHERE length(pc.content) > 10
        GROUP BY pc.class_id, pc.subject_id
        ORDER BY pc.class_id, pc.subject_id
    """).fetchall()
    conn.close()

    subjects = []
    for r in by_subject:
        pct = round(r["embedded"] / r["total"] * 100, 1) if r["total"] else 0
        subjects.append({
            "class_id":   r["class_id"],
            "subject_id": r["subject_id"],
            "total":      r["total"],
            "embedded":   r["embedded"],
            "pct":        pct,
            "done":       r["embedded"] == r["total"],
        })

    return jsonify({
        "success":       True,
        "total_content": total,
        "embedded":      embedded,
        "remaining":     total - embedded,
        "pct_done":      round(embedded / total * 100, 1) if total else 0,
        "model":         EMBEDDING_MODEL,
        "by_subject":    subjects,
    })
