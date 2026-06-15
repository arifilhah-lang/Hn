# Study AI — Master Blueprint
**Version:** v15 (চলমান)
**Last Updated:** June 2026

---

## প্রথম কথা — Project কী করে

```
PDF (বোর্ড বই / প্রশ্নপত্র / গাইড)
        ↓  Gemini Vision (page by page)
   JSON file  →  SQLite DB (pdf_content)
        ↓  FTS5 search
   Gemini  →  উত্তর/MCQ/CQ
```

**তিন ধরনের বই, তিনটা আলাদা কাজ:**

| বই | source_type | কী কাজে লাগে |
|----|-------------|--------------|
| পাঠ্যবই (NCTB) | `board_book` | Theory, Definition, Formula — build_answer() এর context |
| প্রশ্নপত্র | `test_paper` | Real board MCQ+CQ → mcq_bank এ সরাসরি |
| গাইড বই | `guide` | CQ model answer — Gemini call ছাড়াই দেওয়া যায় |

**এই logic টা correct। বদলাতে হবে না।**

---

## 🔴 IMMEDIATE — শুরুর আগেই করতে হবে

---

### IM-1 — Chunking Fix ✅ (Done — v15)
**File:** `app.py` → `_parse_page_into_chunks()`
1 page = typed chunks (definition, formula, mcq, cq, text)।
Search accurate, Gemini token 60-70% কম।

### IM-2 — MCQ Auto-Bank Population ✅ (Done — v15)
**File:** `app.py` → `_db_import_json_to_fts()`
JSON import এর সময় [MCQ] block → `mcq_bank` auto-insert।
Admin: "DB Import" button → MCQ count দেখাবে।

### IM-3 — CQ Model Answer Table ✅ (Done — v15)
**File:** `app.py` → `init_db()` + `_parse_cq_for_model_answers()`
নতুন `cq_model_answers` table। Guide CQ → 0 token।
```sql
cq_model_answers (id, class_id, subject_id, chapter, chapter_num,
  stimulus, question_ka/kha/ga/gha, answer_ka/kha/ga/gha,
  source_type, board_name, board_year, created_at)
```

### IM-4 — File Folder Organization ✅ (Done — v15)
**File:** `config.py` → `get_data_filepath()` + `find_all_data_files()`
```
data/ssc/physics/board_book.json
data/ssc/physics/test_paper.json
data/ssc/physics/guide.json
```

### IM-5 — Double Cache Cleanup ✅ (Done — v15)
**File:** `app.py`
`_response_cache` (in-memory) সরানো হয়েছে। শুধু `response_cache` SQLite।

### IM-6 — Connection Leak Fix ✅ (Done — v15)
**File:** `app.py` — সব জায়গায় `try/finally conn.close()`।

### IM-7 — Step14/15 Integrate ✅ (Done — v15)
**File:** `app.py`
`_build_search_context()` → FTS5 কম হলে `hybrid_search()` call।
`build_answer()` → `get_cached_content()` call।

---

## Admin Panel — v15 Changes ✅ (Done)

### নতুন API Endpoints (`admin_app.py`):

| Endpoint | Method | কাজ |
|----------|--------|-----|
| `/admin/api/db-import` | POST | JSON → FTS5 chunked import (IM-1+2+3 একসাথে) |
| `/admin/api/db-stats` | GET | সব table row count + DB size |
| `/admin/api/cache/clear` | POST | response_cache clear (all / subject) |
| `/admin/api/cq-model-list` | GET | cq_model_answers browse (paginated) |
| `/admin/api/cq-model-delete` | POST | cq_model_answers delete (by id / subject) |
| `/admin/api/mcq-bank/stats` | GET | MCQ bank subject-wise count |

### নতুন Admin UI (`admin.html`):

**Tab: ডেটা ম্যানেজমেন্ট — নতুন cards:**
- 🗂️ DB Import card — class+subject → "DB Import করুন" → chunk/MCQ/CQ count দেখায়
- 🔄 Chapter Sync card — DB import এর পরে subject_chapters refresh
- 📊 MCQ Bank Status card — summary + manual import option

**নতুন Tab: 🗃️ DB স্বাস্থ্য:**
- 📈 Table Stats — সব table row count + DB size + chunk type breakdown
- 🧹 Cache Management — response_cache clear (subject-level বা সব)
- 📖 CQ Model Answers Browser — paginated list, প্রতিটায় delete option

---

## 🟡 IMPORTANT — Phase 1 Launch এর আগে

### IMP-1 — Gunicorn ✅ (Done — v15)
`railway.json` → `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`

### IMP-2 — Auto-Warm ✅ (Done — v15)
`features/step15_cache.py` → startup thread, top 5 subject auto-cache

### IMP-3 — Chapter-level chapter_num Fix ✅ (Already Done)
**File:** `app.py` → `init_db()`
`CREATE TABLE pdf_content` এ `chapter_num INTEGER` কলাম already আছে।
ALTER TABLE migration লাইনটা পুরনো DB এর জন্য রাখা হয়েছে (নতুন DB তে duplicate-column error silently ignore হয়)।

### IMP-4 — Phased Content Collection Strategy
```
Phase 1 — Launch এর আগে (৫টা subject):
  SSC: Physics, Chemistry, Biology, Math, BGS
  প্রতিটায়: board_book + test_paper + guide
  মোট: ১৫টা PDF

Phase 2 — ১ মাস পর: SSC বাকি + HSC Science
Phase 3 — ৩ মাস পর: HSC Business + Humanities
```

---

## 🟢 Student Features — Phase 2

### S-1 — Weakness Detection
`GET /api/progress/weakness` — কোন chapter এ বেশি ভুল

### S-2 — Spaced Repetition
```sql
mcq_review_schedule (student_id, mcq_id, next_review, interval_days, ease_factor)
```

### S-3 — Flashcard
Definition/Formula → flashcard (front: term, back: meaning)

### S-4 — CQ Model Answer Endpoint ✅ (Partially done — v15)
`cq_model_answers` table ready। Endpoint:
```
POST /api/cq/model-answer { class_id, subject_id, chapter, question }
```
→ table এ থাকলে 0 token। না থাকলে Gemini generate।

---

## 🔵 AI Self-Improvement — Phase 3

### AI-1 — Fine-tuning Export
`training_feedback` → JSONL → Vertex AI fine-tune। (৫০০+ positive feedback এ)

### AI-2 — Semantic Re-ranking
FTS5 ২০টা → SequenceMatcher top 5 → Gemini।

### AI-3 — Dynamic Context Window
প্রশ্নের complexity দেখে chunk size adjust।

---

## 🔵 Scale — Phase 4 (50+ users)

### SC-1 — SQLite → PostgreSQL
`get_db()` function বদলাও। Table structure same।

### SC-2 — Redis Cache
`response_cache` SQLite → Redis।

---

## MCQ/CQ System — চূড়ান্ত সিদ্ধান্ত

```
User MCQ চাইলে:
  1. mcq_bank এ আছে? → 0 token ✅
  2. নেই → pdf_content FTS5 + semantic search
  3. chunk আছে? → Gemini format করো (~400 token)
  4. কিছুই নেই? → Gemini generate (~2000 token)

User CQ চাইলে:
  1. cq_model_answers এ আছে? → 0 token ✅
  2. নেই → pdf_content FTS5 search
  3. Gemini generate করো
```

---

## Database — চূড়ান্ত Structure (v15)

| Table | কী জন্য | Status |
|-------|---------|--------|
| pdf_content | chunked extracted content | ✅ আছে + chunking fixed |
| pdf_content_fts | FTS5 search | ✅ আছে |
| mcq_bank | Structured MCQ (0 token) | ✅ আছে + auto-populate |
| cq_model_answers | Guide CQ model answers (0 token) | ✅ আছে (IM-3) |
| subject_chapters | Chapter list cache | ✅ আছে |
| chapter_summaries | Chapter summary cache | ✅ আছে |
| response_cache | Question-answer cache (SQLite only) | ✅ আছে |
| subject_caches | Gemini context cache metadata | ✅ আছে |
| pdf_embeddings | Semantic search vectors | ✅ আছে |
| student_progress | MCQ/CQ score history | ✅ আছে |
| student_routine | Exam routine | ✅ আছে |
| conversation_history | Theory chat memory | ✅ আছে |
| training_feedback | AI training data | ✅ আছে |
| exam_sessions | Mock exam | ✅ আছে |
| mcq_review_schedule | Spaced repetition | ❌ নেই — S-2 |
| flashcards | Flashcard system | ❌ নেই — S-3 |

---

## Token Cost — এখন vs আগে

| Request | আগে | v15 এ |
|---------|-----|-------|
| MCQ (bank এ আছে) | 0 token ✅ | 0 token ✅ |
| MCQ (bank এ নেই) | ~2000 token | ~400 token ✅ |
| CQ (guide এ আছে) | ~1500 token | 0 token ✅ |
| CQ (নেই) | ~2000 token | ~400 token ✅ |
| Theory answer | ~2000 token | Context cached ~100 token ✅ |

---

## এখন কী করব — Priority Queue

```
✅ IM-1: Chunking Fix          → app.py       DONE
✅ IM-2: MCQ Auto-Bank         → app.py       DONE
✅ IM-3: CQ Model Answer table → app.py       DONE
✅ IM-4: Folder Structure      → config.py    DONE
✅ IM-5: Double Cache Cleanup  → app.py       DONE
✅ IM-6: Connection Leak Fix   → app.py       DONE
✅ IM-7: Step14/15 Integrate   → app.py       DONE
✅ Admin Panel v15 Update      → admin_app.py + admin.html  DONE

[ এখন ] Phase 1 Content: ১৫টা PDF extract (৫ subject × ৩ type)
[ Phase 1 Test ] Local test — ১০০ জন beta user

[ Phase 2 ] S-1 থেকে S-4 (student features)
[ Phase 3 ] AI-1 থেকে AI-3 (self-improvement)
[ Phase 4 ] SC-1, SC-2 (50+ users)
```

---

## যা ঠিক আছে — হাত দেবে না

- Blueprint auto-loader (features/ folder) ✅
- 4 API key round-robin pool ✅
- FTS5 search + source_type filter ✅
- MCQ bank 0-token pull ✅
- Training feedback auto-hooks ✅
- Mock exam (step6) ✅
- Chapter summary DB cache ✅
- gemini-flash-lite as default ✅
- Subject/Class config structure ✅
- Extraction prompts (board_book/test_paper/guide) ✅
- Admin panel parallel extraction ✅
