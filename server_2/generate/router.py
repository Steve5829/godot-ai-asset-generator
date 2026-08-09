from generate.asset import IconAsset, BlockAsset, SpriteSheetAsset, GroundAtlasAsset, IsometricBlockAsset, NativeIsometricBlockAsset


ASSET_CLASSES = {
    "icon": IconAsset,
    "block": BlockAsset,
    "spritesheet": SpriteSheetAsset,
    "ground_atlas": GroundAtlasAsset,
    "isometric": NativeIsometricBlockAsset,
    "isometric_composite": IsometricBlockAsset
}

KEYWORDS = {
    "composite": "isometric_composite",
    "isometric": "isometric",
    "block":"block",
    "spritesheet": "spritesheet",
    "atlas": "ground_atlas",
    "icon": "icon"
}

def route(request):
    text = request.prompt.lower()
    for key, value in KEYWORDS.items():
        if key in text:
            return ASSET_CLASSES[value]
    return ASSET_CLASSES["icon"]
    