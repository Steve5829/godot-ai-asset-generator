from asset import IconAsset, BlockAsset

ASSET_CLASSES = {
    "icon": IconAsset,
    "block": BlockAsset
}

def route(request):
    asset_type = "icon"
    return ASSET_CLASSES[asset_type]