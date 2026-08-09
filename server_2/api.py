from fastapi import FastAPI
from pydantic import BaseModel
from generate.request import Request
from generate.pipeline import Pipeline
from generate.provider import PROVIDER_CLASSES
from automate.planner import plan_actions
from reference.select import list_styles
from pathlib import Path
from PIL import Image
from modify.plan import plan_modification
from modify.apply import apply_modification

app = FastAPI()

class GenerateBody(BaseModel):
    prompt: str
    folder: str
    width: int = 32
    height: int = 32
    style: str = "none"
    provider: str = "pixellab"

@app.post("/vibe/generate")
def generate(body: GenerateBody):
    try:
        request = Request(
            prompt = body.prompt,
            width = body.width,
            height = body.height,
            folder = body.folder,
            style = body.style,
            provider = body.provider
        )
        outputs = Pipeline().run(request)
        return {
            "status": "success",
            "type": "asset",
            "file": outputs[0]["file"],   
            "file_path": outputs[0]["file_path"],
            "outputs": outputs
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

class AutomateBody(BaseModel):
    prompt: str
    selected_nodes: list = []
    mode: str = "llm"

@app.post("/vibe/automate")
def automate(body: AutomateBody):
    try:
        actions = plan_actions(body.prompt, body.selected_nodes, body.mode)
        return {"status": "success", "type": "automation", "actions": actions}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

@app.get("/vibe/options")
def options():
    return {
        "providers": list(PROVIDER_CLASSES),
        "styles": list_styles()
    }
class ModifyBody(BaseModel):
    prompt: str
    asset_path: str

@app.post("/vibe/modify")
def modify(body: ModifyBody):
    try:
        source = Path(body.asset_path)
        if not source.is_file():
            raise ValueError("asset not found: " + body.asset_path)

        image = Image.open(source).convert("RGBA")
        plan = plan_modification(body.prompt, image.width, image.height)   
        result = apply_modification(image, plan)

        target = source.with_name(source.stem + plan["suffix"] + ".png")
        result.save(target, format="PNG")

        return {
            "status": "success",
            "type": "asset",
            "file": target.name,
            "file_path": str(target),
            "source_file_path": str(source),
            "plan": plan,
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}