import io
from PIL import Image

NEIGHBORS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def _lum(r, g, b):
    return 0.299 * r + 0.587 * g + 0.114 * b


def deoutline(image_bytes, dark=80, fill=False, passes=4):
    image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    w, h = image.size
    px = image.load()

    def transparent(x, y):
        return x < 0 or y < 0 or x >= w or y >= h or px[x, y][3] <= 128

    dark_pix = set()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a > 128 and _lum(r, g, b) < dark:
                dark_pix.add((x, y))

    outer = {(x, y) for (x, y) in dark_pix if any(transparent(x + dx, y + dy) for dx, dy in NEIGHBORS)}
    for (x, y) in outer:
        r, g, b, _ = px[x, y]
        px[x, y] = (r, g, b, 0)

    if fill:
        inner = dark_pix - outer
        for _ in range(passes):
            updates = {}
            for (x, y) in inner:
                rs = gs = bs = n = 0
                for dx, dy in NEIGHBORS:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in inner:
                        r, g, b, a = px[nx, ny]
                        if a > 128:
                            rs += r
                            gs += g
                            bs += b
                            n += 1
                if n >= 2:
                    updates[(x, y)] = (rs // n, gs // n, bs // n)
            if not updates:
                break
            for (x, y), c in updates.items():
                px[x, y] = (c[0], c[1], c[2], 255)
            inner -= set(updates)

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
