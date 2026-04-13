from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from style_matrix import BENCHMARK_ITEMS, STYLE_MATRIX, build_experiment_matrix


def _serialize_manifest(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "styles": [style.key for style in STYLE_MATRIX.values()],
        "items": [item.key for item in BENCHMARK_ITEMS],
        "row_count": len(rows),
        "rows": rows,
    }


def _write_manifest(manifest: Dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a local benchmark manifest for pixel-art style modeling experiments."
    )
    parser.add_argument(
        "--output",
        default="server/output/style_benchmark_manifest.json",
        help="Path to write the benchmark manifest JSON.",
    )
    parser.add_argument(
        "--print-prompts",
        action="store_true",
        help="Print each generated prompt to stdout for quick inspection.",
    )
    args = parser.parse_args()

    rows = build_experiment_matrix()
    manifest = _serialize_manifest(rows)
    output_path = Path(args.output).resolve()
    _write_manifest(manifest, output_path)

    print(f"Wrote benchmark manifest to {output_path}")
    print(f"Styles: {', '.join(manifest['styles'])}")
    print(f"Items: {', '.join(manifest['items'])}")
    print(f"Prompt combinations: {manifest['row_count']}")

    if args.print_prompts:
        print()
        for row in rows:
            print(f"[{row['style_key']}] {row['item_key']}: {row['prompt']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
