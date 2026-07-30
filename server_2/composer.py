import io
from PIL import Image

class Composer:
    def compose(self, top_bytes, front_bytes):
        raise NotImplementedError

class TwoFaceComposer(Composer):
    def compose(self, top_bytes, front_bytes):
        top = Image.open(io.BytesIO(top_bytes))
        front = Image.open(io.BytesIO(front_bytes))
        width = top.width
        canvas = Image.new("RGBA", (width, top.height + front.height), (0, 0, 0, 255))
        canvas.paste(top, (0,0))
        canvas.paste(front, (0, top.height))
        buf = io.BytesIO()
        canvas.save(buf, format = "PNG")
        return buf.getvalue()

COMPOSER_CLASSES = {
    "two_face" : TwoFaceComposer,
}