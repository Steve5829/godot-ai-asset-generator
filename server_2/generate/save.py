from pathlib import Path
from generate.postprocess import snap_palette

def save_image (image, plan, role, suffix=""):
    if plan.snap_colors:
        image = snap_palette(image, plan.snap_colors)
    folder = plan.output_folder
    filename = plan.filename + suffix
    path = Path(folder)/f"{filename}.png"
    path.parent.mkdir(parents = True, exist_ok = True)
    path.write_bytes(image)
    return {"file": path.name, "file_path": str(path), "role": role}