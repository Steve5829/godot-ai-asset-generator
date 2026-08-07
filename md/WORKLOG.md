# Work Summary

The work centers on the asset-generation side of the Vibe plugin, turning a text prompt in the Godot editor into a finished pixel-art asset through a local backend. The core is a prompt-to-asset pipeline that infers what is being asked for across five asset types, plans the generation with an LLM, and calls an image provider such as PixelLab or GPT Image.

A large part of the effort went into block composition, generating the individual
faces and stacking or projecting them into a finished block, with a two-face layout
for Core Keeper, Terraria, and Stardew and an isometric three-face layout for
Minecraft. Styles themselves run on a data-driven pack system, where a whole game
look, its block layout, and a shared library of material and icon descriptions live
in data files, so adding a style like Stardew is a single JSON file with no code
changes, and the editor picks it up on its own.

On top sits a selectable generation mode that preserves every approach tried, from
plain text to reference analysis to true image-to-image style transfer, side by
side for comparison. Underneath, the planner was refactored into a clean
data-driven pipeline, dead code was cleared out, and a regression test suite was
added.

The backend lives in `server/server.py`, the style and material data in
`server/packs/` and `server/data/`, and the editor plugin in `addons/vibe_agent/`.
The project began as a fork of `pocketpy/godot-vibe-plugin`, with the full history
in the commit log.