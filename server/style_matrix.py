"""Style pack loader.

Each supported game style is a data file under packs/<key>.json with shape:

    {
      "style":        { key, title, resolution, perspective, ... },
      "block_layout": { workflow, final_width, top_height, ... }
    }

Adding a new game style means dropping a new packs/<key>.json file — no code
change here. STYLE_MATRIX maps style key -> the style dict; STYLE_BLOCK_LAYOUTS
maps style key -> the block layout dict.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

PACKS_DIR = Path(__file__).resolve().parent / "packs"

STYLE_MATRIX: Dict[str, Dict[str, str]] = {}
STYLE_BLOCK_LAYOUTS: Dict[str, Dict[str, object]] = {}


def _load_packs() -> None:
    STYLE_MATRIX.clear()
    STYLE_BLOCK_LAYOUTS.clear()
    if not PACKS_DIR.is_dir():
        return
    for pack_path in sorted(PACKS_DIR.glob("*.json")):
        try:
            with pack_path.open(encoding="utf-8") as f:
                pack = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print("Skipping malformed style pack %s: %s" % (pack_path.name, exc))
            continue
        style = pack.get("style") if isinstance(pack.get("style"), dict) else None
        if not style:
            continue
        key = str(style.get("key") or pack_path.stem)
        style.setdefault("key", key)
        STYLE_MATRIX[key] = style
        layout = pack.get("block_layout")
        STYLE_BLOCK_LAYOUTS[key] = layout if isinstance(layout, dict) else {}


def style_profile_dict(style_key: str) -> Dict[str, str]:
    if style_key not in STYLE_MATRIX:
        raise KeyError(f"Unknown style profile: {style_key}")
    return dict(STYLE_MATRIX[style_key])


def style_block_layout(style_key: str) -> Dict[str, object]:
    return dict(STYLE_BLOCK_LAYOUTS.get(style_key, {}))


_load_packs()
