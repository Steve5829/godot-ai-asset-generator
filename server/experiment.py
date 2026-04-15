from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

from style_matrix import BENCHMARK_ITEMS, STYLE_MATRIX, build_experiment_matrix

BASE_DIR = Path(__file__).resolve().parent
for _env_path in (BASE_DIR / ".env", BASE_DIR.parent / ".env"):
    if _env_path.exists():
        load_dotenv(_env_path, override=False)

PIXELLAB_API_KEY = os.getenv("PIXELLAB_API_KEY") or os.getenv("PIXELLAB_SECRET")

OUTPUT_DIR = BASE_DIR / "output"
IMAGES_DIR = OUTPUT_DIR / "images"
RESULTS_DIR = OUTPUT_DIR / "results"




def _serialize_manifest(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "styles": [style.key for style in STYLE_MATRIX.values()],
        "items": [item.key for item in BENCHMARK_ITEMS],
        "row_count": len(rows),
        "rows": rows,
    }


def _write_json(data: Any, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )



def _decode_base64_image(data: Dict[str, Any]) -> bytes:
    if not isinstance(data, dict):
        raise ValueError("PixelLab image payload is not an object")
    encoded = data.get("base64")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("PixelLab image payload does not contain base64 data")
    try:
        return base64.b64decode(encoded)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("PixelLab returned invalid base64 image data") from exc


def _parse_prompt_dimensions(prompt: str, default_w: int, default_h: int) -> tuple[int, int]:
    """Extract WxH from prompt text. PixelLab minimum is 32px per side."""
    match = re.search(r"(\d{2,4})\s*[xX×]\s*(\d{2,4})", prompt)
    if match:
        return (
            max(32, min(400, int(match.group(1)))),
            max(32, min(400, int(match.group(2)))),
        )
    return (default_w, default_h)


def _generate_with_pixellab(
    description: str,
    width: int,
    height: int,
    no_background: bool = True,
) -> bytes:
    if not PIXELLAB_API_KEY:
        raise ValueError(
            "PIXELLAB_API_KEY is not set. "
            "Export it or add it to server/.env before running experiments."
        )
    response = requests.post(
        "https://api.pixellab.ai/v1/generate-image-pixflux",
        headers={"Authorization": "Bearer " + PIXELLAB_API_KEY},
        json={
            "description": description,
            "image_size": {"width": width, "height": height},
            "no_background": no_background,
        },
        timeout=(10, 180),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("PixelLab API returned an unexpected response")
    return _decode_base64_image(payload.get("image"))



def _run_single(
    row: Dict[str, str],
    images_dir: Path,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Generate one image for an (item, style) pair and return a result record."""
    prompt = row["prompt"]
    style_key = row["style_key"]
    item_key = row["item_key"]
    width, height = _parse_prompt_dimensions(prompt, 128, 128)

    filename = f"{style_key}_{item_key}.png"
    image_path = images_dir / filename

    result: Dict[str, Any] = {
        "item_key": item_key,
        "style_key": style_key,
        "provider": "pixellab",
        "prompt": prompt,
        "width": width,
        "height": height,
        "output_image_path": str(image_path.relative_to(BASE_DIR.parent)),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "notes": "",
    }

    if dry_run:
        result["notes"] = "dry-run — no API call made"
        print(f"  [dry-run] {style_key}/{item_key}")
        return result

    t0 = time.monotonic()
    try:
        image_bytes = _generate_with_pixellab(prompt, width, height)
        elapsed = time.monotonic() - t0
        images_dir.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(image_bytes)
        result["elapsed_seconds"] = round(elapsed, 2)
        print(f"  [ok] {style_key}/{item_key}  ({elapsed:.1f}s, {len(image_bytes)} bytes)")
    except requests.HTTPError as exc:
        elapsed = time.monotonic() - t0
        result["elapsed_seconds"] = round(elapsed, 2)
        body = ""
        if exc.response is not None:
            body = exc.response.text[:500]
        result["notes"] = f"error: {exc} | body: {body}"
        print(f"  [FAIL] {style_key}/{item_key}  ({elapsed:.1f}s) — {exc}")
        if body:
            print(f"         API response: {body}")
    except Exception as exc:
        elapsed = time.monotonic() - t0
        result["elapsed_seconds"] = round(elapsed, 2)
        result["notes"] = f"error: {exc}"
        print(f"  [FAIL] {style_key}/{item_key}  ({elapsed:.1f}s) — {exc}")

    return result


def _run_experiments(
    rows: List[Dict[str, str]],
    images_dir: Path,
    results_path: Path,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    total = len(rows)

    for idx, row in enumerate(rows, 1):
        print(f"[{idx}/{total}] {row['style_key']} × {row['item_key']}")
        result = _run_single(row, images_dir, dry_run=dry_run)
        results.append(result)

    summary: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "pixellab",
        "total": total,
        "succeeded": sum(1 for r in results if not r["notes"].startswith("error")),
        "failed": sum(1 for r in results if r["notes"].startswith("error")),
        "results": results,
    }

    _write_json(summary, results_path)
    print(f"\nResults written to {results_path}")
    print(f"  succeeded: {summary['succeeded']}  failed: {summary['failed']}")
    return results

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Style-matrix benchmark: generate prompts or run PixelLab experiments."
    )
    parser.add_argument(
        "--output",
        default=str(OUTPUT_DIR / "style_benchmark_manifest.json"),
        help="Path to write the benchmark manifest JSON.",
    )
    parser.add_argument(
        "--print-prompts",
        action="store_true",
        help="Print each generated prompt to stdout.",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Actually call PixelLab to generate images for every (item, style) pair.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Like --run but skip API calls (useful for testing the pipeline).",
    )
    parser.add_argument(
        "--images-dir",
        default=str(IMAGES_DIR),
        help="Directory to save generated images.",
    )
    parser.add_argument(
        "--results-path",
        default=str(RESULTS_DIR / "style_benchmark_results.json"),
        help="Path to write the structured results JSON.",
    )
    args = parser.parse_args()

    rows = build_experiment_matrix()

    # Always write the manifest
    manifest = _serialize_manifest(rows)
    manifest_path = Path(args.output).resolve()
    _write_json(manifest, manifest_path)
    print(f"Manifest: {manifest_path}")
    print(f"  styles : {', '.join(manifest['styles'])}")
    print(f"  items  : {', '.join(manifest['items'])}")
    print(f"  combos : {manifest['row_count']}")

    if args.print_prompts:
        print()
        for row in rows:
            print(f"  [{row['style_key']}] {row['item_key']}: {row['prompt']}")

    if args.run or args.dry_run:
        print()
        _run_experiments(
            rows,
            images_dir=Path(args.images_dir).resolve(),
            results_path=Path(args.results_path).resolve(),
            dry_run=args.dry_run,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
