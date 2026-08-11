# Google Summer of Code 2026 — Final Work Report

**Contributor:** Steve Chen
**Organization:** PSF (pocketpy)
**Project:** Godot Asset Generator — a text-to-pixel-art plugin for the Godot editor
**Mentor:** blueloveTH
**Project page:** https://summerofcode.withgoogle.com/myprojects/details/Vx6Qs9IE

---

## 1. Project goals

Build a Godot editor plugin that turns a natural-language prompt into a game-ready
pixel-art asset — icon, tile, block, character, spritesheet, scene — generated,
post-processed into clean pixels, and saved into the project, without leaving the
editor. A secondary goal was to evaluate which image-generation provider is
actually suitable for small pixel-art assets, and to make the backend easy to
extend with new providers, asset types, and game styles.

## 2. What I did

- **Built the plugin end to end.** A GDScript `EditorPlugin` frontend
  (`addons/vibe_agent/`) talks over local HTTP to a Python FastAPI backend that
  interprets the prompt, calls an image provider, post-processes the result, and
  writes PNG(s) into the chosen `res://` folder. Endpoints: `/vibe/generate`,
  `/vibe/modify`, `/vibe/automate`, `/vibe/options`.
- **Integrated two providers** behind one interface: **PixelLab** (pixel-art
  native) and **OpenAI GPT Image** (`gpt-image-1`).
- **Added a data-driven style system** — per-game style packs, reference images,
  and material/layout tables — so a new game style or block material is a data
  edit, not a code change.
- **Rewrote the backend as a modular pipeline (`server_2/`, the v2 branch).**
  The whole generate path is one small pipeline; every extension point
  (asset type, provider, workflow, composer, edit action) is a class selected
  from a registry by a string key, with no `if/elif` type-branching. Each module
  has a focused test.
- **Wrote two technical write-ups** documenting the workflow, the architecture,
  and an empirical provider comparison (links in §6).

## 3. Current state

The plugin is **working end to end**: generate, modify (resize / aspect / rotate),
and automate all run from the Godot editor against the local backend. Icons,
tiles (16/24/32), characters (32/36), blocks, isometric blocks, spritesheets, and
ground atlases generate at their target sizes; scenes generate up to each
provider's ceiling. The v2 backend has module-level tests. The two write-ups are
complete.

## 4. What's left to do

- **LLM semantic routing.** Asset type is decided by a keyword table today, with
  `icon` as fallback; the planned LLM layer that infers type from ambiguous
  content words ("a cozy tavern" → scene) has a defined insertion point but is not
  built yet.
- **Adopt a native batch provider (Meowa).** The provider survey found it native
  at small sizes and batch-productive; it fits the existing `Provider` interface
  and would be a one-class addition.
- **Size-aware provider routing, batch/atlas output, and scenes above PixelLab's
  400 px ceiling** — all described in the papers' future-work sections.

## 5. Code — the three-branch history

**Repository:** https://github.com/Steve5829/godot-vibe-plugin

The project was developed as three branches, each a **self-contained, runnable
stage with its own README**. They are all part of this GSoC work; `v2` is the
current branch and where the write-ups live.

| Branch | Stage | What this stage added | Backend | README |
|--------|-------|-----------------------|---------|--------|
| [`v0`](https://github.com/Steve5829/godot-vibe-plugin/tree/v0) | Prototype | generate / modify / automate; structured (non-code) planning; PixelLab | `server/server.py` | [v0 README](https://github.com/Steve5829/godot-vibe-plugin/blob/v0/README.md) |
| [`v1`](https://github.com/Steve5829/godot-vibe-plugin/tree/v1) | Style modeling | per-game style packs, reference images, GPT Image provider, block composition, evaluation cases + tests | `server/server.py` | [v1 README](https://github.com/Steve5829/godot-vibe-plugin/blob/v1/README.md) |
| [`v2`](https://github.com/Steve5829/godot-vibe-plugin/tree/v2) | Modular rewrite (current) | same behavior re-expressed as a small polymorphic pipeline — registry dispatch instead of `if/else`, data resolved at load, per-module tests | `server_2/` | [v2 README](https://github.com/Steve5829/godot-vibe-plugin/blob/v2/README.md) · [backend README](https://github.com/Steve5829/godot-vibe-plugin/blob/v2/server_2/README.md) |

**Upstream contributions** (merged into [`pocketpy/godot-vibe-plugin`](https://github.com/pocketpy/godot-vibe-plugin)):
- [#2 — init: initialize official vibe agent plugin repository](https://github.com/pocketpy/godot-vibe-plugin/pull/2) — merged 2026-03-26.
- [#3 — Vibe agent](https://github.com/pocketpy/godot-vibe-plugin/pull/3) — merged 2026-07-02 (53 commits; mid-term deliverable).
- **Final GSoC merge:** {{PR # + link}} — {{merged date}} _(to be opened / filled in when the v2 work is merged upstream)_.

**Key code in `v2`, so reviewers can find the work fast:**
- `server_2/generate/pipeline.py` — the entire generate path.
- `server_2/generate/router.py`, `asset.py`, `plan.py` — routing and the Plan contract.
- `server_2/generate/provider.py` — PixelLab + GPT Image behind one `generate(plan)`.
- `server_2/generate/composer.py`, `workflow.py` — block/isometric composition, slicing.

> The last commit that is part of my GSoC work is {{commit SHA}}; anything after
> that on `v2` is follow-up.

## 6. Write-ups

Two technical papers, on the `v2` branch, rendering directly on GitHub (images included):

- **Godot Asset Generator — Workflow, Architecture, and Provider Comparison
  (PixelLab vs OpenAI)** — [`md/paper_code_architecture.md`](md/paper_code_architecture.md).
  End-to-end workflow, the v2 code architecture with excerpts, and the
  native-vs-downscale provider analysis.
- **Provider Comparison — Multi-Tool Survey** —
  [`md/provider_comparison.md`](md/provider_comparison.md). Same-prompt quality
  survey across four providers (PixelLab, OpenAI, Meowa, FrameRonin) over tiles,
  characters, icons, and scenes.

**How the documents fit together** (they serve different purposes, so there is
little overlap by design):

- **This report** — the index: goals, what was done, the three branches, the PR, what's left.
- **Per-branch READMEs** — operational and self-contained: what each stage is and how to run *that* stage.
- **The two papers** — the cross-cutting narrative: design rationale, the architecture in depth, and the provider evaluation. They defer setup to the READMEs and are not tied to a single branch.

## 7. Challenges and what I learned

- **Native low-res vs. high-res-then-downscale is the dominant quality factor at
  16–32 px.** A pixel-art-native model (PixelLab) places pixels on the grid; a
  general model (OpenAI) renders at 1024 and must be downscaled and palette-
  snapped, which cannot stay pixel-clean at 24 px without losing detail. This
  finding, validated across four tools, is what shaped the provider recommendation
  and the "route by size" future direction.
- **Designing for extension pays off.** Choosing registry dispatch over type
  branching meant that acting on the survey's finding — adopting a native provider
  — became a one-class change rather than a rewrite. The measurement and the
  architecture reinforce each other.
- **Post-processing is where small pixel art is won or lost** — alpha-preserving
  palette snapping, outline handling, and honest downscaling matter as much as the
  model choice.

---

*This report is the Google Summer of Code 2026 final work submission. The last
GSoC commit is noted in §5; work may continue on the repository afterward.*
