from pathlib import Path
from text import tokens

REFERENCE_ROOT = Path(__file__).parent.parent / "reference_images"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def select_reference(style, reference_dir, prompt):
    folder = REFERENCE_ROOT / style / reference_dir
    if not folder.is_dir():
        return None
    prompt_tokens = tokens(prompt)
    best, best_score = None, 0
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in IMAGE_EXTS:    
            continue
        score = len(prompt_tokens & tokens(path.stem))  
        if score > best_score:
            best, best_score = path, score
    return best

def list_styles():
    if not REFERENCE_ROOT.is_dir():
        return []
    return sorted(
        entry.name                       
        for entry in REFERENCE_ROOT.iterdir()
        if entry.is_dir()          
    )        