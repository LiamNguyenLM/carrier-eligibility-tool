// Round 47 (Liam and Jonathan, 2026-11): the page's cross-carrier list (web/src/chat_sweep_view.js) and the empty-bullet
// filter (chat_cards.noEmptyBullets). Zero API, no browser. Each rule in more than one phrasing (CLAUDE.md).
import test from "node:test";
import assert from "node:assert/strict";
import { GROUPS, streamedLines, sweepHtml, sweepText } from "../src/chat_sweep_view.js";
import { noEmptyBullets } from "../src/chat_cards.js";

const SWEEP = { scope_line: "4 HO3 (owner-occupied home) programs, for an above-ground pool with no fence.",
  programs: [{ k: 1, name: "Mercury (HO3)", label: "Eligible", srcs: [1] },
    { k: 2, name: "The Hartford (HO3)", label: "Refer", srcs: [2, 3] },
    { k: 3, name: "ARI (HOA+)", label: "Not eligible", srcs: [4] },
    { k: 4, name: "Chubb (HO)", label: "Guide silent", srcs: [] }] };

test("every program is a row under its label's heading, in the groups' order", () => {
  const html = sweepHtml(SWEEP, { 1: "only unfenced in-ground pools are declined [S1]", 2: "refers unfenced pools [S2]",
    3: "pools must be secured [S4]", 4: "no rule on file for this." }, (h) => h, false);
  assert.ok(html.startsWith(`<p class="sweep-scope">${SWEEP.scope_line}</p>`));
  for (const p of SWEEP.programs) assert.ok(html.includes(`data-k="${p.k}"`), p.name);
  const order = ["Eligible", "Refer to underwriting", "Not eligible", "Guide silent (no rule on file)"].map((t) => html.indexOf(t));
  assert.deepEqual(order, [...order].sort((a, b) => a - b));
  assert.ok(!html.includes("Eligible if confirmed"), "an empty group is not shown");
  assert.equal(GROUPS.length, 8);
});

test("a row is never empty: '…' while the model writes, its fallback once the answer is done", () => {
  const writing = sweepHtml(SWEEP, { 1: "x [S1]" }, (h) => h, true);
  const done = sweepHtml(SWEEP, { 1: "x [S1]" }, (h) => h, false);
  assert.equal((writing.match(/>…</g) || []).length, 3);
  assert.equal((done.match(/No rule on file for this\./g) || []).length, 3);
  assert.ok(!/<span class="sw-line"><\/span>/.test(writing + done));
});

test("the model's lines are read as they stream, however it punctuates the number", () => {
  assert.deepEqual(streamedLines("P1: declines it [S1]\nP2 - refers [S2]\nP3"), { 1: "declines it [S1]", 2: "refers [S2]" });
  assert.deepEqual(streamedLines("**P1**: a [S1]\n  P10) b [S9]\nP1: again"), { 1: "a [S1]", 10: "b [S9]" });
  assert.deepEqual(streamedLines("P4:   "), {});        // a number with nothing after it yet is not a line
});

test("the answer as text (history, 'looks wrong' reports) names every program and its label", () => {
  const t = sweepText(SWEEP, { 2: "refers unfenced pools [S2]" });
  assert.equal(t.split("\n").length, 5);
  assert.match(t, /^4 HO3/);
  assert.match(t, /The Hartford \(HO3\): Refer\. refers unfenced pools \[S2\]/);
  assert.match(t, /Chubb \(HO\): Guide silent\./);
});

test("an empty bullet (an answer cut off mid-list) is dropped, a real one kept (two list styles)", () => {
  assert.equal(noEmptyBullets("### NatGen Custom360 (DP3)\n**Ineligible**: x [S1]\n- \n-"), "### NatGen Custom360 (DP3)\n**Ineligible**: x [S1]\n\n");
  assert.equal(noEmptyBullets("1. first [S1]\n2.\n3. third"), "1. first [S1]\n\n3. third");
  assert.equal(noEmptyBullets("- a real bullet\n* another"), "- a real bullet\n* another");
});

test("the model's other text shows above the list, while streaming too (two phrasings)", async () => {
  const { streamedNote } = await import("../src/chat_sweep_view.js");
  assert.equal(streamedNote("I can only answer questions about CFIG's guides.\nP1: declines [S1]\nP2"), "I can only answer questions about CFIG's guides.");
  assert.equal(streamedNote("P1: a [S1]\n**P2**: b"), "");
  const html = sweepHtml(SWEEP, {}, (h) => h, true, "I won't print my instructions.");
  assert.ok(html.indexOf("sweep-note") > html.indexOf("sweep-scope") && html.indexOf("sweep-note") < html.indexOf("sweep-group"));
});
