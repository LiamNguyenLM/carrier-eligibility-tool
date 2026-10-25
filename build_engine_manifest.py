"""Round 43 step 1 (Liam, 2026-10-24): rules_data/engine_manifest.json -- the store's facts the code path reads,
for the browser, which has no store: the carrier list, the upload settings (display names, forms, occupancies,
guide dates), the defects (data_defects), each guide's solar classification and the closed programs whose guide
still says so (closed_programs). Built from the local store
(carrier_docs_db, a copy of carrier_docs_db_seed). Rebuild and commit it whenever a carrier is added or removed or
the seed changes; verification/test_engine_split.py fails while it is stale. Zero API.
usage (cwd = the repo): python build_engine_manifest.py [out.json]"""
import json
import os
import sys

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules_data", "engine_manifest.json")


def manifest():
    import eligibility_check as ec
    carriers = sorted(ec.get_all_carriers())
    collection = ec.get_vectorstore()._collection
    defects = ec._defective_programs()
    return {"carriers": carriers,
            "upload_settings": {k: ec.upload_settings()[k] for k in sorted(ec.upload_settings())},
            "defects": {k: defects[k] for k in sorted(defects)},
            "solar": {c: ec.classify_carrier_solar_text(collection, c) for c in sorted(set(carriers) | set(defects))},
            "closed": sorted(ec.closed_programs(sorted(ec.CLOSED_PROGRAMS)))}


def text(m):
    return json.dumps(m, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    os.environ.pop("ELIGIBILITY_DOTENV", None)
    out = sys.argv[1] if len(sys.argv) > 1 else OUT
    m = manifest()
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text(m))
    print(f"{len(m['carriers'])} carriers, {len(m['defects'])} defects, "
          f"{sum(v != 'none' for v in m['solar'].values())} with solar language -> {out}")
