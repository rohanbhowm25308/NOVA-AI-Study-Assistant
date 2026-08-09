/* NOVA — AI Study Assistant frontend logic */

const api = {
  get: (url) => fetch(url).then(r => r.json()),
  post: (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) }).then(r => r.json()),
  put: (url, body) => fetch(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) }).then(r => r.json()),
  del: (url) => fetch(url, { method: "DELETE" }).then(r => r.json()),
};

let state = { subjects: [], chapters: [], topics: [], tutorMode: "normal" };

// ============================================================ NAV =========
document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});

function switchView(view) {
  document.querySelectorAll(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("active", v.id === `view-${view}`));
  const loaders = {
    dashboard: loadDashboard, topics: loadTopics, schedule: loadSchedule,
    quiz: loadQuizSetup, flashcards: loadFlashcardsSetup, notes: loadNotes,
    insights: loadInsights, pdf: loadPdfHistory,
  };
  if (loaders[view]) loaders[view]();
}

function closeModal() { document.getElementById("modalOverlay").classList.remove("active"); }
function openModal(html) {
  document.getElementById("modalBody").innerHTML = html;
  document.getElementById("modalOverlay").classList.add("active");
}
document.getElementById("modalOverlay").addEventListener("click", (e) => {
  if (e.target.id === "modalOverlay") closeModal();
});

// ============================================================ DASHBOARD ===
let subjectChart, priorityChart;

async function loadDashboard() {
  const stats = await api.get("/api/analytics/dashboard");
  document.getElementById("statSubjects").textContent = stats.total_subjects;
  document.getElementById("statTopics").textContent = `${stats.completed_topics}/${stats.total_topics}`;
  document.getElementById("statQuiz").textContent = `${stats.quiz_average_pct}%`;
  document.getElementById("statStreak").textContent = `${stats.streak} days`;
  document.getElementById("streakCount").textContent = stats.streak;
  document.getElementById("progressPct").textContent = `${stats.progress_pct}%`;

  const ring = document.getElementById("progressRing");
  const circumference = 326.7;
  ring.style.strokeDashoffset = circumference - (circumference * stats.progress_pct / 100);

  const upcomingList = document.getElementById("upcomingList");
  upcomingList.innerHTML = stats.upcoming_deadlines.length
    ? stats.upcoming_deadlines.map(d => `
        <div class="list-item">
          <span>${d.name} <span style="color:var(--text-lo)">— ${d.subject_name}</span></span>
          <span class="hint">${d.deadline}</span>
        </div>`).join("")
    : `<p class="hint">No upcoming deadlines set.</p>`;

  const sp = stats.subject_progress;
  if (subjectChart) subjectChart.destroy();
  subjectChart = new Chart(document.getElementById("subjectChart"), {
    type: "bar",
    data: {
      labels: sp.map(s => s.name),
      datasets: [{
        label: "% complete",
        data: sp.map(s => s.total ? Math.round(100 * s.done / s.total) : 0),
        backgroundColor: sp.map(s => s.color || "#35d6ff"),
        borderRadius: 6,
      }],
    },
    options: chartBaseOptions({ y: { max: 100 } }),
  });

  const pb = stats.priority_breakdown;
  if (priorityChart) priorityChart.destroy();
  const colorMap = { High: "#ff6b7a", Medium: "#ffb84d", Low: "#38e6a8" };
  priorityChart = new Chart(document.getElementById("priorityChart"), {
    type: "doughnut",
    data: {
      labels: pb.map(p => p.priority),
      datasets: [{ data: pb.map(p => p.c), backgroundColor: pb.map(p => colorMap[p.priority] || "#4d7dff") }],
    },
    options: { plugins: { legend: { labels: { color: "#9fb3d1" } } } },
  });
}

function chartBaseOptions(scaleOverrides = {}) {
  return {
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { color: "#9fb3d1" }, grid: { color: "rgba(255,255,255,0.05)" } },
      y: { ticks: { color: "#9fb3d1" }, grid: { color: "rgba(255,255,255,0.05)" }, ...(scaleOverrides.y || {}) },
    },
  };
}

// ============================================================ TOPICS ======
async function loadTopics() {
  state.subjects = await api.get("/api/subjects");
  state.chapters = await api.get("/api/chapters");
  state.topics = await api.get("/api/topics");
  renderSubjects();
}

function renderSubjects() {
  const wrap = document.getElementById("subjectsWrap");
  if (!state.subjects.length) {
    wrap.innerHTML = `<div class="panel glass"><p class="hint">No subjects yet — click "+ New Subject" to start building your knowledge tree.</p></div>`;
    return;
  }
  wrap.innerHTML = state.subjects.map(s => {
    const chapters = state.chapters.filter(c => c.subject_id === s.id);
    return `
    <div class="subject-card glass">
      <div class="subject-head">
        <div class="subject-title"><span class="dot" style="background:${s.color};color:${s.color}"></span>${s.name}</div>
        <div class="row-inline">
          <button class="btn-ghost" onclick="addChapterPrompt(${s.id})">+ Chapter</button>
          <button class="btn-danger" onclick="removeSubject(${s.id})">Delete</button>
        </div>
      </div>
      ${chapters.map(c => renderChapter(c)).join("") || `<p class="hint">No chapters yet.</p>`}
    </div>`;
  }).join("");
}

function renderChapter(c) {
  const topics = state.topics.filter(t => t.chapter_id === c.id);
  return `
    <div class="chapter-block">
      <div class="chapter-title row-inline" style="justify-content:space-between;">
        <span>${c.name}</span>
        <button class="btn-ghost" style="padding:4px 10px;" onclick="addTopicPrompt(${c.id})">+ Topic</button>
      </div>
      ${topics.map(t => renderTopicRow(t)).join("") || `<p class="hint">No topics yet.</p>`}
    </div>`;
}

function renderTopicRow(t) {
  const tagClass = { High: "tag-high", Medium: "tag-medium", Low: "tag-low" }[t.priority] || "tag-medium";
  return `
    <div class="topic-row ${t.completed ? "completed" : ""}">
      <input type="checkbox" class="checkbox" ${t.completed ? "checked" : ""} onchange="toggleTopic(${t.id}, this.checked)">
      <span class="topic-name">${t.name}</span>
      <div class="topic-meta">
        <span class="tag ${tagClass}">${t.priority}</span>
        <span>${t.difficulty}</span>
        <span>${t.estimated_time}m</span>
        ${t.deadline ? `<span>⏰ ${t.deadline}</span>` : ""}
      </div>
      <button class="btn-danger" onclick="removeTopic(${t.id})">✕</button>
    </div>`;
}

document.getElementById("btnAddSubject").addEventListener("click", () => {
  openModal(`
    <h3>New Subject</h3>
    <div class="field"><label>Name</label><input id="mSubjectName" placeholder="e.g. Data Structures"></div>
    <div class="field"><label>Color</label><input type="color" id="mSubjectColor" value="#35d6ff"></div>
    <div class="modal-actions">
      <button class="btn-ghost" onclick="closeModal()">Cancel</button>
      <button class="btn-primary" onclick="submitSubject()">Create</button>
    </div>`);
});

async function submitSubject() {
  const name = document.getElementById("mSubjectName").value.trim();
  const color = document.getElementById("mSubjectColor").value;
  if (!name) return;
  await api.post("/api/subjects", { name, color });
  closeModal();
  loadTopics();
}

function addChapterPrompt(subjectId) {
  openModal(`
    <h3>New Chapter</h3>
    <div class="field"><label>Name</label><input id="mChapterName" placeholder="e.g. Linked Lists"></div>
    <div class="modal-actions">
      <button class="btn-ghost" onclick="closeModal()">Cancel</button>
      <button class="btn-primary" onclick="submitChapter(${subjectId})">Create</button>
    </div>`);
}
async function submitChapter(subjectId) {
  const name = document.getElementById("mChapterName").value.trim();
  if (!name) return;
  await api.post("/api/chapters", { subject_id: subjectId, name });
  closeModal();
  loadTopics();
}

function addTopicPrompt(chapterId) {
  openModal(`
    <h3>New Topic</h3>
    <div class="field"><label>Name</label><input id="mTopicName" placeholder="e.g. Reversing a Linked List"></div>
    <div class="field"><label>Priority</label>
      <select id="mTopicPriority"><option>High</option><option selected>Medium</option><option>Low</option></select>
    </div>
    <div class="field"><label>Difficulty</label>
      <select id="mTopicDifficulty"><option>Hard</option><option selected>Medium</option><option>Easy</option></select>
    </div>
    <div class="field"><label>Estimated time (minutes)</label><input type="number" id="mTopicTime" value="60"></div>
    <div class="field"><label>Deadline</label><input type="date" id="mTopicDeadline"></div>
    <div class="field"><label>Notes (used by AI for quizzes/flashcards)</label><textarea id="mTopicNotes" style="min-height:70px"></textarea></div>
    <div class="modal-actions">
      <button class="btn-ghost" onclick="closeModal()">Cancel</button>
      <button class="btn-primary" onclick="submitTopic(${chapterId})">Create</button>
    </div>`);
}
async function submitTopic(chapterId) {
  const name = document.getElementById("mTopicName").value.trim();
  if (!name) return;
  await api.post("/api/topics", {
    chapter_id: chapterId, name,
    priority: document.getElementById("mTopicPriority").value,
    difficulty: document.getElementById("mTopicDifficulty").value,
    estimated_time: parseInt(document.getElementById("mTopicTime").value || "60"),
    deadline: document.getElementById("mTopicDeadline").value || null,
    notes: document.getElementById("mTopicNotes").value,
  });
  closeModal();
  loadTopics();
}

async function toggleTopic(id, completed) {
  await api.post(`/api/topics/${id}/complete`, { completed });
  loadTopics();
}
async function removeTopic(id) { await api.del(`/api/topics/${id}`); loadTopics(); }
async function removeSubject(id) { await api.del(`/api/subjects/${id}`); loadTopics(); }

// ============================================================ SCHEDULE ====
async function loadSchedule() {
  const items = await api.get("/api/schedule");
  renderSchedule(items);
}
function renderSchedule(items, atRisk) {
  const wrap = document.getElementById("scheduleWrap");
  if (!items.length) {
    wrap.innerHTML = `<div class="panel glass"><p class="hint">No schedule yet. Add some topics, then click "Generate Plan".</p></div>`;
    return;
  }
  const byDay = {};
  items.forEach(i => { (byDay[i.session_date] = byDay[i.session_date] || []).push(i); });

  const riskBanner = (atRisk && atRisk.length)
    ? `<div class="quiz-source-banner quiz-source-note glass">⚠️ At your current daily-minutes setting, <strong>${atRisk.join(", ")}</strong> can't realistically be finished before its deadline — extra "catch-up" sessions were added after the deadline so nothing gets silently dropped. Consider raising min/day or moving the deadline.</div>`
    : "";

  wrap.innerHTML = riskBanner + Object.entries(byDay).map(([day, list]) => {
    const dayTotal = list.reduce((sum, i) => sum + i.duration_minutes, 0);
    return `
    <div class="schedule-day glass">
      <div class="schedule-day-head">${day} <span class="hint">· ${dayTotal} min total</span></div>
      ${list.map(i => `
        <div class="schedule-item">
          <span>${i.topic_name} <span class="hint">(${i.subject_name})</span>${i.status === "overflow" ? ` <span class="tag tag-high">catch-up · past deadline</span>` : ""}</span>
          <span class="hint">${i.duration_minutes} min</span>
        </div>`).join("")}
    </div>`;
  }).join("");
}

document.getElementById("btnGenSchedule").addEventListener("click", async () => {
  const daily_minutes = parseInt(document.getElementById("dailyMinutes").value || "120");
  const plan = await api.post("/api/schedule/generate", { daily_minutes });
  const atRisk = (plan && plan[0] && plan[0].at_risk) || [];
  const items = await api.get("/api/schedule");
  renderSchedule(items, atRisk);
});

// ============================================================ AI TUTOR ====
document.querySelectorAll(".mode-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".mode-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    state.tutorMode = btn.dataset.mode;
  });
});

async function loadTutorHistory() {
  const history = await api.get("/api/tutor/history");
  const log = document.getElementById("chatLog");
  if (!history.length) {
    log.innerHTML = `<div class="msg ai">Hi! I'm NOVA, your AI tutor. Ask me to explain a concept, solve a formula, or say "quiz me on &lt;topic&gt;".</div>`;
    return;
  }
  log.innerHTML = history.map(m => `<div class="msg ${m.sender === "user" ? "user" : "ai"}">${escapeHtml(m.message)}</div>`).join("");
  log.scrollTop = log.scrollHeight;
}

document.getElementById("btnSend").addEventListener("click", sendChat);
document.getElementById("chatInput").addEventListener("keydown", (e) => { if (e.key === "Enter") sendChat(); });

async function sendChat() {
  const input = document.getElementById("chatInput");
  const msg = input.value.trim();
  if (!msg) return;
  const log = document.getElementById("chatLog");
  log.insertAdjacentHTML("beforeend", `<div class="msg user">${escapeHtml(msg)}</div>`);
  input.value = "";
  log.scrollTop = log.scrollHeight;
  const res = await api.post("/api/tutor/ask", { message: msg, mode: state.tutorMode });
  log.insertAdjacentHTML("beforeend", `<div class="msg ai">${escapeHtml(res.reply)}</div>`);
  log.scrollTop = log.scrollHeight;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ============================================================ QUIZ ========
async function loadQuizSetup() {
  const topics = await api.get("/api/topics");
  const sel = document.getElementById("quizTopicSelect");
  const previous = sel.value;
  sel.innerHTML = topics.map(t => `<option value="${t.id}">${t.name}</option>`).join("") || `<option value="">No topics yet</option>`;
  if (topics.some(t => String(t.id) === previous)) sel.value = previous;
}

document.getElementById("btnGenQuiz").addEventListener("click", async () => {
  const topic_id = parseInt(document.getElementById("quizTopicSelect").value);
  if (!topic_id) return;
  const type = document.getElementById("quizType").value;
  const num_questions = parseInt(document.getElementById("quizCount").value || "10");
  const quiz = await api.post("/api/quiz/generate", { topic_id, type, num_questions });
  renderQuiz(quiz, topic_id);
});

function renderQuiz(quiz, topicId) {
  const area = document.getElementById("quizArea");
  const total = quiz.questions.length;

  let banner = "";
  if (quiz.domain) {
    banner = `<div class="quiz-source-banner glass">📚 Pulled from NOVA's curated <strong>${quiz.domain}</strong> question bank — ${total} question${total === 1 ? "" : "s"}, no repeats.</div>`;
  } else if (quiz.note) {
    banner = `<div class="quiz-source-banner glass quiz-source-note">ℹ️ ${quiz.note}</div>`;
  }

  area.innerHTML = banner + quiz.questions.map((q, idx) => {
    if (q.type === "mcq") {
      return `<div class="quiz-question glass" data-idx="${idx}">
        <p class="qtext">Q${idx + 1}. ${q.question}</p>
        <div class="quiz-options">
          ${q.options.map(opt => `<div class="quiz-option" onclick="answerMcq(this, '${escapeAttr(opt)}', '${escapeAttr(q.answer)}')">${opt}</div>`).join("")}
        </div></div>`;
    } else if (q.type === "truefalse") {
      return `<div class="quiz-question glass" data-idx="${idx}">
        <p class="qtext">Q${idx + 1}. ${q.question}</p>
        <div class="quiz-options">
          <div class="quiz-option" onclick="answerTF(this, true, ${q.answer})">True</div>
          <div class="quiz-option" onclick="answerTF(this, false, ${q.answer})">False</div>
        </div></div>`;
    } else if (q.type === "fillblank") {
      return `<div class="quiz-question glass" data-idx="${idx}">
        <p class="qtext">Q${idx + 1}. ${q.question}</p>
        <input type="text" placeholder="Fill in the blank…" style="width:100%" onkeydown="if(event.key==='Enter') answerFillblank(this,'${escapeAttr(q.answer)}')">
      </div>`;
    } else {
      // subjective — free text can't be reliably auto-graded against a full
      // sentence answer, so we reveal the model answer and let the learner
      // self-assess, like a flashcard. Informational-only items (no answer,
      // e.g. "add notes to this topic") skip scoring entirely.
      const hasAnswer = q.answer && q.answer.trim().length > 0;
      if (!hasAnswer) {
        return `<div class="quiz-question glass" data-idx="${idx}">
          <p class="qtext">${q.question}</p>
        </div>`;
      }
      return `<div class="quiz-question glass" data-idx="${idx}">
        <p class="qtext">Q${idx + 1}. ${q.question}</p>
        <input type="text" placeholder="Type your answer, then press Enter…" style="width:100%" onkeydown="if(event.key==='Enter') revealSubjective(this,'${escapeAttr(q.answer)}')">
        <div class="subjective-reveal"></div>
      </div>`;
    }
  }).join("") + `<div class="quiz-score-banner glass" id="quizScoreBanner" style="display:none;"></div>`;

  // informational-only items (empty answer) don't count toward the score
  const scorable = quiz.questions.filter(q => q.type !== "subjective" || (q.answer && q.answer.trim().length > 0));
  window.__quizState = { score: 0, answered: 0, total: scorable.length, topicId };
  if (scorable.length === 0) document.getElementById("quizScoreBanner").remove();
}

function markQuestionDone(container, correct) {
  const s = window.__quizState;
  if (!s || s.total === 0) return;
  s.answered += 1;
  if (correct) s.score += 1;
  if (s.answered >= s.total) {
    const banner = document.getElementById("quizScoreBanner");
    if (banner) {
      banner.style.display = "block";
      banner.textContent = `Score: ${s.score} / ${s.total} — ${Math.round(100 * s.score / s.total)}%`;
    }
    api.post("/api/quiz/submit", { topic_id: s.topicId, score: s.score, total: s.total });
  }
}

function answerMcq(el, chosen, correct) {
  const options = el.parentElement.querySelectorAll(".quiz-option");
  if (el.dataset.locked) return;
  options.forEach(o => o.dataset.locked = "1");
  options.forEach(o => { if (o.textContent === correct) o.classList.add("correct"); });
  if (chosen !== correct) el.classList.add("wrong");
  markQuestionDone(el.closest(".quiz-question"), chosen === correct);
}

function answerTF(el, chosen, correct) {
  const options = el.parentElement.querySelectorAll(".quiz-option");
  if (el.dataset.locked) return;
  options.forEach(o => o.dataset.locked = "1");
  const correctText = correct ? "True" : "False";
  options.forEach(o => { if (o.textContent === correctText) o.classList.add("correct"); });
  if ((chosen ? "True" : "False") !== correctText) el.classList.add("wrong");
  markQuestionDone(el.closest(".quiz-question"), chosen === correct);
}

function answerFillblank(el, correct) {
  const container = el.closest(".quiz-question");
  if (el.dataset.locked) return;
  el.dataset.locked = "1";
  const ok = el.value.trim().toLowerCase() === correct.toLowerCase()
    || el.value.trim().toLowerCase().includes(correct.toLowerCase());
  el.style.borderColor = ok ? "var(--green)" : "var(--red)";
  el.insertAdjacentHTML("afterend", `<p class="hint" style="margin-top:6px;color:${ok ? "var(--green)" : "var(--red)"}">Correct answer: ${escapeHtml(correct)}</p>`);
  el.disabled = true;
  markQuestionDone(container, ok);
}

// Subjective questions use full-sentence model answers, which can't be
// reliably auto-graded against free-typed text — so we reveal the answer
// and let the learner honestly self-mark it, like a flashcard.
function revealSubjective(inputEl, correctAnswer) {
  const container = inputEl.closest(".quiz-question");
  if (inputEl.dataset.locked) return;
  inputEl.dataset.locked = "1";
  inputEl.disabled = true;
  const revealDiv = container.querySelector(".subjective-reveal");
  revealDiv.innerHTML = `
    <p class="hint" style="margin-top:10px;"><strong>Model answer:</strong> ${escapeHtml(correctAnswer)}</p>
    <p class="hint" style="margin:8px 0 6px;">How did you do?</p>
    <div class="row-inline">
      <button class="btn-ghost" onclick="selfGrade(this, true)">✅ Got it right</button>
      <button class="btn-ghost" onclick="selfGrade(this, false)">❌ Need to review</button>
    </div>`;
}

function selfGrade(btnEl, correct) {
  const container = btnEl.closest(".quiz-question");
  const buttons = container.querySelectorAll(".subjective-reveal button");
  buttons.forEach(b => b.disabled = true);
  btnEl.style.outline = `2px solid ${correct ? "var(--green)" : "var(--red)"}`;
  markQuestionDone(container, correct);
}

function escapeAttr(str) { return String(str).replace(/'/g, "\\'").replace(/"/g, "&quot;"); }

// ============================================================ FLASHCARDS ==
async function loadFlashcardsSetup() {
  const topics = await api.get("/api/topics");
  const sel = document.getElementById("fcTopicSelect");
  sel.innerHTML = topics.map(t => `<option value="${t.id}">${t.name}</option>`).join("") || `<option>No topics yet</option>`;
  loadFlashcards();
}

async function loadFlashcards() {
  const cards = await api.get("/api/flashcards");
  renderFlashcards(cards);
}

function renderFlashcards(cards) {
  const wrap = document.getElementById("flashcardsWrap");
  wrap.innerHTML = cards.length ? cards.map(c => `
    <div class="flashcard" onclick="this.classList.toggle('flipped')">
      <button class="fc-fav" onclick="event.stopPropagation(); toggleFav(${c.id})">${c.favorite ? "⭐" : "☆"}</button>
      <div class="flashcard-inner">
        <div class="flashcard-face front">${c.front}</div>
        <div class="flashcard-face back">${c.back}</div>
      </div>
    </div>`).join("") : `<p class="hint">No flashcards yet — select a topic and click "AI Generate".</p>`;
}

async function toggleFav(id) { await api.post(`/api/flashcards/${id}/favorite`); loadFlashcards(); }

document.getElementById("btnGenFlashcards").addEventListener("click", async () => {
  const topic_id = parseInt(document.getElementById("fcTopicSelect").value);
  if (!topic_id) return;
  await api.post("/api/flashcards/generate", { topic_id });
  loadFlashcards();
});

// ============================================================ PDF LAB =====
let currentPdfId = null;

document.getElementById("btnUploadPdf").addEventListener("click", async () => {
  const fileInput = document.getElementById("pdfFile");
  if (!fileInput.files.length) return;
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);

  const resultEl = document.getElementById("pdfResult");
  resultEl.innerHTML = `<div class="loading-row"><span class="spinner"></span>Reading the PDF — trying text extraction, then OCR if it's a scanned document…</div>`;

  let res;
  try {
    res = await fetch("/api/pdf/upload", { method: "POST", body: fd }).then(r => r.json());
  } catch (err) {
    resultEl.innerHTML = `<div class="pdf-error-banner">Upload failed: ${escapeHtml(String(err))}</div>`;
    return;
  }
  currentPdfId = res.id;

  if (res.chars < 30) {
    const ocrNote = res.ocr_available
      ? ""
      : `<br><br>💡 OCR support (for scanned pages) isn't installed in this environment. Install the <strong>tesseract-ocr</strong> engine on this machine and restart the app to enable it.`;
    resultEl.innerHTML = `
      <div class="pdf-error-banner">
        <strong>📄 ${escapeHtml(res.filename)}</strong> — couldn't extract readable text.<br><br>
        ${escapeHtml(res.reason || "This file may be empty, corrupted, or a scan with no OCR available.")}${ocrNote}
      </div>`;
    loadPdfHistory();
    return;
  }

  const summaryRes = await fetch(`/api/pdf/${res.id}/summary?length=medium`).then(r => r.json());
  const badgeClass = res.method === "ocr" ? "ocr" : "ok";
  const badgeLabel = res.method === "ocr" ? "extracted via OCR" : res.method.replace("text ", "");
  resultEl.innerHTML = `
    <div class="panel glass">
      <h3>📄 ${escapeHtml(res.filename)}
        <span class="hint">(${res.chars.toLocaleString()} characters, ${res.pages} page${res.pages === 1 ? "" : "s"})</span>
        <span class="extraction-badge ${badgeClass}">${badgeLabel}</span>
      </h3>
      <p class="hint">AI Summary</p>
      <pre>${escapeHtml(summaryRes.summary)}</pre>
      <p class="hint">Key Topics</p>
      <div class="row-inline">${summaryRes.keywords.map(k => `<span class="tag tag-medium">${k}</span>`).join("")}</div>
    </div>
    <div class="panel glass">
      <h3>Ask a question about this PDF</h3>
      <div class="row-inline">
        <input type="text" id="pdfQuestion" placeholder="e.g. What is the main conclusion?" style="flex:1">
        <button class="btn-primary" onclick="askPdf()">Ask</button>
      </div>
      <div id="pdfAnswer" class="hint" style="margin-top:12px;"></div>
    </div>`;
  loadPdfHistory();
});

async function askPdf() {
  const q = document.getElementById("pdfQuestion").value.trim();
  if (!q || !currentPdfId) return;
  const res = await api.post(`/api/pdf/${currentPdfId}/ask`, { question: q });
  document.getElementById("pdfAnswer").innerHTML = `<strong>Answer:</strong> ${escapeHtml(res.answer)}`;
}

async function loadPdfHistory() {
  const pdfs = await api.get("/api/pdf");
  const heading = document.getElementById("pdfHistoryHeading");
  const wrap = document.getElementById("pdfHistoryList");
  heading.style.display = pdfs.length ? "block" : "none";
  wrap.innerHTML = pdfs.map(p => `
    <div class="list-item">
      <span>📄 ${escapeHtml(p.filename)} <span class="hint">(${p.extraction_method || "unknown"}${p.page_count ? `, ${p.page_count}p` : ""})</span></span>
      <button class="btn-danger" onclick="deletePdf(${p.id})">Delete</button>
    </div>`).join("");
}
async function deletePdf(id) {
  await api.del(`/api/pdf/${id}`);
  loadPdfHistory();
  if (currentPdfId === id) {
    currentPdfId = null;
    document.getElementById("pdfResult").innerHTML = "";
  }
}

// ============================================================ NOTES =======
document.getElementById("btnGenNotes").addEventListener("click", async () => {
  const text = document.getElementById("notesSource").value.trim();
  const style = document.getElementById("notesStyle").value;
  if (!text) return;
  const res = await api.post("/api/notes/generate", { text, style, title: text.slice(0, 40) });
  document.getElementById("notesOutput").innerHTML = `<div class="panel glass"><pre>${escapeHtml(res.notes)}</pre></div>`;
  loadNotes();
});

document.getElementById("btnGenNotesFromFile").addEventListener("click", async () => {
  const fileInput = document.getElementById("notesFile");
  if (!fileInput.files.length) return;
  const style = document.getElementById("notesStyle").value;
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  fd.append("style", style);

  const outputEl = document.getElementById("notesOutput");
  outputEl.innerHTML = `<div class="loading-row"><span class="spinner"></span>Reading the file and generating notes…</div>`;

  const resp = await fetch("/api/notes/generate-from-file", { method: "POST", body: fd });
  const res = await resp.json();

  if (!resp.ok) {
    const ocrNote = res.ocr_available === false
      ? `<br><br>💡 OCR support (for scanned pages) isn't installed in this environment. Install the <strong>tesseract-ocr</strong> engine on this machine and restart the app to enable it.`
      : "";
    outputEl.innerHTML = `<div class="pdf-error-banner">${escapeHtml(res.error || "Couldn't read this file.")}${ocrNote}</div>`;
    return;
  }
  outputEl.innerHTML = `<div class="panel glass"><h3>${escapeHtml(res.title)}</h3><pre>${escapeHtml(res.notes)}</pre></div>`;
  loadNotes();
});

async function loadNotes() {
  const notes = await api.get("/api/notes");
  const wrap = document.getElementById("savedNotesList");
  wrap.innerHTML = notes.length ? notes.map(n => `
    <div class="list-item">
      <span>${escapeHtml(n.title)} <span class="hint">(${n.style}${n.source_filename ? " · from " + escapeHtml(n.source_filename) : ""})</span></span>
      <button class="btn-danger" onclick="deleteNote(${n.id})">Delete</button>
    </div>`).join("") : `<p class="hint">No saved notes yet.</p>`;
}
async function deleteNote(id) { await api.del(`/api/notes/${id}`); loadNotes(); }


// ============================================================ INSIGHTS ====
async function loadInsights() {
  const readiness = await api.get("/api/analytics/prediction");
  const burnout = await api.get("/api/analytics/burnout");

  document.getElementById("readinessWrap").innerHTML = `
    <p class="stat-value" style="font-size:36px;">${readiness.readiness_score}%</p>
    <p class="hint">Status: <strong style="color:var(--cyan)">${readiness.status}</strong> · Confidence ${readiness.confidence}%</p>
    <ul>${readiness.advice.map(a => `<li class="hint">${a}</li>`).join("")}</ul>`;

  document.getElementById("burnoutWrap").innerHTML = `
    <p class="stat-value" style="font-size:22px;text-transform:capitalize;">${burnout.status.replace(/-/g, " ")}</p>
    <p class="hint">${burnout.message}</p>`;
}

// ============================================================ INIT ========
loadDashboard();
loadTutorHistory();
switchView("dashboard");
