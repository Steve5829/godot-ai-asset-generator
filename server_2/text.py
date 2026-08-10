import re

LABEL_OVERRIDES = {"pixellab": "PixelLab", "gpt_image": "GPT Image"}

def slug(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")

def tokens(text):
    return set(re.findall(r"[a-z0-9]+", str(text).lower()))

def label(value):
    return LABEL_OVERRIDES.get(value, str(value).replace("_", " ").title())