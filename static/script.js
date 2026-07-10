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
const directLLM = document.getElementById("direct-llm");

let documents = [];

init();

async function init() {
  await refreshDocuments();
  chatForm.addEventListener("submit", handleSend);
  const testBtn = document.getElementById('stream-test-btn');
  if (testBtn) testBtn.addEventListener('click', runStreamTest);
}

async function runStreamTest() {
  console.info('Starting /stream-test');
  try {
    const res = await fetch(`${API_BASE}/stream-test`, { method: 'GET' });
    if (!res.ok) {
      console.error('/stream-test returned', res.status);
      return;
    }
    if (!res.body || !res.body.getReader) {
      console.warn('Streaming not available in this environment for /stream-test');
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line) continue;
        try {
          const obj = JSON.parse(line);
          console.log('stream-test line:', obj);
        } catch (e) {
          console.error('Failed to parse stream-test line', e, line);
        }
      }
    }
    console.info('/stream-test finished');
  } catch (e) {
    console.error('stream-test error', e);
  }
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
  if (directLLM) directLLM.disabled = !hasDocs;
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

  const loadingEl = addMessage("assistant", "", { loading: true });

  try {
    const payload = { question, top_k: 5 };
    if (directLLM && directLLM.checked) payload.use_direct_llm = true;

    const res = await fetch(`${API_BASE}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const err = await res.text();
      throw new Error(err || "Chat request failed");
    }

    console.debug("/chat/stream response headers:", [...res.headers.entries()]);
    // Some browsers/environments (or intermediaries) may not expose a streaming
    // response body. In that case, fall back to a standard JSON response from
    // the non-streaming `/chat` endpoint so the UI still works.
    if (!res.body || !res.body.getReader) {
      console.warn("Streaming not available in this environment; falling back to /chat JSON response");
      try {
        const data = await fetch(`${API_BASE}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }).then(r => r.json());

        loadingEl.remove();
        addMessage("assistant", data.answer, {
          noContext: !data.found_context,
          sources: data.sources,
          suggestedQuestions: data.suggested_questions || [],
        });
        return;
      } catch (e) {
        throw e;
      }
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let completeSources = [];
    let usedDirect = false;

    // Update bubble text incrementally
    let currentText = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let nl;
      while ((nl = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line) continue;
        try {
          const obj = JSON.parse(line);
          console.debug('stream line parsed', obj);
          if (obj.delta) {
            currentText += obj.delta;
            // update the loading element's bubble
            const bubble = loadingEl.querySelector('.msg-bubble');
            bubble.textContent = currentText;
            messages.scrollTop = messages.scrollHeight;
          }
          if (obj.done) {
            completeSources = obj.sources || [];
            usedDirect = !!obj.used_direct_llm;
          }
        } catch (e) {
          console.error('Failed to parse stream line', e, line);
        }
      }
    }

    // Replace loading indicator with final message (already rendered)
    // Append sources if present
    const bubble = loadingEl.querySelector('.msg-bubble');
    // Ensure final text is present
    bubble.textContent = currentText || bubble.textContent || "(no response)";

    // Append sources if present
    if (completeSources.length > 0) {
      const src = document.createElement('div');
      src.className = 'sources';
      src.innerHTML = 'Sources: ' + completeSources
        .map(s => `<span class="source-tag">${escapeHtml(s.filename)} — ${escapeHtml(s.section)}</span>`)
        .join('');
      bubble.appendChild(src);
    }

    // Remove loading state so styles update and the bubble is interactive
    loadingEl.classList.remove('msg-loading');

  } catch (err) {
    const bubble = loadingEl.querySelector('.msg-bubble');
    bubble.textContent = `Error: ${err.message}`;
    loadingEl.classList.add('no-context');
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
  // For loading placeholders, insert a visible ellipsis so the bubble is
  // clearly noticeable while streaming (avoids a tiny empty square).
  bubble.textContent = opts.loading ? "…" : text;
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
