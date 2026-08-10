# Godot Vibe Plugin

> ✅ **Current branch (v2)** — the latest version. Earlier stages: [`v1`](../../tree/v1) · [`v0`](../../tree/v0).

Generate pixel-art assets, edit them, and automate scene changes from
natural-language prompts, inside the Godot editor. A GDScript editor plugin talks to
a local FastAPI backend (`server_2/`).

## Contents

- [How it works](#how-it-works)
- [Branches](#branches)
- [Setup](#setup)
- [Usage](#usage)
- [Troubleshooting](#troubleshooting)

## How it works

Right-click in the editor. The plugin sends your prompt to the local backend, which
runs one pipeline and writes PNG(s) into the chosen `res://` folder.

```
Godot editor (right-click)
   │  prompt + context (style, provider)
   ▼
POST http://127.0.0.1:8000/vibe/{generate|modify|automate}
   ▼
route → build_plan → provider → workflow → save
   ▼
PNG(s) in the chosen res:// folder
```

| Endpoint | Does |
|---|---|
| `generate` | prompt → asset (icon, block, isometric block, spritesheet, ground atlas) |
| `modify`   | geometric edit of an image (resize / aspect ratio / rotate) |
| `automate` | prompt + selected nodes → structured editor actions |
| `options`  | styles and providers for the dialog dropdowns |

The asset type is inferred from prompt keywords (`block`, `isometric`, `composite`,
`spritesheet`, `atlas`, `icon`; default `icon`). Images come from **PixelLab**
(pixel-art native) or **GPT Image**. Styles are folders under
`server_2/reference_images/<style>/`.

The backend pipeline, extension points, and data tables are documented in
[server_2/README.md](server_2/README.md).

## Branches

The project is developed as three branches, each a distinct stage. `v2` is the
active branch; `v0` and `v1` are kept for reference.

### v0 — prototype

The first working version. A single `server/server.py` (~750 lines) exposes the
three workflows — generate, modify, automate — planning through an OpenAI-compatible
model and generating with PixelLab. No style system yet: no style packs, no
reference images, no tests. The smallest, clearest read of the core idea.

### v1 — style modeling

The style-fidelity era. `server/server.py` grows to ~2762 lines and gains a full
style layer: per-game style packs (`server/packs/*.json`), reference images, data
tables, evaluation cases, plan snapshots, and planner / reference tests.
Feature-complete, with room to improve the structure.

Both v0 and v1 carry `server/experiment.py`, an offline style-benchmark runner that
renders an item × style matrix so outputs can be compared side by side while tuning
style profiles. It is a research tool, not part of the running plugin.

### v2 — modular rewrite

The current branch. The v1 `server/` is kept for reference, and a new `server_2/`
reimplements the same behavior as a small, polymorphic pipeline — one pipeline, dict
dispatch over long conditionals, data resolved once at load. See
[server_2/README.md](server_2/README.md).

## Setup

Requirements: Python 3.10+, Godot 4.x, and API keys for PixelLab and/or an
OpenAI-compatible provider.

```bash
pip install -r server_2/requirements.txt
```

Create `server_2/.env`:

```dotenv
PIXELLAB_API_KEY=your-pixellab-api-key
OPENAI_API_KEY=your-openai-api-key
```

Run the backend (serves `http://127.0.0.1:8000`), then enable the plugin in Godot:

```bash
cd server_2 && python api.py
```

## Usage

- **Generate** — FileSystem dock, right-click a folder → `Vibe: Generate Asset`.
  Pick a style and provider, then prompt, e.g. `a 32x32 pixel pickaxe icon` or
  `a rock block`.
- **Modify** — right-click an image → `Vibe: Modify Asset`, e.g. `resize into 16:9`.
- **Automate** — Scene dock, right-click a node → `Vibe: Automation`, e.g.
  `rename all children as "child_%d" starting from 0`.

## Troubleshooting

- Menu items missing: enable the plugin, then reopen the project.
- Requests fail: make sure `python api.py` is running; check the Godot output panel
  and the backend terminal.
- Model errors: verify `PIXELLAB_API_KEY` / `OPENAI_API_KEY` in `server_2/.env` and
  that the machine can reach those endpoints.

Developed by Steve Chen as part of the pocketpy ecosystem.
