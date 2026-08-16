"""Show exactly what gets retrieved for one carrier under the standard
verification test profile, and whether is_eligibility_content() drops any
of it. Bypasses the Claude API call entirely -- this is about retrieval,
not the model's answer.

Usage:
    python verification/diagnose_carrier.py "Allied Trust"
    python verification/diagnose_carrier.py "Allied Trust" --k 15
"""
import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-diagnostic-placeholder")

from eligibility_check import (
    PER_CARRIER_FETCH_K,
    PER_CARRIER_KEEP,
    build_retrieval_query,
    get_all_carriers,
    is_eligibility_content,
)
from shared_resources import get_vectorstore
from profiles import STANDARD_PROFILE as TEST_PROFILE, resolve_carrier as _resolve_carrier


def resolve_carrier(query_substring):
    return _resolve_carrier(query_substring, get_all_carriers())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("carrier", help="Carrier name or substring, e.g. 'Allied Trust'")
    parser.add_argument("--k", type=int, default=PER_CARRIER_FETCH_K,
                         help="How many raw results to pull for inspection "
                              "(production fetches k=%d, keeps the first %d "
                              "survivors past is_eligibility_content)"
                              % (PER_CARRIER_FETCH_K, PER_CARRIER_KEEP))
    args = parser.parse_args()

    matches = resolve_carrier(args.carrier)
    if not matches:
        print(f"No carrier in the database matches '{args.carrier}'.")
        print("Known carriers:")
        for c in sorted(get_all_carriers()):
            print("  -", c)
        return
    if len(matches) > 1:
        print(f"'{args.carrier}' matches multiple carriers, be more specific:")
        for c in matches:
            print("  -", c)
        return

    carrier = matches[0]
    print(f"Carrier: {carrier}\n")

    vectorstore = get_vectorstore()
    collection = vectorstore._collection

    total = collection.get(where={"carrier": carrier}, include=[])
    print(f"Total chunks in DB for this carrier: {len(total['ids'])}")

    home_age = date.today().year - TEST_PROFILE["year_built"]
    query = build_retrieval_query(TEST_PROFILE, home_age)

    results = vectorstore.similarity_search_with_score(
        query, k=args.k, filter={"carrier": carrier}
    )

    print(f"Top {len(results)} raw results by similarity "
          f"(production fetches k={PER_CARRIER_FETCH_K}, keeps first {PER_CARRIER_KEEP} survivors):\n")
    kept_for_production = 0
    for i, (chunk, score) in enumerate(results, start=1):
        kept = is_eligibility_content(chunk)
        within_fetch_window = i <= PER_CARRIER_FETCH_K
        would_reach_prompt = kept and within_fetch_window and kept_for_production < PER_CARRIER_KEEP
        if would_reach_prompt:
            kept_for_production += 1
        tag = "KEPT" if kept else "FILTERED (is_eligibility_content)"
        reaches = " -> reaches prompt" if would_reach_prompt else ""
        page = chunk.metadata.get("page", "?")
        preview = chunk.page_content.strip().replace("\n", " ")[:200]
        print(f"[{i}] score={score:.4f} page={page} {tag}{reaches}")
        print(f"    {preview}")
        print()

    print(f"Chunks that would actually reach the LLM prompt for this carrier: {kept_for_production}")
    if kept_for_production == 0:
        print("-> This carrier would fall into the zero-chunk safety net "
              "(explicitly listed, forced to INSUFFICIENT_INFORMATION).")


if __name__ == "__main__":
    main()
