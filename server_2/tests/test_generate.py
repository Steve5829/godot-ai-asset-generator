from pathlib import Path
from generate.request import Request
from generate.pipeline import Pipeline

req = Request(
    prompt="a red apple icon 32x32",
    width=32,
    height=32,
    folder="output_test",
    provider="pixellab",
)

outputs = Pipeline().run(req)

assert isinstance(outputs, list), f"expected list, got {type(outputs)}"
assert len(outputs) == 1, f"expected 1 output, got {len(outputs)}"
rec = outputs[0]
assert rec["role"] == "single_image"
assert Path(rec["file_path"]).exists(), "png not written"
print("ok:", rec)
