from dataclasses import dataclass

@dataclass
class Plan:
    description: str
    width: int
    height: int
    output_folder: str
    filename: str
    no_background: bool = True
    workflow: str = "icon"
    faces: dict|None = None
    reference_mode : str = "none"
    reference_image: str|None = None
    snap_colors: int = 0
    compose_mode: str = "two_face"
    deoutline: dict|None = None
    block_layout: dict|None = None
    