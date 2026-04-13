# Style Modeling

This repository now includes a first-pass style modeling baseline for pixel-art benchmarking. The goal is to define style targets as structured dimensions before integrating them into any Godot workflow.

## Style Matrix

| Dimension | Core Keeper | Minecraft | Terraria |
| --- | --- | --- | --- |
| Resolution | 32x32 or 48x48 | 16x16 | 16x16 or 32x32 |
| Perspective | Top-down | Front-facing icon view | Side-view |
| Outlines | Soft edge separation using darker local colors | Minimal or absent explicit outlines | Strong dark outlines |
| Lighting | Soft internal glow and compact shading | Simple flat shading with low contrast | Bright highlights with dithered or high-contrast shadow steps |
| Palette | Muted earthy tones with selective accent colors | Vibrant but limited, strong block-color readability | Bright and high-contrast |
| Rendering | Stylized pixel art | Simple pixel icon | Stylized pixel art |
| Detail density | Medium | Low | Medium-high |
| Shape language | Chunky readable silhouettes with handcrafted texture clusters | Blocky, geometric, low-frequency detail | Thin readable profiles with strong edge contrast |

## Benchmark Items

- `iron_sword`: tests long silhouettes, edge readability, and metallic highlights.
- `healing_potion`: tests container shape, liquid separation, and glass readability.
- `crystal_ore`: tests irregular geometry, internal glow, and texture clustering.

## Experiment Script

Use the local manifest generator to produce a structured set of benchmark prompts:

```bash
python3 server/experiment.py --print-prompts
```

This writes:

- `server/output/style_benchmark_manifest.json`

The manifest is meant to be the baseline for later provider comparisons and prompt-synthesis experiments.
