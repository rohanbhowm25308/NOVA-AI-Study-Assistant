"""
AI Engine for the Study Assistant.

Everything here is self-contained (no external LLM API key required) so the
project runs fully offline:
  - Smart scheduling  -> weighted priority/urgency/difficulty algorithm
  - Summarization      -> extractive, frequency-based sentence scoring
  - Keyword extraction -> stopword-filtered term frequency
  - Quiz generation     -> keyword/definition based MCQ, fill-blank, T/F
  - Flashcards          -> auto term/definition pair extraction
  - AI Tutor            -> retrieval + template based response engine
  - Exam readiness      -> weighted scoring model over topic + quiz data
  - Burnout detector    -> rule-based over recent study-time distribution

Swap `tutor_answer` / `summarize_text` for a real LLM call later (e.g. the
Anthropic API) by dropping in an API-backed implementation with the same
function signature.
"""
import re
import math
import random
import itertools
from collections import Counter
from datetime import date, datetime, timedelta

from question_bank import QUESTION_BANK, DOMAIN_LABELS

try:
    from PyPDF2 import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None

try:
    import pymupdf as _fitz  # PyMuPDF — far more reliable than PyPDF2 on
except ImportError:          # real-world PDFs (custom fonts, odd encodings,
    try:                      # PowerPoint/Canva/Google-Docs exports, etc.)
        import fitz as _fitz
    except ImportError:  # pragma: no cover
        _fitz = None

try:
    import pdfplumber as _pdfplumber
except ImportError:  # pragma: no cover
    _pdfplumber = None

try:
    import pytesseract as _pytesseract
    from PIL import Image as _PILImage
    import io as _io
    # Also confirms the tesseract *binary* itself is actually installed —
    # pytesseract is just a thin wrapper around it, and pip installing the
    # wrapper doesn't install the underlying OCR engine.
    _pytesseract.get_tesseract_version()
    _OCR_AVAILABLE = True
except Exception:  # pragma: no cover — no binary, no wrapper, or version check failed
    _pytesseract = None
    _OCR_AVAILABLE = False

STOPWORDS = set("""
a about above after again against all am an and any are aren't as at be because
been before being below between both but by can't cannot could couldn't did
didn't do does doesn't doing don't down during each few for from further had
hadn't has hasn't have haven't having he he'd he'll he's her here here's hers
herself him himself his how how's i i'd i'll i'm i've if in into is isn't it
it's its itself let's me more most mustn't my myself no nor not of off on once
only or other ought our ours ourselves out over own same shan't she she'd
she'll she's should shouldn't so some such than that that's the their theirs
them themselves then there there's these they they'd they'll they're they've
this those through to too under until up very was wasn't we we'd we'll we're
we've were weren't what what's when when's where where's which while who
who's whom why why's with won't would wouldn't you you'd you'll you're you've
your yours yourself yourselves this is it its an also may can will using use
used within thus hence etc
""".split())

PRIORITY_WEIGHT = {"High": 3, "Medium": 2, "Low": 1}
DIFFICULTY_WEIGHT = {"Hard": 3, "Medium": 2, "Easy": 1}


# ============================================================ SCHEDULING ===
def generate_schedule(topics, daily_minutes=120, horizon_days=21):
    """
    Greedy weighted scheduler:
      score = 3*priority + 2*difficulty + urgency_bonus
      urgency_bonus rises sharply as the deadline approaches.
    Topics are ordered by score, then packed into daily buckets of
    `daily_minutes` minutes across the next `horizon_days`.
    """
    today = date.today()
    scored = []
    for t in topics:
        pw = PRIORITY_WEIGHT.get(t.get("priority", "Medium"), 2)
        dw = DIFFICULTY_WEIGHT.get(t.get("difficulty", "Medium"), 2)
        deadline = t.get("deadline")
        days_left = horizon_days
        if deadline:
            try:
                d = datetime.strptime(deadline, "%Y-%m-%d").date()
                days_left = max((d - today).days, 0)
            except ValueError:
                pass
        urgency = 10 / (days_left + 1)
        score = pw * 3 + dw * 2 + urgency * 5
        scored.append((score, days_left, t))

    scored.sort(key=lambda x: (-x[0], x[1]))

    days = [{"date": (today + timedelta(days=i)).isoformat(), "items": [], "minutes_used": 0}
            for i in range(horizon_days)]

    at_risk = []

    for score, days_left, t in scored:
        remaining = int(t.get("estimated_time", 60))
        needed_total = remaining
        deadline_idx = min(days_left, horizon_days - 1)

        def _place(chunk_target, day_idx, overflow):
            """Try to place up to chunk_target minutes on days[day_idx],
            respecting the daily cap. Returns minutes actually placed.
            Fills the day's remaining budget in one go (rather than an
            arbitrary fixed block size) so a topic doesn't get needlessly
            split across days when the current day still has room; if a
            second call lands on the same day for the same topic (can
            happen via the overflow pass), it merges into the existing
            line instead of adding a duplicate row."""
            day = days[day_idx]
            free = daily_minutes - day["minutes_used"]
            if free <= 10:
                return 0
            chunk = min(free, chunk_target)
            if (day["items"] and day["items"][-1]["topic_id"] == t["id"]
                    and day["items"][-1]["overflow"] == overflow):
                day["items"][-1]["duration"] += chunk
            else:
                day["items"].append({
                    "topic_id": t["id"],
                    "topic_name": t["name"],
                    "subject_name": t.get("subject_name", ""),
                    "priority": t.get("priority"),
                    "duration": chunk,
                    "overflow": overflow,
                })
            day["minutes_used"] += chunk
            return chunk

        # Pass 1: place within the topic's own deadline, respecting the cap.
        day_idx = 0
        while remaining > 0 and day_idx <= deadline_idx:
            remaining -= _place(remaining, day_idx, overflow=False)
            day_idx += 1

        # Pass 2: whatever didn't fit before the deadline spills into the
        # days *after* it (still respecting the daily cap on each of those
        # days) instead of being dumped entirely onto one day. This is what
        # actually fixes the "410 minutes crammed into one day" bug — a
        # capacity shortfall now shows up as several flagged catch-up
        # sessions after the deadline, not one impossible mega-session.
        day_idx = deadline_idx + 1
        while remaining > 0 and day_idx < horizon_days:
            remaining -= _place(remaining, day_idx, overflow=True)
            day_idx += 1

        # Only if the entire horizon is full (rare) do we fall back to
        # stacking the last bit on the final day, so no study time is lost.
        if remaining > 0:
            last = days[horizon_days - 1]
            last["items"].append({
                "topic_id": t["id"], "topic_name": t["name"],
                "subject_name": t.get("subject_name", ""),
                "priority": t.get("priority"), "duration": remaining,
                "overflow": True,
            })
            last["minutes_used"] += remaining
            remaining = 0

        if needed_total > daily_minutes * max(days_left, 1):
            at_risk.append(t["name"])

    result = [d for d in days if d["items"]]
    if result:
        result[0]["at_risk"] = at_risk  # surfaced once, not per-day
    return result


# ============================================================== NLP UTIL ===
def _split_sentences(text):
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if len(s.strip()) > 20]


def _tokenize(text):
    return [w for w in re.findall(r"[a-zA-Z']+", text.lower()) if w not in STOPWORDS and len(w) > 2]


def extract_keywords(text, top_n=10):
    words = _tokenize(text)
    if not words:
        return []
    freq = Counter(words)
    max_freq = max(freq.values())
    for w in freq:
        freq[w] = freq[w] / max_freq
    return [w for w, _ in freq.most_common(top_n)]


def summarize_text(text, length="medium"):
    """Extractive summary via word-frequency sentence scoring (Luhn-style)."""
    sentences = _split_sentences(text)
    if not sentences:
        return "Not enough text to summarize."
    n_map = {"short": 3, "medium": 6, "long": 10}
    n = min(n_map.get(length, 6), len(sentences))

    words = _tokenize(text)
    freq = Counter(words)
    max_freq = max(freq.values()) if freq else 1
    for w in freq:
        freq[w] /= max_freq

    scores = []
    for i, s in enumerate(sentences):
        s_words = _tokenize(s)
        if not s_words:
            scores.append((0, i, s))
            continue
        score = sum(freq.get(w, 0) for w in s_words) / len(s_words)
        # slight boost for early sentences (often topic sentences)
        position_boost = 1.15 if i < 3 else 1.0
        scores.append((score * position_boost, i, s))

    top = sorted(scores, key=lambda x: -x[0])[:n]
    top.sort(key=lambda x: x[1])  # restore original order
    return " ".join(s for _, _, s in top)


def answer_from_text(question, text):
    """Very light-weight retrieval QA: finds the sentence(s) most overlapping
    with the question's keywords."""
    q_words = set(_tokenize(question))
    if not q_words:
        return "Could you rephrase your question?"
    sentences = _split_sentences(text)
    if not sentences:
        return "I couldn't find readable text in this document."
    scored = []
    for s in sentences:
        s_words = set(_tokenize(s))
        overlap = len(q_words & s_words)
        if overlap:
            scored.append((overlap, s))
    if not scored:
        return "I couldn't find anything about that in the document. Try rephrasing, or ask about a different topic covered in the text."
    scored.sort(key=lambda x: -x[0])
    best = [s for _, s in scored[:2]]
    return " ".join(best)


def extract_pdf_text(path):
    """
    Robust PDF text extraction with a real fallback chain, instead of relying
    on a single library. This is what actually fixes the "0 characters /
    not enough text to summarize" bug: PyPDF2 alone silently returns an
    empty string on a large class of real-world PDFs (custom font
    encodings, PDFs exported from PowerPoint/Canva/Google Docs/Notion,
    etc.) even though the text is genuinely there and other libraries can
    read it fine. And if a PDF is a scan / photographed pages with no text
    layer at all, no text-extraction library can help — that needs OCR.

    Order: PyMuPDF -> pdfplumber -> PyPDF2 -> OCR (only if all three
    extractors combined still yield ~nothing, since OCR is much slower).

    Returns a dict: {text, method, pages, ocr_available} so the caller can
    show the person an accurate, specific message instead of a bare
    character count.
    """
    methods_tried = []

    def _clean(t):
        return re.sub(r"[ \t]+", " ", (t or "")).strip()

    # ---- 1) PyMuPDF: fastest and most reliable for the widest range of
    # real-world PDFs; also gives us page rasterization for OCR later with
    # no extra system dependency (no poppler needed). ----------------------
    if _fitz is not None:
        try:
            doc = _fitz.open(path)
            text = "\n".join(page.get_text() for page in doc)
            methods_tried.append(("pymupdf", len(_clean(text))))
            if len(_clean(text)) >= 30:
                return {"text": _clean(text), "method": "text (pymupdf)",
                        "pages": doc.page_count, "ocr_available": _OCR_AVAILABLE}
        except Exception:
            pass

    # ---- 2) pdfplumber: different underlying parser, catches PDFs that
    # trip up PyMuPDF (rare, but layout-heavy/table-heavy PDFs sometimes
    # extract better here). --------------------------------------------
    if _pdfplumber is not None:
        try:
            with _pdfplumber.open(path) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            methods_tried.append(("pdfplumber", len(_clean(text))))
            if len(_clean(text)) >= 30:
                return {"text": _clean(text), "method": "text (pdfplumber)",
                        "pages": len(pdf.pages), "ocr_available": _OCR_AVAILABLE}
        except Exception:
            pass

    # ---- 3) PyPDF2: kept as a last plain-text-extraction resort. ---------
    if PdfReader is not None:
        try:
            reader = PdfReader(path)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            methods_tried.append(("pypdf2", len(_clean(text))))
            if len(_clean(text)) >= 30:
                return {"text": _clean(text), "method": "text (pypdf2)",
                        "pages": len(reader.pages), "ocr_available": _OCR_AVAILABLE}
        except Exception:
            pass

    # ---- 4) OCR fallback: every text extractor came back empty (or nearly
    # empty), which means this is very likely a scanned document / photos
    # of pages with no real text layer — the only way to read that is to
    # rasterize each page and run OCR on the image. ------------------------
    best_partial = max((t for _, t in methods_tried), default=0)
    if _fitz is not None and _OCR_AVAILABLE:
        try:
            doc = _fitz.open(path)
            ocr_pages = []
            for page in doc:
                pix = page.get_pixmap(dpi=200)
                img = _PILImage.open(_io.BytesIO(pix.tobytes("png")))
                ocr_pages.append(_pytesseract.image_to_string(img))
            text = _clean("\n".join(ocr_pages))
            if len(text) >= 20:
                return {"text": text, "method": "ocr", "pages": doc.page_count,
                        "ocr_available": True}
        except Exception:
            pass

    # ---- Nothing worked: say so precisely instead of a bare "0 characters" ---
    if best_partial > 0:
        reason = ("This PDF only contains a tiny amount of extractable text "
                   "(it may be mostly images/diagrams with little real text).")
    elif _fitz is not None:
        reason = ("This looks like a scanned or image-only PDF with no real "
                   "text layer, and " +
                   ("OCR also couldn't read it clearly." if _OCR_AVAILABLE else
                    "OCR isn't available in this environment (the tesseract-ocr "
                    "engine isn't installed), so it can't be read automatically."))
    else:
        reason = "No PDF-reading library is available in this environment."
    return {"text": "", "method": "failed", "pages": 0,
            "ocr_available": _OCR_AVAILABLE, "reason": reason}


# ============================================================ DOMAIN MATCH ==
_DOMAIN_PHRASE_RULES = [
    # order matters: more specific / less ambiguous phrases are checked first
    ("cpp", ["c++", "cpp", "object oriented programming in c++"]),
    ("cybersecurity", ["cybersecurity", "cyber security", "ethical hacking",
                        "network security", "information security", "infosec"]),
    ("data_science", ["data science", "exploratory data analysis", " eda "]),
    ("ml", ["machine learning", "deep learning", "neural network", "cnn", "rnn",
            "supervised learning", "unsupervised learning", "convolutional",
            "backpropagation", "gradient descent"]),
    ("ai", ["artificial intelligence"]),
    ("dsa", ["data structure", "dsa", "algorithm", "linked list", "binary tree",
             "binary search", "sorting", "recursion", "dynamic programming",
             "hashing", " stack", " queue", " graph", " heap", " array"]),
]
# short/ambiguous single-word domains matched with strict word boundaries so
# "java" doesn't match "javascript" and "c"/"ai"/"ml" don't match substrings
# inside unrelated words
_DOMAIN_WORD_RULES = [
    ("java", r"\bjava\b"),
    ("ai", r"\bai\b"),
    ("ml", r"\bml\b"),
    ("cpp", r"\bcpp\b"),
    ("c", r"\bc\b"),
]


def match_domain(text):
    """Best-effort match of free-text topic name/notes to a curated question
    bank domain. Returns a domain key from QUESTION_BANK, or None."""
    t = f" {text.lower()} "
    for domain, phrases in _DOMAIN_PHRASE_RULES:
        for p in phrases:
            if p in t:
                return domain
    for domain, pattern in _DOMAIN_WORD_RULES:
        if re.search(pattern, t):
            return domain
    return None


# =================================================================== QUIZ ===
def _topic_corpus(topic):
    return f"{topic.get('name', '')}. {topic.get('notes', '')}"


# Varied phrasing so the *generic* fallback (used only when a topic doesn't
# match a known domain) never produces literal duplicate questions even when
# there are only one or two keywords to work with — this was the root cause
# of the "what is deep / what is learning" repeat bug.
_TF_TEMPLATES_TRUE = [
    "'{kw}' is closely related to the topic '{name}'.",
    "Understanding '{kw}' helps build a foundation for '{name}'.",
    "'{kw}' is one of the key ideas typically covered under '{name}'.",
]
_TF_TEMPLATES_FALSE = [
    "'{kw}' has no connection at all to '{name}'.",
    "'{kw}' is completely unrelated to '{name}'.",
]
_MCQ_TEMPLATES = [
    "Which term below is most closely associated with '{name}'?",
    "Which of these concepts is a key part of studying '{name}'?",
    "Which keyword best relates to the topic '{name}'?",
]
_SUBJECTIVE_TEMPLATES = [
    "Briefly explain the concept of '{kw}' in the context of {name}.",
    "How does '{kw}' relate to {name}? Explain in your own words.",
    "Describe why '{kw}' matters when studying {name}.",
]


def generate_quiz(topic, num_questions=5, qtype="mcq"):
    domain = match_domain(f"{topic.get('name', '')} {topic.get('notes', '')}")

    # --- 1) prefer the curated, factually-checked question bank ------------
    if domain and domain in QUESTION_BANK:
        bank = QUESTION_BANK[domain].get(qtype, [])
        if bank:
            n = max(1, min(num_questions, len(bank)))
            chosen = random.sample(bank, n)
            questions = []
            for item in chosen:
                if qtype == "mcq":
                    options = item["options"][:]
                    random.shuffle(options)
                    questions.append({"type": "mcq", "question": item["q"],
                                       "options": options, "answer": item["answer"]})
                elif qtype == "truefalse":
                    questions.append({"type": "truefalse", "question": item["q"],
                                       "answer": item["answer"]})
                elif qtype == "fillblank":
                    questions.append({"type": "fillblank", "question": item["q"],
                                       "answer": item["answer"]})
                else:
                    questions.append({"type": "subjective", "question": item["q"],
                                       "answer": item.get("answer", "")})
            return {"topic": topic.get("name"), "domain": DOMAIN_LABELS.get(domain),
                     "source": "bank", "questions": questions}

    # --- 2) generic fallback for topics with no domain match ---------------
    # Only reached for custom/unrecognized topics. Uses whatever real content
    # exists in the topic's notes, and — critically — rotates through several
    # phrasing templates so a small keyword pool never yields literal
    # duplicate questions the way the old single-template version did.
    corpus = _topic_corpus(topic)
    keywords = extract_keywords(corpus, max(num_questions * 3, 12))
    sentences = _split_sentences(corpus)
    name = topic.get("name", "this topic")
    pool = keywords if keywords else [name]

    seen_questions = set()
    questions = []
    attempts = 0
    max_attempts = num_questions * 6  # generous ceiling so we can skip dupes

    kw_cycle = itertools.cycle(pool)
    tf_true_cycle = itertools.cycle(_TF_TEMPLATES_TRUE)
    tf_false_cycle = itertools.cycle(_TF_TEMPLATES_FALSE)
    mcq_cycle = itertools.cycle(_MCQ_TEMPLATES)
    subj_cycle = itertools.cycle(_SUBJECTIVE_TEMPLATES)
    sent_cycle = itertools.cycle(sentences) if sentences else None

    while len(questions) < num_questions and attempts < max_attempts:
        attempts += 1
        kw = next(kw_cycle)

        if qtype == "mcq":
            template = next(mcq_cycle)
            q_text = template.format(name=name)
            distractors = random.sample(
                [w for w in keywords if w != kw] or ["theory", "method", "process"],
                k=min(3, max(1, len(set(keywords)) - 1)) or 1,
            )
            options = list(dict.fromkeys(distractors + [kw]))  # dedupe, keep order
            random.shuffle(options)
            key = (q_text, kw)
            if key in seen_questions:
                continue
            seen_questions.add(key)
            questions.append({"type": "mcq", "question": q_text, "options": options, "answer": kw})

        elif qtype == "truefalse":
            make_true = len(questions) % 2 == 0  # alternate so it's not all-true or all-false
            template = next(tf_true_cycle) if make_true else next(tf_false_cycle)
            stmt = template.format(kw=kw, name=name)
            if stmt in seen_questions:
                continue
            seen_questions.add(stmt)
            questions.append({"type": "truefalse", "question": stmt, "answer": make_true})

        elif qtype == "fillblank":
            sent = next(sent_cycle) if sent_cycle else f"_____ is an important concept in {name}."
            blanked = re.sub(rf"\b{re.escape(kw)}\b", "_____", sent, flags=re.IGNORECASE, count=1)
            if blanked == sent:
                blanked = f"_____ is a key idea within {name}."
            if blanked in seen_questions:
                continue
            seen_questions.add(blanked)
            questions.append({"type": "fillblank", "question": blanked, "answer": kw})

        else:  # subjective
            template = next(subj_cycle)
            q_text = template.format(kw=kw, name=name)
            if q_text in seen_questions:
                continue
            seen_questions.add(q_text)
            questions.append({"type": "subjective", "question": q_text, "answer": kw})

    note = None
    if not topic.get("notes"):
        note = ("This topic has no notes yet, so questions are generated from its name only. "
                "Add notes to the topic (or use a recognized subject like DSA, Java, C, C++, AI, "
                "ML, Data Science, or Cybersecurity) for richer, curated questions.")

    return {"topic": name, "domain": None, "source": "generated", "note": note, "questions": questions}


# ============================================================= FLASHCARDS ==
def generate_flashcards(topic):
    corpus = _topic_corpus(topic)
    sentences = _split_sentences(corpus)
    keywords = extract_keywords(corpus, 8)
    cards = []

    if sentences:
        for kw in keywords:
            match = next((s for s in sentences if kw in s.lower()), None)
            if match:
                cards.append({"front": kw.capitalize(), "back": match})
    if not cards:
        cards.append({
            "front": topic.get("name", "Topic"),
            "back": topic.get("notes") or f"Review the core idea of {topic.get('name')}.",
        })
    return cards[:10]


# ============================================================== AI TUTOR ===
GREETINGS = ("hi", "hello", "hey", "namaste")


def tutor_answer(message, mode, topics_context):
    msg = message.strip()
    lower = msg.lower()

    if any(lower.startswith(g) for g in GREETINGS):
        return "Hey! I'm your AI study tutor. Ask me to explain a concept, solve a problem, or just say 'quiz me on <topic>'."

    # try to find a matching topic for grounded context (word-overlap match,
    # not just exact substring, so "explain linked list" still finds a topic
    # named "Singly Linked List")
    matched = None
    msg_words = set(_tokenize(msg))
    best_overlap = 0
    for t in topics_context:
        if t["name"].lower() in lower:
            matched = t
            break
        topic_words = set(_tokenize(t["name"]))
        overlap = len(msg_words & topic_words)
        if overlap > best_overlap:
            best_overlap = overlap
            matched = t
    if best_overlap == 0 and matched and matched["name"].lower() not in lower:
        matched = None

    base = ""
    if matched and matched.get("notes"):
        base = summarize_text(matched["notes"], "short")
    elif matched:
        base = f"'{matched['name']}' is part of {matched.get('chapter_name','')} in {matched.get('subject_name','')}."

    explanation = base or _generic_explainer(msg)

    if mode == "eli5":
        return _simplify(explanation, msg)
    elif mode == "professor":
        return _formalize(explanation, msg)
    return explanation


def _generic_explainer(msg):
    if "solve" in msg.lower() or re.search(r"\d+\s*[\+\-\*/]\s*\d+", msg):
        result = _try_solve_math(msg)
        if result is not None:
            return f"Working through it step by step: {result}"
    return (f"Here's a general breakdown of '{msg.strip('?. ')}': start with the definition, "
            f"identify the key components, then connect it back to what you've already studied. "
            f"Add this topic with some notes and I can give you a grounded, detailed explanation.")


def _try_solve_math(msg):
    try:
        expr = re.sub(r"[^0-9\.\+\-\*/\(\) ]", "", msg)
        if not expr.strip():
            return None
        # safe eval: only digits and arithmetic operators reach here
        value = eval(expr, {"__builtins__": {}})
        return f"{expr.strip()} = {value}"
    except Exception:
        return None


def _simplify(text, topic):
    return (f"Imagine you're explaining '{topic.strip('?. ')}' to a curious 5-year-old: "
            f"think of it like a simple everyday example — small pieces building up to something bigger. "
            f"In short: {text[:220]}")


def _formalize(text, topic):
    return (f"From a formal standpoint, '{topic.strip('?. ')}' can be examined through its underlying "
            f"principles and their theoretical implications. {text} "
            f"Consider how this connects to broader frameworks in the subject.")


# ====================================================== EXAM PREDICTION ===
def predict_exam_readiness(topics, quiz_history):
    if not topics:
        return {"readiness_score": 0, "status": "No data", "confidence": 0, "advice": "Add topics to get a readiness score."}

    total = len(topics)
    completed = sum(1 for t in topics if t.get("completed"))
    completion_ratio = completed / total if total else 0

    if quiz_history:
        avg_quiz = sum(q["score"] / q["total"] for q in quiz_history if q.get("total")) / max(len(quiz_history), 1)
    else:
        avg_quiz = 0.5  # neutral prior when no quiz data yet

    high_priority_pending = sum(1 for t in topics if not t.get("completed") and t.get("priority") == "High")
    urgency_penalty = min(high_priority_pending * 0.05, 0.3)

    score = (completion_ratio * 0.5 + avg_quiz * 0.4) * 100 - urgency_penalty * 100
    score = max(0, min(100, round(score, 1)))

    if score >= 80:
        status = "Ready"
    elif score >= 60:
        status = "Almost Ready"
    elif score >= 35:
        status = "Needs Revision"
    else:
        status = "High Risk"

    advice = []
    if completion_ratio < 0.6:
        advice.append("Cover more pending topics — completion is under 60%.")
    if avg_quiz < 0.6:
        advice.append("Quiz scores suggest revisiting weaker topics before moving on.")
    if high_priority_pending:
        advice.append(f"{high_priority_pending} high-priority topic(s) are still pending — tackle these first.")
    if not advice:
        advice.append("You're on track. Keep up the spaced revision.")

    return {
        "readiness_score": score,
        "status": status,
        "confidence": round(min(95, 40 + total * 3), 1),
        "advice": advice,
    }


def detect_burnout(sessions):
    if not sessions:
        return {"status": "insufficient_data", "message": "Not enough recent activity to assess study load."}

    minutes = [s["minutes"] or 0 for s in sessions]
    avg = sum(minutes) / len(minutes)
    high_load_days = sum(1 for m in minutes if m > 240)
    zero_days = sum(1 for m in minutes if m == 0)

    if high_load_days >= 3:
        return {
            "status": "over-studying",
            "message": "You've had several 4+ hour study days recently. Consider scheduled breaks to avoid burnout.",
            "recommend_rest": True,
        }
    if zero_days >= 5:
        return {
            "status": "low-productivity",
            "message": "Study activity has been low the past days. A short, focused session can help rebuild momentum.",
            "recommend_rest": False,
        }
    return {
        "status": "balanced",
        "message": f"Study load looks balanced (avg ~{int(avg)} min/day). Keep the consistency going.",
        "recommend_rest": False,
    }


# ============================================================ NOTES GEN ===
def generate_notes(text, style="bullet"):
    if not text.strip():
        return "No content provided."
    sentences = _split_sentences(text)
    keywords = extract_keywords(text, 10)

    if style == "bullet":
        top_sentences = sorted(sentences, key=lambda s: -sum(1 for k in keywords if k in s.lower()))[:8]
        return "\n".join(f"• {s}" for s in top_sentences) or "• " + text[:200]

    if style == "cheatsheet":
        # Give each keyword its own *unique* supporting sentence where
        # possible instead of repeating the same sentence for every
        # keyword that happens to come from it — on short source text,
        # several keywords often share one sentence, and reusing it
        # verbatim for each line just produces a wall of duplicates.
        used_sentences = set()
        lines = []
        for kw in keywords:
            match = next((s for s in sentences if kw in s.lower() and s not in used_sentences), None)
            if match:
                used_sentences.add(match)
                lines.append(f"- {kw.capitalize()}: {match}")
            else:
                lines.append(f"- {kw.capitalize()}: key term in this material")
        return "\n".join(lines)

    if style == "mindmap":
        center = keywords[0].capitalize() if keywords else "Topic"
        branches = keywords[1:8]
        lines = [f"[{center}]"]
        for b in branches:
            lines.append(f"  └── {b}")
        return "\n".join(lines)

    return summarize_text(text, "medium")
