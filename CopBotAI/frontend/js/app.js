/* =========================================================================
   CopBot AI — frontend application logic
   Vanilla JS, no build step. Talks to the FastAPI backend via fetch + SSE.
   ========================================================================= */

const API = ""; // same-origin

const el = (sel) => document.querySelector(sel);
const els = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  sessionId: localStorage.getItem("copbot_session_id") || null,
  sending: false,
  theme: localStorage.getItem("copbot_theme") || "dark",
};

document.body.setAttribute("data-theme", state.theme);
el("#themeToggle").textContent = state.theme === "dark" ? "🌙" : "☀️";

/* ------------------------------------------------------------------ */
/* Utilities                                                           */
/* ------------------------------------------------------------------ */

function renderMarkdown(text) {
  try {
    const raw = marked.parse(text, { breaks: true });
    return DOMPurify.sanitize(raw);
  } catch {
    return text.replace(/</g, "&lt;");
  }
}

function toast(message, type = "info") {
  const container = el("#toastContainer");
  const node = document.createElement("div");
  node.className = `toast ${type}`;
  node.textContent = message;
  container.appendChild(node);
  setTimeout(() => node.remove(), 4500);
}

function scrollToBottom(smooth = true) {
  const scroll = el("#chatScroll");
  scroll.scrollTo({ top: scroll.scrollHeight, behavior: smooth ? "smooth" : "auto" });
}

function autoResize(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = Math.min(textarea.scrollHeight, 160) + "px";
}

function formatTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

/* ------------------------------------------------------------------ */
/* Health / provider status                                            */
/* ------------------------------------------------------------------ */

async function refreshHealth() {
  try {
    const res = await fetch(`${API}/api/health`);
    const data = await res.json();
    const groqDot = el("#dotGroq");
    const ollamaDot = el("#dotOllama");
    groqDot.className = "dot " + (data.providers.groq.available ? "online" : "offline");
    ollamaDot.className = "dot " + (data.providers.ollama.available ? "online" : "offline");
    groqDot.title = data.providers.groq.detail;
    ollamaDot.title = data.providers.ollama.detail;
  } catch {
    // backend not reachable yet; will retry
  }
}
refreshHealth();
setInterval(refreshHealth, 20000);

/* ------------------------------------------------------------------ */
/* Sessions (sidebar)                                                   */
/* ------------------------------------------------------------------ */

async function loadSessions() {
  try {
    const res = await fetch(`${API}/api/sessions`);
    const sessions = await res.json();
    const list = el("#sessionList");
    list.innerHTML = "";
    if (!sessions.length) {
      list.innerHTML = `<div class="session-empty">No conversations yet</div>`;
      return;
    }
    for (const s of sessions) {
      const item = document.createElement("div");
      item.className = "session-item" + (s.id === state.sessionId ? " active" : "");
      item.innerHTML = `<span class="s-title">${s.title}</span><button class="s-del" data-id="${s.id}">✕</button>`;
      item.addEventListener("click", (e) => {
        if (e.target.closest(".s-del")) return;
        loadSession(s.id);
      });
      item.querySelector(".s-del").addEventListener("click", async (e) => {
        e.stopPropagation();
        await fetch(`${API}/api/sessions/${s.id}`, { method: "DELETE" });
        if (state.sessionId === s.id) startNewChat();
        loadSessions();
      });
      list.appendChild(item);
    }
  } catch {
    /* ignore */
  }
}

async function loadSession(sessionId) {
  state.sessionId = sessionId;
  localStorage.setItem("copbot_session_id", sessionId);
  closeSidebarMobile();
  const res = await fetch(`${API}/api/sessions/${sessionId}/messages`);
  const messages = await res.json();
  el("#messages").innerHTML = "";
  el("#welcomeScreen").style.display = messages.length ? "none" : "";
  for (const m of messages) {
    appendMessage(m.role, m.content, {
      id: m.id,
      provider: m.provider,
      model: m.model,
      sources: m.sources ? JSON.parse(m.sources) : null,
      time: m.created_at,
    });
  }
  const titleGuess = messages.find((m) => m.role === "user");
  el("#chatTitle").textContent = titleGuess ? titleGuess.content.slice(0, 48) : "New Conversation";
  loadSessions();
  scrollToBottom(false);
}

function startNewChat() {
  state.sessionId = null;
  localStorage.removeItem("copbot_session_id");
  el("#messages").innerHTML = "";
  el("#welcomeScreen").style.display = "";
  el("#chatTitle").textContent = "New Conversation";
  el("#emergencyBanner").hidden = true;
  loadSessions();
}

/* ------------------------------------------------------------------ */
/* Message rendering                                                    */
/* ------------------------------------------------------------------ */

function appendMessage(role, content, meta = {}) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  const avatar = role === "user" ? "🧑" : "🛡️";

  wrap.innerHTML = `
    <div class="msg-avatar">${avatar}</div>
    <div class="msg-col">
      <div class="bubble">${renderMarkdown(content)}</div>
      ${meta.sources && meta.sources.length ? renderSources(meta.sources) : ""}
      <div class="msg-meta">
        ${meta.provider ? `<span class="provider-tag">${meta.provider}${meta.model ? " · " + meta.model : ""}</span>` : ""}
        <span>${meta.time ? formatTime(meta.time) : "now"}</span>
        <div class="msg-actions">
          <button class="copy-btn" title="Copy">📋</button>
          ${role === "assistant" ? `
          <span class="feedback-btns" data-message-id="${meta.id ?? ""}">
            <button class="fb-up" title="Helpful">👍</button>
            <button class="fb-down" title="Not helpful">👎</button>
          </span>` : ""}
        </div>
      </div>
    </div>
  `;
  wrap.querySelector(".copy-btn").addEventListener("click", () => {
    navigator.clipboard.writeText(content);
    toast("Copied to clipboard", "success");
  });
  if (role === "assistant") {
    wireFeedbackButtons(wrap, meta.feedback);
  }
  el("#messages").appendChild(wrap);
  return wrap;
}

function wireFeedbackButtons(wrap, existingRating) {
  const box = wrap.querySelector(".feedback-btns");
  if (!box) return;
  const upBtn = box.querySelector(".fb-up");
  const downBtn = box.querySelector(".fb-down");
  if (existingRating === 1) upBtn.classList.add("active-up");
  if (existingRating === -1) downBtn.classList.add("active-down");

  async function sendFeedback(rating, btn, otherBtn) {
    const messageId = box.dataset.messageId;
    if (!messageId) {
      toast("Still generating — try again in a moment", "error");
      return;
    }
    otherBtn.classList.remove("active-up", "active-down");
    btn.classList.toggle(rating === 1 ? "active-up" : "active-down");
    try {
      await fetch(`${API}/api/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: Number(messageId), rating }),
      });
      toast(rating === 1 ? "Thanks for the feedback!" : "Thanks — we'll aim to do better.", "success");
    } catch {
      toast("Could not save feedback", "error");
    }
  }

  upBtn.addEventListener("click", () => sendFeedback(1, upBtn, downBtn));
  downBtn.addEventListener("click", () => sendFeedback(-1, downBtn, upBtn));
}

function renderFollowUps(questions) {
  if (!questions || !questions.length) return null;
  const wrap = document.createElement("div");
  wrap.className = "followup-chips";
  wrap.innerHTML = questions
    .map((q) => `<button class="followup-chip">${q.replace(/</g, "&lt;")}</button>`)
    .join("");
  wrap.querySelectorAll(".followup-chip").forEach((btn) => {
    btn.addEventListener("click", () => sendMessage(btn.textContent));
  });
  el("#messages").appendChild(wrap);
  return wrap;
}

function renderSources(sources) {
  const items = sources
    .map(
      (s) => `<div class="src-item"><span class="src-label">${s.source}</span> — ${s.text.replace(/</g, "&lt;")}</div>`
    )
    .join("");
  return `<details class="sources-box"><summary>📚 ${sources.length} source${sources.length > 1 ? "s" : ""} used</summary>${items}</details>`;
}

function appendTypingBubble() {
  const wrap = document.createElement("div");
  wrap.className = "msg assistant";
  wrap.innerHTML = `
    <div class="msg-avatar">🛡️</div>
    <div class="msg-col">
      <div class="bubble"><div class="typing-dots"><span></span><span></span><span></span></div></div>
    </div>
  `;
  el("#messages").appendChild(wrap);
  return wrap;
}

/* ------------------------------------------------------------------ */
/* Sending messages (SSE streaming)                                     */
/* ------------------------------------------------------------------ */

async function sendMessage(text) {
  if (!text.trim() || state.sending) return;
  state.sending = true;
  el("#sendBtn").disabled = true;
  el("#welcomeScreen").style.display = "none";
  el("#emergencyBanner").hidden = true;

  appendMessage("user", text);
  scrollToBottom();

  const typingBubble = appendTypingBubble();
  scrollToBottom();

  const provider = el("#providerSelect").value;
  let assistantBubble = null;
  let fullText = "";
  let metaInfo = { provider: null, model: null };
  let sourcesForMsg = null;

  try {
    const res = await fetch(`${API}/api/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: state.sessionId, provider }),
    });

    if (res.status === 429) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || "Too many requests — please slow down.");
    }
    if (!res.ok || !res.body) {
      throw new Error(`Server responded with ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split("\n\n");
      buffer = parts.pop();

      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const jsonStr = line.slice(5).trim();
        if (!jsonStr) continue;
        let event;
        try {
          event = JSON.parse(jsonStr);
        } catch {
          continue;
        }

        switch (event.type) {
          case "session":
            state.sessionId = event.session_id;
            localStorage.setItem("copbot_session_id", event.session_id);
            break;
          case "sources":
            sourcesForMsg = event.sources;
            break;
          case "emergency":
            el("#emergencyBanner").hidden = false;
            break;
          case "meta":
            metaInfo = { provider: event.provider, model: event.model };
            if (!assistantBubble) {
              typingBubble.remove();
              assistantBubble = appendMessage("assistant", "", metaInfo);
              assistantBubble.querySelector(".bubble").classList.add("stream-cursor");
            }
            break;
          case "chunk":
            fullText += event.content;
            if (!assistantBubble) {
              typingBubble.remove();
              assistantBubble = appendMessage("assistant", "", metaInfo);
              assistantBubble.querySelector(".bubble").classList.add("stream-cursor");
            }
            assistantBubble.querySelector(".bubble").innerHTML = renderMarkdown(fullText);
            scrollToBottom();
            break;
          case "warning":
            toast(event.message, "error");
            break;
          case "suggestions":
            renderFollowUps(event.questions);
            scrollToBottom();
            break;
          case "done":
            if (assistantBubble) {
              assistantBubble.querySelector(".bubble").classList.remove("stream-cursor");
              if (sourcesForMsg && sourcesForMsg.length) {
                const existing = assistantBubble.querySelector(".sources-box");
                if (!existing) {
                  assistantBubble.querySelector(".bubble").insertAdjacentHTML("afterend", renderSources(sourcesForMsg));
                }
              }
              const tag = assistantBubble.querySelector(".provider-tag");
              if (tag) tag.textContent = `${event.provider}${event.model ? " · " + event.model : ""}`;
              const fbBox = assistantBubble.querySelector(".feedback-btns");
              if (fbBox && event.message_id) fbBox.dataset.messageId = event.message_id;
            }
            loadSessions();
            break;
        }
      }
    }
  } catch (err) {
    typingBubble.remove();
    if (!assistantBubble) {
      appendMessage("assistant", "⚠️ Sorry, I couldn't reach the server. Please check that the backend is running and try again.");
    }
    toast("Connection error: " + err.message, "error");
  } finally {
    state.sending = false;
    el("#sendBtn").disabled = false;
    scrollToBottom();
  }
}

/* ------------------------------------------------------------------ */
/* Composer                                                             */
/* ------------------------------------------------------------------ */

const input = el("#composerInput");
input.addEventListener("input", () => {
  autoResize(input);
  el("#charCounter").textContent = `${input.value.length}/2000`;
});
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    el("#composerForm").requestSubmit();
  }
});

el("#composerForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value;
  input.value = "";
  autoResize(input);
  el("#charCounter").textContent = "0/2000";
  sendMessage(text);
});

els(".suggestion-card, .quick-chip[data-prompt]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const prompt = btn.dataset.prompt;
    if (!prompt) return;
    sendMessage(prompt);
    closeSidebarMobile();
  });
});

/* ------------------------------------------------------------------ */
/* Voice input (Web Speech API, optional / graceful fallback)           */
/* ------------------------------------------------------------------ */

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SpeechRecognition) {
  const recognizer = new SpeechRecognition();
  recognizer.continuous = false;
  recognizer.interimResults = false;
  recognizer.lang = "en-IN";
  let listening = false;

  el("#micBtn").addEventListener("click", () => {
    if (listening) {
      recognizer.stop();
      return;
    }
    try {
      recognizer.start();
      listening = true;
      el("#micBtn").classList.add("recording");
    } catch {
      /* already started */
    }
  });
  recognizer.addEventListener("result", (e) => {
    const transcript = e.results[0][0].transcript;
    input.value = (input.value + " " + transcript).trim();
    autoResize(input);
  });
  recognizer.addEventListener("end", () => {
    listening = false;
    el("#micBtn").classList.remove("recording");
  });
  recognizer.addEventListener("error", () => {
    listening = false;
    el("#micBtn").classList.remove("recording");
  });
} else {
  el("#micBtn").addEventListener("click", () => toast("Voice input isn't supported in this browser", "error"));
}

/* ------------------------------------------------------------------ */
/* Sidebar / theme / misc controls                                      */
/* ------------------------------------------------------------------ */

function closeSidebarMobile() {
  el("#sidebar").classList.remove("open");
  el("#sidebarScrim").classList.remove("show");
}

el("#sidebarOpen").addEventListener("click", () => {
  el("#sidebar").classList.add("open");
  el("#sidebarScrim").classList.add("show");
});
el("#sidebarClose").addEventListener("click", closeSidebarMobile);
el("#sidebarScrim").addEventListener("click", closeSidebarMobile);

el("#newChatBtn").addEventListener("click", () => {
  startNewChat();
  closeSidebarMobile();
});

el("#clearChatBtn").addEventListener("click", () => {
  if (!confirm("Start a new conversation? This chat will remain in your history.")) return;
  startNewChat();
});

el("#themeToggle").addEventListener("click", () => {
  state.theme = state.theme === "dark" ? "light" : "dark";
  document.body.setAttribute("data-theme", state.theme);
  localStorage.setItem("copbot_theme", state.theme);
  el("#themeToggle").textContent = state.theme === "dark" ? "🌙" : "☀️";
});

el("#dismissEmergency").addEventListener("click", () => {
  el("#emergencyBanner").hidden = true;
});

/* ------------------------------------------------------------------ */
/* Complaint tracker modal                                              */
/* ------------------------------------------------------------------ */

function openComplaintModal() {
  el("#complaintModal").hidden = false;
  el("#complaintIdInput").focus();
}
function closeComplaintModal() {
  el("#complaintModal").hidden = true;
  el("#complaintResult").innerHTML = "";
  el("#complaintIdInput").value = "";
}

el("#trackComplaintChip").addEventListener("click", openComplaintModal);
el("#closeComplaintModal").addEventListener("click", closeComplaintModal);
el("#complaintModal").addEventListener("click", (e) => {
  if (e.target.id === "complaintModal") closeComplaintModal();
});

el("#complaintForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = el("#complaintIdInput").value.trim();
  const resultBox = el("#complaintResult");
  resultBox.innerHTML = `<div class="typing-dots"><span></span><span></span><span></span></div>`;
  try {
    const res = await fetch(`${API}/api/complaint/lookup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ complaint_id: id }),
    });
    if (!res.ok) {
      resultBox.innerHTML = `<p style="color:var(--danger)">No complaint found with ID "${id}".</p>`;
      return;
    }
    const data = await res.json();
    const statusClass = (data.status || "").toLowerCase().replace(/\s+/g, "-");
    resultBox.innerHTML = `
      <div class="complaint-card">
        <div class="complaint-row"><span class="k">Complaint ID</span><span>${data.complaint_id}</span></div>
        <div class="complaint-row"><span class="k">Crime Type</span><span>${data.crime_type}</span></div>
        <div class="complaint-row"><span class="k">Date Reported</span><span>${data.date_reported}</span></div>
        <div class="complaint-row"><span class="k">Status</span><span class="status-pill ${statusClass}">${data.status}</span></div>
      </div>`;
  } catch {
    resultBox.innerHTML = `<p style="color:var(--danger)">Could not reach the server. Try again.</p>`;
  }
});

/* ------------------------------------------------------------------ */
/* File a Complaint modal                                                */
/* ------------------------------------------------------------------ */

function openFileComplaintModal() {
  el("#fileComplaintModal").hidden = false;
  el("#fcCrimeType").focus();
}
function closeFileComplaintModal() {
  el("#fileComplaintModal").hidden = true;
  el("#fileComplaintResult").innerHTML = "";
  el("#fileComplaintForm").reset();
}

el("#fileComplaintChip").addEventListener("click", openFileComplaintModal);
el("#closeFileComplaintModal").addEventListener("click", closeFileComplaintModal);
el("#fileComplaintModal").addEventListener("click", (e) => {
  if (e.target.id === "fileComplaintModal") closeFileComplaintModal();
});

el("#fileComplaintForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    crime_type: el("#fcCrimeType").value.trim(),
    description: el("#fcDescription").value.trim(),
    location: el("#fcLocation").value.trim(),
    complainant_name: el("#fcName").value.trim(),
    contact: el("#fcContact").value.trim(),
    session_id: state.sessionId,
  };
  const resultBox = el("#fileComplaintResult");
  resultBox.innerHTML = `<div class="typing-dots"><span></span><span></span><span></span></div>`;
  try {
    const res = await fetch(`${API}/api/complaint/file`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      resultBox.innerHTML = `<p style="color:var(--danger)">${err.detail || "Could not file complaint."}</p>`;
      return;
    }
    const data = await res.json();
    resultBox.innerHTML = `
      <div class="complaint-card">
        <div class="complaint-row"><span class="k">Complaint ID</span><span><strong>${data.complaint_id}</strong></span></div>
        <div class="complaint-row"><span class="k">Crime Type</span><span>${data.crime_type}</span></div>
        <div class="complaint-row"><span class="k">Status</span><span class="status-pill registered">${data.status}</span></div>
      </div>
      <p style="margin-top:10px; font-size:12px; color:var(--text-muted);">
        Save this ID — you can check its status anytime with "Track a Complaint".
      </p>`;
    toast("Complaint filed successfully", "success");
  } catch {
    resultBox.innerHTML = `<p style="color:var(--danger)">Could not reach the server. Try again.</p>`;
  }
});

/* ------------------------------------------------------------------ */
/* Init                                                                  */
/* ------------------------------------------------------------------ */

(async function init() {
  loadSessions();
  if (state.sessionId) {
    try {
      await loadSession(state.sessionId);
    } catch {
      startNewChat();
    }
  }
})();
