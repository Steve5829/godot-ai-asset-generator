from pathlib import Path
from generate.plan import Plan
from generate.save import save_image

src = Path("reference_images/minecraft/block_texture/stone.png")
image = src.read_bytes()

plan = Plan(
    description="stone block",
    width=16,
    height=16,
    output_folder="output_test",
    filename="stone_test",
)

rec = save_image(image, plan, role="single_image")

assert rec["role"] == "single_image"
assert rec["file"] == "stone_test.png"
out = Path(rec["file_path"])
assert out.exists() and out.read_bytes() == image
print("ok:", rec)

out.unlink()
