// Shared by the cloudflare/scripts: a small RFC 4180 CSV reader, SQL literals, and a D1 stand-in on node:sqlite
// (the subset of the D1 Workers API the Worker uses: prepare/bind/first/all/run/raw, batch, exec).
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";

/** Rows of a CSV file as objects keyed by the header (quotes, doubled quotes and CRLF handled). */
export const readCsv = (path) => parseCsv(readFileSync(path, "utf8"), path);

export function parseCsv(text, path = "csv") {
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  const rows = [];
  let row = [], field = "", i = 0, quoted = false;
  while (i < text.length) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i += 2; continue; }
      if (c === '"') { quoted = false; i++; continue; }
      field += c; i++; continue;
    }
    if (c === '"') { quoted = true; i++; continue; }
    if (c === ",") { row.push(field); field = ""; i++; continue; }
    if (c === "\r" || c === "\n") {
      row.push(field); field = "";
      if (!(row.length === 1 && row[0] === "")) rows.push(row);
      row = [];
      i += c === "\r" && text[i + 1] === "\n" ? 2 : 1;
      continue;
    }
    field += c; i++;
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  const [header, ...body] = rows;
  return body.map((r, n) => {
    if (r.length !== header.length) throw new Error(`${path}: line ${n + 2} has ${r.length} fields, header has ${header.length}`);
    return Object.fromEntries(header.map((h, k) => [h, r[k]]));
  });
}

/** A SQL literal: NULL, a number, or a single-quoted string. */
export function sqlLit(v) {
  if (v === null || v === undefined) return "NULL";
  if (typeof v === "boolean") return v ? "1" : "0";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) throw new Error(`not a finite number: ${v}`);
    return String(v);
  }
  return "'" + String(v).replaceAll("'", "''") + "'";
}

/** INSERT statements of at most `per` rows each (D1 caps one statement at 100 KB). */
export function inserts(table, cols, rows, { per = 250, verb = "INSERT" } = {}) {
  const out = [];
  for (let i = 0; i < rows.length; i += per) {
    const vals = rows.slice(i, i + per).map((r) => "(" + r.map(sqlLit).join(",") + ")").join(",\n");
    out.push(`${verb} INTO ${table} (${cols.join(", ")}) VALUES\n${vals};`);
  }
  return out;
}

// ----------------------------------------------------------------------------------------------- D1 stand-in
const toParam = (v) => {
  if (v === undefined) throw new Error("D1_TYPE_ERROR: undefined cannot be bound");   // as D1 does
  return typeof v === "boolean" ? (v ? 1 : 0) : v;
};

class Stmt {
  constructor(db, sql, params = []) { this.db = db; this.sql = sql; this.params = params; }
  bind(...params) { return new Stmt(this.db, this.sql, params.map(toParam)); }
  _prep() {
    if (this.db.record) this.db.record.push([this.sql, this.params]);
    let s = this.db.cache.get(this.sql);
    if (!s) { s = this.db.sqlite.prepare(this.sql); this.db.cache.set(this.sql, s); }
    return s;
  }
  async all() { return this._all(); }
  _all() {
    const rows = this._prep().all(...this.params).map((r) => ({ ...r }));
    return { results: rows, success: true, meta: { rows_read: rows.length } };
  }
  async first(col) {
    const r = this._prep().get(...this.params);
    if (!r) return null;
    return col === undefined ? { ...r } : r[col];
  }
  async run() { return this._run(); }
  _run() {
    const info = this._prep().run(...this.params);
    return { results: [], success: true, meta: { changes: Number(info.changes), last_row_id: Number(info.lastInsertRowid) } };
  }
  async raw() {
    const s = this._prep();
    s.setReturnArrays?.(true);
    try { return s.all(...this.params); } finally { s.setReturnArrays?.(false); }
  }
}

/** env.DB for Node: `new D1Stub(path or ":memory:")`. batch() is one transaction, as on D1. */
export class D1Stub {
  constructor(path = ":memory:") { this.sqlite = new DatabaseSync(path); this.cache = new Map(); }
  prepare(sql) { return new Stmt(this, sql); }
  async batch(stmts) {
    this.sqlite.exec("BEGIN");
    try {
      const out = stmts.map((s) => (/^\s*(SELECT|WITH)\b/i.test(s.sql) ? s._all() : s._run()));
      this.sqlite.exec("COMMIT");
      return out;
    } catch (e) {
      this.sqlite.exec("ROLLBACK");
      throw e;
    }
  }
  async exec(sql) { this.sqlite.exec(sql); return { count: 1, duration: 0 }; }
}
