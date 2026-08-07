#!/usr/bin/env python3
"""
validate.py — consistency gate between the source registry and the daily editions.

This is the check the "cache that drifted from its source of truth" story in the
README is about. The live pipeline keeps a fast in-line copy of the registry to
classify senders; this gate proves the two never disagree. It runs over the demo
data shipped in this repo and is dependency-free (Python standard library only).

Checks:
  1. Registry integrity      — every source has a name, an in-vocabulary category,
                               and a sender_match; the category list is well-formed.
  2. Cache mirrors source    — data/sources.json (the SPA's generated copy of the
                               registry) is byte-for-byte the registry. This is the
                               literal drift check: a generated cache is never
                               allowed to diverge from its source of truth.
  3. Category vocabulary      — every card's category is one the registry declares.
  4. Source coverage         — every card's source resolves to a registry source
                               (no "orphan" source shipping uncatalogued).
  5. Category consistency     — every card's category matches its registry source's
                               category. THIS is the sender-map drift check: an
                               edition can never ship a source under a category the
                               registry disagrees with.
  6. Card schema             — every card has the shared fields and a payload that
                               matches its declared card_type (single/hybrid_c/flavor_1).
  7. Excluded senders        — no source the registry excludes (include:false, or an
                               excluded pattern) appears as a shipped card.
  8. Edition index           — data/index.json lists exactly the editions on disk.

Exit code 0 = all gates pass, 1 = at least one failure (usable in CI / pre-commit).

Usage:  python3 validate.py            # validate the repo's demo data
        python3 validate.py --quiet    # only print the final verdict
"""
from __future__ import annotations

import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(REPO, "config", "newsletter-registry.json")
DATA_DIR = os.path.join(REPO, "data")
SOURCES_COPY = os.path.join(DATA_DIR, "sources.json")
EDITION_GLOB = os.path.join(DATA_DIR, "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].json")

# Payload key each declared card_type must carry (and no other shape's key).
CARD_SHAPES = {"single": "bullets", "hybrid_c": "top_picks", "flavor_1": "stories"}
SHARED_FIELDS = ("source", "category", "headline", "one_liner", "arrival_ist")


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _registry_index(registry):
    """Return (categories, source_name->category, excluded_source_names)."""
    raw_cats = registry.get("categories", [])
    categories = {c if isinstance(c, str) else (c.get("id") or c.get("name")) for c in raw_cats}
    src_category, excluded_names = {}, set()
    for tier in registry.get("newsletters", {}).values():
        for src in tier.get("sources", []):
            name = src.get("name")
            src_category[name] = src.get("category")
            if src.get("include") is False:          # an in-registry source marked "do not ship"
                excluded_names.add(str(name).lower())
    for ex in registry.get("excluded", {}).get("senders", []):
        for key in ("name", "source", "pattern"):     # excluded blocks may be keyed by name or pattern
            if ex.get(key):
                excluded_names.add(str(ex[key]).lower())
    return categories, src_category, excluded_names


def validate(quiet=False):
    results = []  # (ok, name, detail)

    def check(name, failures, detail_ok=""):
        results.append((not failures, name, failures if failures else detail_ok))

    try:
        registry = _load_json(REGISTRY)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  FAIL  Load registry\n        - {REGISTRY}: {exc}")
        print("\nRESULT: FAILURES — see above")
        return 1

    categories, src_category, excluded_names = _registry_index(registry)

    # 1. Registry integrity
    bad_sources = []
    for tier_name, tier in registry.get("newsletters", {}).items():
        for src in tier.get("sources", []):
            if not src.get("name"):
                bad_sources.append(f"{tier_name}: source with no name")
            elif not src.get("sender_match"):
                bad_sources.append(f"{src['name']}: no sender_match")
            elif src.get("category") not in categories:
                bad_sources.append(f"{src['name']}: category {src.get('category')!r} not in vocabulary")
    if not categories:
        bad_sources.append("registry declares no categories")
    check("Registry integrity", bad_sources, f"{len(src_category)} sources, {len(categories)} categories")

    # 2. Cache mirrors source of truth — data/sources.json must equal the registry
    mirror_fail = []
    if not os.path.exists(SOURCES_COPY):
        mirror_fail.append("data/sources.json missing (the SPA's registry copy)")
    else:
        try:
            if _load_json(SOURCES_COPY) != registry:
                mirror_fail.append("data/sources.json has drifted from config/newsletter-registry.json — regenerate it")
        except json.JSONDecodeError as exc:
            mirror_fail.append(f"data/sources.json is not valid JSON: {exc}")
    check("Cache mirrors source of truth", mirror_fail, "data/sources.json == registry")

    # load editions
    editions, load_fail = [], []
    for path in sorted(glob.glob(EDITION_GLOB)):
        try:
            editions.append((os.path.basename(path), _load_json(path)))
        except json.JSONDecodeError as exc:
            load_fail.append(f"{os.path.basename(path)}: {exc}")
    check("Editions parse as JSON", load_fail, f"{len(editions)} editions loaded")

    bad_cat, orphans, cat_mismatch, bad_shape, excl_shipped = [], [], [], [], []
    card_count = 0
    for day, edition in editions:
        for tab in ("main", "curious"):
            for card in edition.get(tab, []):
                card_count += 1
                src = (card.get("source") or "").strip()
                cat = card.get("category")

                if cat not in categories:                                   # 3
                    bad_cat.append(f"{day} [{tab}] {src!r}: category {cat!r} not in vocabulary")
                if src not in src_category:                                 # 4
                    orphans.append(f"{day} [{tab}] {src!r}: not in registry")
                elif src_category[src] != cat:                             # 5 (drift gate)
                    cat_mismatch.append(f"{day} [{tab}] {src!r}: edition={cat} vs registry={src_category[src]}")

                # 6. schema shape — payload must match the DECLARED card_type
                missing_shared = [f for f in SHARED_FIELDS if not card.get(f)]
                declared = card.get("card_type", "single")
                if missing_shared:
                    bad_shape.append(f"{day} [{tab}] {src!r}: missing {missing_shared}")
                elif declared not in CARD_SHAPES:
                    bad_shape.append(f"{day} [{tab}] {src!r}: unknown card_type {declared!r}")
                else:
                    want = CARD_SHAPES[declared]
                    others = [k for t, k in CARD_SHAPES.items() if t != declared and card.get(k)]
                    if not card.get(want):
                        bad_shape.append(f"{day} [{tab}] {src!r}: card_type {declared!r} but no {want!r} payload")
                    elif others:
                        bad_shape.append(f"{day} [{tab}] {src!r}: card_type {declared!r} but also carries {others}")

                if src.lower() in excluded_names:                          # 7
                    excl_shipped.append(f"{day} [{tab}] {src!r}: source is on the excluded list")

    check("Category vocabulary", bad_cat, f"{card_count} cards, all categories valid")
    check("Source coverage (no orphans)", orphans, "every card source is a registry source")
    check("Category consistency (drift gate)", cat_mismatch, "every card agrees with the registry category")
    check("Card schema shape", bad_shape, "shared fields + payload matches declared card_type")
    check("Excluded senders not shipped", excl_shipped, "no excluded source in any edition")

    # 8. index.json lists exactly the editions on disk
    on_disk = {name[:-5] for name, _ in editions}
    if os.path.exists(os.path.join(DATA_DIR, "index.json")):
        listed = set(_load_json(os.path.join(DATA_DIR, "index.json")))
        idx = []
        if on_disk - listed:
            idx.append(f"on disk but not in index.json: {sorted(on_disk - listed)}")
        if listed - on_disk:
            idx.append(f"in index.json but not on disk: {sorted(listed - on_disk)}")
        check("Edition index matches disk", idx, f"{len(on_disk)} editions listed and present")
    elif not quiet:
        print("  INFO  Edition index matches disk       skipped — data/index.json absent (generated at runtime)")

    # report
    width = max(len(name) for _, name, _ in results)
    all_ok = True
    for ok, name, detail in results:
        all_ok = all_ok and ok
        if ok:
            if not quiet:
                print(f"  PASS  {name.ljust(width)}  {detail}")
        else:
            print(f"  FAIL  {name.ljust(width)}")
            for line in (detail if isinstance(detail, list) else [detail]):
                print(f"        - {line}")
    print()
    print("RESULT:", "ALL GATES PASS" if all_ok else "FAILURES — see above")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(validate(quiet="--quiet" in sys.argv))
