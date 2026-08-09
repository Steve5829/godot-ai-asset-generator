# Vibe Agent Backend (server_2)

The pixel-art generation backend for the Godot Vibe plugin. This is the **v2 rewrite**
of the original `server/` — same job, upgraded structure.
`server_2` keeps every proven behavior but splits it into a small, polymorphic pipeline.

## The creed

Every design decision here follows the same rules:

- **One pipeline, single responsibility.** Each stage does one thing and hands off.
- **Polymorphism + dict dispatch, not `if/else`.** Behavior is selected by looking a
  key up in a table, never by branching on type strings.
- **Resolve data once, at load.** Config (materials, prompts) is normalized when it is
  read, so the code that consumes it is pure lookup with no fallback branches.
- **Additive, never destructive.** A new capability is a new option alongside the old
  ones — existing behavior is never replaced in place.

## Workflow

A request flows through one pipeline (`generate/pipeline.py`):

```
Request  ──►  route()  ──►  Asset.build_plan()  ──►  Provider  ──►  Workflow  ──►  save
 input       pick asset      resolve a Plan         make pixels    orchestrate    output
             class by         (size, prompt,        (PixelLab /    (single /      records
             keyword          faces, workflow)      GPT Image)     compose /
                                                                   slice)
```

- **Request** (`generate/request.py`) — the raw input: prompt, size, folder, style, provider.
- **route** (`generate/router.py`) — matches a keyword in the prompt to an `Asset` class.
- **Asset** (`generate/asset.py`) — resolves a fully-specified `Plan`: dimensions, the
  final description, per-face descriptions for material blocks, which workflow to run.
- **Provider** (`generate/provider.py`) — turns a description into image bytes.
- **Workflow** (`generate/workflow.py`) — orchestrates provider calls and assembles the
  result. Current workflows:
  - `icon` — single image.
  - `block` — generates block faces and composes them (two-face stack or isometric cube).
  - `isometric_native` — PixelLab's native isometric tile endpoint.
  - `spritesheet` / `ground_atlas` — generate a sheet, then slice it into cells.
- **Composer** (`generate/composer.py`) — stitches faces into a block texture.
- **postprocess / save** (`generate/postprocess.py`, `generate/save.py`) — palette snap
  and write the PNG(s), returning output records for the plugin.

## Layout

```
server_2/
  api.py            FastAPI app, endpoints, and run entrypoint
  config.py         env vars and API keys
  text.py           tokens() / slug() helpers
  generate/
    request.py      Request dataclass (input)
    router.py       prompt keyword -> Asset class
    asset.py        Asset subclasses -> build a Plan
    plan.py         Plan dataclass (resolved recipe)
    prompt.py       data-driven block-face prompt builder
    provider.py     PixellabProvider / GPTProvider
    workflow.py     Icon / Block / Slice workflows
    composer.py     two-face and isometric composition
    postprocess.py  image cleanup (palette snap, ...)
    save.py         write outputs
    pipeline.py     the one pipeline
    data/           materials.json, block_prompt.json
  reference/        style/reference image selection + vision analysis
  automate/         editor automation planner
  modify/           geometric transforms (resize / aspect / rotate)
  reference_images/<style>/<asset>/   reference art, grouped by style
  tests/
```

## Endpoints

| Method | Path            | Purpose                                             |
|--------|-----------------|-----------------------------------------------------|
| POST   | `/vibe/generate`| Generate an asset from a prompt                     |
| POST   | `/vibe/automate`| Plan editor actions from a prompt + selected nodes  |
| POST   | `/vibe/modify`  | Geometric edit of an existing asset (resize/rotate) |
| GET    | `/vibe/options` | Available styles and providers for the dropdowns    |

## Usage

Install dependencies:

```bash
pip install -r requirements.txt
```

Add a `server_2/.env` with your keys:

```
PIXELLAB_API_KEY=your_key
OPENAI_API_KEY=your_key
```

Run the server (serves `http://127.0.0.1:8000`, the address the plugin expects):

```bash
python api.py
```

Then use the plugin from the Godot editor, or call it directly:

```bash
curl -X POST http://127.0.0.1:8000/vibe/generate \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"a rock block","folder":"output_test","width":16,"height":16}'
```

## Extending

Three extension points, each a small local change:

1. **Add a style** — drop a folder under `reference_images/<style>/`. No code change.
2. **Add an asset type** — subclass `Asset`, then add a keyword to `router.KEYWORDS`.
3. **Add a provider** — subclass `Provider`, then add an entry to `PROVIDER_CLASSES`.

The same shape applies deeper in: a new block material is a row in `data/materials.json`,
and a new composition mode is a `Composer` subclass plus a `COMPOSER_CLASSES` entry.
