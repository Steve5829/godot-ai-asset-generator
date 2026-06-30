# Generation Approaches

This document records every style-generation approach the plugin has tried. All of
them are preserved: you can switch between them live in the editor via the
**Generation Mode** dropdown, and you can revisit each stage's implementation in the
git history.

> In Godot: right-click a folder → `Vibe: Generate` → pick a **Generation Mode**.
> A description of the selected mode is shown right under the dropdown.

---

## The four selectable modes (built into the plugin)

| Mode | What it does | Best for | Approach stage |
|---|---|---|---|
| **Plain text** | Generates from the text prompt plus the built-in style/material descriptions only. No reference images. | Most stable and fast; subject stays clear | The original "hardcoded descriptions" approach |
| **Reference analysis** | Uses GPT-4o vision to analyze matching reference images, summarizes their style in words, and adds that to the prompt. | Getting closer to a reference while keeping the subject | The mid-stage "reference-guided" approach |
| **Style transfer** | Feeds the matching reference image's pixels straight into PixelLab (bitforge) for true style transfer. | Block/ground textures that closely match the target game | The latest "image-to-image" approach |
| **Auto (smart)** | Picks the method per asset type: style transfer for block/ground, reference analysis for icons. | Everyday default; auto-selects the best | A smart hybrid of all three |

---

## Each approach in detail, with key commits

### 1. Plain text — hardcoded descriptions (original approach)
- **Idea**: each material/item carries a fixed visual description in the data
  ("dark purple-black volcanic glass", "gold metal with amber noise", ...) that is
  composed into the prompt and sent to PixelLab pixflux (text-to-image).
- **Status**: those descriptions now live in `server/data/materials.json`
  (46 blocks) and `server/data/icons.json` (32 icon categories), and the
  **Plain text mode still uses them**.
- **Key commits**:
  - `5ae4918` Use profiled block face materials — introduced material profiles
  - `ae92749` Constrain block face generation prompts — constrained face prompts
  - `04037d8` Add asset type image generation framework — overall framework
- **Demo**: pick Plain text, generate `obsidian block` / `healing potion`; the
  hardcoded visual text shows up in the description.

### 2. Reference analysis — text guidance from references (mid-stage)
- **Idea**: place real game art under `reference_images/<game>/<type>/`. At
  generation time a vision model analyzes them and summarizes traits
  (palette / outline / material) into words that are added to the prompt. The
  reference pixels themselves never reach the generator.
- **Key commits**:
  - `489fb11` Add reference image guidance — introduced reference analysis
  - `a6b2019` Select reference images by prompt — match references by prompt
- **Demo**: pick Reference analysis, generate an icon; the backend log shows
  `references: analyzed (N)`.

### 3. Style transfer — image-to-image (latest)
- **Idea**: pass the matching reference image's pixels directly as `style_image`
  to PixelLab's **bitforge** endpoint for real style transfer, instead of only
  passing text.
- **Key commits**:
  - `e97e800` Pass reference images to PixelLab as style guidance — wired bitforge
  - `4765b89` Resize style image to match PixelLab output size — size-match fix
  - `f93510b` Generate styled block faces at crisp integer-multiple sizes — blur fix
  - `009c8f6` Limit style transfer to material asset types — gate to textures
  - `3701d4d` Snap styled block faces to a tight palette — palette quantization
- **Known behavior**: works well for block/ground textures; for icons (e.g. a
  zombie) it overwhelms the subject into a muddy block, so Auto mode does not
  apply it to icons by default (but selecting Style transfer explicitly does, for
  side-by-side comparison).
- **Demo**: pick Style transfer, generate `diamond block` (minecraft); the backend
  log shows `Using style reference image for PixelLab generation`.

#### Observed failure mode: `axe` (minecraft, Style transfer) → blurry green block

A concrete example of why Auto excludes icons from style transfer. Three causes stack:

1. **Bad reference image** — `reference_images/minecraft/icon/axe.png` is 310x338,
   fully opaque, ~76% near-white background. It is a large render, not a clean
   pixel-art sprite, so it is garbage input for style transfer.
2. **Wrong tool for icons** — bitforge fills the canvas with the reference's look;
   for an icon it erases the subject silhouette (the axe shape) into a filled block.
3. **No palette cleanup on icons** — the palette-snap step that de-muddies output
   only runs on block faces, not the single-image (icon) path, so the soft bitforge
   colors stay.

The green tint is not from the reference (which is white/gold) — under heavy style
strength plus the transparent-background-vs-opaque-reference conflict, bitforge
collapses into a muddy mid-tone. Net: bad reference x wrong tool x no cleanup =
blurry green block. Useful as the "why not" demo against applying style transfer to
icons.

### 4. Auto — smart hybrid (current default)
- **Idea**: combines the above, choosing the best method per asset type.
- **Key commits**:
  - `94ea0da` Add selectable generation mode — introduced mode selection
  - `ff8edb7` Show a description under the generation mode dropdown — mode descriptions

---

## Architecture evolution (making "add a game = add a file" possible)

Beyond the generation methods, the code structure was refactored so that adding a
new game style needs no Python changes:

| Stage | Commit | Result |
|---|---|---|
| Data-driven branches | `a01bc32` | Moved hardcoded if/else branches into data tables |
| Externalized data | `cc8fb9d` `4420843` | Styles/materials/icons moved to JSON in `packs/` and `data/` |
| Dynamic registration | `fe12f6b` | Backend serves options dynamically; editor dropdowns update automatically |
| Regression tests | `1ee9dba` | `test_planner.py` (108) + `test_plan_snapshot.py` (9) guard refactors |

**Result**: adding the Stardew style took just one new file, `packs/stardew.json`
(see `8884a18`), with zero Python changes — the editor dropdown picks up Stardew
automatically.

---

## How to compare approaches

Use the **same prompt + same Style Target**, then generate once per Generation Mode
and compare the results side by side. Suggested combinations:

- `diamond block` × minecraft — compare the block across Plain / Reference / Style transfer
- `healing potion` × core_keeper — compare an icon across modes
- `forest ground` × stardew — compare ground terrain across modes

The backend logs `mode: xxx` on every request, so you can record which method each
image used.
