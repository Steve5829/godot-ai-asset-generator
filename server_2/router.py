from asset import IconAsset, BlockAsset

ASSET_CLASSES = {
    "icon": IconAsset,
    "block": BlockAsset
}

KEYWORDS = {
    "block":"block",
    "icon": "icon"
}

def route(request):
    text = request.prompt.lower()
    for key, value in KEYWORDS.items():
        if key in text:
            return ASSET_CLASSES[value]
    return ASSET_CLASSES["icon"]
    