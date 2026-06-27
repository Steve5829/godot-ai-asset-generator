"""Regression eval for the planner's deterministic layer.

Runs cases from eval_cases.json through:
  - _infer_asset_type_from_prompt  (rule-based asset_type classification)
  - _block_material_profile        (block_texture profile picker)
  - _icon_reference_profile        (icon profile picker)

No LLM calls, no image generation. Fast and free. Run before/after every
change to the planner code or to the profile tables.

    cd server && python test_planner.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import server


GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


def _ok(label: str, prompt: str) -> None:
    print(f"  {GREEN}✓{RESET} {label:<40} {DIM}{prompt}{RESET}")


def _fail(label: str, prompt: str, expected, got) -> None:
    print(f"  {RED}✗ {label:<40} {prompt!r}{RESET}")
    print(f"      expected: {expected!r}")
    print(f"      got:      {got!r}")


def run_asset_type_cases(cases: list[dict]) -> tuple[int, int]:
    print("\nasset_type inference")
    passed = failed = 0
    for case in cases:
        prompt = case["prompt"]
        expected = case["expect"]
        got = server._infer_asset_type_from_prompt(prompt, "auto")
        if got == expected:
            _ok(expected, prompt)
            passed += 1
        else:
            _fail(expected, prompt, expected, got)
            failed += 1
    return passed, failed


def run_block_profile_cases(cases: list[dict]) -> tuple[int, int]:
    print("\nblock material profile matching")
    profile_to_key = {id(v): k for k, v in server.BLOCK_MATERIAL_PROFILES.items()}
    passed = failed = 0
    for case in cases:
        prompt = case["prompt"]
        expected = case["expect"]
        plan = {"user_prompt": prompt, "description": prompt, "descriptions": {}, "filename_stub": prompt.replace(" ", "_")}
        matched = server._block_material_profile(plan)
        got = profile_to_key.get(id(matched)) if matched else None
        if got == expected:
            _ok(expected or "no-match", prompt)
            passed += 1
        else:
            _fail(expected or "no-match", prompt, expected, got)
            failed += 1
    return passed, failed


def run_icon_profile_cases(cases: list[dict]) -> tuple[int, int]:
    print("\nicon reference profile matching")
    passed = failed = 0
    for case in cases:
        prompt = case["prompt"]
        style = case.get("style", "none")
        expected = case["expect"]
        matched = server._icon_reference_profile(prompt, style)
        got = matched["key"] if matched else None
        label = f"{expected or 'no-match'} [{style}]"
        if got == expected:
            _ok(label, prompt)
            passed += 1
        else:
            _fail(label, prompt, expected, got)
            failed += 1
    return passed, failed


def main() -> int:
    cases_path = Path(__file__).parent / "eval_cases.json"
    with cases_path.open() as f:
        cases = json.load(f)

    total_passed = total_failed = 0
    for runner, key in (
        (run_asset_type_cases, "asset_type_cases"),
        (run_block_profile_cases, "block_profile_cases"),
        (run_icon_profile_cases, "icon_profile_cases"),
    ):
        passed, failed = runner(cases[key])
        total_passed += passed
        total_failed += failed

    print(f"\n{'-' * 60}")
    if total_failed == 0:
        print(f"{GREEN}{total_passed} passed, 0 failed{RESET}")
        return 0
    print(f"{RED}{total_failed} failed{RESET}, {total_passed} passed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
