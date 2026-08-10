# Godot Vibe Plugin

> ✅ **Current branch (v2)** — the latest version. Earlier stages: [`v1`](../../tree/v1) · [`v0`](../../tree/v0).

An AI-powered editor automation tool for Godot, powered by pocketpy.

Godot Vibe Plugin brings prompt-driven asset generation, asset modification, and
editor automation into the Godot editor. It combines a GDScript editor plugin with
a local FastAPI backend that plans structured actions through an OpenAI-compatible
model and generates pixel art through PixelLab (or GPT Image).

## Contents

- [Features](#features)
- [How it works](#how-it-works)
  - [Request flow](#request-flow)
  - [Asset types](#asset-types)
  - [Generation modes](#generation-modes)
  - [How blocks are composed](#how-blocks-are-composed)
  - [Providers](#providers)
- [Generation approaches and evolution](#generation-approaches-and-evolution)
- [Branches](#branches)
- [Adding a new game style](#adding-a-new-game-style)
- [Repository layout](#repository-layout)
- [Setup](#setup)
- [Usage](#usage)
- [Troubleshooting](#troubleshooting)

## Features

- Generate new assets from text prompts directly from the FileSystem dock.
- Modify existing image assets with structured operations (resize, aspect-ratio
  canvas changes, rotation).
- Automate scene editing tasks from natural-language prompts in the Scene dock.
- Use structured planning instead of arbitrary code execution for safer actions.

## How it works

### Request flow

```
Godot editor (right-click menu)
      |  prompt + context (style, provider, generation mode)
      v
POST http://127.0.0.1:8000/vibe/<generate|modify|automate>
      v
Backend planning  (server/server.py)
      |  1. infer asset type from the prompt
      |  2. build a fallback plan (deterministic, rule-based)
      |  3. ask the LLM to refine the plan (description, size, workflow)
      |  4. attach style signals according to the generation mode
      v
Backend execution
      |  call the image provider, then post-process / compose
      v
PNG files saved into the chosen res:// folder
```

The plan is a plain dictionary describing what to make (asset type, workflow,
width/height, descriptions, postprocess settings). Generation never runs arbitrary
code; it only fills in a fixed plan shape.

### Asset types

The asset type is inferred from the prompt automatically (no manual picker).

| Asset type | Produces | Default size | Transparent bg |
|---|---|---|---|
| `icon` | A single inventory/UI item or static sprite | 128x128 | yes |
| `block_texture` | A tileable block composed from per-face textures | per style | no |
| `ground_atlas` | One continuous tileable terrain swatch | 128x128 | no |
| `spritesheet` | A grid of animation frames | 256x256 | yes |
| `reference_scene` | A building / structure / environment concept | 400x400 | no |

Routing keywords: `block` picks `block_texture`; `atlas` / `tilemap` / `ground` /
`floor` / `terrain` pick `ground_atlas`; `spritesheet` / `animation` /
`walk cycle` pick `spritesheet`; building words (house, castle, tower, ruins, ...)
pick `reference_scene`; anything else falls back to `icon`. Explicit type words
(`atlas`, `block`, `spritesheet`) override the LLM's guess so the user's intent
always wins.

### Generation modes

The Generate dialog has a Generation Mode dropdown. The mode does not change which
asset type or workflow is chosen; it only controls how style is applied, through
two switches:

- Switch 1, reference analysis: a vision model looks at matching reference images
  and summarizes their style into words that are added to the prompt.
- Switch 2, style transfer: the matching reference image's pixels are fed directly
  into PixelLab's bitforge endpoint for true image-to-image style transfer.

| Mode | Reference analysis (text) | Style transfer (pixels) | Net effect |
|---|---|---|---|
| Plain text | off | off | Pure text to pixflux |
| Reference analysis | on | off | Vision-summarized traits added to the prompt |
| Style transfer | off | on (all asset types) | Reference pixels fed to bitforge |
| Auto (smart) | on | on (material asset types only) | Hybrid: icons use text, blocks/ground use style transfer |

What stays the same in every mode: prompt routing, the chosen asset type/workflow,
and the built-in style/material/icon descriptions (from `server/data/`). That is
why Plain text already produces meaningful output: the hardcoded descriptions are
always part of the prompt.

### How blocks are composed

A block is not one flat image. The backend generates the individual faces and then
stacks or projects them into a final block image. The layout depends on the style.

Face generation:

- Uniform materials (stone, metal, gem, obsidian, glass, ...) generate one face
  image and reuse it for every face.
- Multi-face materials (forest grass-over-dirt, desert sand-over-sandstone, ocean,
  wood log) generate each face separately, because the top and the side really do
  look different.
- Faces are generated at an integer multiple of the final face size, then resized
  down with nearest-neighbor so pixels stay crisp.

Two-face layout (Core Keeper, Terraria, Stardew), `compose_mode = vertical_strip`:

```
Core Keeper example (final width 32):
  +----------------+   top face   32 x 16   (the surface seen from above)
  |      top       |
  +----------------+
  |                |   front face 32 x 32   (the wall seen from the front)
  |     front      |
  |                |
  +----------------+   composed image: 32 x 48, top stacked above front
```

Three-face isometric layout (Minecraft), `compose_mode = isometric`:

```
  Three 16x16 faces (top, front, side) are warped into a cube preview:
        /\
       /  \        top   -> diamond on the cap (brightest shading)
      |\  /|        front -> left parallelogram (mid shading)
      | \/ |        side  -> right parallelogram (darkest shading)
       \  /
        \/
  composed output: 32 x 32 isometric block preview
```

Outputs saved per block: the composed block PNG plus each source face
(`*_top.png`, `*_front.png`, and `*_side.png` for three-face).

### Providers

- PixelLab: pixel-art native. `pixflux` for text-to-image, `bitforge` for style
  transfer with a reference image.
- GPT Image: better at composition and following instructions, useful for
  reference scenes.

Style transfer (and the style-transfer step inside Auto) is PixelLab only. GPT
Image has no bitforge equivalent yet, so those modes fall back to text generation
when GPT Image is selected.

## Generation approaches and evolution

The project tried several ways to make output match a target game style. All of
them are preserved as selectable modes, and each maps to a development stage in the
git history.

| Approach | Mode | Idea | Key commits |
|---|---|---|---|
| Hardcoded descriptions | Plain text | Fixed visual text per material/item, composed into the prompt. Now stored in `server/data/materials.json` (46 blocks) and `server/data/icons.json` (32 categories). | `5ae4918`, `ae92749`, `04037d8` |
| Reference-guided | Reference analysis | A vision model summarizes reference images into style words added to the prompt. Reference pixels never reach the generator. | `489fb11`, `a6b2019` |
| Image-to-image | Style transfer | Reference image pixels are fed to PixelLab bitforge for true style transfer. | `e97e800`, `4765b89`, `f93510b`, `009c8f6`, `3701d4d` |
| Smart hybrid | Auto | Picks per asset type: style transfer for blocks/ground, reference analysis for icons. | `94ea0da`, `ff8edb7` |

Observed failure mode, useful as a "why not" example: generating `axe` (minecraft)
in Style transfer mode yields a blurry green block. Three causes stack: the
reference `axe.png` is a 310x338 mostly-white render rather than a clean sprite;
bitforge fills the canvas and erases the icon silhouette; and the icon path does
not run the palette cleanup that block faces get. Auto mode avoids this by never
applying style transfer to icons.

To compare approaches, use the same prompt and style and generate once per mode:

- `diamond block` x minecraft (block across modes)
- `healing potion` x core_keeper (icon across modes)
- `forest ground` x stardew (terrain across modes)

The backend logs `mode: xxx` on every request so you can record which method each
image used.

## Branches

The project is developed as three branches, each a distinct stage. `v2` is the
active branch; `v0` and `v1` are kept for reference.

### v0 — prototype

The first working version. A single `server/server.py` (~750 lines) exposes the
three workflows — generate, modify, automate — planning through an OpenAI-compatible
model and generating with PixelLab. There is no style system yet: no style packs,
no reference images, no tests. This branch is the smallest, clearest read of the
core idea.

### v1 — style modeling

The style-fidelity era. `server/server.py` grows to ~2762 lines and gains a full
style layer: per-game **style packs** (`server/packs/*.json`), **reference images**,
data tables, evaluation cases (`eval_cases.json`), plan snapshots, and planner /
reference tests. A single `server.py` handles planning, provider calls,
composition, and post-processing — feature-complete, with room to improve the
structure.

Both v0 and v1 carry `server/experiment.py`, an **offline style-benchmark runner**.
It generates an item × style matrix (every test item rendered in every style) so
the output could be compared side by side while tuning style profiles. It is a
research tool, not part of the running plugin — in v1 it is guarded off and exits
immediately unless the benchmark symbols it depends on are restored in
`style_matrix.py`.

### v2 — modular rewrite

The current branch. The v1 `server/` is kept intact for reference, and a new
`server_2/` reimplements the same behavior as a small, polymorphic pipeline —
one pipeline, dict dispatch instead of `if/elif`, data resolved once at load.
See [server_2/README.md](server_2/README.md) for its structure and usage.

## Adding a new game style

The engine carries no game-specific knowledge in code. Styles, block layouts,
materials, and icon anchors all live in data files:

- `server/packs/<style>.json`: a style's look description plus its block layout.
- `server/data/materials.json`: shared block material descriptions.
- `server/data/icons.json`: shared icon category descriptions.
- `server/reference_images/<style>/<asset_type>/`: reference images.

Adding a new style is one new `packs/<style>.json` file with zero Python changes.
The backend serves the style list to the editor dynamically, so the dropdown picks
it up automatically. Stardew support was added exactly this way (commit `8884a18`).

Regression tests guard the planner: `server/test_planner.py` (routing and profile
matching) and `server/test_plan_snapshot.py` (full plan snapshots).

## Repository layout

- `addons/vibe_agent/`: Godot editor plugin (GDScript).
- `server/server.py`: FastAPI backend for planning, generation, and image editing.
- `server/packs/`, `server/data/`: style and material/icon data.
- `server/reference_images/`: reference art per style and asset type.
- `server/requirements.txt`: Python dependencies for the backend.

## Setup

Requirements: Python 3.7+, Godot 4.x, a PixelLab API key, and an OpenAI-compatible
API key for prompt planning.

Install backend dependencies:

```bash
python3 -m pip install -r server/requirements.txt
```

Create `server/.env`:

```dotenv
PIXELLAB_API_KEY=your-pixellab-api-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4o-mini
```

Start the backend from the repository root (restart it after editing
`server/server.py`):

```bash
python3 server/server.py
```

Enable the plugin in Godot. The plugin source lives in `addons/vibe_agent/`.

## Usage

Generate Asset: in the FileSystem dock, right-click a folder and choose
`Vibe: Generate Asset`. Pick a Style Target, Provider, and Generation Mode, then
type a prompt, for example `a 32x32 pixel pickaxe icon`.

Modify Asset: right-click an existing image and choose `Vibe: Modify Asset`, for
example `Resize the image into 16:9`.

Editor Automation: in the Scene dock, right-click a node and choose
`Vibe: Automation`, for example `Rename all children start from 0 with "child_%d"`.

## Troubleshooting

If menu items do not appear, make sure the plugin is enabled and reopen the project
after updating plugin scripts.

If requests fail, make sure `python3 server/server.py` is running, and check both
the Godot output panel and the backend terminal logs.

If model-backed features misbehave, verify `PIXELLAB_API_KEY`, `OPENAI_API_KEY`,
`OPENAI_BASE_URL`, and `OPENAI_MODEL`, and confirm the machine can reach those
endpoints. Remember to restart the backend after changing `server/server.py`.

Developed by Steve Chen as part of the pocketpy ecosystem.
