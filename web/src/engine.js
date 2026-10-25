// Round 43 step 2 (Liam, 2026-10-24): the rules engine in the browser. Loads Pyodide from ./pyodide/ (the npm
// package's core files, copied by build.mjs), unpacks the engine bundle (engine.tar.gz: engine/**/*.py, the data
// files it reads and rules_data/engine_manifest.json) into Pyodide's in-memory file system -- which holds nothing
// else, so the engine can read no other file -- loads the manifest (the store's facts: no store, no retrieval, no
// model) and imports engine.api. Every call crosses the JS/Python boundary as JSON.

const BUNDLE = "engine.tar.gz";
const APP_DIR = "/home/pyodide/app";

// json.dumps of whatever an engine function returns; mod "api" is engine.api, else a module path
// ("engine.intake_fields"). Tuples come back as lists.
const GLUE = `
import importlib, json, os, sys
if ${JSON.stringify(APP_DIR)} not in sys.path:
    sys.path.insert(0, ${JSON.stringify(APP_DIR)})
import engine.api as _web_api
with open(os.path.join(${JSON.stringify(APP_DIR)}, "rules_data", "engine_manifest.json"), encoding="utf-8") as _fh:
    _web_api.load(manifest=json.load(_fh))
def _web_call(mod, fn, args_json):
    m = _web_api if mod == "api" else importlib.import_module(mod)
    return json.dumps(getattr(m, fn)(*json.loads(args_json)), ensure_ascii=False, default=str)
`;

const now = () => performance.now();

export class Engine {
  constructor({ base = document.baseURI } = {}) {
    this.base = new URL("./", base);
    this.py = null;
    this.timings = {};          // first-load timings, seconds
  }

  url(path) { return new URL(path, this.base).href; }

  async load() {
    const t0 = now();
    const bundleFetch = fetch(this.url(BUNDLE)).then((r) => {
      if (!r.ok) throw new Error(`engine bundle: HTTP ${r.status}`);
      return r.arrayBuffer();
    });
    const { loadPyodide } = await import(this.url("pyodide/pyodide.mjs"));
    const py = await loadPyodide({ indexURL: this.url("pyodide/") });
    const t1 = now();
    const buf = await bundleFetch;
    py.unpackArchive(buf, "gztar", { extractDir: APP_DIR });
    const t2 = now();
    py.runPython(GLUE);
    this._call = py.globals.get("_web_call");
    this.py = py;
    const t3 = now();
    this.timings = {
      pyodide_s: (t1 - t0) / 1000, bundle_s: (t2 - t1) / 1000, import_s: (t3 - t2) / 1000,
      bundle_bytes: buf.byteLength,
    };
    return this;
  }

  // engine.api.<fn>(...args), or <mod>.<fn>(...args)
  api(fn, ...args) { return this.call("api", fn, ...args); }

  call(mod, fn, ...args) {
    const out = this._call(mod, fn, JSON.stringify(args));
    return JSON.parse(out);
  }

  async formSpec() { return this.api("form_spec"); }

  // engine.api.check(property_details, checked_topics) -> {result, engine_s}. pdJson: property_details as the JSON
  // text Python wrote (form_request's property_details_json), passed through untouched -- a JS copy would turn 9.0
  // into 9 and the card would read "9 mi" where the app reads "9.0 mi".
  async check(pd, checked, pdJson = null) {
    const t0 = now();
    const result = pdJson === null ? this.api("check", pd, checked)
      : this.api("check_json", pdJson, JSON.stringify(checked ?? null));
    return { result, engine_s: (now() - t0) / 1000 };
  }
}
