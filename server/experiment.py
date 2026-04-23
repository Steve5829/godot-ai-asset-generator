from __future__ import annotations

import argparse
import base64
import binascii
import io
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
from PIL import Image

from style_matrix import BENCHMARK_ITEMS, STYLE_MATRIX, benchmark_item_dict, build_experiment_matrix, style_profile_dict

BASE_DIR = Path(__file__).resolve().parent
for _env_path in (BASE_DIR / ".env", BASE_DIR.parent / ".env"):
    if _env_path.exists():
        load_dotenv(_env_path, override=False)

PIXELLAB_API_KEY = os.getenv("PIXELLAB_API_KEY") or os.getenv("PIXELLAB_SECRET")
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"

OUTPUT_DIR = BASE_DIR / "output"
IMAGES_DIR = OUTPUT_DIR / "images"
RESULTS_DIR = OUTPUT_DIR / "results"
SHEETS_DIR = IMAGES_DIR / "sheets"
LLM_CACHE_PATH = RESULTS_DIR / "llm_description_cache.json"




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

def _read_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None



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

def _extract_json_object(text: str) -> Dict[str, Any]:
    stripped = str(text or "").strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LLM response does not contain a JSON object")
    return json.loads(stripped[start : end + 1])


def _chat_json(messages: List[Dict[str, str]], temperature: float) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not configured")

    response = requests.post(
        OPENAI_BASE_URL + "/chat/completions",
        headers={
            "Authorization": "Bearer " + OPENAI_API_KEY,
            "Content-Type": "application/json",
        },
        json={
            "model": OPENAI_MODEL,
            "temperature": float(temperature),
            "response_format": {"type": "json_object"},
            "messages": messages,
        },
        timeout=(10, 90),
    )
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("LLM returned no choices")
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        text = "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    else:
        text = str(content)
    return _extract_json_object(text)


def _llm_description_cache_key(style_key: str, item_key: str) -> str:
    return "%s:%s" % (style_key, item_key)


def _get_llm_visual_description(
    *,
    item_key: str,
    style_key: str,
    temperature: float,
    cache: Dict[str, Any],
    cache_path: Path,
) -> Dict[str, str]:
    """
    Returns {"description": "...", "source": "cache|llm"}.
    """
    key = _llm_description_cache_key(style_key, item_key)
    cached = cache.get(key)
    if isinstance(cached, dict) and isinstance(cached.get("description"), str) and cached["description"].strip():
        return {"description": cached["description"].strip(), "source": "cache"}

    style = style_profile_dict(style_key)
    item = benchmark_item_dict(item_key)

    system = (
        "You are a senior pixel-art game artist. "
        "Given an item spec and a style profile, write a concrete VISUAL description "
        "of what the item looks like in that style. "
        "Be specific about silhouette, materials, shading, palette direction, and readability. "
        "Do NOT mention famous games by name. "
        "Do NOT include layout or spritesheet instructions. "
        "Output JSON only: {\"description\": \"...\"}. Keep it 1-3 sentences."
    )
    user = json.dumps(
        {
            "item": item,
            "style_profile": style,
            "constraints": {
                "transparent_background": True,
                "pixel_art": True,
                "avoid": ["text", "watermarks", "logos", "blurry edges", "anti-aliasing"],
            },
        },
        ensure_ascii=True,
    )

    payload = _chat_json(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
    )
    description = str(payload.get("description") or "").strip()
    if not description:
        raise ValueError("LLM returned empty description")

    cache[key] = {
        "description": description,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "style_key": style_key,
        "item_key": item_key,
        "model": OPENAI_MODEL,
    }
    _write_json(cache, cache_path)
    return {"description": description, "source": "llm"}


def _clamp_sheet_dimensions(width: int, height: int) -> tuple[int, int]:
    return (max(32, min(400, int(width))), max(32, min(400, int(height))))


def _build_spritesheet_prompt(
    *,
    style_key: str,
    rows_for_style: List[Dict[str, str]],
    sheet_cols: int,
    cell_size: int,
    llm_cell_descriptions: Optional[Dict[str, str]] = None,
) -> str:
    """
    Ask PixFlux to generate a strict grid spritesheet.
    This is best-effort: the model may not perfectly respect layout.
    """
    style = STYLE_MATRIX[style_key]
    sheet_cols = max(1, int(sheet_cols))
    cell_size = max(16, int(cell_size))
    sheet_rows = (len(rows_for_style) + sheet_cols - 1) // sheet_cols

    # Provide explicit cell mapping so we can crop deterministically.
    # Keep each cell instruction SHORT to avoid the model collapsing everything into one dominant item.
    item_by_key = {item.key: item for item in BENCHMARK_ITEMS}
    cells: List[str] = []
    for idx, row in enumerate(rows_for_style):
        r = idx // sheet_cols
        c = idx % sheet_cols
        item_key = row["item_key"]
        item_title = row.get("item_title") or item_key
        if llm_cell_descriptions and isinstance(llm_cell_descriptions.get(item_key), str):
            detail = llm_cell_descriptions[item_key].strip()
            cells.append(f"Cell (row {r+1}, col {c+1}): {item_title}. {detail}")
            continue

        item = item_by_key.get(item_key)
        focus = (item.visual_focus if item else "").strip()
        base_desc = (item.description if item else "").strip()
        detail_bits = []
        if base_desc:
            detail_bits.append(base_desc)
        if focus:
            detail_bits.append(f"Focus: {focus}")
        detail = " ".join(detail_bits).strip()
        cells.append(f"Cell (row {r+1}, col {c+1}): {item_title}. {detail}" if detail else f"Cell (row {r+1}, col {c+1}): {item_title}.")

    return (
        "Create a pixel art spritesheet on a transparent background.\n"
        f"Canvas: {sheet_cols * cell_size}x{sheet_rows * cell_size} pixels.\n"
        f"Grid: {sheet_cols} columns × {sheet_rows} rows.\n"
        f"Each cell is exactly {cell_size}x{cell_size} pixels.\n"
        "Rules:\n"
        "- Put exactly ONE item in each cell, centered in its cell.\n"
        "- Do NOT overlap across cells.\n"
        "- Leave at least 1px padding to the cell border.\n"
        "- No text, labels, borders, shadows outside the sprites.\n"
        "- Keep lighting, palette, and line treatment consistent across all cells.\n"
        f"Style target: {style.title} ({style.key}).\n"
        f"- Perspective: {style.perspective}\n"
        f"- Palette: {style.palette}\n"
        f"- Outlines: {style.outlines}\n"
        f"- Lighting: {style.lighting}\n"
        f"- Rendering: {style.rendering}\n"
        f"- Detail density: {style.detail_density}\n"
        f"- Shape language: {style.shape_language}\n"
        "Cells:\n"
        + "\n".join(cells)
    )


def _crop_sheet_to_items(
    *,
    sheet_png_bytes: bytes,
    rows_for_style: List[Dict[str, str]],
    sheet_cols: int,
    cell_size: int,
    images_dir: Path,
    style_key: str,
) -> List[Dict[str, Any]]:
    image = Image.open(io.BytesIO(sheet_png_bytes)).convert("RGBA")
    results: List[Dict[str, Any]] = []
    sheet_cols = max(1, int(sheet_cols))
    cell_size = max(1, int(cell_size))

    for idx, row in enumerate(rows_for_style):
        r = idx // sheet_cols
        c = idx % sheet_cols
        left = c * cell_size
        upper = r * cell_size
        right = left + cell_size
        lower = upper + cell_size

        item_key = row["item_key"]
        filename = f"{style_key}_{item_key}.png"
        image_path = images_dir / filename
        images_dir.mkdir(parents=True, exist_ok=True)
        sprite = image.crop((left, upper, right, lower))
        sprite.save(image_path, format="PNG")

        results.append(
            {
                "item_key": item_key,
                "style_key": style_key,
                "provider": "pixellab",
                "prompt": row["prompt"],
                "output_image_path": str(image_path.relative_to(BASE_DIR.parent)),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "notes": "",
                "spritesheet": {
                    "cell_index": idx,
                    "row": r,
                    "col": c,
                    "cell_size": cell_size,
                    "sheet_size": {"width": image.width, "height": image.height},
                },
            }
        )

    return results


def _run_spritesheet_experiments(
    rows: List[Dict[str, str]],
    *,
    images_dir: Path,
    sheets_dir: Path,
    results_path: Path,
    sheet_cols: int,
    cell_size: int,
    dry_run: bool = False,
    llm_augment: bool = False,
    llm_temperature: float = 0.0,
    llm_cache_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    all_results: List[Dict[str, Any]] = []
    total_styles = len(STYLE_MATRIX)
    cache_path = llm_cache_path or LLM_CACHE_PATH
    cache = _read_json_if_exists(cache_path)
    if not isinstance(cache, dict):
        cache = {}

    for style_idx, style in enumerate(STYLE_MATRIX.values(), 1):
        style_key = style.key
        rows_for_style = [r for r in rows if r["style_key"] == style_key]
        sheet_rows = (len(rows_for_style) + max(1, sheet_cols) - 1) // max(1, sheet_cols)
        sheet_w, sheet_h = _clamp_sheet_dimensions(sheet_cols * cell_size, sheet_rows * cell_size)

        llm_cell_descriptions: Optional[Dict[str, str]] = None
        if llm_augment:
            llm_cell_descriptions = {}
            for row in rows_for_style:
                item_key = row["item_key"]
                desc = _get_llm_visual_description(
                    item_key=item_key,
                    style_key=style_key,
                    temperature=llm_temperature,
                    cache=cache,
                    cache_path=cache_path,
                )
                llm_cell_descriptions[item_key] = desc["description"]

        sheet_prompt = _build_spritesheet_prompt(
            style_key=style_key,
            rows_for_style=rows_for_style,
            sheet_cols=sheet_cols,
            cell_size=cell_size,
            llm_cell_descriptions=llm_cell_descriptions,
        )

        sheet_filename = f"{style_key}_sheet_{sheet_cols}x{sheet_rows}_{cell_size}px.png"
        sheet_path = sheets_dir / sheet_filename
        sheets_dir.mkdir(parents=True, exist_ok=True)

        print(f"[style {style_idx}/{total_styles}] {style_key} spritesheet {sheet_w}x{sheet_h} ({sheet_cols}x{sheet_rows})")

        if dry_run:
            print("  [dry-run] skipping API call and crop")
            for row in rows_for_style:
                all_results.append(
                    {
                        "item_key": row["item_key"],
                        "style_key": style_key,
                        "provider": "pixellab",
                        "prompt": row["prompt"],
                        "llm_description": (llm_cell_descriptions or {}).get(row["item_key"], ""),
                        "output_image_path": str(
                            (images_dir / f"{style_key}_{row['item_key']}.png").relative_to(BASE_DIR.parent)
                        ),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "notes": "dry-run — no API call made",
                        "spritesheet": {
                            "sheet_path": str(sheet_path.relative_to(BASE_DIR.parent)),
                            "cell_size": cell_size,
                            "sheet_cols": sheet_cols,
                        },
                    }
                )
            continue

        t0 = time.monotonic()
        try:
            sheet_bytes = _generate_with_pixellab(sheet_prompt, sheet_w, sheet_h, no_background=True)
            elapsed = time.monotonic() - t0
            sheet_path.write_bytes(sheet_bytes)
            print(f"  [ok] generated sheet ({elapsed:.1f}s, {len(sheet_bytes)} bytes) -> {sheet_path}")

            cropped_results = _crop_sheet_to_items(
                sheet_png_bytes=sheet_bytes,
                rows_for_style=rows_for_style,
                sheet_cols=sheet_cols,
                cell_size=cell_size,
                images_dir=images_dir,
                style_key=style_key,
            )
            for r in cropped_results:
                r["elapsed_seconds"] = round(elapsed, 2)
                r["spritesheet"]["sheet_path"] = str(sheet_path.relative_to(BASE_DIR.parent))
                r["spritesheet"]["sheet_cols"] = sheet_cols
                r["spritesheet"]["requested_sheet_size"] = {"width": sheet_w, "height": sheet_h}
            all_results.extend(cropped_results)
        except requests.HTTPError as exc:
            elapsed = time.monotonic() - t0
            body = ""
            if exc.response is not None:
                body = exc.response.text[:500]
            print(f"  [FAIL] {style_key} sheet  ({elapsed:.1f}s) — {exc}")
            if body:
                print(f"         API response: {body}")
            for row in rows_for_style:
                all_results.append(
                    {
                        "item_key": row["item_key"],
                        "style_key": style_key,
                        "provider": "pixellab",
                        "prompt": row["prompt"],
                        "output_image_path": str(
                            (images_dir / f"{style_key}_{row['item_key']}.png").relative_to(BASE_DIR.parent)
                        ),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "notes": f"error: {exc} | body: {body}",
                        "elapsed_seconds": round(elapsed, 2),
                        "spritesheet": {
                            "sheet_path": str(sheet_path.relative_to(BASE_DIR.parent)),
                            "cell_size": cell_size,
                            "sheet_cols": sheet_cols,
                            "requested_sheet_size": {"width": sheet_w, "height": sheet_h},
                        },
                    }
                )
        except Exception as exc:
            elapsed = time.monotonic() - t0
            print(f"  [FAIL] {style_key} sheet  ({elapsed:.1f}s) — {exc}")
            for row in rows_for_style:
                all_results.append(
                    {
                        "item_key": row["item_key"],
                        "style_key": style_key,
                        "provider": "pixellab",
                        "prompt": row["prompt"],
                        "output_image_path": str(
                            (images_dir / f"{style_key}_{row['item_key']}.png").relative_to(BASE_DIR.parent)
                        ),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "notes": f"error: {exc}",
                        "elapsed_seconds": round(elapsed, 2),
                        "spritesheet": {
                            "sheet_path": str(sheet_path.relative_to(BASE_DIR.parent)),
                            "cell_size": cell_size,
                            "sheet_cols": sheet_cols,
                            "requested_sheet_size": {"width": sheet_w, "height": sheet_h},
                        },
                    }
                )

    summary: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "pixellab",
        "mode": "spritesheet",
        "sheet_cols": sheet_cols,
        "cell_size": cell_size,
        "total": len(all_results),
        "succeeded": sum(1 for r in all_results if not str(r.get("notes", "")).startswith("error")),
        "failed": sum(1 for r in all_results if str(r.get("notes", "")).startswith("error")),
        "results": all_results,
    }
    _write_json(summary, results_path)
    print(f"\nSpritesheet results written to {results_path}")
    print(f"  succeeded: {summary['succeeded']}  failed: {summary['failed']}")
    return all_results



def _run_single(
    row: Dict[str, str],
    images_dir: Path,
    dry_run: bool = False,
    llm_augment: bool = False,
    llm_temperature: float = 0.0,
    llm_cache_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Generate one image for an (item, style) pair and return a result record."""
    prompt = row["prompt"]
    style_key = row["style_key"]
    item_key = row["item_key"]
    width, height = _parse_prompt_dimensions(prompt, 128, 128)

    cache_path = llm_cache_path or LLM_CACHE_PATH
    cache = _read_json_if_exists(cache_path)
    if not isinstance(cache, dict):
        cache = {}
    llm_desc: Optional[Dict[str, str]] = None
    if llm_augment:
        llm_desc = _get_llm_visual_description(
            item_key=item_key,
            style_key=style_key,
            temperature=llm_temperature,
            cache=cache,
            cache_path=cache_path,
        )

    filename = f"{style_key}_{item_key}.png"
    image_path = images_dir / filename

    final_description = (llm_desc or {}).get("description") or prompt
    result: Dict[str, Any] = {
        "item_key": item_key,
        "style_key": style_key,
        "provider": "pixellab",
        "prompt": prompt,
        "llm_description": (llm_desc or {}).get("description", ""),
        "description_source": (llm_desc or {}).get("source", "human_prompt"),
        "final_description": final_description,
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
        image_bytes = _generate_with_pixellab(final_description, width, height)
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
    llm_augment: bool = False,
    llm_temperature: float = 0.0,
    llm_cache_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    total = len(rows)

    for idx, row in enumerate(rows, 1):
        print(f"[{idx}/{total}] {row['style_key']} × {row['item_key']}")
        result = _run_single(
            row,
            images_dir,
            dry_run=dry_run,
            llm_augment=llm_augment,
            llm_temperature=llm_temperature,
            llm_cache_path=llm_cache_path,
        )
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
        "--run-spritesheet",
        action="store_true",
        help="Generate one spritesheet per style, then crop into per-item PNGs (fewer API calls).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip API calls (useful for testing the pipeline).",
    )
    parser.add_argument(
        "--llm-augment",
        action="store_true",
        help="Use an LLM to generate a visual description per (item, style) before calling PixelLab.",
    )
    parser.add_argument(
        "--llm-temperature",
        type=float,
        default=0.0,
        help="LLM temperature (default 0.0 for reproducibility).",
    )
    parser.add_argument(
        "--llm-cache",
        default=str(LLM_CACHE_PATH),
        help="Path to LLM description cache JSON.",
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
    parser.add_argument(
        "--spritesheet-cols",
        type=int,
        default=3,
        help="Spritesheet columns (per style). Default 3 (fits 3 benchmark items in one row).",
    )
    parser.add_argument(
        "--spritesheet-cell",
        type=int,
        default=32,
        help="Spritesheet cell size in pixels (square). Default 32.",
    )
    parser.add_argument(
        "--sheets-dir",
        default=str(SHEETS_DIR),
        help="Directory to save generated spritesheets.",
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
            llm_augment=bool(args.llm_augment),
            llm_temperature=float(args.llm_temperature),
            llm_cache_path=Path(args.llm_cache).resolve() if args.llm_cache else None,
        )

    if args.run_spritesheet:
        print()
        results_path = Path(args.results_path).resolve()
        # If caller kept the default results path, write spritesheet results to a separate file.
        if str(results_path).endswith("style_benchmark_results.json"):
            results_path = results_path.with_name("style_benchmark_results_spritesheet.json")
        _run_spritesheet_experiments(
            rows,
            images_dir=Path(args.images_dir).resolve(),
            sheets_dir=Path(args.sheets_dir).resolve(),
            results_path=results_path,
            sheet_cols=int(args.spritesheet_cols),
            cell_size=int(args.spritesheet_cell),
            dry_run=bool(args.dry_run),
            llm_augment=bool(args.llm_augment),
            llm_temperature=float(args.llm_temperature),
            llm_cache_path=Path(args.llm_cache).resolve() if args.llm_cache else None,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
