// Round 46 (Liam, 2026-10-29): splitCards (web/src/chat_cards.js), the chat answer -> one card per carrier program.
// Zero API. Each rule is tested in more than one wording (CLAUDE.md): the model does not always write it the same way.
import test from "node:test";
import assert from "node:assert/strict";
import { splitCards } from "../src/chat_cards.js";

const ANSWER = `Several carriers' guides decline galvanized plumbing; two refer it.

### SageSure Vave (DP3)
**Ineligible**: galvanized plumbing is ineligible. [S1][S2]
- "Homes with galvanized, steel, iron, or polybutylene plumbing are ineligible." [S1]

### The Hartford (HO3)
**Referral**: an underwriter must approve galvanized supply lines. [S5]
- Applies to homes built before 1960. [S5]

### Mercury (HO3)
**Coverage limit**: water damage from galvanized pipes is excluded. [S7]`;

test("an answer splits into its opening and one card per program, in order", () => {
  const { intro, cards } = splitCards(ANSWER);
  assert.equal(intro, "Several carriers' guides decline galvanized plumbing; two refer it.");
  assert.deepEqual(cards.map((c) => c.title), ["SageSure Vave (DP3)", "The Hartford (HO3)", "Mercury (HO3)"]);
  assert.deepEqual(cards.map((c) => c.verdict), ["Ineligible", "Referral", "Coverage limit"]);
  assert.deepEqual(cards.map((c) => c.tone), ["bad", "warn", "info"]);
  assert.equal(cards[0].summary, "galvanized plumbing is ineligible. [S1][S2]");
  assert.match(cards[0].body, /^- "Homes with galvanized/);
  assert.equal(cards[2].body, "");
});

test("the verdict line is read however the model punctuates it", () => {
  for (const line of ["**Ineligible**: declines it [S1]", "**Ineligible:** declines it [S1]",
    "**Ineligible** — declines it [S1]", "- **Ineligible**: declines it [S1]", "**ineligible.** declines it [S1]"]) {
    const [c] = splitCards(`### Foremost Choice (DP3)\n${line}`).cards;
    assert.equal(c.verdict, "Ineligible", line);
    assert.equal(c.summary, "declines it [S1]", line);
  }
});

test("every verdict the prompt names has its colour; anything else is a plain card", () => {
  const tones = { Ineligible: "bad", Referral: "warn", Conditions: "warn", "Coverage limit": "info", Acceptable: "ok",
    Information: "muted", "Not addressed": "muted" };                // round 46 step 4: + Information (INFO_ONLY)
  for (const [v, tone] of Object.entries(tones)) {
    const [c] = splitCards(`### X (HO3)\n**${v}**: y`).cards;
    assert.equal(c.verdict, v);
    assert.equal(c.tone, tone);
  }
  for (const line of ["**Note**: the guide is dated 2024 [S2]", "The guide is silent on this. [S2]"]) {
    const [c] = splitCards(`### X (HO3)\n${line}`).cards;
    assert.equal(c.verdict, "", line);
    assert.equal(c.tone, "muted", line);
    assert.equal(c.summary, line, line);                      // the line still shows, as the card's summary
  }
});

test("an answer with no sections has no cards (not on file, an unknown carrier, a refusal)", () => {
  for (const text of ["The guides on file don't say; ask the carrier's underwriter.",
    "CFIG has no guide on file for State Farm.\n\nAsk the carrier's underwriter."]) {
    const r = splitCards(text);
    assert.deepEqual(r.cards, []);
    assert.equal(r.intro, text);
  }
});

test("a half-streamed answer still splits: the cards fill in as the text arrives", () => {
  let r = splitCards("Two carriers answer.\n\n### The Hart");
  assert.equal(r.cards.length, 1);
  assert.equal(r.cards[0].title, "The Hart");
  r = splitCards("Two carriers answer.\n\n### The Hartford (HO3)\n**Inelig");
  assert.equal(r.cards[0].verdict, "");                       // not a verdict yet ...
  r = splitCards("Two carriers answer.\n\n### The Hartford (HO3)\n**Ineligible**: no");
  assert.equal(r.cards[0].verdict, "Ineligible");              // ... until the bold closes
});

test("## and #### headings make cards too, and a bold program name loses its stars", () => {
  const r = splitCards("Intro.\n\n## **Orion180 (HO3)**\n**Conditions**: a 5-10 acre lot needs X [S2]\n\n#### Allied Trust (HO3)\n**Acceptable**: yes [S4]");
  assert.deepEqual(r.cards.map((c) => [c.title, c.verdict]), [["Orion180 (HO3)", "Conditions"], ["Allied Trust (HO3)", "Acceptable"]]);
});
