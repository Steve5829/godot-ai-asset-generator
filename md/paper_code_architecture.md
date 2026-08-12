# Godot Asset Generator Plugin — Workflow and Provider Comparison (PixelLab vs OpenAI)

## 1. Project overview

A Godot editor plugin that turns a text prompt into a game-ready pixel-art asset without leaving the editor. The user types "a healing potion" (optionally with a size and a target game style); the asset is generated, post-processed into clean pixels, and saved into the project's asset folder.

Two halves:

* **Frontend** — a Godot `EditorPlugin` in GDScript (`addons/vibe_agent/vibe_plugin.gd`, registered via `plugin.cfg`). Draws the editor panel, collects the prompt and parameters, and calls the backend over local HTTP.
* **Backend** — a Python FastAPI service that does the work: interpret the prompt, call an image-generation provider, post-process the result. Runs at `127.0.0.1:8000`.

The project has grown in three stages, kept as branches: **v0** a single-file prototype (generate / modify / automate, PixelLab only, no style system), **v1** a full style layer (per-game style packs, reference images, tests), and **v2** the current branch — a modular rewrite of the backend as `server_2/`, where each step is a small module with a single responsibility. The workflow below describes the v2 logic.

Every design decision in v2 follows one creed, stated in the backend README and visible throughout §4: **one pipeline with single-responsibility steps; polymorphism and dict dispatch instead of `if/else`; data resolved once at load; new capability added alongside the old, never replacing it in place.**

---

## 2. Workflow

### 2.1 End-to-end path

```
Artist in Godot editor
   │  types prompt (+ size, style, provider)
   ▼
GDScript plugin ──HTTP──► FastAPI backend (127.0.0.1:8000)
                              │
                              ▼
     Request        raw user input (prompt, size, folder, style, provider)
                              │
                              ▼
     route()        infer the asset type from the prompt → pick an Asset class
                              │
                              ▼
     build_plan()   the Asset turns the Request into a Plan
                              │
                              ▼
     Plan           data contract: size, output folder, flags (compose_mode, reference_mode, …)
                              │
                              ▼
     generate()     the chosen Provider calls its image API with the Plan
                              │
                              ▼
     compose + post-process   stitch (if needed), downscale, palette snap
                              │
                              ▼
     save           write PNG to the project's asset folder
                              │
                   ◄──── response ────┘
   │
   ▼
Asset appears in Godot, ready to use
```

### 2.2 Step by step (v2)

1. **Request** — the plugin's HTTP payload becomes a `Request`: prompt, size, output folder, style, provider. It only stores the input, it does not interpret it.
2. **route()** — decides the asset type by **deterministic keyword matching**: the prompt is checked against a keyword table (`icon`, `block`, `isometric`, `composite`, `spritesheet`, `atlas`) and the corresponding `Asset` class is returned. Selection happens once here through a lookup, so no other step branches on type. When nothing matches, it defaults to `icon` — this is also the path a plain "scene" prompt takes, since a scene is generated as a single image at the requested size rather than a dedicated asset type. An LLM layer for inferring type from ambiguous content words is planned but not built (§5).
3. **build_plan()** — the selected `Asset` converts the `Request` into a `Plan`. It reads the Asset's own class attributes (workflow, compose mode, palette-snap count, …) and freezes them into the contract. The LLM can enter *here*, but only for **reference-trait extraction**: when an asset is generated against a target style, a vision model summarizes transferable traits (palette, outline, shading) from a chosen reference image and appends them to the description. It never decides the asset type, and it is fail-safe — an empty or failed reply just leaves the description unchanged (see §4.6).
4. **Plan** — the single data contract every downstream step reads: refined description, target size, output folder, and flags such as `compose_mode`, `reference_mode`, and `snap_colors`.
5. **generate()** — the `Provider` named in the request (PixelLab, GPT Image) is looked up in a table and called with the `Plan`. Every provider exposes the same `generate(plan)` signature, so the caller never branches on which provider it is.
6. **compose + post-process** — multi-part assets (block faces, isometric cubes) are stitched by a `Composer`; sheet assets are sliced into cells. The result is brought to the target size and its palette is snapped.

   Example of the compose step — a block generated as a grass top and a dirt front, stitched into one 32×48 texture:

   ![composed block](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/forest_grass_dirt_32x48.png " =196x294")
7. **save** — optional per-asset cleanup (outline removal, palette snap) runs, then the finished PNG is written to the asset folder and the path is returned to the plugin.

### 2.3 Endpoints

The backend exposes `/vibe/generate` (new asset), `/vibe/modify` (geometric edit of an existing image — resize / aspect / rotate), `/vibe/automate` (prompt + selected nodes → structured editor actions), and `/vibe/options` (styles and providers the plugin queries at startup for its dropdowns).

---

## 3. Provider comparison

### *(see more in "**Provider Comparison — Multi-Tool Survey**")*

### 3.1 The core divide

The single fact that organizes everything below: **native low-resolution generation** (PixelLab) versus **high-resolution generation followed by downscaling** (OpenAI GPT Image).

In the first family the model decides where each pixel sits. In the second, pixel placement is reconstructed by a post-processing pipeline that has to collapse soft, anti-aliased AI color onto a clean grid. At 16–24 px this divide dominates every other consideration, because a 24×24 tile is only 576 pixels — any smear or leftover in-between color has nowhere to hide.

### 3.2 Providers under test

| Provider | Kind | Native size capability | Status |
|----------|------|------------------------|--------|
| **PixelLab** | Pixel-art-specific API | Renders directly at small target sizes (16/32, etc.) | Integrated |
| **OpenAI GPT Image** (`gpt-image-1`) | General-purpose | Emits only 1024×1024 / 1024×1536 / 1536×1024; must be downscaled | Integrated |

### 3.3 Per-provider analysis

For each provider: what it does well and, argued from evidence, where it falls short. The recommendations follow from these limitations, not from a single score.

#### PixelLab

**Strengths.** Renders natively at the target resolution, so pixel placement is decided by the model, not by downscaling. Edges land on-grid and the palette is already tight, which means minimal post-processing and the most predictable behavior at 16–24 px.

**Limitations.**

* *Low texture information density.* In the forest-ground example (see 3.5) the PixelLab tile is dark, low-frequency, and blobby — clean pixels but little material detail. Fine for a hero prop; flat for a ground texture that must tile and carry surface interest.
* *Narrow stylistic range.* Pixel-specialization is a double edge: outputs converge on one "correct" pixel look and are harder to push toward a specific game's art direction (Terraria's high-contrast dithering vs Core Keeper's soft internal glow). Style must be coaxed through prompt wording.
* *Weakest where general models are strongest.* At scene scale (640×360), where composition and palette richness matter more than per-pixel grid discipline, the small-size specialization stops being an advantage.
* *Hard 400 px resolution ceiling.* The PixelLab API rejects any dimension above 400 px (a 640-wide request returns HTTP 422). It therefore **cannot render the 640×360 scene target at all** — the largest same-aspect scene it can produce is 400×224. This is a firm capability gap at scene scale, not a quality judgement: for a full 640×360 concept scene PixelLab is simply out of range, and the comparison in that row is between a true 640×360 (OpenAI) and PixelLab's 400×224 ceiling.

**Takeaway:** default for small icons/characters where grid-clean edges dominate; suspect for high-detail textures, and unavailable above 400 px, which rules it out for full-resolution scenes.

#### OpenAI GPT Image (`gpt-image-1`)

**Strengths.** Strong prompt understanding and rich, varied output; the forest-ground example (3.5) shows denser grass grain and a brighter, more materially convincing surface than PixelLab. Good stylistic range for scenes and references.

**Limitations.**

* *No native small size — everything is a downscale.* The model only emits 1024-class images (sizes forced to 1024×1024 / 1024×1536 / 1536×1024). Every 16/24/32 asset is a large image squeezed down.
* *Soft intermediate colors.* An anti-aliased source carries AI in-between colors that must be quantized away (`MEDIANCUT`). Without that step the palette is not pixel-clean; with it, fine detail is the first thing lost. This is the central weakness at 24 px.
* *Aspect-ratio coarseness.* Only three coarse aspect ratios, so non-matching targets are cropped or stretched before downscaling — extra edge damage for characters and odd tile shapes.
* *Cost and latency.* A full 1024 render per 24×24 tile is expensive and slow versus a native small-size call — a real concern for batch atlas generation.

**Takeaway:** strong for scenes and style references at 640×360; structurally handicapped at 16–24 px.

### 3.4 Result grid — `provider × asset type × size`

Same prompt per row, only the size and provider change. Images are shown **upscaled ×8 (nearest-neighbor)** for legibility — the true asset sizes are as labeled (16/24/32 px, etc.); scenes are at native size.

**Tile — 16×16**

| PixelLab | OpenAI GPT Image |
|----------|------------------|
|  ![PixelLab tile 16](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/pixellab_tile_16.png) |  ![OpenAI tile 16](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/openai_tile_16.png) |

**Tile — 24×24 (tentative tile size)**

| PixelLab | OpenAI GPT Image |
|----------|------------------|
|  ![PixelLab tile 24](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/pixellab_tile_24.png " =192x") |  ![OpenAI tile 24](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/openai_tile_24.png) |

**Tile — 32×32**

| PixelLab | OpenAI GPT Image |
|----------|------------------|
|  ![PixelLab tile 32](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/pixellab_tile_32.png) |  ![OpenAI tile 32](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/openai_tile_32.png) |

**Character — 32×32**

| PixelLab | OpenAI GPT Image |
|----------|------------------|
|  ![PixelLab char 32](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/pixellab_character_32.png) |  ![OpenAI char 32](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/openai_character_32.png) |

**Character — 36×36**

| PixelLab | OpenAI GPT Image |
|----------|------------------|
|  ![PixelLab char 36](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/pixellab_character_36.png) |  ![OpenAI char 36](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/openai_character_36.png) |

**Scene — 640×360** (PixelLab capped at its 400 px ceiling → 400×224; OpenAI at the true target)

| PixelLab (400×224, max) | OpenAI GPT Image (640×360) |
|-------------------------|----------------------------|
|  ![PixelLab scene](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/pixellab_scene_400x224.png) |  ![OpenAI scene](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/display/openai_scene_640x360.png) |

### 3.5 Existing head-to-head examples

These are real artifacts from earlier runs (the v0/v1 style-benchmark runner, `experiment.py`, renders an item × style matrix offline for exactly this kind of side-by-side). Sizes are not aligned to the targets above (128×128 and 64×64), so they illustrate quality character only, not the formal comparison.

**Forest ground texture, 128×128:**

| PixelLab | OpenAI GPT Image |
|----------|------------------|
|  ![pixellab forest ground](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/forest_ground_128x128.png) |  ![openai forest ground](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/forest_ground_openai_128x128.png) |

The PixelLab tile is darker, low-frequency, and blobby — clean pixels but sparse texture. The OpenAI tile is brighter with dense grass grain and richer detail, but retains AI in-between colors unless the palette-snap step is applied.

**High-resolution style reference, 1024×1024** (the kind of rich, full-resolution source a general model produces before downscaling — it is exactly this density that must survive the squeeze to a 24 px tile):

 ![forest style reference](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/core_keeper_forest_style_ref.png)

**OpenAI GPT Image 1024×1024 sources** (every small OpenAI asset in 3.4 starts as one of these and is then downscaled):

| Tile source | Character source |
|-------------|------------------|
|  ![openai tile 1024 source](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/openai_tile_source_1024.png) |  ![openai character 1024 source](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/openai_character_source_1024.png) |

**Style benchmark, PixelLab, 64×64** (same item, three style constraints — Core Keeper / Minecraft / Terraria):

| Item | Core Keeper | Minecraft | Terraria |
|------|-------------|-----------|----------|
| Iron Sword |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/core_keeper_iron_sword.png " =193x193") |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/minecraft_iron_sword.png " =157x157") |  ![](https://raw.githubusercontent.com/Steve5829/godot-vibe-plugin/v2/md/images/terraria_iron_sword.png " =155x155") |

---

## 4. Code architecture

The v2 backend is built from one idea: **a string key selects a class from a registry, and every class in that family shares one method signature.** No step branches on the asset type, the provider, or the workflow — it looks the object up in a table and calls the same method, so type-specific behavior lives inside the classes as *data*, not as `if/elif` chains scattered through the pipeline.

### 4.1 The whole run in nine lines

`Pipeline.run` is the entire generate path. The four steps map 1:1 onto the workflow in §2:

```python
class Pipeline:
    def run(self, request):
        asset = route(request)()
        plan = asset.build_plan(request)
        provider = PROVIDER_CLASSES[request.provider]()
        return WORKFLOW_CLASSES[plan.workflow]().execute(plan, provider)
```

`route` picks the Asset class, the Asset builds a `Plan`, the request names the Provider, and the Plan names the Workflow. Three of the four lines are a table lookup. There is no `if asset_type == …` anywhere below this method — the Plan already carries every decision.

### 4.2 Registry dispatch, everywhere

The same shape repeats across the codebase. Each registry maps a key to a class (or function), and each family shares one call signature:

| Registry | Key comes from | Family | Shared call |
|----------|----------------|--------|-------------|
| `ASSET_CLASSES` | `route()` keyword match | `Asset` subclasses | `build_plan(request)` |
| `PROVIDER_CLASSES` | `request.provider` | `Provider` subclasses | `generate(plan)` |
| `WORKFLOW_CLASSES` | `plan.workflow` | `Workflow` subclasses | `execute(plan, provider)` |
| `COMPOSER_CLASSES` | `plan.compose_mode` | `Composer` subclasses | `compose(faces, layout)` |
| `AUTOMATE_STRATEGIES` | `body.mode` | planner functions | `plan(prompt, nodes)` |
| `ACTION_APPLIERS` | `plan["action"]` | modify functions | `apply(image, plan)` |

The router is the canonical example — the only place asset type is decided, a plain keyword table with an explicit fallback:

```python
KEYWORDS = {
    "composite": "isometric_composite",
    "isometric": "isometric",
    "block": "block",
    "spritesheet": "spritesheet",
    "atlas": "ground_atlas",
    "icon": "icon",
}

def route(request):
    text = request.prompt.lower()
    for key, value in KEYWORDS.items():
        if key in text:
            return ASSET_CLASSES[value]
    return ASSET_CLASSES["icon"]
```

Adding a new asset type is: write the `Asset` subclass, add it to `ASSET_CLASSES`, add one keyword. The pipeline, the providers, and the save step are untouched.

### 4.3 Assets are thin subclasses — variation as data

Each asset type is a handful of class attributes over a shared base. The base holds the defaults and the one non-trivial method (`build_plan`); subclasses override only what differs:

```python
class Asset:
    no_background = True
    workflow = "icon"
    reference_dir = "icon"
    reference_mode = "none"
    snap_colors = 0
    compose_mode = "two_face"
    deoutline = None

    def faces_for(self, request):
        return None

    def describe(self, request, description):
        return description


class IconAsset(Asset):
    reference_mode = "analyze"


class BlockAsset(Asset):
    no_background = False
    workflow = "block"
    reference_dir = "block_texture"
    snap_colors = 32
    block_faces = ("top", "front")


class IsometricBlockAsset(BlockAsset):
    compose_mode = "isometric"
    block_faces = ("top", "front", "side")
```

`IconAsset` differs from the base by a single line. An isometric block is a regular block with a third face and a different composer — expressed as two attribute overrides, no new logic. The behavior that *is* code (`faces_for`, `describe`) is overridden only where a type genuinely needs it (blocks split a material into per-face descriptions; everything else uses the base no-ops).

### 4.4 The Plan is the single contract

`build_plan` runs once, reads the Asset's attributes, and freezes every downstream decision into one dataclass. After this point nothing re-derives anything — each step only *reads* the Plan:

```python
@dataclass
class Plan:
    description: str
    width: int
    height: int
    output_folder: str
    filename: str
    no_background: bool = True
    workflow: str = "icon"
    faces: dict | None = None
    reference_mode: str = "none"
    reference_image: str | None = None
    snap_colors: int = 0
    compose_mode: str = "two_face"
    deoutline: dict | None = None
    block_layout: dict | None = None
```

The provider reads `width`/`height`/`no_background`; the workflow reads `compose_mode`/`faces`; the save step reads `snap_colors`/`deoutline`. Because the contract is explicit and flat, a step can be tested in isolation by handing it a literal `Plan`.

### 4.5 Data-driven, not hard-coded

Materials, per-style block layouts, and the block-prompt wrapper are loaded from JSON at import time and turned into lookup dicts. Adding a material or a game style is a JSON edit, not a code change:

```python
BLOCK_MATERIALS = {
    name: _material(entry)
    for name, entry in json.loads(MATERIALS_PATH.read_text()).items()
}

def match_material(prompt):
    words = tokens(prompt)
    for material in BLOCK_MATERIALS.values():
        if any(keyword in words for keyword in material["keywords"]):
            return material
    return None
```

`block_layout(style)` resolves the same way — the layout for a style is looked up once and merged with a default, so the composer never carries per-style constants. This keeps the pixel-placement rules (how tall the top face is, how many colors to snap to) in data where an artist can tune them. It is the "resolve data once, at load" half of the creed: config is normalized when read, so the consuming code is pure lookup with no fallback branches.

### 4.6 The LLM is optional and isolated

Routing is deterministic keyword-first (§4.2). The LLM is reserved for the two jobs a table cannot do, and it is fail-safe by construction — every call goes through one wrapper that returns an empty string on any error, so an outage degrades to the deterministic path instead of failing the request:

```python
def chat(messages, temperature=0.1, response_format=None):
    if not OPENAI_API_KEY:
        return ""
    try:
        response = requests.post(OPENAI_BASE_URL + "/chat/completions", ...)
        response.raise_for_status()
        choices = response.json().get("choices") or []
        return choices[0]["message"]["content"].strip() if choices else ""
    except Exception as exc:
        print("llm chat failed:", exc)
        return ""
```

Its two call sites:

* **Reference trait extraction** (icons and ground atlases). When an asset is generated with a target style, `analyze_reference` shows the reference image to a vision model and asks for *transferable* traits (palette, outline, shading) that are appended to the description — with an explicit instruction never to copy the image or mention its checkerboard background. An empty reply simply leaves the description as-is.
* **Editor automation.** `/vibe/automate` turns a plain-language editor instruction into a constrained JSON action list, validated against a fixed `ACTION_CATALOG` before it is returned. The `"rule"` strategy is a keyword-only fallback for the same task.

### 4.7 A few elegant details

* **Alpha-preserving palette snap.** Quantizing an RGBA image would fold transparency into the palette. `snap_palette` splits the alpha channel off, MEDIANCUT-quantizes only the RGB, then re-attaches the original alpha — the clean-up step that reins in OpenAI's soft in-between colors (§3.2) without eating the cut-out edge:

  ```python
  alpha = image.getchannel("A")
  quantized = image.convert("RGB").quantize(
      colors=colors, method=Image.MEDIANCUT, dither=Image.NONE)
  result = quantized.convert("RGBA")
  result.putalpha(alpha)
  ```

* **The downscale, in one place.** The native-vs-downscale divide of §3.1 is literally the last line of `GPTProvider.generate`: the model can only emit 1024-class sizes (`openai_image_size` snaps to the nearest of three), so the output is LANCZOS-resized to the real target before it leaves the provider. PixelLab returns the target size directly and has no such line.

* **Isometric faces by inverse mapping.** The composite block composer projects each square face onto a parallelogram by walking the destination pixels and solving for the source `(u, v)` with the inverse of the face's affine basis, skipping anything outside the unit square and shading each face by a fixed factor — a self-contained rasterizer in ~30 lines, no image library transform needed.

### 4.8 Test surface

Each module has a focused test (`test_router`, `test_generate`, `test_compose`, `test_save`, `test_block_faces`, `test_automate`). Because every step reads and writes plain data (`Request`, `Plan`, PNG bytes), the tests construct a literal input and assert on the output without standing up the HTTP layer or a live provider.

---

## 5. Limitations and future directions

The architecture is deliberately small; several capabilities are stubbed at the seam where they will later plug in, and the provider study points directly at the next integrations.

* **Semantic routing is not built yet.** Asset type is decided by the keyword table in §4.2, with `icon` as the fallback. Content words that name no type ("a wooden treasure chest", "a cozy tavern") therefore fall through to the default. The intended second layer — an LLM that makes the semantic guess a table cannot (chest → icon, tavern → scene) and fills the rest of the Plan in the same call — has a clean insertion point in `build_plan` and the same fail-safe contract as the existing LLM calls (§4.6): a type-naming keyword still wins, and an LLM outage falls back to the deterministic Plan.

* **Adopt the native batch providers from the comparison.** The companion survey finds Meowa's template mode produces *native* small sizes and returns a whole batch of variations per job — the most productive of the tools tested. It fits the existing `Provider` interface unchanged (`generate(plan)`), so adding it is one class plus one `PROVIDER_CLASSES` row. This is where the two papers meet: the §3 finding (native beats downscale at 16–32 px) becomes a one-line engineering change because of the §4 registry design.

* **Route the provider by size, not just by name.** §3 shows native tools win below ~32 px while general models win at scene scale. Today the caller picks the provider explicitly. A natural next step is a size-aware default — small assets to a native provider, scenes to a general one — so the pipeline defends the quality boundary automatically and avoids paying for a 1024 render per 24 px tile.

* **Batch and atlas output.** The pipeline returns one asset per call, but the slice workflows already crop grids, and native providers already emit variation sets. A batch endpoint that returns a whole tileset or icon set in one request is a small extension of the existing `SliceWorkflow`.

* **Scenes beyond the 400 px ceiling.** PixelLab cannot render the full 640×360 scene target (§3.3); the current answer is OpenAI at native size. Tiling a scene from native tiles, or a super-resolution pass, would let the native family reach scene scale without the downscale penalty.

* **Richer modify pipeline.** `/vibe/modify` is regex-driven today (resize, aspect, rotate). The same `ACTION_APPLIERS` registry can host LLM-planned edits and region inpainting without changing the endpoint's shape.

## 6. Conclusion

This project has two results that reinforce each other. The first is engineering: a backend built from one pattern — a key selects a class from a registry — so behavior lives in data and thin subclasses rather than branching, and the system stays small as it grows (§4).

The second is empirical: across icons, tiles, characters, and scenes, the factor that dominates quality at 16–32 px is not the model's raw strength but *where the pixels come from* — native low-resolution generation versus high-resolution generation followed by downscaling. PixelLab places pixels on the grid directly and stays clean at small sizes; OpenAI renders richly but pays for every small asset through a downscale-and-quantize pipeline. The companion survey extends the same conclusion to two more providers.

The two results close a loop. The comparison says: prefer native generation for the small assets that make up most of a 2D game, and reserve general models for scenes and style references. The architecture makes acting on that finding cheap — adopting a native provider, or routing by size to defend the boundary automatically, is a localized change, not a rewrite. Good measurements are only useful if the system can act on them; here the design was chosen so it can.
