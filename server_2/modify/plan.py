import re

def derive_aspect_canvas(width, height, ratio_w, ratio_h):
    if width >= height:
        target_w = width
        target_h = round(width * ratio_h / ratio_w)
    else:
        target_h = height
        target_w = round(height * ratio_w / ratio_h)
    return target_w, target_h


def plan_modification(prompt, width, height):
    text = prompt.lower()

    size = re.search(r"(\d{2,4})\s*[xX×]\s*(\d{2,4})", prompt)
    if size:
        return {
            "action": "resize_image",
            "target_width": int(size.group(1)),
            "target_height": int(size.group(2)),
            "suffix": "_resized",
        }

    aspect = re.search(r"(\d{1,3})\s*:\s*(\d{1,3})", prompt)
    if aspect:
        tw, th = derive_aspect_canvas(width, height, int(aspect.group(1)), int(aspect.group(2)))
        return {
            "action": "resize_canvas",
            "target_width": tw,
            "target_height": th,
            "suffix": "_aspect",
        }

    if "rotate" in text or "旋转" in text:
        deg = re.search(r"(\d{1,3})", prompt)
        return {
            "action": "rotate",
            "degrees": int(deg.group(1)) if deg else 90,
            "suffix": "_rotated",
        }

    return {
        "action": "resize_image",
        "target_width": width,
        "target_height": height,
        "suffix": "_modified",
    }
