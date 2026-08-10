from pathlib import Path
from PIL import Image
import io
from generate.composer import COMPOSER_CLASSES

ref = Path("reference_images/minecraft/block_texture")
top_bytes = (ref / "Sandstone.png").read_bytes()      # 16x16 as fake "top"
front_bytes = (ref / "stone.png").read_bytes()        # 16x16 as fake "front"

composer = COMPOSER_CLASSES["two_face"]()
result = composer.compose({"top": top_bytes, "front": front_bytes})

assert isinstance(result, bytes), f"expected bytes, got {type(result)}"
img = Image.open(io.BytesIO(result))
assert img.size == (16, 32), f"expected 16x32 stacked, got {img.size}"

iso = COMPOSER_CLASSES["isometric"]()
iso_result = iso.compose({"top": top_bytes, "front": front_bytes, "side": top_bytes})
assert isinstance(iso_result, bytes), f"expected bytes, got {type(iso_result)}"
iso_img = Image.open(io.BytesIO(iso_result))
assert iso_img.size == (32, 32), f"expected 32x32 isometric, got {iso_img.size}"

out = Path("output_test/composed.png")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(result)
print("ok:", out, img.size, "iso", iso_img.size)
