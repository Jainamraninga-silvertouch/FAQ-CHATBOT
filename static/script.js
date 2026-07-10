const API_BASE = "";

const docList = document.getElementById("doc-list");
const docEmpty = document.getElementById("doc-empty");
const docCount = document.getElementById("doc-count");
const messages = document.getElementById("messages");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const chatSubtitle = document.getElementById("chat-subtitle");
const toast = document.getElementById("toast");

let documents = [];

init();

async function init() {
  await refreshDocuments();
  chatForm.addEventListener("submit", handleSend);
}

// ---------------- Documents ----------------

async function refreshDocuments() {
  try {
    const res = await fetch(`${API_BASE}/documents`);
    if (!res.ok) throw new Error("Failed to load documents");
    documents = await res.json();
    renderDocuments();
    updateChatAvailability();
  } catch (err) {
    showToast(err.message, true);
  }
}

function renderDocuments() {
  docCount.textContent = documents.length;
  docList.querySelectorAll(".doc-item").forEach(el => el.remove());
  docEmpty.hidden = documents.length > 0;

  for (const doc of documents) {
    const li = document.createElement("li");
    li.className = "doc-item";
    li.innerHTML = `
      <div class="doc-name">${escapeHtml(doc.filename)}</div>
      <div class="doc-meta">${doc.num_sections} section${doc.num_sections === 1 ? "" : "s"}</div>
    `;
    docList.appendChild(li);
  }
}

function updateChatAvailability() {
  const hasDocs = documents.length > 0;
  chatInput.disabled = !hasDocs;
  sendBtn.disabled = !hasDocs;
  docSelectAll.disabled = !hasDocs;
  docClearSelection.disabled = !hasDocs;
  chatSubtitle.textContent = hasDocs
    ? `Ask questions about ${documents.length} loaded document${documents.length === 1 ? "" : "s"}.`
    : "No documents loaded. Place files in /upload folder and restart server.";
}

// ---------------- Chat ----------------

async function handleSend(e) {
  e.preventDefault();
  const question = chatInput.value.trim();
  if (!question) return;

  addMessage("user", question);
  chatInput.value = "";
  chatInput.disabled = true;
  sendBtn.disabled = true;

  const loadingEl = addMessage("assistant", "Thinking…", { loading: true });

  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, top_k: 5 }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Chat request failed");

    loadingEl.remove();
    addMessage("assistant", data.answer, {
      noContext: !data.found_context,
      sources: data.sources,
      suggestedQuestions: data.suggested_questions || []
    });
  } catch (err) {
    loadingEl.remove();
    addMessage("assistant", `Error: ${err.message}`, { noContext: true });
  } finally {
    chatInput.disabled = false;
    sendBtn.disabled = false;
    chatInput.focus();
  }
}

function addMessage(role, text, opts = {}) {
  const wrap = document.createElement("div");
  wrap.className = `msg msg-${role}${opts.loading ? " msg-loading" : ""}${opts.noContext ? " no-context" : ""}`;

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.textContent = text;
  wrap.appendChild(bubble);

  if (opts.sources && opts.sources.length > 0) {
    const src = document.createElement("div");
    src.className = "sources";
    src.innerHTML = "Sources: " + opts.sources
      .map(s => `<span class="source-tag">${escapeHtml(s.filename)} — ${escapeHtml(s.section)}</span>`)
      .join("");
    bubble.appendChild(src);
  }

  if (opts.suggestedQuestions && opts.suggestedQuestions.length > 0) {
    const suggestions = document.createElement("div");
    suggestions.className = "suggested-questions";
    suggestions.innerHTML = "<strong>Related questions:</strong>";
    
    const questionList = document.createElement("div");
    questionList.className = "question-list";
    
    opts.suggestedQuestions.forEach(q => {
      const btn = document.createElement("button");
      btn.className = "suggested-question-btn";
      btn.textContent = q;
      btn.onclick = () => {
        chatInput.value = q;
        chatForm.dispatchEvent(new Event('submit'));
      };
      questionList.appendChild(btn);
    });
    
    suggestions.appendChild(questionList);
    bubble.appendChild(suggestions);
  }

  messages.appendChild(wrap);
  messages.scrollTop = messages.scrollHeight;
  return wrap;
}

// ---------------- Utils ----------------

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

let toastTimer;
function showToast(msg, isError = false) {
  toast.textContent = msg;
  toast.className = `toast${isError ? " error" : ""}`;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toast.hidden = true), 3500);
}
