// Round 43 step 2 (Liam, 2026-10-24): the Eligibility Check tab of app.py as a static page. The form is built from
// engine.form.form_spec(); every rule about the form -- which follow-up questions show, the ZIP -> County prefill,
// the captions, the property_details the submit builds -- runs in Python (engine/form.py, which app.py uses too).
// This file only renders, wires the widgets' events, and puts the engine's strings on the page.

import { Engine } from "./engine.js";
import { markdown, escapeHtml } from "./markdown.js";
import * as worker from "./worker_api.js";

const params = new URLSearchParams(location.search);
const engine = new Engine();
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const now = () => performance.now();
const nextFrame = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));
// the same words as the Worker's FEEDBACK_NOT_SAVED (cloudflare/src/routes.js), which answers a failed D1 write
const FEEDBACK_NOT_SAVED = "Couldn’t save — try again later.";

// The results page's strings: form_spec()["results"] (engine/form.py). Only the f-string parts are put together
// here.
let T = null;
let COLUMNS = null;
const h3 = (md) => md.replace(/^#+\s*/, "");

function resultTexts(R) {
  T = {
    analysis: R.analysis, inspection: R.inspection, fallback: R.fallback, unusable: R.unusable,
    notChecked: (names) => `Could not check ${names.length} carrier${names.length !== 1 ? "s" : ""}: `
      + names.join(", ") + R.not_checked_tail,
    topBoxTitle: R.top_box_title.replace(/\n$/, ""),
    topBoxLine: (text, n, of) => `- ${text} — asked by ${n} of ${of} carriers`,
    topBoxCaption: R.top_box_caption, partialEligible: R.partial_eligible, couldNot: h3(R.could_not_title),
    missing: R.missing.replace(/\n$/, ""),
  };
  COLUMNS = R.columns.map((c) => ({ ...c, title: h3(c.title) }));
}

const state = {
  spec: null, fields: new Map(), values: {}, chk: {}, shown: {},
  lastForm: null, lastResult: null, lastTimings: null, seq: 0, placementPromise: Promise.resolve(),
  build: null, who: null, loadTimings: null, posts: [],
};

// ---------------------------------------------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------------------------------------------
const hook = {
  ready: false, error: null, mode: "engine",
  whenReady: null,
  loadTimings: () => state.loadTimings,
  fillForm: (pd, checked) => fillForm(pd, checked),
  submit: () => submit(),
  runCheck: (pd, checked) => runAndRender(pd, checked),
  runCheckJson: (pdJson, checked) => runAndRender(JSON.parse(pdJson), checked, pdJson),
  lastForm: () => clone(state.lastForm),
  lastResult: () => clone(state.lastResult),
  lastTimings: () => clone(state.lastTimings),
  readResults: () => readResultsFromDom(),
  placementSettled: () => state.placementPromise,
  spec: () => state.spec,
  call: (fn, ...args) => engine.api(fn, ...args),
};
window.__eligibility = hook;

hook.whenReady = (async () => {
  const t0 = now();
  const status = $("#loading");
  try {
    state.build = await worker.buildInfo(engine.url("build.json"));
    worker.whoami().then(showWho);
    await engine.load();
    const t1 = now();
    state.spec = await engine.formSpec();
    resultTexts(state.spec.results);
    const t2 = now();
    buildForm(state.spec);
    if (state.who) showWho(state.who);        // round 44: whoami usually answers first; now the name field exists
    const t3 = now();
    state.loadTimings = { ...engine.timings, spec_s: (t2 - t1) / 1000, form_s: (t3 - t2) / 1000,
                          total_s: (t3 - t0) / 1000 };
    status.remove();
    hook.ready = true;
  } catch (e) {
    hook.error = String(e && e.stack || e);
    status.className = "alert error";
    status.textContent = "The rules engine did not load: " + e;
    throw e;
  }
})();

function showWho(who) {
  state.who = who;
  const el = $("#who");
  if (!who) return;
  // round 44: under the password gate there is no email -- the name typed at the login, if any -- and its own logout
  el.innerHTML = `<span class="email">${escapeHtml(who.email || who.name || "Signed in")}</span>`
    + (who.admin ? ` · <a href="/api/admin/feedback.csv" id="dl-feedback">Download feedback</a>` : "")
    + ` · <a href="${escapeHtml(who.logout || "/cdn-cgi/access/logout")}">Log out</a>`;
  const nameField = $("#f-tester_name");
  if (nameField && who.name && !nameField.value) nameField.value = who.name;      // the login's name, for feedback
  const dl = $("#dl-feedback");
  if (dl) dl.addEventListener("click", (e) => { e.preventDefault(); downloadFeedback(); });
}

// Round 43 step 3: the Worker sends the feedback 300 reports at a time (the Free plan's 10 ms CPU); fetch every part
// and save one file.
async function downloadFeedback() {
  const chunks = [];
  let parts = 1;
  for (let part = 1; part <= parts; part++) {
    const r = await fetch(`/api/admin/feedback.csv?part=${part}`, { credentials: "same-origin" });
    if (!r.ok) { alert(`Could not download the feedback (HTTP ${r.status}).`); return; }
    parts = Number(r.headers.get("x-feedback-parts") || "1");
    chunks.push(await r.text());
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob(chunks, { type: "text/csv" }));
  a.download = "feedback_log.csv";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
}

// ---------------------------------------------------------------------------------------------------------------
// The form
// ---------------------------------------------------------------------------------------------------------------
function buildForm(spec) {
  document.title = spec.texts.page_title;
  for (const f of spec.fields) {
    state.fields.set(f.key, f);
    state.values[f.key] = clone(f.default);
  }
  for (const t of spec.topics) state.chk[t.key] = false;
  const tx = spec.texts;
  const root = $("#app");
  root.innerHTML = `
    <h1>${escapeHtml(tx.title)}</h1>
    <div class="caption">${escapeHtml(tx.caption)}</div>
    <details class="expander"><summary>${escapeHtml(tx.about_label)}</summary>
      <div class="md">${markdown(tx.tester_note)}</div></details>
    <div class="field" data-key="tester_name">
      <label for="f-tester_name">${escapeHtml(tx.name_label)}${help(tx.name_help)}</label>
      <input type="text" id="f-tester_name" autocomplete="name">
    </div>
    <div class="select-buttons">
      <button type="button" id="select-all">${escapeHtml(tx.select_all)}</button>
      <button type="button" id="clear-all">${escapeHtml(tx.clear)}</button>
    </div>
    <div class="caption">${escapeHtml(tx.scope_caption)}</div>
    <div id="form"></div>
    <button type="button" id="submit" class="primary wide">${escapeHtml(tx.submit)}</button>
    <div id="submit-error"></div>
    <div id="results" aria-live="polite"></div>`;
  const form = $("#form");
  for (const block of spec.layout) form.append(renderBlock(block));
  form.addEventListener("change", onChange);
  $("#f-tester_name").addEventListener("change", () => clearResults());
  $("#select-all").addEventListener("click", () => { setAll(true); clearResults(); });
  $("#clear-all").addEventListener("click", () => { setAll(false); clearResults(); });
  $("#submit").addEventListener("click", () => { submit(); });
  refresh();
}

function help(text) {
  return text ? ` <span class="help" title="${escapeHtml(text)}" aria-label="${escapeHtml(text)}">?</span>` : "";
}

function renderBlock(block) {
  const el = document.createElement("div");
  if (block.type === "divider") { el.innerHTML = "<hr>"; return el.firstChild; }
  if (block.type === "section") {
    el.className = "section";
    el.innerHTML = `<h3>${escapeHtml(block.title)}</h3>`;
    el.append(renderColumns(block.columns));
  } else if (block.type === "columns") {
    el.className = "section";
    el.append(renderColumns(block.columns));
  } else if (block.type === "row") {
    el.className = "row";
    for (const item of block.items) el.append(renderItem(item));
  }
  return el;
}

function renderColumns(columns) {
  const cols = document.createElement("div");
  cols.className = `cols cols-${columns.length}`;
  for (const col of columns) {
    const c = document.createElement("div");
    c.className = "col";
    for (const item of col) c.append(renderItem(item));
    cols.append(c);
  }
  return cols;
}

function renderItem(item) {
  const el = document.createElement("div");
  if (typeof item === "string") return renderField(state.fields.get(item));
  if (item.check) {
    const tx = state.spec.texts;
    el.className = "check";
    el.dataset.topic = item.check;
    el.innerHTML = `<label title="${escapeHtml(tx.check_help)}"><input type="checkbox" data-topic="${item.check}"
      id="chk-${item.check}"> ${escapeHtml(tx.check_label)}${help(tx.check_help)}</label>
      <div class="caption not-checked">${escapeHtml(tx.not_checked)}</div>`;
    return el;
  }
  if (item.messages) { el.className = "messages"; el.dataset.messages = item.messages; return el; }
  if (item.caption) { el.className = "caption"; el.textContent = item.caption; return el; }
  throw new Error("unknown layout item " + JSON.stringify(item));
}

function renderField(f) {
  const el = document.createElement("div");
  el.className = `field kind-${f.kind}`;
  el.dataset.key = f.key;
  const id = `f-${f.key}`;
  const label = `${escapeHtml(f.label)}${help(f.help)}`;
  const options = () => f.choices.map((c, i) =>
    `<option value="${escapeHtml(c)}">${escapeHtml(f.labels[i])}</option>`).join("");
  switch (f.kind) {
    case "select":
      el.innerHTML = `<label for="${id}">${label}</label><select id="${id}">${options()}</select>`;
      break;
    case "text":
      el.innerHTML = `<label for="${id}">${label}</label>
        <input type="text" id="${id}" placeholder="${escapeHtml(f.placeholder || "")}">`;
      break;
    case "number":
      el.innerHTML = `<label for="${id}">${label}</label>
        <input type="number" id="${id}" min="${f.min}" max="${f.max}" step="${f.step || 1}">`;
      break;
    case "radio":
      el.innerHTML = `<fieldset><legend>${label}</legend><div class="radios">${f.choices.map((c, i) =>
        `<label><input type="radio" name="${id}" value="${escapeHtml(c)}"> ${escapeHtml(f.labels[i])}</label>`)
        .join("")}</div></fieldset>`;
      break;
    case "toggle":
      el.innerHTML = `<label class="toggle"><input type="checkbox" role="switch" id="${id}">
        <span class="track"></span> ${label}</label>`;
      break;
    case "checkbox":
      el.innerHTML = `<label class="checkbox"><input type="checkbox" id="${id}"> ${label}</label>`;
      break;
    case "multiselect":
      el.innerHTML = `<fieldset><legend>${label}</legend>
        ${f.placeholder ? `<div class="caption">${escapeHtml(f.placeholder)}</div>` : ""}
        <div class="multi-opts">${f.choices.map((c, i) =>
          `<label><input type="checkbox" value="${escapeHtml(c)}"> ${escapeHtml(f.labels[i])}</label>`).join("")}</div>
        <div class="multi-picked caption"></div></fieldset>`;
      break;
    default:
      throw new Error("unknown field kind " + f.kind);
  }
  writeDom(f.key, state.values[f.key], el);
  return el;
}

// The widget's value as app.py's widget returns it.
function readDom(key) {
  const f = state.fields.get(key);
  const el = $(`[data-key="${key}"]`);
  switch (f.kind) {
    case "select": case "text": return $("select,input", el).value;
    case "number": { const v = $("input", el).value; return v === "" ? null : Number(v); }
    case "toggle": case "checkbox": return $("input", el).checked;
    case "radio": { const r = $("input:checked", el); return r ? r.value : f.default; }
    case "multiselect": return state.values[key];          // kept in pick order by onChange
    default: return undefined;
  }
}

function writeDom(key, value, el = $(`[data-key="${key}"]`)) {
  const f = state.fields.get(key);
  if (!el) return;
  switch (f.kind) {
    case "select": case "text": $("select,input", el).value = value ?? ""; break;
    case "number": $("input", el).value = value == null ? "" : String(value); break;
    case "toggle": case "checkbox": $("input", el).checked = !!value; break;
    case "radio": for (const r of $$("input", el)) r.checked = r.value === value; break;
    case "multiselect":
      for (const c of $$(".multi-opts input", el)) c.checked = (value || []).includes(c.value);
      $(".multi-picked", el).textContent = (value || []).length ? "Picked: " + value.join("; ") : "";
      break;
    default: break;
  }
}

function setValue(key, value) {
  state.values[key] = clone(value);
  writeDom(key, value);
}

function onChange(ev) {
  const t = ev.target;
  if (t.dataset.topic) {                                    // a "Check this" box
    state.chk[t.dataset.topic] = t.checked;
    refresh();
    clearResults();
    return;
  }
  const wrap = t.closest("[data-key]");
  if (!wrap) return;
  const key = wrap.dataset.key;
  const f = state.fields.get(key);
  if (f.kind === "multiselect") {                           // Streamlit keeps the order things were picked in
    const cur = (state.values[key] || []).filter((x) => x !== t.value);
    state.values[key] = t.checked ? [...cur, t.value] : cur;
    writeDom(key, state.values[key]);
  } else if (f.kind === "number") {
    let v = readDom(key);
    if (v != null && Number.isFinite(v)) {                  // st.number_input never holds a value outside its range
      v = Math.round(Math.min(Math.max(v, f.min), f.max));
      writeDom(key, v);
    }
    state.values[key] = v;
  } else {
    state.values[key] = readDom(key);
  }
  fieldChanged(key);
}

// app.py's on_change callbacks, then the rerun.
function fieldChanged(key) {
  const f = state.fields.get(key);
  if (f.topic && !same(state.values[key], f.default)) setChk(f.topic, true);       // _autotick
  for (const g of state.spec.fields) {                      // a key that holds this answer starts again (app.py 344)
    if (g.reset_on === key) setValue(g.key, g.default);
  }
  if (key === "zip") {                                      // _zip_changed
    const r = engine.api("zip_changed", state.values.zip);
    setValue("county", r.county);
    if (r.tick_county) setChk("county", true);
  }
  refresh();
  clearResults();
}

function setChk(topic, on) {
  state.chk[topic] = on;
  const box = $(`#chk-${topic}`);
  if (box) box.checked = on;
}

function setAll(on) {
  for (const t of state.spec.topics) setChk(t.key, on);
  refresh();
}

function isShown(f) {
  const c = f.show_if;
  if (!c) return true;
  const v = state.values[c.field];
  if (c.in) return c.in.some((x) => same(x, v));
  if (c.not_in) return !c.not_in.some((x) => same(x, v));
  return true;
}

// The rerun: which questions show (a hidden one goes back to its default, as Streamlit drops a widget's state when
// it is not drawn), the captions under ZIP / amount / solar, and the "Not checked" lines.
function refresh() {
  for (const f of state.spec.fields) {
    const shown = isShown(f);
    if (!shown && !same(state.values[f.key], f.default)) setValue(f.key, f.default);
    $(`[data-key="${f.key}"]`).hidden = !shown;
    state.shown[f.key] = shown;
  }
  const msgs = engine.api("form_messages", formValues());
  for (const slot of $$("[data-messages]")) {
    slot.innerHTML = (msgs[slot.dataset.messages] || []).map((m) => m.kind === "warning"
      ? `<div class="alert warning">${escapeHtml(m.text)}</div>`
      : `<div class="caption">${escapeHtml(m.text)}</div>`).join("");
  }
  for (const c of $$(".check[data-topic]")) {
    $(".not-checked", c).hidden = !!state.chk[c.dataset.topic];
  }
}

function formValues() {
  return { ...clone(state.values), chk: { ...state.chk }, tester_name: $("#f-tester_name")?.value || "" };
}

// ---------------------------------------------------------------------------------------------------------------
// Submit and results
// ---------------------------------------------------------------------------------------------------------------
async function submit() {
  const req = engine.api("form_request", formValues());
  state.lastForm = { property_details: req.property_details, checked_topics: req.checked_topics,
                     error: req.error || null };
  $("#submit-error").innerHTML = "";
  if (!req.ok) {
    clearResults();
    $("#submit-error").innerHTML = `<div class="alert error">${escapeHtml(req.error)}</div>`;
    return { ok: false, error: req.error };
  }
  return runAndRender(req.property_details, req.checked_topics, req.property_details_json);
}

function clearResults() {
  state.seq++;
  const r = $("#results");
  if (r) r.innerHTML = "";
}

async function runAndRender(pd, checked, pdJson = null) {
  const t0 = now();
  clearResults();
  const seq = state.seq;
  const results = $("#results");
  results.innerHTML = `<div class="spinner">${escapeHtml(state.spec.texts.spinner)}</div>`;
  await nextFrame();
  let result, engine_s;
  try {
    ({ result, engine_s } = await engine.check(pd, checked, pdJson));
  } catch (e) {
    results.innerHTML = `<div class="alert error">The check failed: ${escapeHtml(String(e.message || e))}</div>`;
    state.lastResult = null;
    state.lastTimings = null;
    return { ok: false, error: String(e.message || e) };
  }
  const t1 = now();
  results.innerHTML = renderResults(result, pd, checked);
  wireFeedback(results, result, pd, checked);
  const render_s = (now() - t1) / 1000;
  state.lastResult = result;
  state.lastTimings = { engine_s, render_s, placement_s: null };
  state.placementPromise = placementAndUsage(result, seq, t0, engine_s, render_s);
  return { ok: true, engine_s, render_s };
}

async function placementAndUsage(result, seq, t0, engine_s, render_s) {
  const tp = now();
  let panel = null;
  try {
    panel = await worker.placement(engine.api("placement_request", result));
    if (panel && seq === state.seq) {
      const md = engine.api("placement_markdown", panel);
      $("#placement-slot").innerHTML = `<div class="box placement"><div class="md">${markdown(md)}</div>
        <div class="caption">${escapeHtml(panel.footer || "")}</div></div>`;
    }
  } catch (e) {
    panel = null;                                         // the panel never breaks a check
  }
  const placement_s = (now() - tp) / 1000;
  if (state.lastTimings && seq === state.seq) state.lastTimings.placement_s = placement_s;
  const wall_s = (now() - t0) / 1000;
  try {
    worker.usage(engine.api("usage_record", appVersion(), wall_s, (result.cards || []).length, engine_s, render_s,
                            placement_s));
  } catch { /* ignored */ }
  return { panel: !!panel, placement_s };
}

function appVersion() { return (state.build && state.build.commit) || "unknown"; }

function renderResults(res, pd, checked) {
  const h = res.header || {};
  const partial = !!h.partial_line;
  const parts = [`<hr><h2 class="analysis">${escapeHtml(T.analysis)}</h2>`,
                 `<div class="caption">${escapeHtml(T.inspection)}</div>`];
  if (h.fallback) parts.push(`<div class="caption">${escapeHtml(T.fallback)}</div>`);
  if (partial) parts.push(`<div class="alert info">${escapeHtml(h.partial_line)}</div>`);
  if (h.usable_answers === 0) parts.push(`<div class="alert error">${escapeHtml(T.unusable)}</div>`);
  if ((h.not_checked_names || []).length) {
    parts.push(`<div class="alert warning">${escapeHtml(T.notChecked(h.not_checked_names))}</div>`);
  }
  if ((res.top_box || []).length) {
    const md = T.topBoxTitle + "\n" + res.top_box.map(([t, n, of]) => T.topBoxLine(t, n, of)).join("\n");
    parts.push(`<div class="box top-box"><div class="md">${markdown(md)}</div>
      <div class="caption">${escapeHtml(T.topBoxCaption)}</div></div>`);
  }
  parts.push(`<div id="placement-slot"></div>`);
  const cards = res.cards || [];
  const cols = res.columns || {};
  parts.push(`<div class="cols cols-4 verdicts">`);
  for (const c of COLUMNS) {
    const idx = cols[c.key] || [];
    parts.push(`<div class="col" data-col="${c.key}"><h3>${escapeHtml(c.title)}</h3>`);
    if (c.key === "eligible" && partial) parts.push(`<div class="caption">${escapeHtml(T.partialEligible)}</div>`);
    if (idx.length) for (const i of idx) parts.push(renderCard(cards[i], i, c.key));
    else parts.push(`<div class="alert ${c.kind}">${escapeHtml(c.empty)}</div>`);
    parts.push(`</div>`);
  }
  parts.push(`</div>`);
  const cnc = cols.could_not_check || [];
  if (cnc.length) {
    parts.push(`<div class="could-not" data-col="could_not_check"><h3>${escapeHtml(T.couldNot)}</h3>`);
    for (const i of cnc) parts.push(renderCouldNot(cards[i], i));
    parts.push(`</div>`);
  }
  parts.push(rawScript("results-raw", { top_box: res.top_box || [], header: h, columns: cols }));
  return parts.join("\n");
}

const RAW_KEYS = ["carrier", "status", "name", "first", "missing", "confirm_html", "details_html", "ids_html",
                  "warning"];

function rawScript(cls, obj) {
  // "<" escaped so no string can close the script element
  return `<script type="application/json" class="${cls}">${JSON.stringify(obj).replace(/</g, "\\u003c")}</script>`;
}

function cardAttrs(card, i, column) {
  return `data-index="${i}" data-carrier="${escapeHtml(card.carrier)}" data-status="${escapeHtml(card.status)}"
    data-column="${column}"`;
}

function rawOf(card) {
  return Object.fromEntries(RAW_KEYS.map((k) => [k, card[k]]));
}

// app.py render_carrier, inside the card's expander
function renderCard(card, i, column) {
  const body = [`<div class="card-first md">${markdown(card.first)}</div>`];
  if ((card.missing || []).length) {
    body.push(`<div class="card-missing md">${markdown(T.missing + "\n" + card.missing.map((m) => "- " + m)
      .join("\n"))}</div>`);
  }
  if (card.confirm_html) body.push(`<div class="card-confirm html">${card.confirm_html}</div>`);
  if (card.details_html) body.push(`<div class="card-details html">${card.details_html}</div>`);
  if (card.ids_html) body.push(`<div class="card-ids html">${card.ids_html}</div>`);
  body.push(feedbackControl(i));
  return `<details class="card" ${cardAttrs(card, i, column)}><summary>${escapeHtml(card.name)}</summary>
    <div class="card-body">${body.join("\n")}</div>${rawScript("card-raw", rawOf(card))}</details>`;
}

// app.py 672-681: the warning line, Details, and "This looks wrong"
function renderCouldNot(card, i) {
  return `<div class="could-not-row" ${cardAttrs(card, i, "could_not_check")}>
    <div class="alert warning md">${markdown(card.warning)}</div>
    ${card.details_html ? `<div class="card-details html">${card.details_html}</div>` : ""}
    ${feedbackControl(i)}${rawScript("card-raw", rawOf(card))}</div>`;
}

function feedbackControl(i) {
  const tx = state.spec.texts;
  const choices = state.spec.feedback_choices;
  const name = `fb-${state.seq}-${i}`;
  return `<details class="feedback" data-fb="${i}"><summary>${escapeHtml(tx.feedback_label)}</summary>
    <div class="alert success sent" hidden>${escapeHtml(tx.feedback_sent)}</div>
    <div class="alert error send-failed" hidden></div>
    <form class="fb-form">
      <fieldset><legend>${escapeHtml(tx.feedback_radio)}</legend>${choices.map((c, k) =>
        `<label><input type="radio" name="${name}" value="${escapeHtml(c)}" ${k === choices.length - 1 ? "checked" : ""}>
         ${escapeHtml(c)}</label>`).join("")}</fieldset>
      <label>${escapeHtml(tx.feedback_comment)}<textarea name="comment" rows="3"></textarea></label>
      <button type="submit">${escapeHtml(tx.feedback_send)}</button>
    </form></details>`;
}

function wireFeedback(root, res, pd, checked) {
  for (const box of $$("details.feedback", root)) {
    const card = res.cards[Number(box.dataset.fb)];
    const form = $("form", box);
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const choice = ($("input[type=radio]:checked", form) || {}).value;
      const comment = form.elements.comment.value;
      const record = engine.api("feedback_record", card, pd, choice, comment, $("#f-tester_name").value, checked,
                                appVersion());
      $(".send-failed", box).hidden = true;
      try {
        await worker.feedback(record);
        state.posts.push({ kind: "feedback", record });
        $(".sent", box).hidden = false;
        form.reset();                                        // clear_on_submit=True
      } catch (e) {
        // round 44b (Liam, 2026-10-25): one message for every failure -- D1 refusing the write (the Worker's 503),
        // a timeout or no network. What was typed stays in the form for the retry.
        console.error("feedback not saved --", e);
        $(".sent", box).hidden = true;
        $(".send-failed", box).textContent = FEEDBACK_NOT_SAVED;
        $(".send-failed", box).hidden = false;
      }
    });
  }
}

// What a test reads back: every card in the engine's order, with its column and its raw strings.
function readResultsFromDom() {
  const root = $("#results");
  const raw = $("script.results-raw", root);
  if (!raw) return null;
  const cards = $$("[data-carrier]", root).map((el) => {
    const r = JSON.parse($("script.card-raw", el).textContent);
    return { index: Number(el.dataset.index), carrier: el.dataset.carrier, status: el.dataset.status,
             column: el.dataset.column, in_column: el.closest("[data-col]")?.dataset.col || null, ...r,
             raw_carrier: r.carrier };
  }).sort((a, b) => a.index - b.index);
  const top = JSON.parse(raw.textContent);
  return { top_box: top.top_box, header: top.header, cards,
           placement_shown: !!$("#placement-slot .placement", root) };
}

// ---------------------------------------------------------------------------------------------------------------
// Test hook: fill the form from a profile, through the widgets' own DOM events
// ---------------------------------------------------------------------------------------------------------------
const yes = (v) => v === "Yes";
const numText = (v) => (v == null ? "" : String(v));

// pd key -> widget, in the order a person fills the form (a question appears only after the answer it follows)
const FILL_PLAN = [
  ["occupancy_type", "occupancy"], ["ownership_type", "ownership"], ["trust_type", "trust_type"],
  ["primary_home_carrier", () => (state.shown.primary_carrier ? "primary_carrier"
    : state.shown.owner_home_carrier ? "owner_home_carrier" : "primary_carrier")],
  ["primary_home_miles", "primary_miles", numText], ["rental_units_total", "rental_units"],
  ["rental_term", "rental_term"],
  ["ppc", "ppc"], ["fire_station_miles", "station_miles", numText], ["hydrant_1000ft", "hydrant"],
  ["coastal_tier", "coastal", (v) => { const f = state.fields.get("coastal"); return f.choices[f.pd_values.indexOf(v)]; }],
  ["has_dogs", "dogs", yes], ["dog_breeds", "dog_breeds"],
  ["year_built", "year"], ["roof_age", "roofage"],
  ["roof_type", "rooftype"], ["construction_type", "construction"], ["plumbing_type", "plumbing"],
  ["roof_shape", "roofshape"],
  ["swimming_pool", "pool"], ["pool_accessories", "poolacc"], ["pool_fence_4ft", "pool_fence_4ft"],
  ["pool_gate_locking", "pool_gate_locking"],
  ["solar_panels", "solar", yes], ["solar_type", "solar_type"], ["solar_tesla", "solar_tesla"],
  ["zip", "zip"], ["county", "county"], ["harris_east_146", "harris_east_146"],
  ["dwelling_amount", "dwelling_amount", numText], ["dwelling_type", "dwelling_type"],
  ["units_in_building", "units_in_building"],
  ["losses_5yr", "losses_5yr"], ["loss_types", "loss_types"], ["loss_year", "loss_year"],
  ["losses_3yr", "losses_3yr"], ["electrical", "electrical"],
];

function resetForm() {
  for (const f of state.spec.fields) setValue(f.key, f.default);
  for (const t of state.spec.topics) setChk(t.key, false);
  const name = $("#f-tester_name");
  if (name) name.value = "";
  refresh();
  clearResults();
}

const fire = (el, type) => el.dispatchEvent(new Event(type, { bubbles: true }));

// Set one widget as a person would: a value it cannot hold is reported, never forced.
function domSet(key, value) {
  const f = state.fields.get(key);
  const el = $(`[data-key="${key}"]`);
  switch (f.kind) {
    case "select": {
      const s = $("select", el);
      if (!f.choices.some((c) => c === value)) return `not one of the choices: ${JSON.stringify(value)}`;
      if (s.value !== value) { s.value = value; fire(s, "input"); fire(s, "change"); }
      return null;
    }
    case "text": case "number": {
      const i = $("input", el);
      const text = value == null ? "" : String(value);
      if (f.kind === "number" && text !== "" && !Number.isFinite(Number(text))) return `not a number: ${text}`;
      if (i.value !== text) { i.value = text; fire(i, "input"); fire(i, "change"); }
      return null;
    }
    case "toggle": case "checkbox": {
      if (typeof value !== "boolean") return `not true/false: ${JSON.stringify(value)}`;
      const i = $("input", el);
      if (i.checked !== value) i.click();
      return null;
    }
    case "radio": {
      const r = $$("input", el).find((x) => x.value === value);
      if (!r) return `not one of the choices: ${JSON.stringify(value)}`;
      if (!r.checked) r.click();
      return null;
    }
    case "multiselect": {
      if (!Array.isArray(value)) return `not a list: ${JSON.stringify(value)}`;
      const bad = value.filter((v) => !f.choices.includes(v));
      for (const v of value) {
        const c = $$(".multi-opts input", el).find((x) => x.value === v);
        if (c && !c.checked) c.click();
      }
      return bad.length ? `not among the choices: ${JSON.stringify(bad)}` : null;
    }
    default: return `unknown widget ${f.kind}`;
  }
}

async function fillForm(pd, checked) {
  resetForm();
  const notes = [];
  for (const [pdKey, w, conv] of FILL_PLAN) {
    if (!(pdKey in pd)) continue;
    const key = typeof w === "function" ? w() : w;
    const f = state.fields.get(key);
    const value = conv ? conv(pd[pdKey]) : pd[pdKey];
    if (!state.shown[key]) {
      if (!same(value, f.default)) notes.push({ key: pdKey, why: `question not shown (${JSON.stringify(f.show_if)})` });
      continue;
    }
    if (value === undefined) { notes.push({ key: pdKey, why: `no widget value for ${JSON.stringify(pd[pdKey])}` }); continue; }
    const err = domSet(key, value);
    if (err) notes.push({ key: pdKey, why: err });
  }
  for (const k of Object.keys(pd)) {
    if (!FILL_PLAN.some(([p]) => p === k)) notes.push({ key: k, why: "no question on the form for this key" });
  }
  const want = checked == null ? null : new Set(checked);
  const topics = state.spec.topics.map((t) => t.key);
  if (want) for (const t of want) if (!topics.includes(t)) notes.push({ key: "checked", why: `topic ${t} has no box` });
  for (const t of topics) {
    const box = $(`#chk-${t}`);
    const on = want ? want.has(t) : true;
    if (box.checked !== on) box.click();
  }
  return { notes };
}

// ---------------------------------------------------------------------------------------------------------------
function same(a, b) { return JSON.stringify(a ?? null) === JSON.stringify(b ?? null); }
function clone(v) { return v === undefined ? undefined : JSON.parse(JSON.stringify(v)); }
