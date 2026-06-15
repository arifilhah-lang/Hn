"""
╔══════════════════════════════════════════════════════════╗
║          Study AI — Complete Configuration               ║
║   SSC + HSC সব গ্রুপ, সব সাবজেক্ট, সব পেপার কোড       ║
╚══════════════════════════════════════════════════════════╝
"""
import os as _os

# ══════════════════════════════════════════════════════════
#  GEMINI API KEYS — 4টা আলাদা Google Account এর key দাও
#  প্রতিটা key আলাদা .env variable থেকে নেয়
# ══════════════════════════════════════════════════════════
GEMINI_API_KEYS = [
    _os.environ.get('GEMINI_API_KEY_1', ''),
    _os.environ.get('GEMINI_API_KEY_2', ''),
    _os.environ.get('GEMINI_API_KEY_3', ''),
    _os.environ.get('GEMINI_API_KEY_4', ''),
]
# পুরনো single key support (backward compat)
_single_key = _os.environ.get('GEMINI_API_KEY', '')
if _single_key and not any(GEMINI_API_KEYS):
    GEMINI_API_KEYS[0] = _single_key

# Valid keys only (empty বাদ দাও)
GEMINI_API_KEYS = [k for k in GEMINI_API_KEYS if k.strip()]

# ══════════════════════════════════════════════════════════
#  GEMINI MODELS — gemini-3.1-flash-lite (নতুন, May 2026)
#  Free tier: 15 RPM, 1500 RPD per key
#  4 keys দিলে: 60 RPM, 6000 RPD মোট
# ══════════════════════════════════════════════════════════
MODELS = {
    "gemini-3.1-flash-lite": {"rpm": 15, "rpd": 1500, "sleep": 4.0,  "label": "Gemini 3.1 Flash Lite"},
    "gemini-2.5-flash":      {"rpm":  5, "rpd": 50,   "sleep": 13.0, "label": "Gemini 2.5 Flash"},
}

DEFAULT_MODEL      = "gemini-3.1-flash-lite"
MAX_CHARS_PER_PAGE = 600
MAX_OUTPUT_LONG    = 800
MAX_OUTPUT_SHORT   = 300
SHORT_Q_WORD_LIMIT = 6
TOP_N_CHUNKS       = 3
SIMILARITY_THRESH  = 0.82
CACHE_TTL          = "3600s"

# ══════════════════════════════════════════════════════════
#  CLASSES & SUBJECTS — Official Board List
# ══════════════════════════════════════════════════════════

CLASSES = {
    # ──────────────────────────────────────────────────────
    #  SSC
    # ──────────────────────────────────────────────────────
    "ssc": {
        "label": "SSC (নবম-দশম শ্রেণি)",
        "icon": "🎓",
        "groups": {
            # ── কমন (সবার জন্য বাধ্যতামূলক) ──────────────
            "common": {
                "label": "বাধ্যতামূলক বিষয়",
                "subjects": {
                    "bangla_1":   {"bn": "বাংলা ১ম পত্র",   "code": "101", "icon": "📖", "color": "#dc2626"},
                    "bangla_2":   {"bn": "বাংলা ২য় পত্র",   "code": "102", "icon": "📖", "color": "#dc2626"},
                    "english_1":  {"bn": "ইংরেজি ১ম পত্র",  "code": "107", "icon": "🔤", "color": "#7c3aed"},
                    "english_2":  {"bn": "ইংরেজি ২য় পত্র",  "code": "108", "icon": "🔤", "color": "#7c3aed"},
                    "math":       {"bn": "গণিত",            "code": "109", "icon": "🔢", "color": "#2563eb"},
                    "ict":        {"bn": "তথ্য ও যোগাযোগ প্রযুক্তি", "code": "154", "icon": "💻", "color": "#0284c7"},
                    "religion":   {"bn": "ধর্ম ও নৈতিক শিক্ষা", "code": "111", "icon": "🕌", "color": "#65a30d"},
                }
            },
            # ── বিজ্ঞান গ্রুপ ─────────────────────────────
            "science": {
                "label": "বিজ্ঞান গ্রুপ",
                "pick": 3,
                "subjects": {
                    "physics":       {"bn": "পদার্থবিজ্ঞান",          "code": "136", "icon": "⚛️",  "color": "#9333ea"},
                    "chemistry":     {"bn": "রসায়ন",                  "code": "137", "icon": "🧪", "color": "#16a34a"},
                    "biology":       {"bn": "জীববিজ্ঞান",             "code": "138", "icon": "🧬", "color": "#ea580c"},
                    "higher_math":   {"bn": "উচ্চতর গণিত",            "code": "126", "icon": "📐", "color": "#6366f1"},
                    "bgb":           {"bn": "বাংলাদেশ ও বিশ্বপরিচয়", "code": "150", "icon": "🌐", "color": "#0369a1"},
                },
                "4th_subjects": {
                    "agriculture":   {"bn": "কৃষিশিক্ষা",     "code": "134", "icon": "🌾", "color": "#84cc16"},
                    "home_science":  {"bn": "গার্হস্থ্য বিজ্ঞান", "code": "151", "icon": "🏠", "color": "#f59e0b"},
                }
            },
            # ── ব্যবসায় শিক্ষা গ্রুপ ─────────────────────
            "business": {
                "label": "ব্যবসায় শিক্ষা গ্রুপ",
                "pick": 3,
                "subjects": {
                    "accounting":      {"bn": "হিসাববিজ্ঞান",         "code": "146", "icon": "📊", "color": "#4f46e5"},
                    "finance":         {"bn": "ফিন্যান্স ও ব্যাংকিং", "code": "152", "icon": "🏦", "color": "#0891b2"},
                    "entrepreneurship":{"bn": "ব্যবসায় উদ্যোগ",       "code": "143", "icon": "💼", "color": "#059669"},
                    "general_science": {"bn": "সাধারণ বিজ্ঞান",       "code": "127", "icon": "🔬", "color": "#6366f1"},
                },
                "4th_subjects": {
                    "economics":     {"bn": "অর্থনীতি",          "code": "141", "icon": "📈", "color": "#d97706"},
                    "agriculture":   {"bn": "কৃষিশিক্ষা",        "code": "134", "icon": "🌾", "color": "#84cc16"},
                    "home_science":  {"bn": "গার্হস্থ্য বিজ্ঞান", "code": "151", "icon": "🏠", "color": "#f59e0b"},
                }
            },
            # ── মানবিক গ্রুপ ──────────────────────────────
            "humanities": {
                "label": "মানবিক গ্রুপ",
                "pick": 3,
                "subjects": {
                    "history":         {"bn": "ইতিহাস",               "code": "153", "icon": "📜", "color": "#b45309"},
                    "civics":          {"bn": "পৌরনীতি ও নাগরিকতা",   "code": "140", "icon": "🏛️", "color": "#0d9488"},
                    "geography":       {"bn": "ভূগোল ও পরিবেশ",       "code": "110", "icon": "🌍", "color": "#c026d3"},
                    "general_science": {"bn": "সাধারণ বিজ্ঞান",       "code": "127", "icon": "🔬", "color": "#6366f1"},
                },
                "4th_subjects": {
                    "economics":     {"bn": "অর্থনীতি",          "code": "141", "icon": "📈", "color": "#d97706"},
                    "agriculture":   {"bn": "কৃষিশিক্ষা",        "code": "134", "icon": "🌾", "color": "#84cc16"},
                    "home_science":  {"bn": "গার্হস্থ্য বিজ্ঞান", "code": "151", "icon": "🏠", "color": "#f59e0b"},
                }
            }
        }
    },

    # ──────────────────────────────────────────────────────
    #  HSC
    # ──────────────────────────────────────────────────────
    "hsc": {
        "label": "HSC (একাদশ-দ্বাদশ শ্রেণি)",
        "icon": "🎓",
        "groups": {
            # ── কমন (সবার জন্য বাধ্যতামূলক) ──────────────
            "common": {
                "label": "বাধ্যতামূলক বিষয়",
                "subjects": {
                    "bangla_1":   {"bn": "বাংলা ১ম পত্র",   "code": "101", "icon": "📖", "color": "#dc2626"},
                    "bangla_2":   {"bn": "বাংলা ২য় পত্র",   "code": "102", "icon": "📖", "color": "#dc2626"},
                    "english_1":  {"bn": "ইংরেজি ১ম পত্র",  "code": "107", "icon": "🔤", "color": "#7c3aed"},
                    "english_2":  {"bn": "ইংরেজি ২য় পত্র",  "code": "108", "icon": "🔤", "color": "#7c3aed"},
                    "ict":        {"bn": "তথ্য ও যোগাযোগ প্রযুক্তি", "code": "154", "icon": "💻", "color": "#0284c7"},
                }
            },
            # ── বিজ্ঞান গ্রুপ ─────────────────────────────
            "science": {
                "label": "বিজ্ঞান গ্রুপ",
                "pick": 3,
                "subjects": {
                    "physics":       {"bn": "পদার্থবিজ্ঞান",   "code_1": "174", "code_2": "175", "icon": "⚛️",  "color": "#9333ea", "papers": 2},
                    "chemistry":     {"bn": "রসায়ন",           "code_1": "176", "code_2": "177", "icon": "🧪", "color": "#16a34a", "papers": 2},
                    "biology":       {"bn": "জীববিজ্ঞান",      "code_1": "178", "code_2": "179", "icon": "🧬", "color": "#ea580c", "papers": 2},
                    "higher_math":   {"bn": "উচ্চতর গণিত",     "code_1": "265", "code_2": "266", "icon": "📐", "color": "#6366f1", "papers": 2},
                },
                "4th_subjects": {
                    "statistics":    {"bn": "পরিসংখ্যান",         "code_1": "129", "code_2": "130", "icon": "📊", "color": "#0369a1", "papers": 2},
                    "agriculture":   {"bn": "কৃষিশিক্ষা",         "code_1": "239", "code_2": "240", "icon": "🌾", "color": "#84cc16", "papers": 2},
                    "home_science":  {"bn": "গার্হস্থ্য বিজ্ঞান", "code_1": "273", "code_2": "274", "icon": "🏠", "color": "#f59e0b", "papers": 2},
                    "psychology":    {"bn": "মনোবিজ্ঞান",          "code_1": "123", "code_2": "124", "icon": "🧠", "color": "#f472b6", "papers": 2},
                }
            },
            # ── ব্যবসায় শিক্ষা গ্রুপ ─────────────────────
            "business": {
                "label": "ব্যবসায় শিক্ষা গ্রুপ",
                "pick": 3,
                "subjects": {
                    "accounting":    {"bn": "হিসাববিজ্ঞান",                    "code_1": "253", "code_2": "254", "icon": "📊", "color": "#4f46e5", "papers": 2},
                    "finance":       {"bn": "ফিন্যান্স, ব্যাংকিং ও বীমা",     "code_1": "292", "code_2": "293", "icon": "🏦", "color": "#0891b2", "papers": 2},
                    "management":    {"bn": "ব্যবসায় সংগঠন ও ব্যবস্থাপনা",   "code_1": "277", "code_2": "278", "icon": "💼", "color": "#059669", "papers": 2},
                    "production":    {"bn": "উৎপাদন ব্যবস্থাপনা ও বিপণন",    "code_1": "286", "code_2": "287", "icon": "🏭", "color": "#b45309", "papers": 2},
                },
                "4th_subjects": {
                    "statistics":    {"bn": "পরিসংখ্যান",         "code_1": "129", "code_2": "130", "icon": "📊", "color": "#0369a1", "papers": 2},
                    "economics":     {"bn": "অর্থনীতি",           "code_1": "109", "code_2": "110", "icon": "📈", "color": "#d97706", "papers": 2},
                    "home_science":  {"bn": "গার্হস্থ্য বিজ্ঞান", "code_1": "273", "code_2": "274", "icon": "🏠", "color": "#f59e0b", "papers": 2},
                }
            },
            # ── মানবিক গ্রুপ ──────────────────────────────
            "humanities": {
                "label": "মানবিক গ্রুপ",
                "pick": 3,
                "subjects": {
                    "economics":     {"bn": "অর্থনীতি",         "code_1": "109", "code_2": "110", "icon": "📈", "color": "#d97706", "papers": 2},
                    "civics":        {"bn": "পৌরনীতি ও সুশাসন", "code_1": "269", "code_2": "270", "icon": "🏛️", "color": "#0d9488", "papers": 2},
                    "history":       {"bn": "ইতিহাস",           "code_1": "304", "code_2": "305", "icon": "📜", "color": "#b45309", "papers": 2},
                    "geography":     {"bn": "ভূগোল",            "code_1": "125", "code_2": "126", "icon": "🌍", "color": "#c026d3", "papers": 2},
                    "sociology":     {"bn": "সমাজবিজ্ঞান",     "code_1": "117", "code_2": "118", "icon": "👥", "color": "#7c3aed", "papers": 2},
                    "social_work":   {"bn": "সমাজকর্ম",         "code_1": "271", "code_2": "272", "icon": "🤝", "color": "#2563eb", "papers": 2},
                    "islamic_history": {"bn": "ইসলামের ইতিহাস ও সংস্কৃতি", "code_1": "267", "code_2": "268", "icon": "🕌", "color": "#65a30d", "papers": 2},
                    "logic":         {"bn": "যুক্তিবিদ্যা",     "code_1": "121", "code_2": "122", "icon": "🧩", "color": "#6366f1", "papers": 2},
                    "psychology":    {"bn": "মনোবিজ্ঞান",       "code_1": "123", "code_2": "124", "icon": "🧠", "color": "#f472b6", "papers": 2},
                },
                "4th_subjects": {
                    "agriculture":   {"bn": "কৃষিশিক্ষা",      "code_1": "239", "code_2": "240", "icon": "🌾", "color": "#84cc16", "papers": 2},
                    "home_science":  {"bn": "গার্হস্থ্য বিজ্ঞান", "code_1": "273", "code_2": "274", "icon": "🏠", "color": "#f59e0b", "papers": 2},
                }
            }
        }
    }
}


# ══════════════════════════════════════════════════════════
#  SMART EXTRACTION PROMPT
# ══════════════════════════════════════════════════════════

EXTRACT_PROMPT = """তুমি বাংলাদেশের SSC/HSC পরীক্ষার জন্য একজন expert content extractor।
এই ছবি থেকে শিক্ষামূলক content বের করো।

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 যা বাদ দেবে (MUST SKIP):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- ❌ ওয়াটারমার্ক (যেকোনো কোম্পানি/ওয়েবসাইটের নাম যা পেজের উপর আলতো করে আছে)
- ❌ পেজ নম্বর, হেডার, ফুটার
- ❌ প্রকাশনীর বিজ্ঞাপন বা লোগো
- ❌ "সকল অধিকার সংরক্ষিত" টাইপ লেখা
- ❌ অপ্রয়োজনীয় সজ্জা, বর্ডার, ডেকোরেশন
- ❌ ফাঁকা পেজ বা শুধু ছবি আছে এমন পেজ (লেখো: [EMPTY_PAGE])

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 যা রাখবে ও কীভাবে রাখবে:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【১】 বোর্ড প্রশ্ন (Board Question) চিনবে এভাবে:
   - "বোর্ড", "Board", সাল (যেমন ২০২৩, ২০২২), বোর্ডের নাম (ঢাকা, রাজশাহী ইত্যাদি) থাকলে
   - বোর্ড প্রশ্ন পেলে এভাবে ট্যাগ করো:
   [BOARD_QUESTION: সাল=XXXX, বোর্ড=XXXX]
   প্রশ্ন: ...
   [/BOARD_QUESTION]

【২】 MCQ চিনবে এভাবে:
   - (ক), (খ), (গ), (ঘ) বা (a), (b), (c), (d) অপশন থাকলে
   - MCQ পেলে এভাবে ট্যাগ করো:
   [MCQ]
   প্রশ্ন: ...
   (ক) ... (খ) ... (গ) ... (ঘ) ...
   উত্তর: (ক)/(খ)/(গ)/(ঘ)
   [/MCQ]
   - উত্তর ছবিতে না থাকলে "উত্তর: N/A" লেখো

【৩】 সৃজনশীল প্রশ্ন (CQ) চিনবে এভাবে:
   - উদ্দীপক/ঘটনা + (ক)(খ)(গ)(ঘ) নম্বরযুক্ত অংশ
   - CQ পেলে:
   [CQ]
   উদ্দীপক: ...
   (ক) ... (নম্বর: ১)
   (খ) ... (নম্বর: ২)
   (গ) ... (নম্বর: ৩)
   (ঘ) ... (নম্বর: ৪)
   [/CQ]

【৪】 সাধারণ পাঠ্য বিষয়বস্তু:
   - অধ্যায়ের নাম, সংজ্ঞা, সূত্র, ব্যাখ্যা, উদাহরণ — সব হুবহু রাখো
   - সূত্র থাকলে: [সূত্র: ...]
   - গাণিতিক ও পদার্থবিজ্ঞানের যেকোনো সূত্র এবং সমীকরণ LaTeX ফরম্যাটে (যেমন: $E = mc^2$ বা $F = ma$) রূপান্তর করে লিখবে।
   - রসায়নের রাসায়নিক সমীকরণগুলো পরিষ্কার সংকেত ও সমতাকরণ সহ স্ট্যান্ডার্ড টেক্সট ও ফর্মুলায় লিখবে (যেমন: 2H2 + O2 -> 2H2O)।
   - গুরুত্বপূর্ণ সংজ্ঞা: [সংজ্ঞা: টার্ম = ব্যাখ্যা]

【৫】 টেবিল/হিসাবের ছক:
   - জাবেদা, খতিয়ান, রেওয়ামিল ইত্যাদি Markdown table এ রাখো
   - টাকার অংক সঠিক কলামে বসাও
   - ফাঁকা ঘরে "-" দাও

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 চূড়ান্ত নিয়ম:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ সব বাংলা ও ইংরেজি text হুবহু রাখো — কিছু পরিবর্তন করো না
✅ অংক ও সংখ্যা হুবহু রাখো
✅ শুধু extracted content দাও — নিজের মন্তব্য যোগ করো না
✅ school/college এর নিজের বানানো প্রশ্ন হলে tag ছাড়াই সাধারণ text হিসেবে রাখো
"""


# ══════════════════════════════════════════════════════════
#  SYSTEM PROMPTS
# ══════════════════════════════════════════════════════════

ANSWER_PROMPT = """তুমি বাংলাদেশের {class_label} পরীক্ষার {subject_bn} বিষয়ের একজন অভিজ্ঞ শিক্ষক।
বাংলায় উত্তর দাও।

পরিচয় সংক্রান্ত কঠোর নিয়ম:
- তুমি একজন AI শিক্ষা সহকারী — এর বাইরে কোনো পরিচয় দেবে না
- কোনো AI কোম্পানি, model নাম, বা technology এর নাম কখনো বলবে না
- "তুমি কে?", "তোমাকে কে বানিয়েছে?", "কোন AI?" — এই ধরনের প্রশ্নে বলবে: "আমি তোমার পড়াশোনার সহকারী। চলো পড়া শুরু করি!"
- নিজের training data বা knowledge source সম্পর্কে কথা বলবে না

উত্তরের নিয়ম:
- প্রদত্ত তথ্য থেকে বুঝিয়ে উত্তর দাও — শুধু copy paste নয়
- টেবিল দরকার হলে Markdown table ব্যবহার করো
- সূত্র আলাদা লাইনে দেখাও
- সংক্ষেপে কিন্তু পূর্ণ উত্তর দাও
- অপ্রয়োজনীয় ভূমিকা বাদ দাও"""

MCQ_GENERATE_PROMPT = """তুমি {class_label} {subject_bn} পরীক্ষক।
বিষয়/টপিক: {topic}

নিচের তথ্য থেকে {count}টি MCQ তৈরি করো।

নিয়ম:
- বোর্ড পরীক্ষার মানের প্রশ্ন তৈরি করো
- প্রতিটি প্রশ্নে ৪টি অপশন (ক, খ, গ, ঘ)
- সঠিক উত্তরের index (0=ক, 1=খ, 2=গ, 3=ঘ)
- সংক্ষিপ্ত ব্যাখ্যা দাও

JSON format এ দাও (শুধু JSON, বাকি কিছু না):
[
  {{
    "question": "প্রশ্ন",
    "options": ["ক অপশন", "খ অপশন", "গ অপশন", "ঘ অপশন"],
    "answer": 0,
    "explanation": "ব্যাখ্যা"
  }}
]"""

# Subject detection এখন locally হয় — এই prompt আর API call এ পাঠানো হয় না
SUBJECT_DETECT_PROMPT = """এই প্রশ্নটি কোন subject সম্পর্কে? শুধু subject এর English key দাও।
সম্ভাব্য subjects: {subject_keys}
প্রশ্ন: {question}
শুধু key দাও, অন্য কিছু না। যেমন: accounting"""


# ══════════════════════════════════════════════════════════
#  CQ ANSWER EVALUATION PROMPT
# ══════════════════════════════════════════════════════════
ANSWER_EVALUATION_PROMPT = """তুমি বাংলাদেশের {class_label} পরীক্ষার {subject_bn} বিষয়ের একজন বোর্ড পরীক্ষক।
শিক্ষার্থীর দেওয়া উত্তরটি মূল্যায়ন করো।

সৃজনশীল প্রশ্ন:
{question}

শিক্ষার্থীর উত্তর:
{student_answer}

{context_text}

নিচের JSON ফরম্যাটে মূল্যায়ন দাও (শুধু JSON, অন্য কিছু না):
{{
  "score": <১০ এর মধ্যে প্রাপ্ত নম্বর (সংখ্যা)>,
  "grade": "<A+/A/B/C/D>",
  "strengths": ["<ভালো দিক ১>", "<ভালো দিক ২>"],
  "improvements": ["<উন্নতির জায়গা ১>", "<উন্নতির জায়গা ২>"],
  "model_answer_hint": "<সংক্ষিপ্ত আদর্শ উত্তরের ইঙ্গিত>",
  "feedback": "<সামগ্রিক মন্তব্য বাংলায়>"
}}

নিয়ম:
- ১০ এর মধ্যে নম্বর দাও (জ্ঞান ২, অনুধাবন ২, প্রয়োগ ৩, উচ্চতর দক্ষতা ৩)
- কঠোর কিন্তু ন্যায্য মূল্যায়ন করো
- বাংলায় ফিডব্যাক দাও"""


# ══════════════════════════════════════════════════════════
#  STUDY ROUTINE GENERATOR PROMPT
# ══════════════════════════════════════════════════════════
ROUTINE_GENERATOR_PROMPT = """তুমি একজন বাংলাদেশের {class_label} পরীক্ষার বিশেষজ্ঞ শিক্ষা পরামর্শদাতা।
শিক্ষার্থীর জন্য একটি কার্যকর পড়ার রুটিন তৈরি করো।

শিক্ষার্থীর তথ্য:
- শ্রেণি: {class_label}
- পরীক্ষার তারিখ: {exam_date}
- দুর্বল বিষয়সমূহ: {weak_subjects}
- প্রতিদিন পড়ার সময়: {daily_hours} ঘণ্টা
- বর্তমান তারিখ: {today}

নিচের JSON ফরম্যাটে ৭ দিনের রুটিন তৈরি করো (শুধু JSON, অন্য কিছু না):
{{
  "title": "পরীক্ষা প্রস্তুতির রুটিন",
  "exam_date": "{exam_date}",
  "days_remaining": <পরীক্ষা পর্যন্ত বাকি দিন>,
  "daily_study_hours": {daily_hours},
  "strategy": "<সামগ্রিক পড়ার কৌশল ৩-৪ লাইনে>",
  "week": [
    {{
      "day": "দিন ১ (তারিখ)",
      "focus": "মূল বিষয়/অধ্যায়",
      "schedule": [
        {{"time": "সকাল ৬টা-৭টা", "task": "কাজ", "subject": "বিষয়"}},
        {{"time": "সকাল ৯টা-১১টা", "task": "কাজ", "subject": "বিষয়"}}
      ],
      "revision": "রাতে কী রিভিশন করবে",
      "tip": "বিশেষ টিপস"
    }}
  ],
  "important_tips": ["<টিপস ১>", "<টিপস ২>", "<টিপস ৩>"]
}}"""


# ══════════════════════════════════════════════════════════
#  SQLite DATABASE PATH
# ══════════════════════════════════════════════════════════
DB_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "study_ai.db")


# ══════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════
def get_all_subjects(class_id):
    """একটা class এর সব unique subject ফেরত দাও"""
    cls = CLASSES.get(class_id, {})
    groups = cls.get("groups", {})
    subjects = {}
    for group_id, group in groups.items():
        for subj_id, subj in group.get("subjects", {}).items():
            subjects[subj_id] = {**subj, "group": group_id}
        for subj_id, subj in group.get("4th_subjects", {}).items():
            if subj_id not in subjects:
                subjects[subj_id] = {**subj, "group": group_id, "is_4th": True}
    return subjects


def get_subject_info(class_id, subject_id):
    """একটা নির্দিষ্ট subject এর info দাও"""
    subjects = get_all_subjects(class_id)
    return subjects.get(subject_id)


def get_data_filename(class_id, subject_id):
    """JSON data file এর নাম তৈরি করো"""
    return f"{class_id}_{subject_id}.json"


# ══════════════════════════════════════════════════════════
#  LOCAL SUBJECT DETECTION — Gemini API call ছাড়াই
#  keyword matching দিয়ে subject detect করে
# ══════════════════════════════════════════════════════════

# প্রতিটি subject এর বাংলা ও English keywords
SUBJECT_KEYWORDS = {
    # SSC/HSC Common
    "bangla_1":        ["বাংলা", "বাংলা সাহিত্য", "গদ্য", "পদ্য", "উপন্যাস", "কবিতা", "ব্যাকরণ", "সাহিত্য"],
    "bangla_2":        ["বাংলা ব্যাকরণ", "রচনা", "ব্যাকরণ", "প্রবন্ধ", "অনুচ্ছেদ", "সারাংশ", "পত্র"],
    "english_1":       ["english", "reading", "comprehension", "passage", "seen", "unseen", "paragraph"],
    "english_2":       ["grammar", "writing", "composition", "tense", "voice", "narration", "transformation"],
    "math":            ["গণিত", "সংখ্যা", "বীজগণিত", "জ্যামিতি", "ত্রিকোণমিতি", "পরিসংখ্যান", "অনুপাত", "ক্ষেত্রফল", "math", "algebra"],
    "ict":             ["আইসিটি", "ict", "কম্পিউটার", "ইন্টারনেট", "প্রোগ্রামিং", "database", "network", "hardware", "software"],
    "religion":        ["ধর্ম", "ইসলাম", "নৈতিক", "আখলাক", "ইবাদত", "কোরআন", "হাদিস", "সালাত"],
    # SSC Science
    "physics":         ["পদার্থ", "পদার্থবিজ্ঞান", "physics", "বল", "গতি", "শক্তি", "তাপ", "আলো", "শব্দ", "বিদ্যুৎ", "চুম্বক", "তরঙ্গ"],
    "chemistry":       ["রসায়ন", "chemistry", "পরমাণু", "অণু", "বন্ধন", "বিক্রিয়া", "এসিড", "ক্ষার", "লবণ", "জৈব", "অজৈব"],
    "biology":         ["জীববিজ্ঞান", "biology", "কোষ", "টিস্যু", "উদ্ভিদ", "প্রাণী", "মানব", "শ্বসন", "পুষ্টি", "প্রজনন", "বাস্তুতন্ত্র"],
    "higher_math":     ["উচ্চতর গণিত", "higher math", "ক্যালকুলাস", "ম্যাট্রিক্স", "ভেক্টর", "লগারিদম", "সংযুক্তি"],
    # SSC Business
    "accounting":      ["হিসাববিজ্ঞান", "হিসাব", "accounting", "জাবেদা", "খতিয়ান", "রেওয়ামিল", "উদ্বৃত্তপত্র", "নগদান", "ক্রেডিট", "ডেবিট", "লেনদেন"],
    "finance":         ["ফিন্যান্স", "ব্যাংকিং", "finance", "banking", "বীমা", "ঋণ", "সুদ", "বিনিয়োগ", "শেয়ার"],
    "entrepreneurship": ["উদ্যোগ", "ব্যবসায় উদ্যোগ", "উদ্যোক্তা", "entrepreneurship", "ব্যবসা পরিকল্পনা"],
    # SSC Humanities
    "geography":       ["ভূগোল", "geography", "পরিবেশ", "মাটি", "নদী", "জলবায়ু", "বায়ুমণ্ডল", "সম্পদ", "মানচিত্র"],
    "civics":          ["পৌরনীতি", "civics", "নাগরিক", "সংবিধান", "গণতন্ত্র", "সরকার", "রাষ্ট্র", "সুশাসন", "মৌলিক অধিকার"],
    "economics":       ["অর্থনীতি", "economics", "চাহিদা", "যোগান", "বাজার", "মূল্য", "জাতীয় আয়", "উৎপাদন", "ভোক্তা", "জিডিপি"],
    "history":         ["ইতিহাস", "history", "মুক্তিযুদ্ধ", "ঐতিহাসিক", "সভ্যতা", "আন্দোলন", "ভাষা আন্দোলন", "স্বাধীনতা"],
    # HSC Science extras
    "statistics":      ["পরিসংখ্যান", "statistics", "গড়", "মধ্যক", "প্রচুরক", "বিস্তার", "সম্ভাবনা"],
    "agriculture":     ["কৃষি", "agriculture", "ফসল", "মাটি", "সার", "পানি সেচ", "বীজ", "চাষাবাদ"],
    # HSC Business extras
    "management":      ["ব্যবস্থাপনা", "management", "পরিকল্পনা", "সংগঠন", "নেতৃত্ব", "নিয়ন্ত্রণ"],
    "production":      ["উৎপাদন", "বিপণন", "production", "marketing", "পণ্য", "বাজারজাত", "বিক্রয়"],
    # HSC Humanities extras
    "sociology":       ["সমাজবিজ্ঞান", "sociology", "সমাজ", "পরিবার", "সংস্কৃতি", "সামাজিক"],
    "social_work":     ["সমাজকর্ম", "social work", "সেবা", "কল্যাণ", "সামাজিক উন্নয়ন"],
    "islamic_history": ["ইসলামের ইতিহাস", "ইসলামিক", "খলিফা", "মুসলিম সভ্যতা", "হযরত"],
    "logic":           ["যুক্তিবিদ্যা", "logic", "যুক্তি", "প্রমাণ", "অনুমান", "বাক্য"],
    "psychology":      ["মনোবিজ্ঞান", "psychology", "আচরণ", "মন", "শিক্ষা মনোবিজ্ঞান", "ব্যক্তিত্ব"],
    "home_science":    ["গার্হস্থ্য", "home science", "পুষ্টি", "রান্না", "গৃহ ব্যবস্থাপনা"],
    "general_science": ["সাধারণ বিজ্ঞান", "general science", "বিজ্ঞান"],
    "music":           ["সংগীত", "music", "গান", "সুর", "তাল", "রাগ"],
}


def detect_subject_locally(question, subject_keys):
    """
    Gemini API call ছাড়াই keyword matching দিয়ে subject detect করো।
    subject_keys = available subjects এর list
    Returns: detected subject key অথবা None
    """
    if not question or not subject_keys:
        return None

    question_lower = question.lower()
    scores = {}

    for key in subject_keys:
        if key not in SUBJECT_KEYWORDS:
            continue
        keywords = SUBJECT_KEYWORDS[key]
        score = 0
        for kw in keywords:
            if kw.lower() in question_lower:
                # দীর্ঘ keyword বেশি score পায়
                score += len(kw.split())
        if score > 0:
            scores[key] = score

    if not scores:
        return None

    # সবচেয়ে বেশি score যার
    return max(scores, key=scores.get)


# ══════════════════════════════════════════════════════════
#  FOLDER STRUCTURE — New organized path system
#  data/ssc/universal/bangla_1.json
#  data/ssc/science/physics.json
#  data/hsc/business/accounting.json
# ══════════════════════════════════════════════════════════

def get_subject_group_folder(class_id, subject_id):
    """
    Subject টা কোন group folder এ যাবে সেটা বের করো।
    common group → 'universal'
    science/business/humanities → নিজের নাম
    Priority: subjects > 4th_subjects (duplicate হলে primary group জেতে)
    """
    cls = CLASSES.get(class_id, {})
    groups = cls.get("groups", {})
    # প্রথমে primary subjects এ খোঁজো
    for group_id, group in groups.items():
        if subject_id in group.get("subjects", {}):
            return "universal" if group_id == "common" else group_id
    # তারপর 4th_subjects এ খোঁজো
    for group_id, group in groups.items():
        if subject_id in group.get("4th_subjects", {}):
            return "universal" if group_id == "common" else group_id
    return "universal"


def get_data_filepath(class_id, subject_id, base_data_dir):
    """
    New folder structure path return করো।
    e.g.  data/ssc/science/physics.json
          data/hsc/universal/bangla_1.json
    """
    import os
    group_folder = get_subject_group_folder(class_id, subject_id)
    folder = _os.path.join(base_data_dir, class_id, group_folder)
    _os.makedirs(folder, exist_ok=True)
    return _os.path.join(folder, f"{subject_id}.json")


def find_data_file(class_id, subject_id, base_data_dir):
    """
    নতুন path আগে দেখো, না পেলে পুরনো flat path দেখো।
    Returns filepath অথবা None
    """
    # নতুন: data/ssc/science/physics.json
    new_path = get_data_filepath(class_id, subject_id, base_data_dir)
    if _os.path.exists(new_path):
        return new_path
    # পুরনো legacy: data/ssc_physics.json
    legacy_path = _os.path.join(base_data_dir, f"{class_id}_{subject_id}.json")
    if _os.path.exists(legacy_path):
        return legacy_path
    return None


# ══════════════════════════════════════════════════════════
#  3টা EXTRACTION PROMPT  (v3 — improved)
#
#  ১. BOARD BOOK      — NCTB পাঠ্যবই থেকে full content
#  ২. TEST PAPER      — স্কুল/বোর্ড প্রশ্নপত্র, year+source tagged
#  ৩. GUIDE BOOK      — গাইড বই, শুধু প্রশ্ন+উত্তর, কোনো filler নেই
# ══════════════════════════════════════════════════════════

# ─── ১. BOARD BOOK PROMPT ─────────────────────────────────
EXTRACT_PROMPT_BOARD_BOOK = """তুমি বাংলাদেশ জাতীয় শিক্ষাক্রম ও পাঠ্যপুস্তক বোর্ডের (NCTB) পাঠ্যবই থেকে content extract করছো।

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 সম্পূর্ণ বাদ দেবে — একটাও রাখবে না:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
❌ ওয়াটারমার্ক, publisher logo, প্রকাশনীর যেকোনো চিহ্ন বা নাম
❌ পেজ নম্বর, হেডার, ফুটার, border, decorative line
❌ "সর্বস্বত্ব সংরক্ষিত", "মুদ্রণ", ISBN, edition তথ্য
❌ পাঠ্যবইয়ের ভূমিকা, লেখক পরিচিতি, সম্পাদক নাম
❌ ফাঁকা পেজ → শুধু লেখো [EMPTY_PAGE]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 কী রাখবে এবং কীভাবে:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【অধ্যায়/পাঠের শিরোনাম】
[CHAPTER: অধ্যায় নম্বর — অধ্যায়ের নাম]

【সংজ্ঞা ও ধারণা】
[DEFINITION: পরিভাষা = সম্পূর্ণ সংজ্ঞা বাংলায়]
- একাধিক সংজ্ঞা থাকলে প্রতিটা আলাদা লাইনে

【সূত্র ও সমীকরণ】
[FORMULA: সূত্রের নাম → LaTeX: $সূত্র$]
- উদাহরণ: [FORMULA: নিউটনের ২য় সূত্র → $F = ma$]
- রসায়নের সমীকরণ: [EQUATION: 2H₂ + O₂ → 2H₂O]

【মূল পাঠ্য বিষয়বস্তু】
- অধ্যায়ের ব্যাখ্যা, তত্ত্ব, বর্ণনা — হুবহু রাখো
- অনুচ্ছেদ ভেঙে পড়ার উপযোগী করো

【টেবিল ও তুলনামূলক তথ্য】
- Markdown table ফরম্যাটে রাখো
- হিসাব/accounting টেবিল সঠিক column এ রাখো

【উদাহরণ ও সমাধান】
[EXAMPLE: উদাহরণ নম্বর]
প্রশ্ন: ...
সমাধান: ...

【অধ্যায়ের শেষের প্রশ্নাবলী (exercise)】
[EXERCISE]
প্রশ্ন: ...
উত্তর: ... (যদি থাকে, না থাকলে N/A)
[/EXERCISE]

【MCQ (বহুনির্বাচনি)】
[MCQ]
প্রশ্ন: ...
(ক) ... (খ) ... (গ) ... (ঘ) ...
উত্তর: (ক/খ/গ/ঘ)
[/MCQ]

【সৃজনশীল প্রশ্ন (CQ)】
[CQ]
উদ্দীপক: ...
(ক) ... (নম্বর: ১)
(খ) ... (নম্বর: ২)
(গ) ... (নম্বর: ৩)
(ঘ) ... (নম্বর: ৪)
[/CQ]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 চূড়ান্ত নিয়ম:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ সব বাংলা ও ইংরেজি text হুবহু রাখো
✅ সংখ্যা ও অংক পরিবর্তন করো না
✅ নিজের মন্তব্য বা সংযোজন করো না
✅ শুধু extracted content দাও"""


# ─── ২. TEST PAPER PROMPT (v3) ────────────────────────────
# স্কুল টেস্ট পেপার + বোর্ড প্রশ্নপত্র — বছর ও উৎস সহ
EXTRACT_PROMPT_TEST_PAPER = """তুমি বাংলাদেশের SSC/HSC পরীক্ষার প্রশ্নপত্র (Test Paper / স্কুল পরীক্ষা / বোর্ড প্রশ্নপত্র) থেকে শুধু প্রশ্ন extract করছো।

🎯 লক্ষ্য: শিক্ষার্থী যখন জিজ্ঞেস করবে "২০২২ সালের ঢাকা বোর্ডের CQ দাও" বা "সেন্ট জোসেফের ২০২৩ এর MCQ দাও" — সে যেন সরাসরি খুঁজে পায়।

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 এগুলো দেখলে সম্পূর্ণ ignore করো — একটা অক্ষরও নেবে না:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
❌ প্রকাশনীর নাম/logo/ওয়াটারমার্ক (অঞ্জলি, পাঞ্জেরী, লেকচার, আইডিয়াল, যেকোনো publisher)
❌ "সর্বস্বত্ব সংরক্ষিত", "Printed by", "Published by", "এই বইয়ের যেকোনো অংশ..."
❌ স্কুল/কলেজের ঠিকানা, ফোন নম্বর, ই-মেইল, সিলমোহর
❌ পরীক্ষার সাধারণ নির্দেশনা ("ডান পাশের সংখ্যা নম্বর বোঝায়", "সব প্রশ্ন সমান মান")
❌ "পরীক্ষার্থীর নাম:", "রোল নম্বর:", "রেজিস্ট্রেশন নম্বর:" — এই ধরনের ফর্ম ঘর
❌ ফাঁকা উত্তর লেখার জায়গা, বিন্দু লাইন (............)
❌ বিজ্ঞাপন, "আমাদের অন্যান্য প্রকাশনী", "পরবর্তী বই"
❌ পেজ নম্বর, হেডার, ফুটার, decorative border
❌ ফাঁকা পেজ → শুধু [EMPTY_PAGE] লেখো

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 STEP 1 — প্রতিটা প্রশ্নপত্রের শুরুতে source tag করো:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

পেজে যদি প্রশ্নপত্রের header দেখো (স্কুল/বোর্ডের নাম, সাল, বিষয়), তাহলে:

বোর্ড পরীক্ষার ক্ষেত্রে:
[SOURCE: type=board, board=ঢাকা, year=2023, subject=পদার্থবিজ্ঞান, class=SSC]

স্কুল/কলেজ পরীক্ষার ক্ষেত্রে:
[SOURCE: type=school, school=ভিকারুননিসা নূন স্কুল অ্যান্ড কলেজ, year=2022, exam=প্রথম সাময়িক, subject=রসায়ন, class=HSC]

⚠️ নিয়ম: header দেখলেই tag করো। পরবর্তী header আসা পর্যন্ত সব প্রশ্ন এই source এর।
⚠️ সাল/বোর্ড/স্কুল না থাকলে: [SOURCE: type=unknown, year=N/A, board=N/A]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 STEP 2 — MCQ extract করো:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[MCQ]
প্রশ্ন: (ক্রমিক নম্বর সহ) পুরো প্রশ্ন হুবহু লেখো
(ক) ... (খ) ... (গ) ... (ঘ) ...
উত্তর: (সঠিক অপশন — answer key থাকলে দাও, না থাকলে N/A)
[/MCQ]

⚠️ MCQ এর ৪টা অপশন অবশ্যই রাখো।
⚠️ উত্তর বানিয়ে লিখবে না — না থাকলে N/A।

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 STEP 3 — CQ (সৃজনশীল প্রশ্ন) extract করো:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[CQ]
প্রশ্ন নং: (নম্বর)
উদ্দীপক: (উদ্দীপকের পুরো text হুবহু — গল্প/ঘটনা/চিত্র বর্ণনা/তথ্য)
(ক) (জ্ঞানমূলক প্রশ্ন হুবহু) [নম্বর: ১]
(খ) (অনুধাবনমূলক প্রশ্ন হুবহু) [নম্বর: ২]
(গ) (প্রয়োগমূলক প্রশ্ন হুবহু) [নম্বর: ৩]
(ঘ) (উচ্চতর দক্ষতামূলক প্রশ্ন হুবহু) [নম্বর: ৪]
[/CQ]

⚠️ উদ্দীপক বাদ দেবে না — এটা ছাড়া প্রশ্ন অর্থহীন।
⚠️ উত্তর এখানে দেবে না — শুধু প্রশ্ন।

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 STEP 4 — SAQ/সংক্ষিপ্ত প্রশ্ন থাকলে:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[SAQ]
প্রশ্ন: (নম্বর সহ) পুরো প্রশ্ন হুবহু
[/SAQ]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 চূড়ান্ত কঠোর নিয়ম:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ SOURCE tag ছাড়া কোনো প্রশ্ন extract করবে না
✅ প্রতিটা প্রশ্ন হুবহু — একটা শব্দও বদলাবে না
✅ নিজে কোনো উত্তর বানাবে না, নোট যোগ করবে না
✅ শুধু প্রশ্ন — কোনো explanation, tips, ব্যাখ্যা নেই"""


# ─── ৩. GUIDE BOOK PROMPT (v3) ───────────────────────────
# গাইড বই — শুধু প্রশ্ন+উত্তর, বোর্ড/স্কুল source tagged
EXTRACT_PROMPT_GUIDE = """তুমি বাংলাদেশের SSC/HSC গাইড বই থেকে প্রশ্ন ও মডেল উত্তর extract করছো।

🎯 লক্ষ্য: শিক্ষার্থী প্রশ্ন করলে সংশ্লিষ্ট মডেল উত্তর খুঁজে পাবে। বোর্ড/স্কুলের বছর ধরে খুঁজতে পারবে।

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 এগুলো দেখলে সম্পূর্ণ ignore করো — একটা অক্ষরও নেবে না:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
❌ প্রকাশনীর নাম/logo/ওয়াটারমার্ক (অঞ্জলি, পাঞ্জেরী, লেকচার, আইডিয়াল, যেকোনো publisher)
❌ "সর্বস্বত্ব সংরক্ষিত", "Printed by", "Published by", লেখক পরিচিতি, সম্পাদক তালিকা
❌ "আমাদের অন্যান্য বই", "পাওয়া যাচ্ছে", বিজ্ঞাপন পেজ
❌ গাইডের নিজস্ব explanation/তত্ত্ব/বর্ণনা (পাঠ্যবইয়ের মতো করে লেখা অংশ)
❌ TIPS, সাজেশন, "পরীক্ষায় ভালো করার উপায়", "মনে রাখার কৌশল"
❌ Chapter summary যদি প্রশ্ন-উত্তর আকারে না হয়
❌ পেজ নম্বর, হেডার, ফুটার, decorative border
❌ ফাঁকা পেজ → শুধু [EMPTY_PAGE] লেখো

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 STEP 1 — অধ্যায় চিহ্নিত করো:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[CHAPTER: অধ্যায় নম্বর — অধ্যায়ের নাম]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 STEP 2 — বোর্ড/স্কুলের প্রশ্ন দেখলে source tag করো:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

গাইডে বোর্ড প্রশ্নের section থাকলে:
[SOURCE: type=board, board=ঢাকা, year=2022]

গাইডে স্কুলের প্রশ্নের section থাকলে:
[SOURCE: type=school, school=স্কুলের নাম, year=2021]

গাইডের নিজস্ব model প্রশ্ন হলে:
[SOURCE: type=model]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 STEP 3 — MCQ extract করো (উত্তর+ব্যাখ্যা সহ):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[MCQ]
প্রশ্ন: পুরো প্রশ্ন হুবহু
(ক) ... (খ) ... (গ) ... (ঘ) ...
উত্তর: (সঠিক অপশন)
ব্যাখ্যা: (গাইডে ব্যাখ্যা থাকলে হুবহু, না থাকলে N/A)
[/MCQ]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 STEP 4 — CQ + মডেল উত্তর extract করো:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[CQ]
উদ্দীপক: (পুরো উদ্দীপক হুবহু)
(ক) (প্রশ্ন হুবহু) [নম্বর: ১]
উত্তর-ক: (গাইডের মডেল উত্তর হুবহু — সংক্ষিপ্ত করবে না)

(খ) (প্রশ্ন হুবহু) [নম্বর: ২]
উত্তর-খ: (গাইডের মডেল উত্তর হুবহু)

(গ) (প্রশ্ন হুবহু) [নম্বর: ৩]
উত্তর-গ: (গাইডের মডেল উত্তর হুবহু)

(ঘ) (প্রশ্ন হুবহু) [নম্বর: ৪]
উত্তর-ঘ: (গাইডের মডেল উত্তর হুবহু)
[/CQ]

⚠️ উত্তর না থাকলে: উত্তর-ক: N/A
⚠️ উত্তর সংক্ষিপ্ত করবে না — গাইড যা দিয়েছে পুরোটা রাখো

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 STEP 5 — SAQ/সংক্ষিপ্ত প্রশ্ন থাকলে:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[SAQ]
প্রশ্ন: পুরো প্রশ্ন হুবহু
উত্তর: (গাইডের উত্তর হুবহু, না থাকলে N/A)
[/SAQ]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 চূড়ান্ত কঠোর নিয়ম:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ শুধু প্রশ্ন ও উত্তর — গাইডের ব্যাখ্যামূলক পাঠ্য নেবে না
✅ প্রশ্ন ও উত্তর হুবহু — নিজে সংক্ষিপ্ত বা পরিবর্তন করবে না
✅ বোর্ড/স্কুল/সাল দেখলে SOURCE tag অবশ্যই দেবে
✅ নিজের কোনো মন্তব্য, সংযোজন, মতামত যোগ করবে না"""


# ── Prompt type mapping ──────────────────────────────────
EXTRACT_PROMPTS = {
    "board_book":  EXTRACT_PROMPT_BOARD_BOOK,
    "test_paper":  EXTRACT_PROMPT_TEST_PAPER,
    "guide":       EXTRACT_PROMPT_GUIDE,
}

EXTRACT_PROMPT_LABELS = {
    "board_book":  "📚 পাঠ্যবই (Board Book)",
    "test_paper":  "📝 প্রশ্নপত্র (Test Paper)",
    "guide":       "📖 গাইড বই (Guide Book)",
}

# Default (backward compat)
EXTRACT_PROMPT = EXTRACT_PROMPT_BOARD_BOOK
