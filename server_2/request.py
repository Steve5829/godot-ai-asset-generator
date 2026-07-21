from dataclasses import dataclass
@dataclass
class Request:
    prompt:str
    width:int
    height:int
    folder: str
    style: str = "none"
    provider: str = "pixellab"