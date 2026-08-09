"""
SQLite data access layer for AI Study Assistant.
Uses plain sqlite3 (no ORM) to keep the project dependency-light.
"""
import sqlite3
import os
from datetime import date, datetime, timedelta

# Configurable via the DB_PATH env var so a persistent disk (or any other
# mount point) can be used in production without touching code — e.g. on
# Render, set DB_PATH=/var/data/study_assistant.db once a disk is attached.
# Falls back to a local file next to this script for local development.
DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "study_assistant.db"),
)
# Make sure the target directory exists (matters if DB_PATH points at a
# freshly-mounted disk path like /var/data/study_assistant.db).
os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            color TEXT DEFAULT '#4da3ff'
        );

        CREATE TABLE IF NOT EXISTS chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            priority TEXT DEFAULT 'Medium',
            difficulty TEXT DEFAULT 'Medium',
            estimated_time INTEGER DEFAULT 60,
            deadline TEXT,
            notes TEXT DEFAULT '',
            completed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            session_date TEXT NOT NULL,
            duration_minutes INTEGER,
            status TEXT DEFAULT 'planned',
            FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS quiz_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER,
            score INTEGER,
            total INTEGER,
            taken_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS flashcards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            front TEXT NOT NULL,
            back TEXT NOT NULL,
            favorite INTEGER DEFAULT 0,
            FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            message TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS pdfs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            content TEXT,
            extraction_method TEXT,
            page_count INTEGER,
            extraction_note TEXT,
            uploaded_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER,
            title TEXT,
            content TEXT,
            style TEXT,
            source_filename TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS streak (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            current_streak INTEGER DEFAULT 0,
            last_active_date TEXT
        );
        """
    )
    # Lightweight migration for people upgrading an existing local database
    # (created before these columns existed) — add whatever's missing
    # instead of requiring them to delete their saved subjects/topics/progress.
    existing_pdf_cols = {row["name"] for row in c.execute("PRAGMA table_info(pdfs)").fetchall()}
    if "extraction_method" not in existing_pdf_cols:
        c.execute("ALTER TABLE pdfs ADD COLUMN extraction_method TEXT")
    if "page_count" not in existing_pdf_cols:
        c.execute("ALTER TABLE pdfs ADD COLUMN page_count INTEGER")
    if "extraction_note" not in existing_pdf_cols:
        c.execute("ALTER TABLE pdfs ADD COLUMN extraction_note TEXT")
    existing_notes_cols = {row["name"] for row in c.execute("PRAGMA table_info(notes)").fetchall()}
    if "source_filename" not in existing_notes_cols:
        c.execute("ALTER TABLE notes ADD COLUMN source_filename TEXT")

    c.execute("INSERT OR IGNORE INTO streak (id, current_streak, last_active_date) VALUES (1, 0, NULL)")
    conn.commit()
    conn.close()


# ------------------------------------------------------------- subjects ----
def add_subject(name, color):
    conn = get_conn()
    cur = conn.execute("INSERT INTO subjects (name, color) VALUES (?, ?)", (name, color))
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def get_subjects():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM subjects ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_subject(subject_id):
    conn = get_conn()
    conn.execute("DELETE FROM subjects WHERE id=?", (subject_id,))
    conn.commit()
    conn.close()


# ------------------------------------------------------------- chapters ----
def add_chapter(subject_id, name):
    conn = get_conn()
    cur = conn.execute("INSERT INTO chapters (subject_id, name) VALUES (?, ?)", (subject_id, name))
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    return cid


def get_chapters(subject_id=None):
    conn = get_conn()
    if subject_id:
        rows = conn.execute("SELECT * FROM chapters WHERE subject_id=? ORDER BY id", (subject_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM chapters ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_chapter(chapter_id):
    conn = get_conn()
    conn.execute("DELETE FROM chapters WHERE id=?", (chapter_id,))
    conn.commit()
    conn.close()


# --------------------------------------------------------------- topics ----
def add_topic(chapter_id, name, priority, difficulty, estimated_time, deadline, notes):
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO topics (chapter_id, name, priority, difficulty, estimated_time, deadline, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (chapter_id, name, priority, difficulty, estimated_time, deadline, notes),
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


def get_topics(chapter_id=None):
    conn = get_conn()
    if chapter_id:
        rows = conn.execute("SELECT * FROM topics WHERE chapter_id=? ORDER BY id", (chapter_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM topics ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_topic(topic_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_topics_flat():
    """Topics joined with chapter & subject names, for AI context."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT t.*, c.name as chapter_name, s.name as subject_name
           FROM topics t
           JOIN chapters c ON t.chapter_id = c.id
           JOIN subjects s ON c.subject_id = s.id
           ORDER BY t.id"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_incomplete_topics():
    conn = get_conn()
    rows = conn.execute(
        """SELECT t.*, c.name as chapter_name, s.name as subject_name
           FROM topics t
           JOIN chapters c ON t.chapter_id = c.id
           JOIN subjects s ON c.subject_id = s.id
           WHERE t.completed = 0
           ORDER BY t.id"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_topic(topic_id, data):
    allowed = ["name", "priority", "difficulty", "estimated_time", "deadline", "notes"]
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return
    conn = get_conn()
    set_clause = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE topics SET {set_clause} WHERE id=?", (*fields.values(), topic_id))
    conn.commit()
    conn.close()


def set_topic_completed(topic_id, completed):
    conn = get_conn()
    conn.execute("UPDATE topics SET completed=? WHERE id=?", (1 if completed else 0, topic_id))
    conn.commit()
    conn.close()


def delete_topic(topic_id):
    conn = get_conn()
    conn.execute("DELETE FROM topics WHERE id=?", (topic_id,))
    conn.commit()
    conn.close()


# ------------------------------------------------------------- schedule ----
def save_schedule(plan):
    conn = get_conn()
    conn.execute("DELETE FROM schedule")
    for day in plan:
        for item in day["items"]:
            status = "overflow" if item.get("overflow") else "planned"
            conn.execute(
                "INSERT INTO schedule (topic_id, session_date, duration_minutes, status) VALUES (?, ?, ?, ?)",
                (item["topic_id"], day["date"], item["duration"], status),
            )
    conn.commit()
    conn.close()


def get_schedule():
    conn = get_conn()
    rows = conn.execute(
        """SELECT sch.*, t.name as topic_name, s.name as subject_name
           FROM schedule sch
           JOIN topics t ON sch.topic_id = t.id
           JOIN chapters c ON t.chapter_id = c.id
           JOIN subjects s ON c.subject_id = s.id
           ORDER BY sch.session_date"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- quiz -----
def save_quiz_result(topic_id, score, total):
    conn = get_conn()
    conn.execute("INSERT INTO quiz_results (topic_id, score, total) VALUES (?, ?, ?)", (topic_id, score, total))
    conn.commit()
    conn.close()


def get_quiz_history():
    conn = get_conn()
    rows = conn.execute(
        """SELECT q.*, t.name as topic_name FROM quiz_results q
           LEFT JOIN topics t ON q.topic_id = t.id
           ORDER BY q.taken_at DESC LIMIT 50"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ----------------------------------------------------------- flashcards ----
def add_flashcard(topic_id, front, back):
    conn = get_conn()
    cur = conn.execute("INSERT INTO flashcards (topic_id, front, back) VALUES (?, ?, ?)", (topic_id, front, back))
    conn.commit()
    fid = cur.lastrowid
    conn.close()
    return fid


def get_flashcards(topic_id=None):
    conn = get_conn()
    if topic_id:
        rows = conn.execute("SELECT * FROM flashcards WHERE topic_id=? ORDER BY id", (topic_id,)).fetchall()
    else:
        rows = conn.execute(
            """SELECT f.*, t.name as topic_name FROM flashcards f
               JOIN topics t ON f.topic_id = t.id ORDER BY f.id"""
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def toggle_flashcard_favorite(card_id):
    conn = get_conn()
    conn.execute("UPDATE flashcards SET favorite = 1 - favorite WHERE id=?", (card_id,))
    conn.commit()
    conn.close()


def delete_flashcard(card_id):
    conn = get_conn()
    conn.execute("DELETE FROM flashcards WHERE id=?", (card_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- chat -----
def save_chat(sender, message):
    conn = get_conn()
    conn.execute("INSERT INTO chat_history (sender, message) VALUES (?, ?)", (sender, message))
    conn.commit()
    conn.close()


def get_chat_history():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM chat_history ORDER BY id ASC LIMIT 200").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- pdfs -----
def save_pdf(filename, content, extraction_method=None, page_count=None, extraction_note=None):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO pdfs (filename, content, extraction_method, page_count, extraction_note) VALUES (?, ?, ?, ?, ?)",
        (filename, content, extraction_method, page_count, extraction_note),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def get_pdf(pdf_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM pdfs WHERE id=?", (pdf_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_pdfs():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, filename, extraction_method, page_count, uploaded_at FROM pdfs ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_pdf(pdf_id):
    conn = get_conn()
    conn.execute("DELETE FROM pdfs WHERE id=?", (pdf_id,))
    conn.commit()
    conn.close()


# --------------------------------------------------------------- notes -----
def save_notes(topic_id, title, content, style, source_filename=None):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO notes (topic_id, title, content, style, source_filename) VALUES (?, ?, ?, ?, ?)",
        (topic_id, title, content, style, source_filename),
    )
    conn.commit()
    nid = cur.lastrowid
    conn.close()
    return nid


def get_notes():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM notes ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_notes(note_id):
    conn = get_conn()
    conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
    conn.commit()
    conn.close()


# ------------------------------------------------------------- streak ------
def touch_streak():
    conn = get_conn()
    row = conn.execute("SELECT * FROM streak WHERE id=1").fetchone()
    today = date.today().isoformat()
    if row["last_active_date"] == today:
        conn.close()
        return
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    new_streak = (row["current_streak"] + 1) if row["last_active_date"] == yesterday else 1
    conn.execute("UPDATE streak SET current_streak=?, last_active_date=? WHERE id=1", (new_streak, today))
    conn.commit()
    conn.close()


def get_streak():
    conn = get_conn()
    row = conn.execute("SELECT * FROM streak WHERE id=1").fetchone()
    conn.close()
    return dict(row) if row else {"current_streak": 0, "last_active_date": None}


# ---------------------------------------------------------- dashboard ------
def get_dashboard_stats():
    conn = get_conn()
    total_topics = conn.execute("SELECT COUNT(*) c FROM topics").fetchone()["c"]
    completed_topics = conn.execute("SELECT COUNT(*) c FROM topics WHERE completed=1").fetchone()["c"]
    total_subjects = conn.execute("SELECT COUNT(*) c FROM subjects").fetchone()["c"]
    upcoming = conn.execute(
        """SELECT t.name, t.deadline, s.name as subject_name FROM topics t
           JOIN chapters c ON t.chapter_id = c.id
           JOIN subjects s ON c.subject_id = s.id
           WHERE t.completed = 0 AND t.deadline IS NOT NULL AND t.deadline != ''
           ORDER BY t.deadline ASC LIMIT 5"""
    ).fetchall()
    quiz_avg = conn.execute(
        "SELECT AVG(1.0*score/total) a FROM quiz_results WHERE total > 0"
    ).fetchone()["a"]
    subject_progress = conn.execute(
        """SELECT s.name, s.color,
                  COUNT(t.id) as total,
                  SUM(CASE WHEN t.completed=1 THEN 1 ELSE 0 END) as done
           FROM subjects s
           LEFT JOIN chapters c ON c.subject_id = s.id
           LEFT JOIN topics t ON t.chapter_id = c.id
           GROUP BY s.id"""
    ).fetchall()
    priority_breakdown = conn.execute(
        "SELECT priority, COUNT(*) c FROM topics WHERE completed=0 GROUP BY priority"
    ).fetchall()
    conn.close()
    streak = get_streak()
    return {
        "total_topics": total_topics,
        "completed_topics": completed_topics,
        "total_subjects": total_subjects,
        "progress_pct": round(100 * completed_topics / total_topics, 1) if total_topics else 0,
        "upcoming_deadlines": [dict(r) for r in upcoming],
        "quiz_average_pct": round((quiz_avg or 0) * 100, 1),
        "subject_progress": [dict(r) for r in subject_progress],
        "priority_breakdown": [dict(r) for r in priority_breakdown],
        "streak": streak["current_streak"],
    }


def get_recent_study_activity():
    """Approximate 'study activity' from schedule + completions for burnout heuristics."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT session_date, SUM(duration_minutes) as minutes
           FROM schedule GROUP BY session_date ORDER BY session_date DESC LIMIT 14"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
