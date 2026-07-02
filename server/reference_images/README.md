Reference images for the Vibe asset generator.

Put images under:

```text
server/reference_images/<style_target>/<asset_type>/
```

Examples:

```text
server/reference_images/core_keeper/icon/potion.png
server/reference_images/core_keeper/block_texture/forest_block.png
server/reference_images/core_keeper/ground_atlas/forest_ground.png
```

Supported image types: `.png`, `.jpg`, `.jpeg`, `.webp`.

When generating an asset, choose the matching style target in Godot. For example,
choose `Core Keeper-like` to use images under `core_keeper/`.
