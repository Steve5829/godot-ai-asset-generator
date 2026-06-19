import base64
import binascii
import io
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from fastapi import FastAPI
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

try:
    from style_matrix import STYLE_MATRIX, style_profile_dict
except Exception as exc:
    print("Failed to import style matrix:", exc)
    STYLE_MATRIX = {}

    def style_profile_dict(style_key: str) -> Dict[str, str]:
        raise KeyError("Style matrix is unavailable")

BASE_DIR = Path(__file__).resolve().parent
for env_path in (
    BASE_DIR / ".env",
    BASE_DIR.parent / ".env",
    BASE_DIR / "vibe-agent-demo" / ".env",
    BASE_DIR / "VibeAgentDemo" / ".env",
):
    if env_path.exists():
        load_dotenv(env_path, override=False)

app = FastAPI()


def _detect_godot_project_dir() -> Path:
    override = os.getenv("GODOT_PROJECT_DIR")
    if override:
        configured = Path(override)
        if not configured.is_absolute():
            configured = (BASE_DIR / configured).resolve()
        return configured

    candidates = (
        BASE_DIR.parent,
        BASE_DIR / "vibe-agent-demo",
        BASE_DIR / "VibeAgentDemo",
    )
    for candidate in candidates:
        if (candidate / "project.godot").exists():
            return candidate.resolve()

    return BASE_DIR.parent.resolve()


GODOT_PROJECT_DIR = _detect_godot_project_dir()
PIXELLAB_API_KEY = os.getenv("PIXELLAB_API_KEY") or os.getenv("PIXELLAB_SECRET")
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL") or "gpt-image-1"
OPENAI_IMAGE_QUALITY = os.getenv("OPENAI_IMAGE_QUALITY") or "medium"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
RESAMPLING = getattr(Image, "Resampling", Image)
SUPPORTED_STYLE_TARGETS = set(STYLE_MATRIX.keys()) or {
    "core_keeper",
    "terraria",
    "minecraft",
}
ASSET_TYPE_SPECS = {
    "icon": {
        "label": "Icon",
        "default_width": 128,
        "default_height": 128,
        "no_background": True,
        "prompt_guidance": (
            "Create a single readable inventory or UI icon. Center the subject, use a clear silhouette, "
            "avoid scene backgrounds, and keep details legible at small sizes."
        ),
    },
    "ground_atlas": {
        "label": "Ground Atlas",
        "default_width": 256,
        "default_height": 256,
        "no_background": False,
        "prompt_guidance": (
            "Create a top-down orthographic terrain/material atlas or reusable tileable ground swatch. "
            "Fill the frame with repeatable material variation; no horizon, no scene composition, no paths or roads "
            "unless explicitly requested, no large trees, trunks, characters, or buildings, and no single focal object."
        ),
    },
    "block_texture": {
        "label": "Block Texture",
        "default_width": 64,
        "default_height": 96,
        "no_background": False,
        "prompt_guidance": (
            "Create a compact block or voxel-style texture with readable top/front material cues. "
            "Use crisp edges and proportions suitable for a placeable terrain or building block."
        ),
    },
    "spritesheet": {
        "label": "Spritesheet",
        "default_width": 256,
        "default_height": 256,
        "no_background": True,
        "prompt_guidance": (
            "Create a sprite animation sheet or organized sprite cells. Keep cells evenly spaced, use consistent scale, "
            "and make each frame readable against a transparent or simple background."
        ),
    },
    "reference_scene": {
        "label": "Reference Scene",
        "default_width": 400,
        "default_height": 400,
        "no_background": False,
        "prompt_guidance": (
            "Create a small concept/reference scene showing composition, palette, mood, and materials. "
            "It can include background context and should prioritize direction over direct sprite readiness."
        ),
    },
}
SUPPORTED_ASSET_TYPES = set(ASSET_TYPE_SPECS.keys())
SUPPORTED_GENERATION_PROVIDERS = {"pixellab", "openai_image"}


class GenerateAssetRequest(BaseModel):
    prompt: str = Field(min_length=1)
    folder_path: str = "res://"
    asset_type: str = "auto"
    workflow_mode: str = "auto"
    style_target: Optional[str] = "none"
    provider: str = "pixellab"
    metadata: Dict[str, Any] = Field(default_factory=dict)


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


def _normalize_style_target(style_target: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(style_target or "").strip().lower()).strip("_")
    if normalized in {"", "none", "no_style", "default", "null", "nil", "undefined"}:
        return "none"
    if normalized in SUPPORTED_STYLE_TARGETS:
        return normalized
    return "core_keeper"


def _style_context(style_target: str) -> Dict[str, Any]:
    normalized = _normalize_style_target(style_target)
    if normalized == "none":
        return {
            "key": "none",
            "title": "No Style Target",
            "target_style_selected": False,
            "notes": "No target style selected; use the user prompt, asset type constraints, and provider constraints only.",
        }
    try:
        return style_profile_dict(normalized)
    except Exception:
        return {
            "key": normalized,
            "title": normalized.replace("_", " ").title(),
            "notes": "No style profile was available; use only the supplied key and user prompt.",
        }


def _normalize_asset_type(asset_type: str, allow_auto: bool = False) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(asset_type or "").strip().lower()).strip("_")
    if allow_auto and normalized in {"", "auto", "automatic", "planned", "planner"}:
        return "auto"
    if normalized in SUPPORTED_ASSET_TYPES:
        return normalized
    return "icon"


def _normalize_workflow_mode(workflow_mode: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(workflow_mode or "").strip().lower()).strip("_")
    if normalized in {"", "auto", "automatic", "planned", "planner"}:
        return "auto"
    return normalized


def _normalize_generation_provider(provider: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(provider or "").strip().lower()).strip("_")
    if normalized in {"gpt_image", "openai", "openai_images", "gpt_images"}:
        return "openai_image"
    if normalized in SUPPORTED_GENERATION_PROVIDERS:
        return normalized
    return "pixellab"


def _asset_type_spec(asset_type: str) -> Dict[str, Any]:
    return ASSET_TYPE_SPECS[_normalize_asset_type(asset_type)]


def _asset_type_constraints(asset_type: str) -> str:
    spec = _asset_type_spec(asset_type)
    return "%s asset. %s" % (spec["label"], spec["prompt_guidance"])


def _description_with_asset_constraints(asset_type: str, description: str) -> str:
    normalized_asset_type = _normalize_asset_type(asset_type)
    cleaned_description = str(description or "").strip()
    if normalized_asset_type != "ground_atlas":
        return cleaned_description

    lowered_description = cleaned_description.lower()
    if "top-down orthographic terrain/material atlas" in lowered_description and "do not create a composed forest scene" in lowered_description:
        return cleaned_description

    ground_constraints = (
        "Generate as a top-down orthographic terrain/material atlas for reusable game ground tiles. "
        "Fill the entire image with tileable material variation. Do not create a composed forest scene, "
        "camera view, horizon, background, path, road, large tree, trunk, character, building, or single focal object."
    )
    if not cleaned_description:
        return ground_constraints
    return "%s. %s" % (cleaned_description.rstrip("."), ground_constraints)


def _provider_constraints(provider: str) -> str:
    normalized_provider = _normalize_generation_provider(provider)
    if normalized_provider == "pixellab":
        return "PixelLab provider. Prefer native-looking pixel art, crisp silhouettes, and no blurry edges."
    if normalized_provider == "openai_image":
        return (
            "GPT Image provider. It can handle richer reference scenes, larger compositions, and atlas-like outputs "
            "better than PixelLab, but the final saved asset will still be clamped to 400px per side. Preserve crisp "
            "game-art readability, avoid photorealism unless requested, and make repeatable materials less object-centric."
        )
    return "No provider-specific constraints supplied."


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
        raise ValueError("OPENAI_API_KEY is not configured")

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


def _default_generation_dimensions(asset_type: str) -> Dict[str, int]:
    spec = _asset_type_spec(asset_type)
    return {
        "width": _clamp_size(spec["default_width"], spec["default_width"]),
        "height": _clamp_size(spec["default_height"], spec["default_height"]),
    }


def _infer_asset_type_from_prompt(prompt: str, requested_asset_type: str) -> str:
    normalized_requested = _normalize_asset_type(requested_asset_type, allow_auto=True)
    if normalized_requested != "auto":
        return normalized_requested

    lowered = prompt.lower()
    if any(token in lowered for token in ("spritesheet", "sprite sheet", "walk cycle", "animation frame", "animation sheet")):
        return "spritesheet"
    if any(token in lowered for token in ("two-face", "two face", "top and front", "top/front", "block texture", "voxel block")):
        return "block_texture"
    if "block" in lowered and any(token in lowered for token in ("texture", "tile", "stone", "dirt", "grass", "ore")):
        return "block_texture"
    if any(token in lowered for token in ("ground atlas", "terrain atlas", "tile atlas", "atlas", "tilemap", "ground tile", "floor tile")):
        return "ground_atlas"
    if any(token in lowered for token in ("reference scene", "concept scene", "scene concept", "background", "environment concept")):
        return "reference_scene"
    return "icon"


def _default_workflow_for_asset_type(asset_type: str) -> str:
    if asset_type == "block_texture":
        return "block_texture_two_face"
    if asset_type == "ground_atlas":
        return "ground_atlas"
    if asset_type == "spritesheet":
        return "spritesheet"
    if asset_type == "reference_scene":
        return "reference_scene"
    return "single_image"


def _parse_grid_config(prompt: str) -> Dict[str, int]:
    lowered = prompt.lower()
    grid_match = re.search(r"(\d{1,2})\s*[xX×]\s*(\d{1,2})\s*(?:grid|sheet|spritesheet|sprite sheet|cells|frames)", prompt)
    if grid_match:
        return {"columns": max(1, int(grid_match.group(1))), "rows": max(1, int(grid_match.group(2)))}

    frame_match = re.search(r"(\d{1,2})\s*(?:frames|frame animation|animation frames)", lowered)
    if frame_match:
        frame_count = max(1, int(frame_match.group(1)))
        return {"columns": frame_count, "rows": 1}

    return {"columns": 4, "rows": 4}


def _default_postprocess_config(prompt: str, asset_type: str) -> Dict[str, Any]:
    lowered = prompt.lower()
    if asset_type == "ground_atlas":
        should_slice = any(token in lowered for token in ("slice", "crop", "split", "tileset cells", "individual tiles"))
        tile_size_match = re.search(r"(\d{2,3})\s*(?:px|pixel)?\s*tiles?", lowered)
        tile_size = int(tile_size_match.group(1)) if tile_size_match else 32
        return {"slice": should_slice, "tile_width": _clamp_size(tile_size, 32), "tile_height": _clamp_size(tile_size, 32)}

    if asset_type == "spritesheet":
        should_crop = any(token in lowered for token in ("crop", "slice", "split", "individual frames", "cells"))
        grid = _parse_grid_config(prompt)
        return {"crop_cells": should_crop, "columns": grid["columns"], "rows": grid["rows"]}

    if asset_type == "block_texture":
        return {"final_width": 32, "top_height": 16, "front_height": 32}

    return {}


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _workflow_expected_outputs(asset_type: str, postprocess: Dict[str, Any]) -> List[str]:
    if asset_type == "block_texture":
        return ["block_texture", "top_face_source", "front_face_source"]
    if asset_type == "ground_atlas":
        return ["full_image", "atlas_tiles"] if bool(postprocess.get("slice", False)) else ["full_image"]
    if asset_type == "spritesheet":
        return ["full_image", "sprite_cells"] if bool(postprocess.get("crop_cells", False)) else ["full_image"]
    return ["full_image"]


def _coerce_postprocess_config(asset_type: str, value: Any, fallback: Dict[str, Any]) -> Dict[str, Any]:
    config = dict(fallback)
    if isinstance(value, dict):
        config.update(value)

    if asset_type == "ground_atlas":
        config["slice"] = bool(config.get("slice", False))
        config["tile_width"] = _clamp_size(config.get("tile_width"), fallback.get("tile_width", 32))
        config["tile_height"] = _clamp_size(config.get("tile_height"), fallback.get("tile_height", 32))
    elif asset_type == "spritesheet":
        config["crop_cells"] = bool(config.get("crop_cells", False))
        config["columns"] = _bounded_int(config.get("columns"), int(fallback.get("columns", 4)), 1, 16)
        config["rows"] = _bounded_int(config.get("rows"), int(fallback.get("rows", 4)), 1, 16)
    elif asset_type == "block_texture":
        config["final_width"] = _clamp_size(config.get("final_width"), fallback.get("final_width", 32))
        config["top_height"] = _clamp_size(config.get("top_height"), fallback.get("top_height", 16))
        config["front_height"] = _clamp_size(config.get("front_height"), fallback.get("front_height", 32))
    return config


def _normalize_workflow(asset_type: str, workflow: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(workflow or "").strip().lower()).strip("_")
    allowed = {
        "single_image",
        "ground_atlas",
        "spritesheet",
        "block_texture_two_face",
        "reference_scene",
    }
    if normalized in allowed:
        return normalized
    return _default_workflow_for_asset_type(asset_type)


def _fallback_generation_plan(prompt: str, asset_type: str, workflow_mode: str, style_target: str, provider: str, note: str) -> Dict[str, Any]:
    normalized_asset_type = _infer_asset_type_from_prompt(prompt, asset_type)
    normalized_style = _normalize_style_target(style_target)
    normalized_provider = _normalize_generation_provider(provider)
    style_context = _style_context(normalized_style)
    default_dimensions = _default_generation_dimensions(normalized_asset_type)
    fallback_dimensions = _parse_prompt_dimensions(
        prompt,
        default_dimensions["width"],
        default_dimensions["height"],
    )
    asset_spec = _asset_type_spec(normalized_asset_type)
    workflow = _normalize_workflow(
        normalized_asset_type,
        workflow_mode if _normalize_workflow_mode(workflow_mode) != "auto" else _default_workflow_for_asset_type(normalized_asset_type),
    )
    postprocess = _default_postprocess_config(prompt, normalized_asset_type)
    description = _description_with_asset_constraints(normalized_asset_type, prompt)
    return {
        "description": description,
        "descriptions": {
            "primary": description,
            "top": "%s, top face only, seamless tile material, viewed straight-on as the top surface" % description,
            "front": "%s, front face only, seamless tile material, viewed straight-on as the vertical face" % description,
        },
        "width": fallback_dimensions["width"],
        "height": fallback_dimensions["height"],
        "filename_stub": _safe_stem("%s_%s_%s" % (normalized_asset_type, normalized_style, prompt), "generated_asset"),
        "no_background": bool(asset_spec["no_background"]),
        "asset_type": normalized_asset_type,
        "workflow": workflow,
        "style_target": normalized_style,
        "style_context": style_context,
        "provider": normalized_provider,
        "postprocess": postprocess,
        "outputs_expected": _workflow_expected_outputs(normalized_asset_type, postprocess),
        "notes": [note],
        "planning_source": "fallback",
        "planning_note": note,
    }


def _plan_generation_workflow(request: GenerateAssetRequest) -> Dict[str, Any]:
    requested_asset_type = _normalize_asset_type(request.asset_type, allow_auto=True)
    normalized_style = _normalize_style_target(request.style_target)
    normalized_provider = _normalize_generation_provider(request.provider)
    workflow_mode = _normalize_workflow_mode(request.workflow_mode)
    fallback = _fallback_generation_plan(
        request.prompt,
        requested_asset_type,
        workflow_mode,
        normalized_style,
        normalized_provider,
        "Used fallback workflow plan before LLM planning completed.",
    )

    failure_reason = ""
    try:
        plan = _chat_json(
            (
                "You are an expert technical artist and AI workflow planner for game asset generation. "
                "Infer the best asset_type and workflow from the user's prompt unless the requested asset_type is not auto. "
                "Supported asset types are icon, ground_atlas, spritesheet, block_texture, and reference_scene. "
                "Supported workflows are single_image, ground_atlas, spritesheet, block_texture_two_face, and reference_scene. "
                "For block_texture, prefer block_texture_two_face and provide separate top and front descriptions for two API calls. "
                "For ground_atlas, create a top-down orthographic terrain/material atlas or reusable tileable ground swatch, not a composed scene. "
                "If the user asks for a forest ground atlas, produce forest floor material texture variation, not trees, paths, or a forest scene. "
                "Only reference_scene may include composed scenes, backgrounds, camera views, horizons, or environment concept art. "
                "For ground_atlas, save the full atlas by default; set postprocess.slice true only when the user asks for sliced tiles. "
                "For spritesheet, save the full sheet by default; set postprocess.crop_cells true only when the user asks for cropped cells. "
                "Use the style_context only when a real style target is selected. If style_target is none, do not invent a game style. "
                "Return JSON with asset_type, workflow, provider, style_target, description, descriptions, width, height, "
                "filename_stub, no_background, postprocess, outputs_expected, and notes. Width and height must be 16-400."
            ),
            {
                "user_prompt": request.prompt,
                "requested_asset_type": requested_asset_type,
                "workflow_mode": workflow_mode,
                "supported_asset_types": sorted(SUPPORTED_ASSET_TYPES),
                "asset_type_constraints": {key: _asset_type_constraints(key) for key in sorted(SUPPORTED_ASSET_TYPES)},
                "target_game_style": normalized_style,
                "style_context": fallback["style_context"],
                "provider_constraints": _provider_constraints(normalized_provider),
                "provider": normalized_provider,
                "fallback": fallback,
            },
        )
    except Exception as exc:
        print("Text model generation planning failed:", exc)
        failure_reason = str(exc)
        plan = None

    if not isinstance(plan, dict):
        fallback["planning_note"] = (
            "Used fallback plan because LLM planning was unavailable."
            if not failure_reason
            else "Used fallback plan because LLM planning failed: %s" % failure_reason
        )
        fallback["notes"] = [fallback["planning_note"]]
        return fallback

    planned_asset_type = _normalize_asset_type(plan.get("asset_type") if requested_asset_type == "auto" else requested_asset_type)
    default_dimensions = _default_generation_dimensions(planned_asset_type)
    fallback_dimensions = _parse_prompt_dimensions(request.prompt, default_dimensions["width"], default_dimensions["height"])
    asset_spec = _asset_type_spec(planned_asset_type)
    workflow = _normalize_workflow(planned_asset_type, plan.get("workflow") or fallback["workflow"])
    fallback_postprocess = _default_postprocess_config(request.prompt, planned_asset_type)
    postprocess = _coerce_postprocess_config(planned_asset_type, plan.get("postprocess"), fallback_postprocess)
    descriptions = plan.get("descriptions") if isinstance(plan.get("descriptions"), dict) else {}
    primary_description = _description_with_asset_constraints(
        planned_asset_type,
        str(plan.get("description") or descriptions.get("primary") or fallback["description"]).strip(),
    )

    return {
        "description": primary_description,
        "descriptions": {
            "primary": primary_description,
            "top": str(descriptions.get("top") or "%s, top face only, seamless tile material" % primary_description).strip(),
            "front": str(descriptions.get("front") or "%s, front face only, vertical side material" % primary_description).strip(),
        },
        "width": _clamp_size(plan.get("width"), fallback_dimensions["width"]),
        "height": _clamp_size(plan.get("height"), fallback_dimensions["height"]),
        "filename_stub": _safe_stem(str(plan.get("filename_stub") or fallback["filename_stub"]), "generated_asset"),
        "no_background": bool(plan.get("no_background", asset_spec["no_background"])),
        "asset_type": planned_asset_type,
        "workflow": workflow,
        "style_target": normalized_style,
        "style_context": fallback["style_context"],
        "provider": normalized_provider,
        "postprocess": postprocess,
        "outputs_expected": plan.get("outputs_expected") if isinstance(plan.get("outputs_expected"), list) else _workflow_expected_outputs(planned_asset_type, postprocess),
        "notes": plan.get("notes") if isinstance(plan.get("notes"), list) else ["Used LLM-generated workflow plan."],
        "planning_source": "llm",
        "planning_note": "Used LLM-generated plan.",
    }


def _provider_rejection_fallback_plan(request: GenerateAssetRequest, planned_asset_type: str, provider: str) -> Dict[str, Any]:
    return _fallback_generation_plan(
        request.prompt,
        planned_asset_type,
        request.workflow_mode,
        request.style_target,
        provider,
        "Used fallback generation plan after provider rejected the planned payload.",
    )


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


def _openai_image_size(width: int, height: int) -> str:
    if width > height:
        return "1536x1024"
    if height > width:
        return "1024x1536"
    return "1024x1024"


def _resize_png_bytes(image_bytes: bytes, width: int, height: int) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as image:
        converted = image.convert("RGBA")
        if converted.size != (width, height):
            converted = converted.resize((width, height), RESAMPLING.LANCZOS)
        output = io.BytesIO()
        converted.save(output, format="PNG")
        return output.getvalue()


def _decode_openai_image_payload(image_data: Dict[str, Any]) -> bytes:
    if not isinstance(image_data, dict):
        raise ValueError("OpenAI image payload is not an object")

    b64_json = image_data.get("b64_json")
    if isinstance(b64_json, str) and b64_json:
        try:
            return base64.b64decode(b64_json)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("OpenAI image API returned invalid base64 image data") from exc

    image_url = image_data.get("url")
    if isinstance(image_url, str) and image_url:
        parsed_url = urlparse(image_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("OpenAI image API returned an invalid image URL")
        image_response = requests.get(image_url, timeout=(10, 180), allow_redirects=False)
        image_response.raise_for_status()
        return image_response.content

    raise ValueError("OpenAI image API response did not include b64_json or url")


def _generate_with_openai_image(description: str, width: int, height: int, no_background: bool) -> bytes:
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not configured")

    payload: Dict[str, Any] = {
        "model": OPENAI_IMAGE_MODEL,
        "prompt": description,
        "size": _openai_image_size(width, height),
        "quality": OPENAI_IMAGE_QUALITY,
        "n": 1,
        "output_format": "png",
    }
    if no_background:
        payload["background"] = "transparent"

    response = requests.post(
        OPENAI_BASE_URL + "/images/generations",
        headers={
            "Authorization": "Bearer " + OPENAI_API_KEY,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=(10, 180),
    )
    response.raise_for_status()

    payload = response.json()
    data = payload.get("data") or []
    if not data or not isinstance(data[0], dict):
        raise ValueError("OpenAI image API returned no image data")

    return _resize_png_bytes(_decode_openai_image_payload(data[0]), width, height)


def _generate_with_provider(provider: str, description: str, width: int, height: int, no_background: bool) -> bytes:
    normalized_provider = _normalize_generation_provider(provider)
    if normalized_provider == "pixellab":
        return _generate_with_pixellab(
            description=description,
            width=width,
            height=height,
            no_background=no_background,
        )
    if normalized_provider == "openai_image":
        return _generate_with_openai_image(
            description=description,
            width=width,
            height=height,
            no_background=no_background,
        )
    raise ValueError("Unsupported image generation provider: %s" % provider)


def _png_image_from_bytes(image_bytes: bytes) -> Image.Image:
    with Image.open(io.BytesIO(image_bytes)) as image:
        return image.convert("RGBA")


def _save_generated_png(image_bytes: bytes, output_path: Path) -> Dict[str, str]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_bytes)
    return {"file": output_path.name, "file_path": _to_res_path(output_path)}


def _append_output(outputs: List[Dict[str, Any]], output_path: Path, role: str) -> None:
    outputs.append({"role": role, "file": output_path.name, "file_path": _to_res_path(output_path)})


def _crop_grid_outputs(image: Image.Image, target_folder: Path, filename_stub: str, role_prefix: str, columns: int, rows: int) -> List[Dict[str, Any]]:
    outputs: List[Dict[str, Any]] = []
    columns = max(1, columns)
    rows = max(1, rows)
    cell_width = max(1, image.width // columns)
    cell_height = max(1, image.height // rows)

    for row in range(rows):
        for column in range(columns):
            left = column * cell_width
            top = row * cell_height
            right = image.width if column == columns - 1 else left + cell_width
            bottom = image.height if row == rows - 1 else top + cell_height
            cell = image.crop((left, top, right, bottom))
            cell_path = target_folder / ("%s_%s_r%02d_c%02d.png" % (filename_stub, role_prefix, row, column))
            _save_png(cell, cell_path)
            _append_output(outputs, cell_path, "%s_cell" % role_prefix)

    return outputs


def _slice_tile_outputs(image: Image.Image, target_folder: Path, filename_stub: str, tile_width: int, tile_height: int) -> List[Dict[str, Any]]:
    outputs: List[Dict[str, Any]] = []
    tile_width = max(1, tile_width)
    tile_height = max(1, tile_height)
    rows = max(1, image.height // tile_height)
    columns = max(1, image.width // tile_width)

    for row in range(rows):
        for column in range(columns):
            left = column * tile_width
            top = row * tile_height
            tile = image.crop((left, top, min(image.width, left + tile_width), min(image.height, top + tile_height)))
            tile_path = target_folder / ("%s_tile_r%02d_c%02d.png" % (filename_stub, row, column))
            _save_png(tile, tile_path)
            _append_output(outputs, tile_path, "atlas_tile")

    return outputs


def _compose_two_face_block(top_bytes: bytes, front_bytes: bytes, config: Dict[str, Any]) -> Image.Image:
    final_width = int(config.get("final_width") or 32)
    top_height = int(config.get("top_height") or 16)
    front_height = int(config.get("front_height") or 32)
    top_face = _png_image_from_bytes(top_bytes).resize((final_width, top_height), RESAMPLING.NEAREST)
    front_face = _png_image_from_bytes(front_bytes).resize((final_width, front_height), RESAMPLING.NEAREST)
    composed = Image.new("RGBA", (final_width, top_height + front_height), (0, 0, 0, 0))
    composed.paste(top_face, (0, 0), top_face)
    composed.paste(front_face, (0, top_height), front_face)
    return composed


def _execute_generation_workflow(plan: Dict[str, Any], target_folder: Path) -> List[Dict[str, Any]]:
    workflow = _normalize_workflow(plan["asset_type"], plan.get("workflow"))
    provider = _normalize_generation_provider(plan.get("provider"))
    filename_stub = _safe_stem(str(plan.get("filename_stub") or "generated_asset"), "generated_asset")
    postprocess = plan.get("postprocess") if isinstance(plan.get("postprocess"), dict) else {}
    outputs: List[Dict[str, Any]] = []

    if workflow == "block_texture_two_face":
        final_width = _clamp_size(postprocess.get("final_width"), 32)
        top_height = _clamp_size(postprocess.get("top_height"), 16)
        front_height = _clamp_size(postprocess.get("front_height"), 32)
        face_config = {"final_width": final_width, "top_height": top_height, "front_height": front_height}
        descriptions = plan.get("descriptions") if isinstance(plan.get("descriptions"), dict) else {}
        top_bytes = _generate_with_provider(
            provider=provider,
            description=str(descriptions.get("top") or plan["description"]),
            width=final_width,
            height=top_height,
            no_background=False,
        )
        front_bytes = _generate_with_provider(
            provider=provider,
            description=str(descriptions.get("front") or plan["description"]),
            width=final_width,
            height=front_height,
            no_background=False,
        )

        top_path = target_folder / ("%s_top.png" % filename_stub)
        front_path = target_folder / ("%s_front.png" % filename_stub)
        composed_path = target_folder / ("%s.png" % filename_stub)
        _save_generated_png(top_bytes, top_path)
        _save_generated_png(front_bytes, front_path)
        _save_png(_compose_two_face_block(top_bytes, front_bytes, face_config), composed_path)
        _append_output(outputs, composed_path, "block_texture")
        _append_output(outputs, top_path, "top_face_source")
        _append_output(outputs, front_path, "front_face_source")
        return outputs

    image_bytes = _generate_with_provider(
        provider=provider,
        description=plan["description"],
        width=plan["width"],
        height=plan["height"],
        no_background=bool(plan["no_background"]),
    )
    full_path = target_folder / ("%s.png" % filename_stub)
    _save_generated_png(image_bytes, full_path)
    _append_output(outputs, full_path, "full_image")

    if workflow == "ground_atlas" and bool(postprocess.get("slice", False)):
        image = _png_image_from_bytes(image_bytes)
        outputs.extend(
            _slice_tile_outputs(
                image,
                target_folder,
                filename_stub,
                int(postprocess.get("tile_width") or 32),
                int(postprocess.get("tile_height") or 32),
            )
        )
    elif workflow == "spritesheet" and bool(postprocess.get("crop_cells", False)):
        image = _png_image_from_bytes(image_bytes)
        outputs.extend(
            _crop_grid_outputs(
                image,
                target_folder,
                filename_stub,
                "cell",
                int(postprocess.get("columns") or 4),
                int(postprocess.get("rows") or 4),
            )
        )

    return outputs


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
        requested_asset_type = _normalize_asset_type(request.asset_type, allow_auto=True)
        style_target = _normalize_style_target(request.style_target)
        provider = _normalize_generation_provider(request.provider)
        metadata = dict(request.metadata or {})
        plan = _plan_generation_workflow(request)
        print(
            "Generation planner source=%s asset_type=%s workflow=%s style=%s provider=%s description=%s"
            % (
                plan.get("planning_source", "unknown"),
                plan.get("asset_type", requested_asset_type),
                plan.get("workflow", "unknown"),
                plan.get("style_target", style_target),
                plan.get("provider", provider),
                plan.get("description", ""),
            )
        )
        try:
            outputs = _execute_generation_workflow(plan, target_folder)
        except requests.HTTPError as exc:
            response = exc.response
            if response is not None and response.status_code == 422:
                print("PixelLab rejected planned payload:", response.text)
                fallback_plan = _provider_rejection_fallback_plan(request, plan.get("asset_type", requested_asset_type), provider)
                outputs = _execute_generation_workflow(fallback_plan, target_folder)
                plan = fallback_plan
            else:
                raise

        if not outputs:
            raise ValueError("Generation workflow produced no output files")
        primary_output = outputs[0]

        return {
            "status": "success",
            "type": "asset",
            "file": primary_output["file"],
            "file_path": primary_output["file_path"],
            "asset_type": plan.get("asset_type", requested_asset_type),
            "workflow": plan.get("workflow", "single_image"),
            "provider": plan.get("provider", provider),
            "style_target": style_target,
            "metadata": metadata,
            "plan": plan,
            "outputs": outputs,
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
