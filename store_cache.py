"""Round 36 step 1: one read of the whole carrier store per store version, shared by every caller.

Before this, one eligibility check read every row of the Chroma collection five times (get_all_carriers
four times, the defect scan once), and every Streamlit rerun -- any click on the form -- read it four more
times for the Manage Carriers tab (fingerprint, carrier list twice). Each read is 0.25-0.65 s locally and
grows with a slower disk and CPU, which is what Railway has.

A cached read is reused only while the store is unchanged. The version is the collection's row count, the
stat of the sqlite files (any write, from any process, changes them) and a counter that this process's own
writes bump (upload_carrier.add / remove), so a change is seen even inside one mtime tick. Callers must
not mutate what read() returns.
"""
import os
import threading

from shared_resources import DB_FOLDER

_lock = threading.Lock()
_cache = {}
_generation = 0


def bump():
    """A write to the store from this process: drop every cached read."""
    global _generation
    with _lock:
        _generation += 1
        _cache.clear()


def _file_stats(folder):
    out = []
    for name in ("chroma.sqlite3", "chroma.sqlite3-wal"):
        try:
            st = os.stat(os.path.join(folder, name))
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def version(collection, folder=DB_FOLDER):
    return (id(collection), _generation, collection.count(), _file_stats(folder))


def read(collection, documents=False):
    """collection.get(include=["metadatas"]) -- or ["documents", "metadatas"] -- cached per store version.
    A cached read with documents also serves a metadata-only request."""
    v = version(collection)
    with _lock:
        for with_documents in ((True,) if documents else (False, True)):
            hit = _cache.get(("raw", with_documents))
            if hit is not None and hit[0] == v:
                return hit[1]
    raw = collection.get(include=["documents", "metadatas"] if documents else ["metadatas"])
    with _lock:
        _cache[("raw", documents)] = (v, raw)
    return raw


def derived(name, collection, compute, documents=False):
    """compute(raw) for this store version, computed once. Callers copy a mutable result."""
    v = version(collection)
    with _lock:
        hit = _cache.get(("derived", name))
        if hit is not None and hit[0] == v:
            return hit[1]
    value = compute(read(collection, documents))
    with _lock:
        _cache[("derived", name)] = (v, value)
    return value


def carriers(collection):
    """Every "carrier" metadata value in the store (a frozenset), as get_all_carriers always read it."""
    return derived("carriers", collection,
                   lambda raw: frozenset(m["carrier"] for m in raw["metadatas"] if m and "carrier" in m))
