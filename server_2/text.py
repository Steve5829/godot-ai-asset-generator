import re
# slug filename for path
def slug(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")

def tokens(text):
    return set(re.findall(r"[a-z0-9]+", str(text).lower()))