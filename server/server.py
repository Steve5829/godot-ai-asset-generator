import base64
import binascii
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
for env_path in (
    BASE_DIR / ".env",
    BASE_DIR / "vibe-agent-demo" / ".env",
    BASE_DIR / "VibeAgentDemo" / ".env",
):
    if env_path.exists():
        load_dotenv(env_path, override=False)

app = FastAPI()

GODOT_PROJECT_DIR = BASE_DIR / "vibe-agent-demo"
PIXELLAB_API_KEY = os.getenv("PIXELLAB_API_KEY") or os.getenv("PIXELLAB_SECRET")
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
RESAMPLING = getattr(Image, "Resampling", Image)


class GenerateAssetRequest(BaseModel):
    prompt: str = Field(min_length=1)
    folder_path: str = "res://"


class ModifyAssetRequest(BaseModel):
    prompt: str = Field(min_length=1)
    asset_path: str


class SelectedNode(BaseModel):
    scene_path: str
    name: str
    type: str
    child_count: int = 0
    child_names: List[str] = Field(default_factory=list)


class AutomationRequest(BaseModel):
    prompt: str = Field(min_length=1)
    selected_nodes: List[SelectedNode] = Field(default_factory=list)


def _error(message: str, **extra: Any) -> Dict[str, Any]:
    payload = {"status": "error", "type": "error", "message": message}
    payload.update(extra)
    return payload


def _safe_stem(text: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip().lower()).strip("._")
    if not cleaned:
        cleaned = fallback
    return cleaned[:80]


def _clamp_size(value: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(16, min(400, parsed))


def _project_root() -> Path:
    return GODOT_PROJECT_DIR.resolve()


def _resolve_res_path(res_path: str, expect_directory: bool = False) -> Path:
    normalized = res_path.strip()
    if normalized.startswith("[") and normalized.endswith("]"):
        try:
            parsed = json.loads(normalized)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list) and parsed:
            normalized = str(parsed[0])

    if normalized.startswith("res://"):
        relative = normalized[len("res://") :]
        target = (_project_root() / relative).resolve()
    else:
        raw_path = Path(normalized)
        if raw_path.is_absolute():
            target = raw_path.resolve()
        else:
            target = (_project_root() / raw_path).resolve()

    try:
        target.relative_to(_project_root())
    except ValueError as exc:
        raise ValueError("Path is outside the Godot project: %s" % res_path) from exc

    if expect_directory and not target.exists():
        target.mkdir(parents=True, exist_ok=True)

    return target


def _to_res_path(path: Path) -> str:
    relative = path.resolve().relative_to(_project_root())
    return "res://" + relative.as_posix()


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped)
    return stripped.strip()


def _extract_json_object(text: str) -> Dict[str, Any]:
    stripped = _strip_code_fences(text)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Model response does not contain a JSON object")
    return json.loads(stripped[start : end + 1])


def _chat_json(system_prompt: str, user_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not OPENAI_API_KEY:
        return None

    response = requests.post(
        OPENAI_BASE_URL + "/chat/completions",
        headers={
            "Authorization": "Bearer " + OPENAI_API_KEY,
            "Content-Type": "application/json",
        },
        json={
            "model": OPENAI_MODEL,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=True)},
            ],
        },
        timeout=(10, 90),
    )
    response.raise_for_status()

    payload = response.json()
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("Text model returned no choices")

    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        text = "".join(
            item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"
        )
    else:
        text = str(content)

    return _extract_json_object(text)


def _decode_base64_image(data: Dict[str, Any]) -> bytes:
    if not isinstance(data, dict):
        raise ValueError("PixelLab image payload is not an object")

    encoded = data.get("base64")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("PixelLab image payload does not contain base64 data")

    try:
        return base64.b64decode(encoded)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("PixelLab returned invalid base64 image data") from exc


def _parse_prompt_dimensions(prompt: str, default_width: int, default_height: int) -> Dict[str, int]:
    match = re.search(r"(\d{2,4})\s*[xX×]\s*(\d{2,4})", prompt)
    if match:
        return {
            "width": _clamp_size(int(match.group(1)), default_width),
            "height": _clamp_size(int(match.group(2)), default_height),
        }
    return {"width": default_width, "height": default_height}


def _plan_generation(prompt: str) -> Dict[str, Any]:
    fallback_dimensions = _parse_prompt_dimensions(prompt, 128, 128)
    fallback = {
        "description": prompt.strip(),
        "width": fallback_dimensions["width"],
        "height": fallback_dimensions["height"],
        "filename_stub": _safe_stem(prompt, "generated_asset"),
        "no_background": True,
    }

    try:
        plan = _chat_json(
            (
                "You convert user asset requests into PixelLab generation settings. "
                "Return JSON with description, width, height, filename_stub, and no_background. "
                "Use pixel art wording when helpful. Width and height must be integers between 16 and 400."
            ),
            {"prompt": prompt, "fallback": fallback},
        )
    except Exception as exc:
        print("Text model generation planning failed:", exc)
        plan = None

    if not isinstance(plan, dict):
        return fallback

    return {
        "description": str(plan.get("description") or fallback["description"]).strip(),
        "width": _clamp_size(plan.get("width"), fallback["width"]),
        "height": _clamp_size(plan.get("height"), fallback["height"]),
        "filename_stub": _safe_stem(str(plan.get("filename_stub") or fallback["filename_stub"]), "generated_asset"),
        "no_background": bool(plan.get("no_background", True)),
    }


def _fallback_generation_plan(prompt: str) -> Dict[str, Any]:
    dimensions = _parse_prompt_dimensions(prompt, 128, 128)
    return {
        "description": prompt.strip(),
        "width": dimensions["width"],
        "height": dimensions["height"],
        "filename_stub": _safe_stem(prompt, "generated_asset"),
        "no_background": True,
    }


def _generate_with_pixellab(description: str, width: int, height: int, no_background: bool) -> bytes:
    if not PIXELLAB_API_KEY:
        raise ValueError("PIXELLAB_API_KEY is not configured")

    response = requests.post(
        "https://api.pixellab.ai/v1/generate-image-pixflux",
        headers={"Authorization": "Bearer " + PIXELLAB_API_KEY},
        json={
            "description": description,
            "image_size": {"width": width, "height": height},
            "no_background": no_background,
        },
        timeout=(10, 180),
    )
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("PixelLab API returned an unexpected response")

    return _decode_base64_image(payload.get("image"))


def _load_image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def _save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")


def _derive_aspect_canvas(current_width: int, current_height: int, ratio_width: int, ratio_height: int) -> Dict[str, int]:
    target_ratio = float(ratio_width) / float(ratio_height)
    current_ratio = float(current_width) / float(current_height)

    if current_ratio >= target_ratio:
        target_width = current_width
        target_height = max(1, int(round(target_width / target_ratio)))
    else:
        target_height = current_height
        target_width = max(1, int(round(target_height * target_ratio)))

    return {"width": target_width, "height": target_height}


def _plan_modification(prompt: str, asset_path: str, current_width: int, current_height: int) -> Dict[str, Any]:
    explicit_size = re.search(r"(\d{2,4})\s*[xX×]\s*(\d{2,4})", prompt)
    aspect = re.search(r"(\d{1,3})\s*:\s*(\d{1,3})", prompt)
    degrees = re.search(r"(-?\d{1,3})\s*(?:degrees|degree)", prompt, flags=re.IGNORECASE)

    fallback: Dict[str, Any]
    if explicit_size:
        fallback = {
            "action": "resize_image",
            "target_width": max(1, int(explicit_size.group(1))),
            "target_height": max(1, int(explicit_size.group(2))),
            "filename_suffix": "resized",
        }
    elif aspect:
        ratio_width = max(1, int(aspect.group(1)))
        ratio_height = max(1, int(aspect.group(2)))
        canvas = _derive_aspect_canvas(current_width, current_height, ratio_width, ratio_height)
        fallback = {
            "action": "resize_canvas",
            "target_width": canvas["width"],
            "target_height": canvas["height"],
            "filename_suffix": "%sx%s" % (ratio_width, ratio_height),
        }
    elif "rotate" in prompt.lower() and degrees:
        fallback = {
            "action": "rotate",
            "degrees": int(degrees.group(1)),
            "filename_suffix": "rotated",
        }
    else:
        fallback = {
            "action": "resize_canvas",
            "target_width": current_width,
            "target_height": current_height,
            "filename_suffix": "modified",
        }

    try:
        plan = _chat_json(
            (
                "You convert image editing prompts into a single structured operation. "
                "Return JSON with action and needed numeric fields. "
                "Allowed actions are resize_image, resize_canvas, and rotate. "
                "Use resize_canvas for aspect-ratio requests like 16:9. "
                "Use resize_image for explicit pixel sizes like 256x128."
            ),
            {
                "prompt": prompt,
                "asset_path": asset_path,
                "current_width": current_width,
                "current_height": current_height,
                "fallback": fallback,
            },
        )
    except Exception as exc:
        print("Text model modification planning failed:", exc)
        plan = None

    if not isinstance(plan, dict):
        return fallback

    action = str(plan.get("action") or fallback["action"])
    resolved = {"action": action, "filename_suffix": _safe_stem(str(plan.get("filename_suffix") or fallback["filename_suffix"]), "modified")}

    if action in ("resize_image", "resize_canvas"):
        resolved["target_width"] = max(1, int(plan.get("target_width") or fallback.get("target_width") or current_width))
        resolved["target_height"] = max(1, int(plan.get("target_height") or fallback.get("target_height") or current_height))
    elif action == "rotate":
        resolved["degrees"] = int(plan.get("degrees") or fallback.get("degrees") or 90)
    else:
        return fallback

    return resolved


def _apply_modification(image: Image.Image, plan: Dict[str, Any]) -> Image.Image:
    action = plan["action"]
    if action == "resize_image":
        return image.resize((int(plan["target_width"]), int(plan["target_height"])), RESAMPLING.NEAREST)

    if action == "resize_canvas":
        target_size = (int(plan["target_width"]), int(plan["target_height"]))
        contained = ImageOps.contain(image, target_size, RESAMPLING.NEAREST)
        canvas = Image.new("RGBA", target_size, (0, 0, 0, 0))
        offset = (
            (target_size[0] - contained.size[0]) // 2,
            (target_size[1] - contained.size[1]) // 2,
        )
        canvas.paste(contained, offset, contained)
        return canvas

    if action == "rotate":
        return image.rotate(-int(plan["degrees"]), expand=True, resample=RESAMPLING.NEAREST)

    raise ValueError("Unsupported modification action: " + str(action))


def _extract_name_pattern(prompt: str, default_pattern: str = "child_%d") -> str:
    quoted_pattern = re.search(r'"([^"]+)"', prompt)
    if quoted_pattern:
        return quoted_pattern.group(1)
    single_quoted = re.search(r"'([^']+)'", prompt)
    if single_quoted:
        return single_quoted.group(1)
    return default_pattern


def _extract_numeric_values(prompt: str) -> List[float]:
    matches = re.findall(r"-?\d+(?:\.\d+)?", prompt)
    return [float(match) for match in matches]


def _fallback_automation_actions(prompt: str, selected_nodes: List[SelectedNode]) -> List[Dict[str, Any]]:
    if not selected_nodes:
        raise ValueError("Select at least one node before running automation")

    primary = selected_nodes[0]
    lower_prompt = prompt.lower()
    name_pattern = _extract_name_pattern(prompt)

    create_match = re.search(
        r"create\s+(\d+)\s+([A-Za-z0-9_]+)\s+children",
        prompt,
        flags=re.IGNORECASE,
    )
    if create_match:
        return [
            {
                "action": "create_node",
                "params": {
                    "target_node_path": primary.scene_path,
                    "count": max(1, int(create_match.group(1))),
                    "node_type": create_match.group(2),
                    "name_pattern": name_pattern,
                },
            }
        ]

    rename_start_match = re.search(r"start(?:ing)?\s+from\s+(-?\d+)", prompt, flags=re.IGNORECASE)
    if "rename" in lower_prompt and "children" in lower_prompt:
        return [
            {
                "action": "rename_children",
                "params": {
                    "target_node_path": primary.scene_path,
                    "pattern": name_pattern if "%d" in name_pattern else "child_%d",
                    "start_index": int(rename_start_match.group(1)) if rename_start_match else 0,
                },
            }
        ]

    if "set position" in lower_prompt or "set_position" in lower_prompt:
        values = _extract_numeric_values(prompt)
        if primary.type.lower().endswith("3d") and len(values) >= 3:
            return [
                {
                    "action": "set_position",
                    "params": {
                        "target_node_path": primary.scene_path,
                        "args": [[values[0], values[1], values[2]]],
                    },
                }
            ]
        if len(values) >= 2:
            return [
                {
                    "action": "set_position",
                    "params": {
                        "target_node_path": primary.scene_path,
                        "args": [[values[0], values[1]]],
                    },
                }
            ]

    if "set name" in lower_prompt or "set_name" in lower_prompt:
        match = re.search(r'"([^"]+)"', prompt) or re.search(r"'([^']+)'", prompt)
        if match:
            return [
                {
                    "action": "set_name",
                    "params": {
                        "target_node_path": primary.scene_path,
                        "args": [match.group(1)],
                    },
                }
            ]

    return []


def _normalize_automation_actions(actions: Any, fallback_actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(actions, list):
        return fallback_actions

    normalized: List[Dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict):
            continue

        action_type = str(action.get("action") or "").strip()
        params = action.get("params", {})
        if not action_type or not isinstance(params, dict):
            continue

        normalized.append({"action": action_type, "params": params})

    return normalized or fallback_actions


def _plan_automation(prompt: str, selected_nodes: List[SelectedNode]) -> List[Dict[str, Any]]:
    fallback_actions = _fallback_automation_actions(prompt, selected_nodes)

    try:
        plan = _chat_json(
            (
                "You convert Godot editor automation requests into structured actions. "
                "Return JSON only. The root object must contain an actions array. "
                "Each action item must look like {\"action\": \"name\", \"params\": {...}}. "
                "For direct node operations, use the Godot method name as the action and put target_node_path and args in params. "
                "Example direct node action: {\"action\": \"set_name\", \"params\": {\"target_node_path\": \".\", \"args\": [\"Player\"]}}. "
                "For generic editor commands that are not a single node method, use abstract action names such as create_node or rename_children. "
                "Example create action: {\"action\": \"create_node\", \"params\": {\"target_node_path\": \".\", \"node_type\": \"Node3D\", \"count\": 10, \"name_pattern\": \"child_%d\"}}. "
                "Example rename action: {\"action\": \"rename_children\", \"params\": {\"target_node_path\": \".\", \"pattern\": \"child_%d\", \"start_index\": 0}}. "
                "Do not wrap params fields at the top level. Keep everything under params."
            ),
            {
                "prompt": prompt,
                "selected_nodes": [node.dict() for node in selected_nodes],
                "fallback": {"actions": fallback_actions},
            },
        )
    except Exception as exc:
        print("Text model automation planning failed:", exc)
        plan = None

    if not isinstance(plan, dict):
        return fallback_actions

    return _normalize_automation_actions(plan.get("actions"), fallback_actions)


@app.post("/vibe/generate")
async def generate_asset(request: GenerateAssetRequest) -> Dict[str, Any]:
    print("Generating asset for prompt:", request.prompt)

    if not GODOT_PROJECT_DIR.exists():
        return _error("Godot project dir not found: %s" % GODOT_PROJECT_DIR)

    try:
        target_folder = _resolve_res_path(request.folder_path, expect_directory=True)
        plan = _plan_generation(request.prompt)
        try:
            image_bytes = _generate_with_pixellab(
                description=plan["description"],
                width=plan["width"],
                height=plan["height"],
                no_background=bool(plan["no_background"]),
            )
        except requests.HTTPError as exc:
            response = exc.response
            if response is not None and response.status_code == 422:
                print("PixelLab rejected planned payload:", response.text)
                fallback_plan = _fallback_generation_plan(request.prompt)
                image_bytes = _generate_with_pixellab(
                    description=fallback_plan["description"],
                    width=fallback_plan["width"],
                    height=fallback_plan["height"],
                    no_background=bool(fallback_plan["no_background"]),
                )
                plan = fallback_plan
            else:
                raise

        file_name = plan["filename_stub"] + ".png"
        save_path = target_folder / file_name
        save_path.write_bytes(image_bytes)

        return {
            "status": "success",
            "type": "asset",
            "file": file_name,
            "file_path": _to_res_path(save_path),
            "plan": plan,
        }
    except Exception as exc:
        print("Asset generation failed:", exc)
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            print("PixelLab error body:", exc.response.text)
        return _error(str(exc))


@app.post("/vibe/modify")
async def modify_asset(request: ModifyAssetRequest) -> Dict[str, Any]:
    print("Modifying asset:", request.asset_path, "prompt:", request.prompt)

    try:
        asset_path = _resolve_res_path(request.asset_path)
        if not asset_path.exists():
            return _error("Selected asset does not exist: %s" % request.asset_path)

        if asset_path.suffix.lower() not in IMAGE_EXTENSIONS:
            return _error("Selected asset is not a supported image file")

        image = _load_image(asset_path)
        plan = _plan_modification(request.prompt, request.asset_path, image.width, image.height)
        modified = _apply_modification(image, plan)

        output_name = "%s_%s.png" % (asset_path.stem, plan["filename_suffix"])
        output_path = asset_path.with_name(output_name)
        _save_png(modified, output_path)

        return {
            "status": "success",
            "type": "asset",
            "file": output_path.name,
            "file_path": _to_res_path(output_path),
            "source_file_path": request.asset_path,
            "plan": plan,
        }
    except Exception as exc:
        print("Asset modification failed:", exc)
        return _error(str(exc))


@app.post("/vibe/automate")
async def automate_editor(request: AutomationRequest) -> Dict[str, Any]:
    print("Automating editor action for prompt:", request.prompt)

    try:
        actions = _plan_automation(request.prompt, request.selected_nodes)
        if not actions:
            return _error("Automation planner returned no supported actions")

        return {
            "status": "success",
            "type": "automation",
            "actions": actions,
            "message": "Automation plan ready",
        }
    except Exception as exc:
        print("Automation planning failed:", exc)
        return _error(str(exc))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
