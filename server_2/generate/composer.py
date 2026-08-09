import io
from PIL import Image

class Composer:
    def compose(self, faces):         
        raise NotImplementedError


def load(face_bytes):
    return Image.open(io.BytesIO(face_bytes)).convert("RGBA")


class TwoFaceComposer(Composer):
    faces = ("top", "front")
    def compose(self, faces):
        top = load(faces["top"])     
        front = load(faces["front"])     
        width = top.width
        canvas = Image.new("RGBA", (width, top.height + front.height), (0, 0, 0, 255))
        canvas.paste(top, (0, 0))
        canvas.paste(front, (0, top.height))
        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        return buf.getvalue()


class IsometricComposer(Composer):
    faces = ("top", "front", "side")
    def compose(self, faces):
        f = load(faces["top"]).width     
        top   = load(faces["top"]).resize((f, f), Image.NEAREST)
        front = load(faces["front"]).resize((f, f), Image.NEAREST)
        side  = load(faces["side"]).resize((f, f), Image.NEAREST)

        W, H = f * 2, f * 2
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))  
        center_x = W // 2
        mid_y = f // 2
        body = H - mid_y

        paste_parallelogram(canvas, side,  (0, mid_y),
                            (center_x, f // 2), (0, body - f // 2), 0.72)
        paste_parallelogram(canvas, front, (center_x, mid_y + f // 2),
                            (center_x, -(f // 2)), (0, body - f // 2), 0.86)
        paste_parallelogram(canvas, top,   (center_x, 0),
                            (center_x, f // 2), (-center_x, f // 2), 1.08)

        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        return buf.getvalue()


def paste_parallelogram(target, source, origin, x_axis, y_axis, shade=1.0):
    det = x_axis[0] * y_axis[1] - x_axis[1] * y_axis[0]
    if det == 0:
        return
    points = (
        origin,
        (origin[0] + x_axis[0], origin[1] + x_axis[1]),
        (origin[0] + x_axis[0] + y_axis[0], origin[1] + x_axis[1] + y_axis[1]),
        (origin[0] + y_axis[0], origin[1] + y_axis[1]),
    )
    min_x = max(0, min(p[0] for p in points))
    max_x = min(target.width - 1, max(p[0] for p in points))
    min_y = max(0, min(p[1] for p in points))
    max_y = min(target.height - 1, max(p[1] for p in points))
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            px = x + 0.5 - origin[0]
            py = y + 0.5 - origin[1]
            u = (px * y_axis[1] - py * y_axis[0]) / det   
            v = (x_axis[0] * py - x_axis[1] * px) / det
            if u < 0.0 or u > 1.0 or v < 0.0 or v > 1.0:
                continue
            sx = min(source.width - 1, max(0, int(u * source.width)))
            sy = min(source.height - 1, max(0, int(v * source.height)))
            r, g, b, a = source.getpixel((sx, sy))
            if a == 0:
                continue
            if shade != 1.0:
                r = max(0, min(255, int(r * shade)))
                g = max(0, min(255, int(g * shade)))
                b = max(0, min(255, int(b * shade)))
            target.putpixel((x, y), (r, g, b, a))


COMPOSER_CLASSES = {
    "two_face": TwoFaceComposer,
    "isometric": IsometricComposer,
}