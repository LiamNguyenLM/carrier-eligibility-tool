// feedback.to_csv()'s row, byte for byte (round 43 step 3). Used when a report is WRITTEN (routes.js, import_logs.mjs):
// the finished line is stored in feedback.csv_row, so the admin CSV is a join of stored lines -- building 1,000 rows
// at download time cost ~36 ms of Worker CPU in the benchmark, over the Free plan's 10 ms.
import { pyCmp } from "./placement.js";

export const CSV_COLUMNS = ["ts", "app_version", "name", "carrier", "display_name", "verdict", "choice", "comment",
  "reasons", "deciding_rows", "model", "rules_table", "checked_topics", "property_details", "email"];
export const CSV_HEADER = CSV_COLUMNS.join(",");

/** json.dumps(v, ensure_ascii=False, sort_keys=True, default=str) -- Python's ", " / ": " separators. */
export function pyJson(v) {
  if (v === null || v === undefined) return "null";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : (v > 0 ? "Infinity" : v < 0 ? "-Infinity" : "NaN");
  if (typeof v === "string") return JSON.stringify(v);
  if (Array.isArray(v)) return "[" + v.map(pyJson).join(", ") + "]";
  return "{" + Object.keys(v).sort(pyCmp).map((k) => JSON.stringify(k) + ": " + pyJson(v[k])).join(", ") + "}";
}

/** Python csv.writer's QUOTE_MINIMAL field. */
export const csvField = (s) => (/[",\r\n]/.test(s) ? '"' + s.replaceAll('"', '""') + '"' : s);

/**
 * One CSV line (no line end) from a feedback row as stored: reasons / deciding_rows / checked_topics /
 * property_details as JSON text, rules_table 0/1. Lists are joined with " | ", checked_topics NULL is "", rules_table
 * is True/False and property_details is Python's sorted json.dumps -- feedback.to_csv()'s rules. email is last.
 */
export function feedbackCsvLine(r) {
  const list = (t) => { try { return JSON.parse(t).map((x) => (typeof x === "string" ? x : JSON.stringify(x))).join(" | "); } catch { return ""; } };
  let pd;
  try { pd = pyJson(JSON.parse(r.property_details)); } catch { pd = String(r.property_details ?? ""); }
  const cell = { ...r, reasons: list(r.reasons), deciding_rows: list(r.deciding_rows),
    checked_topics: r.checked_topics === null || r.checked_topics === undefined ? "" : list(r.checked_topics),
    rules_table: r.rules_table ? "True" : "False", property_details: pd };
  return CSV_COLUMNS.map((c) => csvField(String(cell[c] ?? ""))).join(",");
}
