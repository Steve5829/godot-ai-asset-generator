import json
from pathlib import Path

STYLES_PATH = Path(__file__).parent / "data" / "styles.json"
_raw = json.loads(STYLES_PATH.read_text())
_default = _raw["default"]


def _layout(entry):
    return {
        "width": entry.get("width", _default["width"]),
        "top": entry.get("top", _default["top"]),
        "front": entry.get("front", _default["front"]),
        "side": entry.get("side", _default["side"]),
    }


BLOCK_LAYOUTS = {name: _layout(entry) for name, entry in _raw.items()}
DEFAULT_LAYOUT = BLOCK_LAYOUTS["default"]


def block_layout(style):
    return BLOCK_LAYOUTS.get(style, DEFAULT_LAYOUT)
