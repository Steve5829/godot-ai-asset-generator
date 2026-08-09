import io
from PIL import Image, ImageOps

def resize_image(image, plan):
    return image.resize((plan["target_width"], plan["target_height"]), Image.NEAREST)

def resize_canvas(image, plan):
    size = (plan["target_width"], plan["target_height"])
    contained = ImageOps.contain(image, size, Image.NEAREST)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    offset = ((size[0] - contained.width)//2, (size[1] - contained.height)//2)
    canvas.paste(contained, offset, contained)
    return canvas

def rotate(image, plan):
    return image.rotate(-plan["degrees"], expand=True, resample=Image.NEAREST)

ACTION_APPLIERS = {
    "resize_image": resize_image,
    "resize_canvas": resize_canvas,
    "rotate": rotate,
}

def apply_modification(image, plan):
    return ACTION_APPLIERS[plan["action"]](image, plan)
