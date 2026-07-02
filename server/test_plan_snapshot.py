"""Snapshot regression for the full planning pipeline.

Locks the shape of the plan dict that _plan_generation_workflow produces, so the
resolve-then-build refactor (and any later planner change) can be verified field
by field without calling the LLM or any image provider.

The LLM (_chat_json) and the vision reference builder (_build_reference_context)
are monkeypatched to deterministic stand-ins. The captured fields are written to
plan_snapshot.json on first run; later runs diff against it.

    cd server && python test_plan_snapshot.py          # compare to baseline
    cd server && python test_plan_snapshot.py --update  # rewrite baseline
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import server

SNAPSHOT_PATH = Path(__file__).parent / "plan_snapshot.json"

# (label, request kwargs, llm_reply). llm_reply=None forces the fallback path.
CASES = [
    ("fallback_icon", {"prompt": "iron sword", "style_target": "none"}, None),
    ("fallback_block", {"prompt": "obsidian block", "style_target": "core_keeper"}, None),
    ("fallback_atlas", {"prompt": "forest ground", "style_target": "core_keeper"}, None),
    ("fallback_scene", {"prompt": "stone house", "style_target": "none"}, None),
    (
        "llm_icon",
        {"prompt": "healing potion", "style_target": "terraria"},
        {"asset_type": "icon", "description": "a red healing potion", "width": 64, "height": 64},
    ),
    (
        "llm_block_mc",
        {"prompt": "gold block", "style_target": "minecraft"},
        {"asset_type": "block_texture", "description": "gold block material"},
    ),
    (
        "llm_reclassify_house",
        {"prompt": "stone house", "style_target": "none"},
        {"asset_type": "reference_scene", "description": "a small stone cottage"},
    ),
    # Explicit type-naming keyword must win even when the LLM guesses otherwise.
    (
        "explicit_atlas_over_llm",
        {"prompt": "an atlas of city", "style_target": "none"},
        {"asset_type": "icon", "description": "a city"},
    ),
    (
        "explicit_spritesheet_over_llm",
        {"prompt": "goblin walk spritesheet", "style_target": "none"},
        {"asset_type": "icon", "description": "a goblin"},
    ),
]

CAPTURE_FIELDS = ("asset_type", "workflow", "width", "height", "no_background", "planning_source", "style_target")


def _capture(plan: dict) -> dict:
    descriptions = plan.get("descriptions") if isinstance(plan.get("descriptions"), dict) else {}
    postprocess = plan.get("postprocess") if isinstance(plan.get("postprocess"), dict) else {}
    snap = {field: plan.get(field) for field in CAPTURE_FIELDS}
    snap["description"] = plan.get("description")
    snap["descriptions"] = {k: descriptions[k] for k in sorted(descriptions)}
    snap["filename_stub"] = plan.get("filename_stub")
    snap["postprocess"] = {k: postprocess[k] for k in sorted(postprocess)}
    snap["outputs_expected"] = plan.get("outputs_expected")
    snap["has_reference_context"] = "reference_context" in plan
    return snap


def _run_case(req_kwargs: dict, llm_reply) -> dict:
    server._chat_json = lambda *a, **k: llm_reply
    server._build_reference_context = lambda *a, **k: None
    request = server.GenerateAssetRequest(**req_kwargs)
    return _capture(server._plan_generation_workflow(request))


def main() -> int:
    update = "--update" in sys.argv
    results = {label: _run_case(kw, reply) for label, kw, reply in CASES}

    if update or not SNAPSHOT_PATH.exists():
        SNAPSHOT_PATH.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
        print(f"Wrote baseline for {len(results)} cases -> {SNAPSHOT_PATH.name}")
        return 0

    baseline = json.loads(SNAPSHOT_PATH.read_text())
    failed = 0
    for label in results:
        if results[label] != baseline.get(label):
            failed += 1
            print(f"\033[31m✗ {label}\033[0m")
            print(f"    baseline: {baseline.get(label)}")
            print(f"    current:  {results[label]}")
        else:
            print(f"\033[32m✓ {label}\033[0m")

    print("-" * 50)
    if failed:
        print(f"\033[31m{failed} snapshot mismatch(es)\033[0m — refactor changed behavior")
        return 1
    print(f"\033[32m{len(results)} cases match baseline\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
