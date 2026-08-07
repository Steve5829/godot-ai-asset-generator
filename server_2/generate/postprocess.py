import io
from PIL import Image

def snap_palette(image_bytes, colors):
    if colors <= 0:
        return image_bytes
    image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    alpha = image.getchannel("A")
    quantized = image.convert("RGB").quantize(   
        colors=colors, method=Image.MEDIANCUT, dither=Image.NONE)
    result = quantized.convert("RGBA")
    result.putalpha(alpha)                    
    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue()