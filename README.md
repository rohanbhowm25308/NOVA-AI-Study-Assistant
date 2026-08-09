# NOVA — AI Study Assistant

An AI-powered study companion: add subjects/topics, get an AI-generated study
schedule, quiz yourself, generate flashcards, chat with an AI tutor, summarize
PDFs, auto-generate notes, and see exam-readiness predictions — all running
locally, no API key required.

Built to match the "Project: AI Study Assistant" brief (core CRUD + AI
schedule + quiz + progress tracking, **Advanced** tier: real NLP/ML logic,
SQLite database, Flask REST API, AI-generated plans) plus a first slice of
the bigger feature list (AI Tutor, PDF Learning Assistant, Flashcards, Notes
Generator, Analytics Dashboard, Exam Readiness / Burnout insights).

## Tech stack
- **Backend:** Python, Flask (REST API), SQLite (no external DB server needed)
- **AI/NLP:** hand-rolled, dependency-light algorithms — frequency-based
  extractive summarization, keyword extraction, weighted-priority scheduler,
  retrieval-style QA/tutor, rule-based exam-readiness & burnout scoring
- **Frontend:** vanilla HTML/CSS/JS single-page app, Chart.js for graphs
- **PDF parsing:** PyMuPDF → pdfplumber → PyPDF2 fallback chain, plus OCR (Tesseract) for scanned/image-only pages

## Run it locally

```bash
cd study_assistant
python3 -m venv venv && source venv/bin/activate   # optional but recommended
pip install -r requirements.txt
python app.py
```

Then open **http://localhost:5000** in your browser. The SQLite database
(`study_assistant.db`) is created automatically on first run — and if you're
upgrading from an older copy of this project, your existing subjects,
topics, and progress are preserved automatically (the app adds any new
columns it needs on startup rather than requiring a fresh database).

### Optional: OCR for scanned PDFs

PDF Lab and the Notes Generator can read normal (text-based) PDFs out of
the box with no extra setup. If you also want to handle **scanned or
photographed** PDF pages (no real text layer at all), install the
Tesseract OCR engine — this is a separate one-time system install, not a
pip package:

- **Windows:** install from https://github.com/UB-Mannheim/tesseract/wiki
- **macOS:** `brew install tesseract`
- **Linux:** `sudo apt install tesseract-ocr`

Without it, everything else still works fine — you'll just get a clear
message if you upload a scanned PDF instead of a silent failure.

## What's implemented (v1)

| Module | Features |
|---|---|
| **Topics** | Subjects → Chapters → Topics, priority, difficulty, estimated time, deadlines, notes, edit/delete, mark complete |
| **AI Schedule** | Weighted algorithm (priority × difficulty × deadline urgency) packs topics into daily study blocks up to each deadline |
| **AI Tutor** | Chat with grounded answers pulled from your own topic notes, plus ELI5 / Normal / Professor explanation modes and basic arithmetic solving |
| **Quiz Generator** | Auto-generates MCQ / True-False / Fill-in-the-blank / Subjective questions from a topic's notes using keyword extraction, scored instantly |
| **Flashcards** | Auto-generated term/definition cards from topic notes, flip-to-reveal UI, favorites |
| **PDF Lab** | Upload a PDF → AI summary, keyword extraction, ask-a-question over the document. Uses a 3-library fallback chain (PyMuPDF → pdfplumber → PyPDF2) so exports from PowerPoint/Canva/Google Docs/Notion — which regularly break single-library extractors — still work, plus automatic OCR for scanned/photographed pages |
| **Notes Generator** | Paste text, or upload a PDF directly, → bullet notes / cheat sheet / mind-map outline (PDF path reuses the same extraction + OCR pipeline as PDF Lab) |
| **Dashboard** | Progress ring, subject/priority charts, upcoming deadlines, study streak |
| **AI Insights** | Exam readiness score + status (Ready/Almost Ready/Needs Revision/High Risk) with advice, and a burnout heuristic over recent study load |

## Roadmap (from your full feature list)

The feature document you shared covers 31 categories — Voice AI, OCR notes
scanning, Google Calendar sync, gamification (XP/badges/leaderboards), study
groups, multilingual support, mind-map visual generator, and more. These are
natural v2+ additions on top of this same Flask + SQLite foundation:

- Swap the rule-based AI Tutor / summarizer for a real LLM call (e.g. the
  Anthropic API) — `ai_engine.py` is structured so `tutor_answer()` and
  `summarize_text()` can be replaced with an API-backed version without
  touching the rest of the app.
- Add OCR (`pytesseract`) for handwritten notes scanning.
- Add `scikit-learn` for a proper difficulty/marks prediction model once
  you have enough quiz history to train on.
- Add gamification tables (XP, badges) — the schema pattern in `database.py`
  extends easily.
- Add user accounts (Flask-Login) if this becomes multi-user.

## Project structure

```
study_assistant/
  app.py            # Flask routes (REST API + page route)
  database.py        # SQLite schema + all data access functions
  ai_engine.py        # All "AI" logic: scheduling, NLP, quiz/flashcard/notes generation, tutor, predictions
  requirements.txt
  templates/
    index.html        # Single-page app shell
  static/
    css/style.css      # Dark holographic theme
    js/app.js           # Frontend logic, wires UI to the API
```

## About

NOVA is an AI/ML-powered study companion — Python and Flask on the backend,
with NLP-driven summarization and keyword extraction, a weighted adaptive
scheduling engine, a curated-domain quiz generator, and predictive analytics
for exam-readiness and burnout scoring.

**Developed by Rohan Bhowmik** — aspiring AI/ML, Data Science & Web Development.

- GitHub: [github.com/rohanbhowm25308](https://github.com/rohanbhowm25308)
- LinkedIn: [linkedin.com/in/rohan-bhowmik-b014473a](https://www.linkedin.com/in/rohan-bhowmik-b014473a1)
- Instagram: [@rohan_._.bhowmik.84](https://www.instagram.com/rohan_._.bhowmik.84/)
