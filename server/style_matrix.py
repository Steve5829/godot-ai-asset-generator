from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict


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


STYLE_MATRIX: Dict[str, StyleProfile] = {
    "core_keeper": StyleProfile(
        key="core_keeper",
        title="Core Keeper-like",
        resolution="32x32 for items, 32x48 for two-face blocks (32x16 top + 32x32 front)",
        perspective="top-down for ground/items, two-face orthographic for blocks (no isometric warp)",
        outlines=(
            "soft 1px edge separation using darker local color tones, never pure black outlines; "
            "inner shapes separated by subtle color steps rather than hard line work"
        ),
        lighting=(
            "soft top-left ambient light with gentle internal glow on minerals and ores; "
            "shadows fall as muted teal-brown rather than pure black; emissive parts have a faint halo"
        ),
        palette=(
            "muted earthy underground palette: warm browns, mossy greens, dusty grays, and tan stone; "
            "accent colors are saturated jewel tones (cyan diamond, magenta scarlet, amber gold) "
            "used sparingly against the desaturated base"
        ),
        rendering=(
            "stylized handcrafted pixel art with visible texture clusters and small cell-shaded color regions; "
            "no dithering, no anti-aliasing, no gradients"
        ),
        detail_density="medium — readable clusters of small shapes (leaves, ore specks, root knots, sand grains)",
        shape_language=(
            "chunky readable silhouettes with rounded corners; "
            "items sit centered on transparent background with consistent ~2px padding; "
            "blocks present a top face and a separate front face stacked vertically (NOT an isometric cube)"
        ),
        notes=(
            "Core Keeper's signature look is underground biomes: forest (mossy green leaves on root walls), "
            "desert (golden sand on layered sandstone), ocean (wet blue-green coral rock), and dirt walls. "
            "Two-face block layout means the top tile and front tile are drawn flat side-by-side, then stacked."
        ),
    ),
    "minecraft": StyleProfile(
        key="minecraft",
        title="Minecraft-like",
        resolution="16x16 for blocks and items; isometric block previews compose three 16x16 faces into 32x32",
        perspective=(
            "front-facing flat tile for individual block faces; "
            "isometric ~30deg cube preview when showing top, front, and side together"
        ),
        outlines=(
            "no explicit outlines — shapes are defined by adjacent color blocks; "
            "items may have an implicit 1px darker border created by texture, not a drawn line"
        ),
        lighting=(
            "flat unshaded pixel grid with at most 2-3 brightness steps per material; "
            "top face is brightest, front face mid-tone, side face slightly darker; no specular highlights"
        ),
        palette=(
            "small high-saturation per-material palette (typically 4-6 colors per block); "
            "iron silver-gray, gold rich yellow, diamond bright cyan, redstone red, "
            "dirt warm brown, stone neutral gray, grass top vivid green, nether deep red"
        ),
        rendering=(
            "raw 16x16 pixel grid, no anti-aliasing, no smoothing, no dithering, no gradient ramps; "
            "each pixel is a single solid color"
        ),
        detail_density="low — coarse noise patterns and a few accent pixels per face, never fine line art",
        shape_language=(
            "perfectly square tiles that tile seamlessly with themselves on all edges; "
            "no object silhouette, no centered icon; the entire 16x16 is filled edge-to-edge with material"
        ),
        notes=(
            "Minecraft blocks are seamless tileable 16x16 material textures. "
            "Isometric block previews stack a 16x16 top diamond on top of left (front) and right (side) parallelograms. "
            "Items keep the same 16x16 grid but show a centered silhouette."
        ),
    ),
    "terraria": StyleProfile(
        key="terraria",
        title="Terraria-like",
        resolution="16x16 for tiles, 32x32 or 40x40 for weapons and items",
        perspective="side-view 2D platformer; items shown at a slight diagonal tilt; blocks tile horizontally",
        outlines=(
            "strong 1px dark-edge outlines, typically near-black or deep saturated brown/blue; "
            "outlines are continuous and define the full item silhouette"
        ),
        lighting=(
            "directional top-left light with bright highlight pixels and 2-3 step dithered shadow ramps; "
            "metal items get a single white-pixel specular hit on the blade or edge"
        ),
        palette=(
            "bright high-contrast palette with vivid saturation; "
            "weapons use warm metallic gradients, potions use vibrant glass colors, tiles use natural earthy bases "
            "with at least one bright accent tone"
        ),
        rendering=(
            "stylized pixel art with controlled dithering on shadow transitions and on glow effects; "
            "no anti-aliasing, no blurring"
        ),
        detail_density=(
            "medium-high — readable per-pixel detail on weapon edges, gem facets, "
            "potion liquid sloshes, and tile cracks"
        ),
        shape_language=(
            "thin readable profiles for weapons (long blades, slim handles) with strong edge contrast; "
            "blocks tile seamlessly on all sides with small natural variation specks"
        ),
        notes=(
            "Terraria's signature look is high-contrast saturated colors on a black-outlined silhouette. "
            "Weapons usually point up-right at ~45deg. Potions are clear glass vials with brightly colored liquid."
        ),
    ),
}


def style_profile_dict(style_key: str) -> Dict[str, str]:
    if style_key not in STYLE_MATRIX:
        raise KeyError(f"Unknown style profile: {style_key}")
    return asdict(STYLE_MATRIX[style_key])

