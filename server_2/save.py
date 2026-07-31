from pathlib import Path

def save_image (image, plan, role, suffix=""):
    folder = plan.output_folder
    filename = plan.filename + suffix
    path = Path(folder)/f"{filename}.png"
    path.parent.mkdir(parents = True, exist_ok = True)
    path.write_bytes(image)
    return {"file": path.name, "file path": str(path), "role": role}