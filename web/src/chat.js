// Ask the Guides (round 45, Liam 2026-10-28): the chat tab. Its own module, loaded beside app.js, so the chat works
// when the rules engine (Pyodide) is still loading or failed, and a chat failure never touches the checker.
//
// The Worker (POST /api/chat) answers as NDJSON: start, text pieces, then done with the citations it built from its
// own index (carrier, guide date, page, rule ID -- never from the model), or error. This page sends only the
// question and the last few turns.

import { markdown, escapeHtml } from "./markdown.js";

const $ = (sel, root = document) => root.querySelector(sel);
const MAX_TURNS = 6;
const FEEDBACK_NOT_SAVED = "Couldn’t save — try again later.";     // the Worker's FEEDBACK_NOT_SAVED
const CHAT_CHOICES = ["The answer is wrong", "A citation is wrong", "It didn't answer the question", "Not sure"];
const UNREACHABLE = "Ask the Guides couldn't be reached. The eligibility check still works; please try again.";

const chat = { turns: [], busy: false, seq: 0, posts: [] };

// ---------------------------------------------------------------------------------------------------------- tabs
function showTab(name) {
  const isChat = name === "chat";
  $("#app").hidden = isChat;
  $("#chat").hidden = !isChat;
  for (const b of document.querySelectorAll(".tabs button")) {
    const on = b.dataset.tab === name;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
  }
  if (isChat) { const q = $("#chat-q"); if (q) q.focus(); }
}

function build() {
  const root = $("#chat");
  root.innerHTML = `
    <h1>Ask the Guides</h1>
    <div class="caption">Questions about a carrier's underwriting guide, answered only from the guides and rules tables
      CFIG has on file, with the carrier, guide date and page for every point. CFIG's own experience is marked
      "CFIG experience". This does not run an eligibility check.</div>
    <div id="chat-log" aria-live="polite"></div>
    <form id="chat-form" class="chat-form">
      <label for="chat-q" class="caption">Your question</label>
      <textarea id="chat-q" rows="2" maxlength="1000"
        placeholder="e.g. Does the Hartford take a trampoline? Which carriers decline Federal Pacific panels?"></textarea>
      <div class="chat-buttons">
        <button type="submit" class="primary" id="chat-ask">Ask</button>
        <button type="button" id="chat-clear">Clear chat</button>
      </div>
    </form>`;
  $("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); ask($("#chat-q").value); });
  $("#chat-q").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask($("#chat-q").value); }
  });
  $("#chat-clear").addEventListener("click", () => { chat.turns = []; $("#chat-log").innerHTML = ""; });
}

// ---------------------------------------------------------------------------------------------------------- render
// [S3], [S3, S5] and ranges [S29-S37] / [S29–S37] (the Worker's CITE_RE / citeNumbers, cloudflare/src/chat.js)
const CITE_RE = /\[S\d+(?:\s*(?:,|[-–—]|to)\s*S?\d+)*\]/g;
function citeNumbers(bracket) {
  const out = [];
  for (const part of bracket.slice(1, -1).split(",")) {
    const [a, b] = part.split(/[-–—]|to/).map((x) => parseInt(x.replace(/\D/g, ""), 10));
    if (Number.isFinite(b) && b >= a && b - a <= 60) for (let n = a; n <= b; n++) out.push(n);
    else if (Number.isFinite(a)) out.push(a);
  }
  return out;
}
const citeLinks = (html, id) => html.replace(CITE_RE, (m) =>
  citeNumbers(m).map((n) => `<sup class="cite"><a href="#${id}-s${n}">S${n}</a></sup>`).join(""));

function renderAnswer(box, text, id) {
  $(".answer", box).innerHTML = citeLinks(markdown(text), id);
}

function citationHtml(c, id) {
  const where = [c.carrier, c.guide_date ? `guide dated ${c.guide_date}` : "guide date not stated",
    c.page ? `page ${c.page}` : ""].filter(Boolean).join(", ");
  if (c.kind === "cfig") {
    return `<li id="${id}-s${c.n}"><b>S${c.n}</b> <span class="cfig">CFIG experience (not the guide)</span>: `
      + `${escapeHtml(c.carrier)} — ${escapeHtml(c.id)}: ${escapeHtml(c.text)}</li>`;
  }
  if (c.kind === "rule") {
    return `<li id="${id}-s${c.n}"><b>S${c.n}</b> ${escapeHtml(where)} — rule ${escapeHtml(c.id)}: ${escapeHtml(c.text)}`
      + (c.quote ? `<div class="quote">Guide: “${escapeHtml(c.quote)}”</div>` : "") + "</li>";
  }
  return `<li id="${id}-s${c.n}"><b>S${c.n}</b> ${escapeHtml(where)}${c.section ? ` — ${escapeHtml(c.section)}` : ""}`
    + `<div class="quote">${escapeHtml(c.text)}</div></li>`;
}

function turnBox(question) {
  const id = `t${++chat.seq}`;
  const el = document.createElement("div");
  el.className = "chat-turn";
  el.dataset.turn = id;
  el.innerHTML = `<div class="chat-q">${escapeHtml(question)}</div>
    <div class="chat-a"><div class="spinner">Reading the guides…</div><div class="md answer"></div>
      <div class="chat-note" hidden></div><div class="chat-cites" hidden></div><div class="chat-fb"></div></div>`;
  $("#chat-log").append(el);
  el.scrollIntoView({ block: "nearest" });
  return { el, id };
}

// ---------------------------------------------------------------------------------------------------------- ask
async function ask(raw) {
  const question = String(raw || "").trim();
  if (!question || chat.busy) return null;
  chat.busy = true;
  $("#chat-ask").disabled = true;
  $("#chat-q").value = "";
  const { el, id } = turnBox(question);
  const turn = { q: question, a: "", citations: [], unverified: [], error: null, carriers: [] };
  const fail = (msg) => {
    turn.error = msg;
    const note = $(".chat-note", el);
    note.className = "chat-note alert error";
    note.textContent = msg;
    note.hidden = false;
  };
  try {
    const history = chat.turns.filter((t) => !t.error).slice(-MAX_TURNS).map((t) => ({ q: t.q, a: t.a }));
    const r = await fetch("/api/chat", { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, history }) });
    if (!r.ok) {
      let msg = UNREACHABLE;
      try { const j = await r.json(); if (j && j.error) msg = j.error; } catch { /* not JSON */ }
      fail(msg);
    } else {
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, i);
          buf = buf.slice(i + 1);
          if (!line.trim()) continue;
          const ev = JSON.parse(line);
          if (ev.t === "start") turn.carriers = ev.carriers || [];
          else if (ev.t === "text") {
            turn.a += ev.d;
            $(".spinner", el)?.remove();
            renderAnswer(el, turn.a, id);
          } else if (ev.t === "done") {
            turn.citations = ev.citations || [];
            turn.unverified = ev.unverified || [];
            turn.stop = ev.stop;
          } else if (ev.t === "error") fail(ev.error);
        }
      }
      if (!turn.a && !turn.error) fail(UNREACHABLE);
    }
  } catch {
    fail(UNREACHABLE);
  }
  $(".spinner", el)?.remove();
  if (turn.citations.length) {
    const cites = $(".chat-cites", el);
    cites.innerHTML = `<div class="caption">Sources</div><ul>${turn.citations.map((c) => citationHtml(c, id)).join("")}</ul>`;
    cites.hidden = false;
  }
  if (turn.unverified.length && !turn.error) {
    const note = $(".chat-note", el);
    note.className = "chat-note alert warning";
    note.textContent = "A quote in this answer could not be found in the sources it was given. Check the guide before relying on it.";
    note.hidden = false;
  }
  if (turn.a && !turn.error) $(".chat-fb", el).append(feedbackControl(turn));
  chat.turns.push(turn);
  chat.busy = false;
  $("#chat-ask").disabled = false;
  return turn;
}

// ---------------------------------------------------------------------------------------------------------- feedback
function agentName() {
  const f = document.getElementById("f-tester_name");
  return (f && f.value) || "";
}

function feedbackControl(turn) {
  const box = document.createElement("details");
  box.className = "feedback";
  const name = `cfb-${chat.seq}`;
  box.innerHTML = `<summary>This answer looks wrong</summary>
    <div class="alert success sent" hidden>Sent -- thank you.</div>
    <div class="alert error send-failed" hidden></div>
    <form class="fb-form">
      <fieldset><legend>What's wrong?</legend>${CHAT_CHOICES.map((c, k) => `<label><input type="radio" name="${name}"
        value="${escapeHtml(c)}" ${k === CHAT_CHOICES.length - 1 ? "checked" : ""}> ${escapeHtml(c)}</label>`).join("")}</fieldset>
      <label>What should it say? (optional)<textarea name="comment" rows="3"></textarea></label>
      <button type="submit">Send</button>
    </form>`;
  const form = $("form", box);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const record = { kind: "chat", ts: new Date().toISOString().slice(0, 19) + "+00:00", name: agentName(),
      question: turn.q, answer: turn.a, carriers: [...new Set(turn.citations.map((c) => c.carrier))],
      choice: ($("input[type=radio]:checked", form) || {}).value, comment: form.elements.comment.value,
      app_version: (window.__eligibility && window.__eligibility.appVersion && window.__eligibility.appVersion()) || "" };
    $(".send-failed", box).hidden = true;
    try {
      const r = await fetch("/api/feedback", { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(record) });
      if (!r.ok) throw new Error(String(r.status));
      chat.posts.push({ kind: "chat_feedback", record });
      $(".sent", box).hidden = false;
      form.reset();
    } catch {
      $(".sent", box).hidden = true;
      $(".send-failed", box).textContent = FEEDBACK_NOT_SAVED;
      $(".send-failed", box).hidden = false;
    }
  });
  return box;
}

// ---------------------------------------------------------------------------------------------------------- boot
function boot() {
  build();
  for (const b of document.querySelectorAll(".tabs button")) b.addEventListener("click", () => {
    history.replaceState(null, "", b.dataset.tab === "chat" ? "#chat" : location.pathname + location.search);
    showTab(b.dataset.tab);
  });
  showTab(location.hash === "#chat" ? "chat" : "check");
}
boot();

// for the browser tests (web/tests): ask a question and read the turn back
window.__chat = { ask: (q) => ask(q), turns: () => JSON.parse(JSON.stringify(chat.turns)),
  posts: () => chat.posts, show: (t) => showTab(t) };
