from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List


@dataclass(frozen=True)
class StyleProfile:
    key: str
    title: str
    resolution: str
    perspective: str
    outlines: str
    lighting: str
    palette: str
    rendering: str
    detail_density: str
    shape_language: str
    notes: str


@dataclass(frozen=True)
class BenchmarkItem:
    key: str
    title: str
    category: str
    description: str
    visual_focus: str


STYLE_MATRIX: Dict[str, StyleProfile] = {
    "core_keeper": StyleProfile(
        key="core_keeper",
        title="Core Keeper-like",
        resolution="32x32 or 48x48",
        perspective="top-down",
        outlines="soft edge separation using darker local colors",
        lighting="soft internal glow and compact shading",
        palette="muted earthy tones with selective accent colors",
        rendering="stylized pixel art",
        detail_density="medium",
        shape_language="chunky readable silhouettes with handcrafted texture clusters",
        notes="Useful baseline for glowing minerals, tools, and underground loot drops.",
    ),
    "minecraft": StyleProfile(
        key="minecraft",
        title="Minecraft-like",
        resolution="16x16",
        perspective="front-facing icon view",
        outlines="minimal or absent explicit outlines",
        lighting="simple flat shading with low contrast",
        palette="vibrant but limited, strong block-color readability",
        rendering="simple pixel icon",
        detail_density="low",
        shape_language="blocky, geometric, low-frequency detail",
        notes="Useful baseline for highly simplified items and low-detail silhouettes.",
    ),
    "terraria": StyleProfile(
        key="terraria",
        title="Terraria-like",
        resolution="16x16 or 32x32",
        perspective="side-view",
        outlines="strong dark outlines, often 1px-black-adjacent edges",
        lighting="bright highlights with dithered or high-contrast shadow steps",
        palette="bright and high-contrast",
        rendering="stylized pixel art",
        detail_density="medium-high",
        shape_language="thin readable profiles with strong edge contrast",
        notes="Useful baseline for weapons, potions, and combat-oriented pickups.",
    ),
}


BENCHMARK_ITEMS: List[BenchmarkItem] = [
    BenchmarkItem(
        key="iron_sword",
        title="Iron Sword",
        category="weapon",
        description="A practical iron sword with a simple guard and readable metallic blade.",
        visual_focus="Long silhouette, edge readability, and metal highlight control.",
    ),
    BenchmarkItem(
        key="healing_potion",
        title="Healing Potion",
        category="consumable",
        description="A small healing potion in a glass vial with vivid liquid inside.",
        visual_focus="Container silhouette, liquid color separation, and glass readability.",
    ),
    BenchmarkItem(
        key="crystal_ore",
        title="Crystal Ore",
        category="resource",
        description="A crystal ore chunk with irregular geometry and visible internal glow.",
        visual_focus="Glow handling, irregular silhouette, and clustered texture detail.",
    ),
]


def style_profile_dict(style_key: str) -> Dict[str, str]:
    if style_key not in STYLE_MATRIX:
        raise KeyError(f"Unknown style profile: {style_key}")
    return asdict(STYLE_MATRIX[style_key])


def benchmark_item_dict(item_key: str) -> Dict[str, str]:
    item = next((entry for entry in BENCHMARK_ITEMS if entry.key == item_key), None)
    if item is None:
        raise KeyError(f"Unknown benchmark item: {item_key}")
    return asdict(item)


def build_prompt(item: BenchmarkItem, style: StyleProfile) -> str:
    return (
        f"{item.title}, {item.description} "
        f"Pixel art asset, {style.resolution}, {style.perspective} perspective, "
        f"{style.outlines}, {style.lighting}, {style.palette}, "
        f"{style.rendering}, {style.detail_density} detail density, "
        f"{style.shape_language}. "
        f"Focus on {item.visual_focus}"
    )


def build_experiment_matrix() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for item in BENCHMARK_ITEMS:
        for style in STYLE_MATRIX.values():
            rows.append(
                {
                    "item_key": item.key,
                    "item_title": item.title,
                    "style_key": style.key,
                    "style_title": style.title,
                    "prompt": build_prompt(item, style),
                }
            )
    return rows
