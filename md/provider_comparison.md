# Provider Comparison — Multi-Tool Survey

A side-by-side quality survey of four text-to-pixel-art providers on the same prompts and asset types. Companion to the main paper (*Godot Asset Generator — Workflow and Provider Comparison*), which deep-dives the **native vs. downscale** mechanism between PixelLab and OpenAI. Here the question is wider and simpler: **given the same request, which tool produces the more usable game asset?**


---

## 1. Providers

| Provider | How generated here | Native pixel output? | Role |
|----------|--------------------|----------------------|------|
| **PixelLab** | reused from main paper | yes (≤400 px)        | baseline |
| **OpenAI GPT Image** | reused from main paper | no (1024 render + downscale) | baseline |
| **Meowa** ([meowa.ai](http://meowa.ai)) | web UI, default settings | mode-dependent (see 4) | new  |
| **FrameRonin** ([frameronin.com](http://frameronin.com)) | web UI →preset / needs API key | no (nano-banana, 1k → downscale) | new  |


PixelLab and OpenAI are **not regenerated** — their images are reused from the main paper as a reference line. Meowa and FrameRonin are generated on their own websites.


---

## 2. Method

* **Self-generated, not gallery images.** Every image is generated with our own prompt.
* **Same prompt per row.** Only the provider changes across a row; the asset and prompt are held fixed
* **Display.** Baseline images are shown upscaled ×8 (nearest-neighbor) for legibility

### 2.1 Prompts

Three prompts, reused from the main paper; for tiles only the size token changes.

* **Tile** (16 / 24 / 32): `stone floor tile <N>x<N>, seamless top-down ground texture, flat even lighting, tight limited palette, crisp hard pixels, no scene, no background`
* **Character** (32): `knight character sprite 32x32, front-facing full body, clear silhouette, readable at small size, limited palette, hard edges, transparent background`
* **Scene** (640×360): `top-down forest clearing scene 640x360, overhead orthographic view for a 2D top-down game, dirt path through grass, pixel art environment, cohesive limited palette, flat ground plane, no horizon, no side perspective, no UI, no text`
* **Icon** (24×24): `healing potion icon 24x24, front-facing, centered, clear silhouette, transparent background, readable at small size, limited palette, hard edges`


### 2.2 Settings

| Asset | Meowa | FrameRonin |
|-------|-------|------------|
| Tile 16 | 模板生成 · 16px native · 36/job | 自由生图 · 1k → crop + downscale to 16 |
| Tile 24 | 模板生成 · 24px native · 15/job | 自由生图 · 1k → crop + downscale to 24 |
| Tile 32 | 模板生成 · 32px native · 15/job | 自由生图 · 1k → crop + downscale to 32 |
| Character 32 | 模板生成 · 32px native (64px avail) · 15/job | 常规角色 V2 preset · 1:1, 1k → downscale to 32 |
| Icon 24 | 模板生成 · 24px native (icon template) | 自由生图 / preset |
| Scene | 万能生成 → 像素场景生成 · 3:2 · 576×382 | 自由生图 (no top-down preset) · 16:9, 1k → downscale to 640×360 |

*FrameRonin: all via `gemini-2.5-flash-image` on OpenRouter. Tiles = one cell cropped from the full tiled-floor grid the model produced (see §4).*


---

## 3. Result grids

### Tile — 16×16

| PixelLab | OpenAI | Meowa | FrameRonin |
|----------|--------|-------|------------|
|  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/pixellab_tile_16.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/openai_tile_16.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/meowa_tile_16.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/frameronin_tile_16.png) |

### Tile — 24×24

| PixelLab | OpenAI | Meowa | FrameRonin |
|----------|--------|-------|------------|
|  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/pixellab_tile_24.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/openai_tile_24.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/meowa_tile_24.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/frameronin_tile_24.png) |

### Tile — 32×32

| PixelLab | OpenAI | Meowa | FrameRonin |
|----------|--------|-------|------------|
|  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/pixellab_tile_32.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/openai_tile_32.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/meowa_tile_32.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/frameronin_tile_32.png) |


### Character — 32×32

| PixelLab | OpenAI | Meowa | FrameRonin |
|----------|--------|-------|------------|
|  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/pixellab_character_32.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/openai_character_32.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/meowa_character_32.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/frameronin_character_32.png) |


### Icon — 24×24

Icon is the plugin's own core asset type — a single item on transparent background. Unlike the other rows, there is **no reused baseline** from the main paper, so PixelLab and OpenAI icons are generated fresh here.

| PixelLab | OpenAI | Meowa | FrameRonin |
|----------|--------|-------|------------|
|  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/pixellab_icon_24.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/openai_icon_24.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/meowa_icon_24.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/frameronin_icon_24.png) |

### Scene

Sizes differ by provider ceiling — label each with its true size.

| PixelLab (400×224, max) | OpenAI (640×360) | Meowa **(576×382 (3:2))** | FrameRonin(640×360) |
|-------------------------|------------------|-----------------------|---------------------|
|  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/pixellab_scene_400x224.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/openai_scene_640x360.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/meowa_scene_576x382.png) |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/frameronin_scene_640x360.png) |


---

## 4. Observations

* **Meowa** — Two generation modes that split along this paper's native-vs-downscale line.
  * **Template mode (模板生成)** sets a true pixel size — 16 / 24 / 32, a fine grid that includes the production 24 px — so it outputs *native* small pixels like PixelLab. The icon thumbnail is only a preview; the prompt drives the output. The tile prompt returned a **batch of 36 native 16×16 stone-floor tiles** in one job (appendix) — effectively a free tileset. Native size plus many variations at once is its real strength.
  * **Universal mode (万能生成)** takes a free prompt but exposes only an aspect ratio, not a pixel size, so it renders large and must be downscaled, like OpenAI. No 1:1 (awkward for square tiles) and no 16:9 (3:2 chosen as closest to 640×360). Better suited to scenes.
  * **Icon (template mode).** The healing-potion prompt returned 15 native 24×24 icons in one job (round, heart, star, test-tube, jar variants), each with a real transparent background and clean hard pixels — a ready icon set at the exact production size, no downscale. Icons behave exactly like tiles: native small size, batch output.
* **FrameRonin** — A bring-your-own-model client, not a turnkey generator.
  * It hosts no model; it is a front-end over an external API defaulting to `nano-banana` (Google's Gemini image model). Every generation needs an API key — a paid relay in practice — or Google access, making it the least self-contained of the four.
  * **Character (preset V2).** Returned a full animation sheet of a green-armored *soldier*, not the requested knight — the preset's own prompt overrode the description, so presets break the same-prompt control. Detailed at 1k, but downscaled to 32×32 it collapses into a muddy blob: the same native-vs-downscale failure as OpenAI, and a sharp contrast with Meowa's crisp native 32.
  * **Scene preset has no top-down** — only front / 45° / Terraria / arcade (side or isometric). The top-down scene was made via free-gen, bypassing the preset.
  * **Tile prompt misread** — free-gen read "stone floor tile" as a full grouted tiled floor (a grid), not a single seamless swatch; grout cannot repeat as a tile. The other three returned a single tileable motif from the same prompt. The raw model needs strong negative constraints (no grid lines / borders / seams) where PixelLab and Meowa give a usable single tile natively.
  * **Icon isn't pixel art, and the transparency is fake.** The same prompt returned a 1024×1024 smooth vector-style potion — anti-aliased and gradient-shaded, not a pixel grid — and its "transparent" background is a painted gray/white checkerboard baked into an RGB image (no alpha channel), so it must be keyed out before use. Downscaled to 24×24 it becomes an anti-aliased blob, the same collapse as the 32 px character.


---

## 5. Verdict

* **Meowa** — Worth adopting, especially for tiles, characters, and icons. Turnkey (no setup), it generates native small sizes across a fine grid — 16 / 24 / 32, including the production 24 px — and returns a whole batch of variations per job (36 tiles, 15 icons), making it the most productive of the new tools. Its universal mode covers scenes OpenAI-style; the only real limit is scene aspect ratio (no 16:9, 3:2 closest).

* **FrameRonin** — Its presets override the prompt (a soldier, not the requested knight) and offer no top-down scene view; its 1k → downscale output collapses at small sizes (the 32 px character became a muddy blob); and its icon came back as a smooth vector potion with a fake painted-checkerboard background, not usable pixels. Free-gen also misread the tile prompt as a grouted floor grid. A capable model at large sizes, but a poor fit for native small tiles, characters, and icons. Niche at best.

* **Overall** — For the sizes that matter here (16 / 24 / 32 px), the pixel-*native* tools (PixelLab, Meowa) beat the high-res-render-then-downscale tools (OpenAI, FrameRonin / nano-banana). This reaffirms the main paper's native-vs-downscale thesis across two more providers.


---

## 6. Appendix — native sheets & evidence

Meowa's template mode returns a full sprite/icon sheet rather than a single asset. The whole sheet is shown here as direct evidence of Meowa's sprite/icon orientation (see 4). 


### 16x16 tile spritesheet

***Meowa:***

 ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/meowa_tile16_sheet.png)


### 24x24 tile spritesheet

***Meowa:***

 ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/meowa_tile24_sheet.png)


### 32x32 tile spritesheet

***Meowa:***

 ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/meowa_tile32_sheet.png)


### 32x32 charactor

***Meowa:***

 ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/meowa_character_sheet.png)


***Frameronin:***

 ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/frameronin_character_sheet.png)


### 24 x 24 icon:

***Meowa:***

 ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/survey/meowa_icon_sheet.png)