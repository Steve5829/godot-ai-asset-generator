from dataclasses import dataclass

@dataclass
class Plan:
    description: str
    width: int
    height: int
    output_folder: str
    filename: str
    compose_mode: str|None = None
    needs_compose: bool = False
    use_style_transfer: bool = False
    reference_image: str|None = None
    