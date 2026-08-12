import json
from pathlib import Path
from text import tokens

BLOCK_PROMPT = json.loads((Path(__file__).parent / "data" / "block_prompt.json").read_text())


def build_face_description(prompt, material, face, width, height):
    guard = BLOCK_PROMPT["icon_guard"]
    triggered = bool(tokens(prompt) & set(guard["tokens"]))
    return BLOCK_PROMPT["wrapper"].format(
        width=width,
        height=height,
        face_label=BLOCK_PROMPT["face_labels"][face],
        material=material[face] + ". Original user material request: " + prompt,
        rules=BLOCK_PROMPT["face_rules"][face] + " ",
        match=BLOCK_PROMPT["match"] + " ",
        guard=(guard["text"] + " ") * triggered,
    )
