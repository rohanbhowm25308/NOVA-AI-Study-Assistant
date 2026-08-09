"""
AI Study Assistant - Smart Learning Companion
Flask backend serving a REST API + single-page frontend.
"""
import os
import io
from datetime import datetime, date
from flask import Flask, request, jsonify, render_template, send_from_directory

import database as db
import ai_engine as ai

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20MB

db.init_db()

# ---------------------------------------------------------------- pages ----
@app.route("/")
def index():
    return render_template("index.html")


# ------------------------------------------------------------- subjects ----
@app.route("/api/subjects", methods=["GET", "POST"])
def subjects():
    if request.method == "POST":
        data = request.get_json(force=True)
        sid = db.add_subject(data["name"], data.get("color", "#4da3ff"))
        return jsonify({"id": sid}), 201
    return jsonify(db.get_subjects())


@app.route("/api/subjects/<int:subject_id>", methods=["DELETE"])
def delete_subject(subject_id):
    db.delete_subject(subject_id)
    return jsonify({"ok": True})


# ------------------------------------------------------------- chapters ----
@app.route("/api/chapters", methods=["GET", "POST"])
def chapters():
    if request.method == "POST":
        data = request.get_json(force=True)
        cid = db.add_chapter(data["subject_id"], data["name"])
        return jsonify({"id": cid}), 201
    subject_id = request.args.get("subject_id", type=int)
    return jsonify(db.get_chapters(subject_id))


@app.route("/api/chapters/<int:chapter_id>", methods=["DELETE"])
def delete_chapter(chapter_id):
    db.delete_chapter(chapter_id)
    return jsonify({"ok": True})


# --------------------------------------------------------------- topics ----
@app.route("/api/topics", methods=["GET", "POST"])
def topics():
    if request.method == "POST":
        data = request.get_json(force=True)
        tid = db.add_topic(
            chapter_id=data["chapter_id"],
            name=data["name"],
            priority=data.get("priority", "Medium"),
            difficulty=data.get("difficulty", "Medium"),
            estimated_time=data.get("estimated_time", 60),
            deadline=data.get("deadline"),
            notes=data.get("notes", ""),
        )
        return jsonify({"id": tid}), 201
    chapter_id = request.args.get("chapter_id", type=int)
    return jsonify(db.get_topics(chapter_id))


@app.route("/api/topics/<int:topic_id>", methods=["PUT", "DELETE"])
def topic_detail(topic_id):
    if request.method == "DELETE":
        db.delete_topic(topic_id)
        return jsonify({"ok": True})
    data = request.get_json(force=True)
    db.update_topic(topic_id, data)
    return jsonify({"ok": True})


@app.route("/api/topics/<int:topic_id>/complete", methods=["POST"])
def complete_topic(topic_id):
    db.set_topic_completed(topic_id, request.get_json(force=True).get("completed", True))
    db.touch_streak()
    return jsonify({"ok": True})


# ------------------------------------------------------------- schedule ----
@app.route("/api/schedule/generate", methods=["POST"])
def generate_schedule():
    data = request.get_json(force=True)
    daily_minutes = data.get("daily_minutes", 120)
    topics_list = db.get_all_incomplete_topics()
    plan = ai.generate_schedule(topics_list, daily_minutes)
    db.save_schedule(plan)
    return jsonify(plan)


@app.route("/api/schedule", methods=["GET"])
def get_schedule():
    return jsonify(db.get_schedule())


# ---------------------------------------------------------------- quiz -----
@app.route("/api/quiz/generate", methods=["POST"])
def generate_quiz():
    data = request.get_json(force=True)
    topic_id = data["topic_id"]
    num_q = data.get("num_questions", 10)
    qtype = data.get("type", "mcq")
    topic = db.get_topic(topic_id)
    quiz = ai.generate_quiz(topic, num_q, qtype)
    return jsonify(quiz)


@app.route("/api/quiz/submit", methods=["POST"])
def submit_quiz():
    data = request.get_json(force=True)
    db.save_quiz_result(data["topic_id"], data["score"], data["total"])
    return jsonify({"ok": True})


@app.route("/api/quiz/history", methods=["GET"])
def quiz_history():
    return jsonify(db.get_quiz_history())


# ----------------------------------------------------------- flashcards ----
@app.route("/api/flashcards", methods=["GET", "POST"])
def flashcards():
    if request.method == "POST":
        data = request.get_json(force=True)
        fid = db.add_flashcard(data["topic_id"], data["front"], data["back"])
        return jsonify({"id": fid}), 201
    topic_id = request.args.get("topic_id", type=int)
    return jsonify(db.get_flashcards(topic_id))


@app.route("/api/flashcards/generate", methods=["POST"])
def generate_flashcards():
    data = request.get_json(force=True)
    topic = db.get_topic(data["topic_id"])
    cards = ai.generate_flashcards(topic)
    for c in cards:
        db.add_flashcard(topic["id"], c["front"], c["back"])
    return jsonify(cards)


@app.route("/api/flashcards/<int:card_id>/favorite", methods=["POST"])
def favorite_flashcard(card_id):
    db.toggle_flashcard_favorite(card_id)
    return jsonify({"ok": True})


@app.route("/api/flashcards/<int:card_id>", methods=["DELETE"])
def delete_flashcard(card_id):
    db.delete_flashcard(card_id)
    return jsonify({"ok": True})


# ------------------------------------------------------------- ai tutor ----
@app.route("/api/tutor/ask", methods=["POST"])
def tutor_ask():
    data = request.get_json(force=True)
    message = data["message"]
    mode = data.get("mode", "normal")  # normal | eli5 | professor
    reply = ai.tutor_answer(message, mode, db.get_all_topics_flat())
    db.save_chat("user", message)
    db.save_chat("ai", reply)
    return jsonify({"reply": reply})


@app.route("/api/tutor/history", methods=["GET"])
def tutor_history():
    return jsonify(db.get_chat_history())


# -------------------------------------------------------------- pdf lab ----
@app.route("/api/pdf/upload", methods=["POST"])
def pdf_upload():
    f = request.files["file"]
    path = os.path.join(UPLOAD_DIR, f.filename)
    f.save(path)
    result = ai.extract_pdf_text(path)
    pdf_id = db.save_pdf(
        f.filename, result["text"], result["method"], result.get("pages", 0),
        result.get("reason"),
    )
    return jsonify({
        "id": pdf_id,
        "filename": f.filename,
        "chars": len(result["text"]),
        "method": result["method"],
        "pages": result.get("pages", 0),
        "ocr_available": result.get("ocr_available", False),
        "reason": result.get("reason"),
    })


@app.route("/api/pdf/<int:pdf_id>/summary", methods=["GET"])
def pdf_summary(pdf_id):
    length = request.args.get("length", "medium")
    record = db.get_pdf(pdf_id)
    if not record or not record.get("content") or len(record["content"].strip()) < 30:
        return jsonify({
            "summary": None,
            "keywords": [],
            "error": record.get("extraction_note") if record else None,
        })
    summary = ai.summarize_text(record["content"], length)
    keywords = ai.extract_keywords(record["content"], 12)
    return jsonify({"summary": summary, "keywords": keywords})


@app.route("/api/pdf/<int:pdf_id>/ask", methods=["POST"])
def pdf_ask(pdf_id):
    question = request.get_json(force=True)["question"]
    record = db.get_pdf(pdf_id)
    if not record or not record.get("content") or len(record["content"].strip()) < 30:
        return jsonify({"answer": "There's no readable text from this PDF to search — see the note above about why extraction didn't find any."})
    answer = ai.answer_from_text(question, record["content"])
    return jsonify({"answer": answer})


@app.route("/api/pdf", methods=["GET"])
def pdf_list():
    return jsonify(db.get_pdfs())


@app.route("/api/pdf/<int:pdf_id>", methods=["DELETE"])
def pdf_delete(pdf_id):
    db.delete_pdf(pdf_id)
    return jsonify({"ok": True})


# -------------------------------------------------------------- notes ------
@app.route("/api/notes/generate", methods=["POST"])
def notes_generate():
    data = request.get_json(force=True)
    source_text = data.get("text", "")
    style = data.get("style", "bullet")  # bullet | mindmap | cheatsheet
    notes = ai.generate_notes(source_text, style)
    nid = db.save_notes(data.get("topic_id"), data.get("title", "Untitled"), notes, style)
    return jsonify({"id": nid, "notes": notes})


@app.route("/api/notes/generate-from-file", methods=["POST"])
def notes_generate_from_file():
    """Same as /api/notes/generate but the source text comes from an
    uploaded PDF instead of pasted text — reuses the same robust
    (PyMuPDF -> pdfplumber -> PyPDF2 -> OCR) extraction pipeline as PDF Lab
    so scanned/awkwardly-encoded PDFs work here too, not just plain text."""
    f = request.files["file"]
    style = request.form.get("style", "bullet")
    path = os.path.join(UPLOAD_DIR, f.filename)
    f.save(path)
    result = ai.extract_pdf_text(path)
    if len(result["text"].strip()) < 30:
        return jsonify({
            "error": result.get("reason", "Couldn't extract readable text from this file."),
            "ocr_available": result.get("ocr_available", False),
        }), 422
    notes = ai.generate_notes(result["text"], style)
    title = os.path.splitext(f.filename)[0]
    nid = db.save_notes(None, title, notes, style, source_filename=f.filename)
    return jsonify({"id": nid, "notes": notes, "title": title, "method": result["method"]})


@app.route("/api/notes", methods=["GET"])
def notes_list():
    return jsonify(db.get_notes())


@app.route("/api/notes/<int:note_id>", methods=["DELETE"])
def delete_note(note_id):
    db.delete_notes(note_id)
    return jsonify({"ok": True})


# ---------------------------------------------------------- analytics ------
@app.route("/api/analytics/dashboard", methods=["GET"])
def analytics_dashboard():
    return jsonify(db.get_dashboard_stats())


@app.route("/api/analytics/prediction", methods=["GET"])
def analytics_prediction():
    topics_list = db.get_all_topics_flat()
    quiz_hist = db.get_quiz_history()
    return jsonify(ai.predict_exam_readiness(topics_list, quiz_hist))


@app.route("/api/analytics/burnout", methods=["GET"])
def analytics_burnout():
    sessions = db.get_recent_study_activity()
    return jsonify(ai.detect_burnout(sessions))


if __name__ == "__main__":
    # debug=True must never run in production — it exposes Werkzeug's
    # interactive debugger, which allows arbitrary code execution if the
    # port is ever reachable publicly. Render (and gunicorn generally)
    # doesn't invoke this block at all — gunicorn imports the `app` object
    # directly — but it's gated here too in case this is ever run directly.
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=debug_mode, host="0.0.0.0", port=port)
