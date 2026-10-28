// Ask the Guides (round 45): the words, shared by the index builder (scripts/build_chat_index.mjs) and the Worker
// (chat.js), so a guide and a question are cut into terms the same way.

const STOP = new Set(("a an and are as at be been being but by can could do does did for from had has have how i if "
  + "in into is it its may me might must my no nor not of on or our should so such than that the their them then "
  + "there these they this those to too under up upon was we were what when where which while who whom why will "
  + "with would you your yes take takes accept accepts allow allows write writes carrier carriers guide guides "
  + "any all also about there's what's whats ok okay please tell know").split(" "));

/** Lower case, letters and digits only; "1,000,000" -> "1000000"; "HO-3" -> "ho3"; "Mercury's" -> "mercury". */
export function normalize(s) {
  return String(s || "").toLowerCase()
    .replace(/([a-z0-9])[‘’']s\b/g, "$1")
    .replace(/[‘’']/g, "")
    .replace(/(\d),(\d{3})/g, "$1$2")
    .replace(/\b(ho|dp|tdp|df)[\s-]+(\d)\b/g, "$1$2");
}

/** A light English stemmer: plurals and the common verb endings, enough to match "pools" with "pool". */
export function stem(w) {
  if (w.length <= 3 || /^\d/.test(w)) return w;
  if (w.endsWith("ies") && w.length > 4) return w.slice(0, -3) + "y";
  if (w.endsWith("sses")) return w.slice(0, -2);
  if (w.endsWith("ing") && w.length > 5) return w.slice(0, -3);
  if (w.endsWith("ed") && w.length > 4) return w.slice(0, -2);
  if (w.endsWith("es") && /(ch|sh|x|z)es$/.test(w)) return w.slice(0, -2);
  if (w.endsWith("s") && !w.endsWith("ss") && !w.endsWith("us") && !w.endsWith("is")) return w.slice(0, -1);
  return w;
}

/** The terms of a text, in order (stop words dropped, stemmed). */
export function terms(text) {
  const out = [];
  for (const w of normalize(text).split(/[^a-z0-9$]+/)) {
    if (!w || STOP.has(w) || (w.length < 2 && !/\d/.test(w))) continue;
    out.push(stem(w));
  }
  return out;
}

// A question's words -> more terms guides use for the same thing. Only the question is expanded, never the index.
// Keys and values are already-stemmed terms; a value with a space adds every term in it.
export const SYNONYMS = {
  fpe: "federal pacific stab lok", stablok: "federal pacific stab lok", zinsco: "zinsco sylvania",
  galvanized: "galvanize steel pipe plumb", galvanised: "galvanize steel pipe plumb", pex: "pex plumb",
  polybutylene: "polybutylene pb plumb", kitec: "kitec plumb", cast: "cast iron",
  trampoline: "trampoline", diving: "diving board", slide: "slide pool", pool: "pool swim", swimming: "pool swim",
  dog: "dog canine breed animal", dogs: "dog canine breed animal", pitbull: "pit bull dog breed",
  breed: "breed dog canine", animal: "animal dog exotic",
  roof: "roof", shingle: "shingle composition roof", metal: "metal roof", tile: "tile roof",
  rental: "rental tenant landlord dwelling", tenant: "tenant rental landlord", landlord: "landlord tenant rental",
  vacant: "vacant vacancy unoccupied", vacancy: "vacant vacancy unoccupied", seasonal: "seasonal secondary",
  secondary: "secondary seasonal", llc: "llc corporation entity", trust: "trust trustee",
  loss: "loss claim", claim: "claim loss", water: "water", wind: "wind hail", hail: "hail wind",
  wire: "wire wiring electrical", wiring: "wire wiring electrical", aluminum: "aluminum wire",
  knob: "knob tube wiring", panel: "panel breaker electrical", fuse: "fuse electrical",
  woodstove: "wood stove burning heat", stove: "stove wood burning heat", fireplace: "fireplace heat",
  solar: "solar panel", tesla: "tesla solar", mobile: "mobile manufactured", manufactured: "manufactured mobile",
  townhome: "townhome townhouse rowhouse", townhouse: "townhome townhouse", condo: "condo condominium unit ho6",
  acre: "acre acreage", acreage: "acre acreage", farm: "farm ranch", ranch: "ranch farm",
  coastal: "coastal tier coast wind", tier: "tier coastal", county: "county", ppc: "ppc protection class fire",
  hydrant: "hydrant fire protection", foundation: "foundation pier beam slab", stilts: "stilt pier elevat",
  flood: "flood", age: "age year old", old: "age year old", year: "year age built",
  coverage: "coverage limit", minimum: "minimum min", maximum: "maximum max", limit: "limit", value: "value",
  inspection: "inspection inspect", vacation: "short term rental vacation airbnb", airbnb: "short term rental airbnb",
  business: "business home occupancy", daycare: "day care business",
};

// Question words -> the rules tables' Topic column (a rule row on a matching topic ranks higher).
export const TOPIC_WORDS = {
  POOL: "pool swim diving slide trampoline", LIABILITY_HAZARDS: "trampoline diving skateboard liability hazard",
  ANIMALS: "dog canine breed animal pit bull rottweiler exotic livestock", ROOF_ELIG: "roof shingle metal tile flat",
  ROOF_SETTLEMENT: "roof settlement acv depreciation", PLUMBING: "plumb pipe galvanize polybutylene pex kitec",
  ELECTRICAL: "electrical wire wiring panel breaker fuse federal pacific zinsco knob aluminum amp",
  OCCUPANCY: "occupancy owner tenant rental landlord vacant vacancy seasonal secondary primary short term",
  OWNERSHIP: "llc trust trustee corporation estate ownership owner", LOSS_HISTORY: "loss claim prior history",
  LOCATION: "county zip coastal tier location territory", DWELLING_LIMITS: "coverage limit minimum maximum value",
  PROTECTION_CLASS: "ppc protection class fire station hydrant", SOLAR: "solar tesla",
  FOUNDATION: "foundation pier beam slab stilt", HOME_AGE: "age year old built", FLOOD: "flood",
  ACREAGE: "acre acreage farm ranch", DWELLING_TYPE: "mobile manufactured townhome townhouse condo duplex modular",
  CONSTRUCTION: "construction frame masonry brick log", INSPECTIONS: "inspection inspect",
  OTHER_SYSTEMS: "hvac heat stove fireplace woodstove water heater", PRODUCT_STATUS: "closed new business moratorium",
};

/** {topic: Set(terms)} from TOPIC_WORDS, stemmed. */
export function topicTerms() {
  const out = {};
  for (const [topic, words] of Object.entries(TOPIC_WORDS)) out[topic] = new Set(terms(words));
  return out;
}

// SYNONYMS keyed by the stemmed word, since questions are stemmed before the lookup ("galvanized" -> "galvaniz")
const SYN_BY_STEM = Object.fromEntries(Object.entries(SYNONYMS).map(([k, v]) => [stem(k), v]));

/** The question's terms plus their synonyms: [{term, weight}] (a synonym counts half). */
export function queryTerms(question) {
  const base = terms(question);
  const w = new Map();
  for (const t of base) w.set(t, Math.max(w.get(t) || 0, 1));
  for (const t of base) {
    const syn = SYN_BY_STEM[t];
    if (!syn) continue;
    for (const s of terms(syn)) if (!w.has(s)) w.set(s, 0.5);
  }
  return [...w].map(([term, weight]) => ({ term, weight }));
}

// ------------------------------------------------------------------------------------------------- carrier names
// Words inside program names that name nothing on their own (the Railway chat's _ALIAS_STOPWORDS, plus "sage"'s
// brand name SageSure, which is handled as a brand).
const ALIAS_STOP = new Set(("and the of or a an non admitted surplus tx guide guides underwriting guideline guidelines "
  + "program programs homeowners homeowner dwelling fire landlord condo condominium unit owners insurance company dp "
  + "ho tdp df choice flex").split(" "));
const PRODUCT = /^(ho-?[3-6]|dp-?[1-3]|ho3|ho5|ho6|dp3)$/i;

/** Every alias (normalized words, joined by a space) -> the programs it names. Built from the display names, the
 * program names and the rules tables' workbook names; "sage" and "sagesure" name the whole SageSure family. */
export function buildAliases(programs) {
  const aliases = new Map();
  const add = (alias, p) => {
    if (alias.length < 3) return;
    if (!aliases.has(alias)) aliases.set(alias, new Set());
    aliases.get(alias).add(p);
  };
  for (const prog of programs) {
    const names = [prog.display, prog.program.replace(/_/g, " "), ...prog.workbook_names];
    for (const name of names) {
      const words = normalize(name.replace(/\d{2}\.\d{2}\.\d{2,4}/g, " ").replace(/\(.*?\)/g, (m) => " " + m + " "))
        .split(/[^a-z0-9+]+/).filter((w) => w && !ALIAS_STOP.has(w) && !PRODUCT.test(w) && !/^\d+$/.test(w));
      for (let size = 1; size <= 3; size++) {
        for (let i = 0; i + size <= words.length; i++) add(words.slice(i, i + size).join(" "), prog.program);
      }
    }
    if (prog.program.startsWith("Sage_")) { add("sage", prog.program); add("sagesure", prog.program); }
    if (prog.program.startsWith("NatGen_")) { add("natgen", prog.program); add("national general", prog.program); }
    if (prog.program.startsWith("Liberty_")) add("safeco", prog.program);
    if (prog.program.startsWith("CHUBB")) add("chubb", prog.program);
  }
  const out = {};
  for (const [a, set] of aliases) out[a] = [...set].sort();
  return out;
}
