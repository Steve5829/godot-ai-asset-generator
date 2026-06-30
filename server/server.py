import base64
import binascii
import io
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from fastapi import FastAPI
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from style_matrix import STYLE_BLOCK_LAYOUTS, STYLE_MATRIX, style_block_layout, style_profile_dict

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
OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL") or OPENAI_MODEL
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL") or "gpt-image-1"
OPENAI_IMAGE_QUALITY = os.getenv("OPENAI_IMAGE_QUALITY") or "medium"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
DATA_DIR = BASE_DIR / "data"
REFERENCE_IMAGE_ROOT = BASE_DIR / "reference_images"


def _load_data_table(filename: str) -> Dict[str, Dict[str, Any]]:
    """Load a name->profile table from data/<filename>; empty dict if missing/broken."""
    path = DATA_DIR / filename
    try:
        with path.open(encoding="utf-8") as f:
            table = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print("Failed to load data table %s: %s" % (filename, exc))
        return {}
    return table if isinstance(table, dict) else {}
GENERATION_LOG_PATH = BASE_DIR / "logs" / "generation_events.jsonl"
MAX_REFERENCE_IMAGES = 3
REFERENCE_IMAGE_MAX_EDGE = 512
RESAMPLING = getattr(Image, "Resampling", Image)
PIXELLAB_MIN_IMAGE_SIZE = 32
PIXELLAB_BLOCK_SOURCE_MIN_WIDTH = 64
PIXELLAB_STYLE_STRENGTH = float(os.getenv("PIXELLAB_STYLE_STRENGTH") or 45)
PIXELLAB_STYLE_IMAGE_MAX_EDGE = 128
STYLE_SNAP_COLORS = int(os.getenv("STYLE_SNAP_COLORS") or 24)
REFERENCE_IMAGE_SYNONYM_GROUPS = (
    {"potion", "healing", "bottle", "vial", "flask", "elixir"},
    {"sword", "blade", "weapon"},
    {"ore", "crystal", "mineral"},
)
BLOCK_TEXTURE_REFERENCE_SYNONYM_GROUPS = (
    {"sand", "dune", "desert", "sandstone", "dry"},
    {"grass", "leaf", "leaves", "moss", "forest", "root", "roots", "dirt", "wood", "tree"},
    {"rock", "stone", "cracked", "barren", "dusty"},
    {"coral", "ocean", "sea", "algae", "water", "underwater"},
    {"brick", "wall"},
)
BLOCK_TEXTURE_GENERIC_TOKENS = {"block", "texture", "face", "top", "front", "side"}
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
        "label": "Ground Texture Swatch",
        "default_width": 128,
        "default_height": 128,
        "no_background": False,
        "prompt_guidance": (
            "Create one single continuous top-down terrain material texture swatch. "
            "Fill the frame with repeatable material variation as one unbroken image; no horizon, no scene composition, no paths or roads "
            "unless explicitly requested, no large trees, trunks, characters, or buildings, and no single focal object. "
            "Do not draw grid lines, individual tile panels, collage layouts, 2x2/3x3 layouts, crosses, tile borders, "
            "seams, cell divisions, cell outlines, or visible tile separators. Any slicing or cropping happens after generation."
        ),
    },
    "block_texture": {
        "label": "Block Texture",
        "default_width": 64,
        "default_height": 96,
        "no_background": False,
        "prompt_guidance": (
            "Create a compact block texture with readable top/front material cues. "
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
SUPPORTED_GENERATION_MODES = {"auto", "plain", "reference", "style_transfer"}
GENERATION_MODE_LABELS = {
    "auto": "Auto (smart)",
    "plain": "Plain text",
    "reference": "Reference analysis",
    "style_transfer": "Style transfer",
}
GENERATION_MODE_DESCRIPTIONS = {
    "auto": "Picks the best method per asset: style transfer for block/ground textures, reference analysis for icons.",
    "plain": "Generates only from the text prompt and the built-in style/material descriptions. No reference images used.",
    "reference": "Looks at matching reference images, summarizes their style in words, and adds that to the prompt.",
    "style_transfer": "Feeds a matching reference image straight into PixelLab (bitforge) to copy its look. Applies to every asset type.",
}
BLOCK_MATERIAL_PROFILES: Dict[str, Dict[str, Any]] = _load_data_table("materials.json")



ICON_REFERENCE_PROFILES: Dict[str, Dict[str, Any]] = _load_data_table("icons.json")


_DEFAULT_BLOCK_LAYOUT = {
    "workflow": "block_texture_two_face",
    "final_width": 32,
    "top_height": 16,
    "front_height": 32,
    "side_height": 0,
}


def _block_texture_layout(style_target: str) -> Dict[str, Any]:
    normalized = _normalize_style_target(style_target)
    layout = style_block_layout(normalized) if normalized != "none" else {}
    if not layout:
        layout = style_block_layout("core_keeper") or _DEFAULT_BLOCK_LAYOUT
    return dict(layout)


def _block_profile_key(profile: Optional[Dict[str, Any]]) -> str:
    if not profile:
        return ""
    for key, candidate in BLOCK_MATERIAL_PROFILES.items():
        if profile is candidate:
            return key
    return ""


def _block_profile_is_uniform(profile: Optional[Dict[str, Any]]) -> bool:
    return bool(profile and profile.get("uniform"))


def _block_requires_multi_face_generation(plan: Dict[str, Any]) -> bool:
    profile = _block_material_profile(plan)
    return bool(profile) and not _block_profile_is_uniform(profile)


class GenerateAssetRequest(BaseModel):
    prompt: str = Field(min_length=1)
    folder_path: str = "res://"
    asset_type: str = "auto"
    workflow_mode: str = "auto"
    generation_mode: str = "auto"
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


def _response_text_excerpt(response: requests.Response, limit: int = 500) -> str:
    text = response.text if response is not None else ""
    if not text:
        return ""
    return text[:limit]


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    return str(value)


def _bounded_error(message: Any, limit: int = 1000) -> str:
    text = str(message or "")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _generation_log_response_path() -> str:
    try:
        return GENERATION_LOG_PATH.resolve().relative_to(BASE_DIR.parent.resolve()).as_posix()
    except ValueError:
        return GENERATION_LOG_PATH.resolve().as_posix()


def _outputs_for_log(outputs: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    logged_outputs: List[Dict[str, str]] = []
    for output in outputs or []:
        if not isinstance(output, dict):
            continue
        logged_outputs.append(
            {
                "role": str(output.get("role") or ""),
                "file_path": str(output.get("file_path") or ""),
            }
        )
    return logged_outputs


def _reference_log_details(plan: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(plan, dict):
        return {
            "reference_images_found": 0,
            "reference_image_paths": [],
            "reference_analysis_status": "none",
        }

    reference_context = plan.get("reference_context") if isinstance(plan.get("reference_context"), dict) else {}
    reference_images = reference_context.get("reference_images") or plan.get("reference_images") or []
    reference_paths: List[str] = []
    if isinstance(reference_images, list):
        for reference_image in reference_images:
            if isinstance(reference_image, dict):
                path = reference_image.get("path")
            else:
                path = reference_image
            if path:
                reference_paths.append(str(path))

    status = str(reference_context.get("status") or "").strip()
    if not reference_paths:
        status = "none"
    elif status not in {"selected", "analyzed", "analysis_failed"}:
        status = "selected"

    return {
        "reference_images_found": len(reference_paths),
        "reference_image_paths": reference_paths,
        "reference_analysis_status": status,
    }


def _generation_log_event(
    event_id: str,
    request: GenerateAssetRequest,
    plan: Optional[Dict[str, Any]],
    status: str,
    elapsed_seconds: float,
    outputs: Optional[List[Dict[str, Any]]] = None,
    error: Optional[Any] = None,
) -> Dict[str, Any]:
    requested_asset_type = _normalize_asset_type(request.asset_type, allow_auto=True)
    normalized_style = _normalize_style_target(request.style_target)
    normalized_provider = _normalize_generation_provider(request.provider)
    plan_payload = plan if isinstance(plan, dict) else {}
    planning_source = str(plan_payload.get("planning_source") or "unknown")
    reference_details = _reference_log_details(plan_payload)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "log_event_id": event_id,
        "prompt": request.prompt,
        "folder_path": request.folder_path,
        "requested_asset_type": requested_asset_type,
        "asset_type": plan_payload.get("asset_type", requested_asset_type),
        "workflow": plan_payload.get("workflow", "unknown"),
        "provider": plan_payload.get("provider", normalized_provider),
        "style_target": plan_payload.get("style_target", normalized_style),
        "planning_source": planning_source,
        "fallback_used": planning_source == "fallback",
        "reference_images_found": reference_details["reference_images_found"],
        "reference_image_paths": reference_details["reference_image_paths"],
        "reference_analysis_status": reference_details["reference_analysis_status"],
        "connection_status": status,
        "generation_status": status,
        "error": _bounded_error(error) if error else "",
        "outputs": _outputs_for_log(outputs),
        "elapsed_seconds": round(elapsed_seconds, 3),
    }


def _append_generation_log_event(event: Dict[str, Any]) -> None:
    try:
        GENERATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with GENERATION_LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(event, ensure_ascii=True, default=_json_default, sort_keys=True) + "\n")
    except Exception as exc:
        print("Generation log write failed:", exc)


def _record_generation_log_event(
    event_id: str,
    request: GenerateAssetRequest,
    plan: Optional[Dict[str, Any]],
    status: str,
    elapsed_seconds: float,
    outputs: Optional[List[Dict[str, Any]]] = None,
    error: Optional[Any] = None,
) -> None:
    try:
        _append_generation_log_event(
            _generation_log_event(
                event_id,
                request,
                plan,
                status,
                elapsed_seconds,
                outputs=outputs,
                error=error,
            )
        )
    except Exception as exc:
        print("Generation log event failed:", exc)


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


def _provider_safe_dimensions(provider: str, width: int, height: int) -> Dict[str, int]:
    safe_width = _clamp_size(width, 32)
    safe_height = _clamp_size(height, 32)
    if _normalize_generation_provider(provider) == "pixellab":
        safe_width = max(PIXELLAB_MIN_IMAGE_SIZE, safe_width)
        safe_height = max(PIXELLAB_MIN_IMAGE_SIZE, safe_height)
    return {"width": safe_width, "height": safe_height}


def _block_face_source_dimensions(
    provider: str,
    final_width: int,
    face_height: int,
    style_native: bool = False,
) -> Dict[str, int]:
    target_width = _clamp_size(final_width, 32)
    target_height = _clamp_size(face_height, 32)
    if _normalize_generation_provider(provider) != "pixellab":
        return {"width": target_width, "height": target_height}

    if style_native:
        # Bitforge (style transfer) keeps pixels crisp when the source is an exact
        # integer multiple of the final face, clamped up to bitforge's 32px minimum.
        multiplier = 1
        while min(target_width, target_height) * multiplier < 32:
            multiplier += 1
        return _provider_safe_dimensions(
            provider,
            min(400, target_width * multiplier),
            min(400, target_height * multiplier),
        )

    source_width = min(400, max(PIXELLAB_BLOCK_SOURCE_MIN_WIDTH, target_width))
    source_height = int(round(float(source_width) * float(target_height) / float(max(1, target_width))))
    return _provider_safe_dimensions(
        provider,
        source_width,
        source_height,
    )


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


def _normalize_generation_mode(mode: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(mode or "").strip().lower()).strip("_")
    return normalized if normalized in SUPPORTED_GENERATION_MODES else "auto"


def _mode_uses_reference_analysis(mode: str) -> bool:
    return _normalize_generation_mode(mode) in {"auto", "reference"}


def _mode_uses_style_transfer(mode: str) -> bool:
    return _normalize_generation_mode(mode) in {"auto", "style_transfer"}


def _asset_type_spec(asset_type: str) -> Dict[str, Any]:
    return ASSET_TYPE_SPECS[_normalize_asset_type(asset_type)]


def _asset_type_constraints(asset_type: str) -> str:
    spec = _asset_type_spec(asset_type)
    return "%s asset. %s" % (spec["label"], spec["prompt_guidance"])


def _reference_response_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(BASE_DIR.parent.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _list_reference_images(directory: Path) -> List[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    return sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ),
        key=lambda path: path.name.lower(),
    )


def _reference_tokens(value: str) -> Set[str]:
    tokens = set()
    for token in re.findall(r"[a-z0-9]+", str(value or "").lower()):
        tokens.add(token)
        if len(token) > 3 and token.endswith("s"):
            tokens.add(token[:-1])
    return tokens


def _expand_reference_tokens(tokens: Set[str], asset_type: str = "") -> Set[str]:
    expanded = set(tokens)
    synonym_groups = REFERENCE_IMAGE_SYNONYM_GROUPS
    if _normalize_asset_type(asset_type) == "block_texture":
        synonym_groups = synonym_groups + BLOCK_TEXTURE_REFERENCE_SYNONYM_GROUPS
    for synonym_group in synonym_groups:
        if expanded.intersection(synonym_group):
            expanded.update(synonym_group)
    return expanded


def _reference_prompt_score(
    prompt_tokens: Set[str],
    expanded_prompt_tokens: Set[str],
    path: Path,
    asset_type: str = "",
) -> int:
    filename_tokens = _reference_tokens(path.stem)
    if not filename_tokens:
        return 0

    material_prompt_tokens = {
        token for token in prompt_tokens if token not in BLOCK_TEXTURE_GENERIC_TOKENS
    }
    exact_overlap = material_prompt_tokens.intersection(filename_tokens)
    synonym_overlap = expanded_prompt_tokens.intersection(_expand_reference_tokens(filename_tokens, asset_type))
    score = (len(exact_overlap) * 4) + (len(synonym_overlap) * 2)
    if _normalize_asset_type(asset_type) == "block_texture":
        if material_prompt_tokens.intersection(filename_tokens):
            score += 6
        if "top" in filename_tokens and "top" in prompt_tokens:
            score += 2
        if "front" in filename_tokens and "front" in prompt_tokens:
            score += 2
    return score


def _rank_reference_images(candidates: List[Path], prompt: str, asset_type: str = "") -> List[Path]:
    prompt_tokens = _reference_tokens(prompt)
    if not prompt_tokens:
        return candidates

    expanded_prompt_tokens = _expand_reference_tokens(prompt_tokens, asset_type)
    scored = [
        (_reference_prompt_score(prompt_tokens, expanded_prompt_tokens, path, asset_type), path)
        for path in candidates
    ]
    matches = sorted(
        ((score, path) for score, path in scored if score > 0),
        key=lambda item: (-item[0], item[1].name.lower()),
    )
    non_matches = [path for score, path in scored if score == 0]
    return [path for _, path in matches] + non_matches


def _select_reference_images(style_target: str, asset_type: str, prompt: str = "") -> List[Path]:
    normalized_style = _normalize_style_target(style_target)
    if normalized_style == "none":
        return []

    normalized_asset_type = _normalize_asset_type(asset_type)
    style_root = REFERENCE_IMAGE_ROOT / normalized_style
    candidates = _list_reference_images(style_root / normalized_asset_type)
    if not candidates and normalized_asset_type != "block_texture":
        candidates = _list_reference_images(style_root)
    if not candidates and normalized_asset_type == "icon":
        candidates = _list_reference_images(style_root / "icon")
    return _rank_reference_images(candidates, prompt, normalized_asset_type)[:MAX_REFERENCE_IMAGES]


def _best_matching_reference(style_target: str, asset_type: str, prompt: str) -> Optional[Path]:
    """Top reference only if it actually matches the prompt, so an unrelated image
    (e.g. a creeper for a 'zombie') never gets force-styled over the real subject."""
    paths = _select_reference_images(style_target, asset_type, prompt)
    if not paths:
        return None
    prompt_tokens = _reference_tokens(prompt)
    if not prompt_tokens:
        return None
    expanded = _expand_reference_tokens(prompt_tokens, asset_type)
    if _reference_prompt_score(prompt_tokens, expanded, paths[0], asset_type) <= 0:
        return None
    return paths[0]


def _pixellab_style_image(style_target: str, asset_type: str, prompt: str) -> Optional[Image.Image]:
    path = _best_matching_reference(style_target, asset_type, prompt)
    if path is None:
        return None
    try:
        with Image.open(path) as image:
            converted = image.convert("RGBA")
            if max(converted.size) > PIXELLAB_STYLE_IMAGE_MAX_EDGE:
                converted.thumbnail((PIXELLAB_STYLE_IMAGE_MAX_EDGE, PIXELLAB_STYLE_IMAGE_MAX_EDGE), RESAMPLING.LANCZOS)
            return converted.copy()
    except Exception as exc:
        print("Could not load style image %s: %s" % (path, exc))
        return None


def _encode_style_image(image: Image.Image, width: int, height: int) -> Dict[str, Any]:
    """PixelLab bitforge requires the style image to match the output size exactly."""
    resized = image.resize((width, height), RESAMPLING.NEAREST)
    buffer = io.BytesIO()
    resized.save(buffer, format="PNG")
    return {"type": "base64", "base64": base64.b64encode(buffer.getvalue()).decode(), "format": "png"}


def _is_neutral_gray_pixel(red: int, green: int, blue: int, alpha: int, min_value: int = 170) -> bool:
    if alpha < 128:
        return True
    return abs(red - green) <= 10 and abs(green - blue) <= 10 and red >= min_value


def _prepare_reference_image_for_vision(image: Image.Image) -> Image.Image:
    """Remove cutout/checkerboard matte backgrounds before vision analysis."""
    converted = image.convert("RGBA")
    pixels = converted.load()
    width, height = converted.size
    matte_rgb = (34, 36, 42)
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            if _is_neutral_gray_pixel(red, green, blue, alpha):
                pixels[x, y] = matte_rgb + (255,)
    return converted


def _image_data_url(path: Path) -> str:
    with Image.open(path) as image:
        converted = _prepare_reference_image_for_vision(image)
        if max(converted.size) > REFERENCE_IMAGE_MAX_EDGE:
            converted.thumbnail((REFERENCE_IMAGE_MAX_EDGE, REFERENCE_IMAGE_MAX_EDGE), RESAMPLING.LANCZOS)

        has_alpha = converted.getchannel("A").getextrema()[0] < 255
        output = io.BytesIO()
        if has_alpha:
            converted.save(output, format="PNG", optimize=True)
            mime_type = "image/png"
        else:
            converted.convert("RGB").save(output, format="JPEG", quality=85, optimize=True)
            mime_type = "image/jpeg"

    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return "data:%s;base64,%s" % (mime_type, encoded)


def _message_content_text(content: Any) -> str:
    if isinstance(content, list):
        return "".join(
            item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"
        )
    return str(content or "")


def _analyze_reference_images(reference_paths: List[Path], prompt: str, style_target: str, asset_type: str) -> str:
    if not reference_paths:
        return ""
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not configured")

    content: List[Dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Summarize reusable visual traits from these game-art reference images for a new asset prompt. "
                "Use them as style evidence only; do not ask to copy the source art verbatim. "
                "Be concise and cover resolution feel, shape language, outline, palette, shading, silhouette, "
                "material details, and what to avoid. Ignore neutral gray backgrounds, cutout mats, transparency "
                "previews, checkerboard patterns, and empty padding; never recommend drawing those in generated art.\n"
                "User prompt: %s\nStyle target: %s\nAsset type: %s"
                % (prompt, style_target, asset_type)
            ),
        }
    ]
    for path in reference_paths:
        content.append({"type": "image_url", "image_url": {"url": _image_data_url(path)}})

    response = requests.post(
        OPENAI_BASE_URL + "/chat/completions",
        headers={
            "Authorization": "Bearer " + OPENAI_API_KEY,
            "Content-Type": "application/json",
        },
        json={
            "model": OPENAI_VISION_MODEL,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a concise game art director. Extract transferable visual traits from references. "
                        "Never instruct the image model to duplicate, trace, or reproduce an existing asset. "
                        "Never mention gray backgrounds, checkerboards, cutout mats, transparency grids, or empty padding."
                    ),
                },
                {"role": "user", "content": content},
            ],
        },
        timeout=(10, 45),
    )
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("Vision model returned no choices")

    return _message_content_text(choices[0].get("message", {}).get("content", "")).strip()


def _build_reference_context(prompt: str, style_target: str, asset_type: str) -> Optional[Dict[str, Any]]:
    normalized_asset_type = _normalize_asset_type(asset_type)
    if normalized_asset_type == "block_texture":
        return None

    reference_paths = _select_reference_images(style_target, asset_type, prompt)
    if not reference_paths:
        return None

    context: Dict[str, Any] = {
        "style_target": _normalize_style_target(style_target),
        "asset_type": _normalize_asset_type(asset_type),
        "reference_images": [{"path": _reference_response_path(path)} for path in reference_paths],
        "status": "selected",
    }
    try:
        analysis = _analyze_reference_images(reference_paths, prompt, context["style_target"], context["asset_type"])
    except Exception as exc:
        print("Reference image analysis failed:", exc)
        context["status"] = "analysis_failed"
        context["failure"] = str(exc)
    else:
        if analysis:
            context["status"] = "analyzed"
            context["analysis"] = analysis

    return context


def _reference_prompt_suffix(reference_context: Optional[Dict[str, Any]]) -> str:
    if not isinstance(reference_context, dict):
        return ""
    analysis = str(reference_context.get("analysis") or "").strip()
    if not analysis:
        return ""
    return "Reference image style traits to apply without copying source art verbatim: %s" % analysis.rstrip(".")


def _description_with_reference_context(description: str, reference_context: Optional[Dict[str, Any]]) -> str:
    cleaned_description = str(description or "").strip()
    suffix = _reference_prompt_suffix(reference_context)
    if not suffix or suffix in cleaned_description:
        return cleaned_description
    if not cleaned_description:
        return suffix
    return "%s. %s" % (cleaned_description.rstrip("."), suffix)


def _enrich_description(
    description: str,
    prompt: str,
    asset_type: str,
    style_target: str,
    reference_context: Optional[Dict[str, Any]],
) -> str:
    enriched = _description_with_asset_constraints(asset_type, description)
    enriched = _description_with_icon_profile(enriched, prompt, asset_type, style_target)
    return _description_with_reference_context(enriched, reference_context)


def _ground_provider_description(description: str) -> str:
    cleaned = str(description or "").strip()
    replacements = (
        (r"\bground[\s_-]+atlas\b", "ground texture swatch"),
        (r"\bterrain[\s_-]+atlas\b", "terrain texture swatch"),
        (r"\btile[\s_-]+atlas\b", "ground texture swatch"),
        (r"\btexture[\s_-]+atlas\b", "texture swatch"),
        (r"\btileset\b", "continuous texture swatch"),
        (r"\btile[\s_-]+set\b", "continuous texture swatch"),
        (r"\btilemap\b", "continuous ground texture"),
        (r"\batlas\b", "texture swatch"),
    )
    for pattern, replacement in replacements:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _icon_reference_profile(prompt: str, style_target: str = "none") -> Optional[Dict[str, Any]]:
    prompt_tokens = _reference_tokens(prompt)
    if not prompt_tokens:
        return None

    normalized_style = _normalize_style_target(style_target)
    best_profile: Optional[Dict[str, Any]] = None
    best_score = 0
    for key, profile in ICON_REFERENCE_PROFILES.items():
        keywords = profile.get("keywords", ()) or ()
        match_all = profile.get("match_all") or ()
        if match_all and not all(token in prompt_tokens for token in match_all):
            continue
        keyword_hits = [keyword for keyword in keywords if keyword in prompt_tokens]
        if not keyword_hits:
            continue
        score = len(keyword_hits) * 2
        if match_all:
            score += 3
        if profile.get("style_affinity") == normalized_style and normalized_style != "none":
            score += 4
        elif profile.get("style_affinity") and profile["style_affinity"] != normalized_style:
            score -= 1
        if score > best_score:
            best_profile = {"key": key, **profile}
            best_score = score
    return best_profile


def _icon_profile_guidance(profile: Optional[Dict[str, Any]]) -> str:
    if not profile:
        return ""
    visual = str(profile.get("visual") or "").strip()
    if not visual:
        return ""
    title = str(profile.get("title") or profile.get("key") or "").strip()
    if title:
        return "Canonical visual reference for %s: %s." % (title, visual.rstrip("."))
    return "Canonical visual reference: %s." % visual.rstrip(".")


def _description_with_icon_profile(description: str, prompt: str, asset_type: str, style_target: str) -> str:
    if _normalize_asset_type(asset_type) != "icon":
        return description
    profile = _icon_reference_profile(prompt, style_target)
    guidance = _icon_profile_guidance(profile)
    if not guidance:
        return description
    cleaned = str(description or "").strip().rstrip(".")
    if not cleaned:
        return guidance
    return "%s. %s" % (cleaned, guidance)


def _description_with_asset_constraints(asset_type: str, description: str) -> str:
    normalized_asset_type = _normalize_asset_type(asset_type)
    cleaned_description = str(description or "").strip()
    if normalized_asset_type != "ground_atlas":
        return cleaned_description

    cleaned_description = _ground_provider_description(cleaned_description)
    lowered_description = cleaned_description.lower()
    if "single continuous top-down terrain material texture swatch" in lowered_description and "do not pre-divide" in lowered_description:
        return cleaned_description

    ground_constraints = (
        "Generate as a single continuous top-down terrain material texture swatch. "
        "Render one unbroken image first; any slicing or cropping into tiles happens after generation by code, not in the image. "
        "Do not pre-divide the image. Fill the entire image with tileable material variation. Do not create a composed forest scene, "
        "camera view, horizon, background, path, road, large tree, trunk, character, building, or single focal object. "
        "Do not draw grid lines, individual tile panels, collage layouts, 2x2 or 3x3 layouts, crosses, tile borders, seams, "
        "cell divisions, cell outlines, or visible tile separators; tile boundaries should not be drawn by the model."
    )
    if not cleaned_description:
        return ground_constraints
    return "%s. %s" % (cleaned_description.rstrip("."), ground_constraints)


def _block_material_profile(plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    descriptions = plan.get("descriptions") if isinstance(plan.get("descriptions"), dict) else {}
    search_text = " ".join(
        str(part or "")
        for part in (
            plan.get("user_prompt"),
            plan.get("description"),
            descriptions.get("primary"),
            descriptions.get("top"),
            descriptions.get("front"),
            descriptions.get("side"),
            plan.get("filename_stub"),
        )
    )
    search_tokens = _reference_tokens(search_text)
    best_profile: Optional[Dict[str, Any]] = None
    best_score = 0
    for profile in BLOCK_MATERIAL_PROFILES.values():
        match_all = profile.get("match_all") or ()
        if match_all and not all(token in search_tokens for token in match_all):
            continue
        keyword_hits = [keyword for keyword in profile["keywords"] if keyword in search_tokens]
        if not keyword_hits:
            continue
        score = len(keyword_hits)
        if match_all:
            score += 3
        if score > best_score:
            best_profile = profile
            best_score = score
    return best_profile


def _block_profile_face_material(profile: Optional[Dict[str, Any]], face: str) -> str:
    if not profile:
        return ""
    if _block_profile_is_uniform(profile):
        shared_material = str(profile.get("material") or profile.get(face) or "").strip()
        if shared_material:
            return shared_material
    return str(profile.get(face) or "").strip()


def _block_face_user_prompt(plan: Dict[str, Any]) -> str:
    return str(plan.get("user_prompt") or plan.get("description") or "").strip()


_GENERIC_FACE_MATCH_CLAUSE = (
    "Cross-face consistency: every face of this block must use the exact same material palette and pixel-noise "
    "pattern; no icons, items, loot sprites, grass, or unrelated materials on any face. "
)


def _face_table_lookup(table: Dict[str, Any], face: str) -> str:
    """Look up a per-face string; side falls back to front, anything else to top."""
    if not isinstance(table, dict):
        return ""
    if face in table:
        return str(table[face] or "")
    if face == "side":
        return str(table.get("front") or "")
    return str(table.get("top") or "")


def _block_face_match_clause(profile: Optional[Dict[str, Any]], face: str) -> str:
    clause = _face_table_lookup((profile or {}).get("face_match", {}), face)
    return clause or _GENERIC_FACE_MATCH_CLAUSE


_BLOCK_ICON_TRIGGER_TOKENS = frozenset(
    {"diamond", "emerald", "lapis", "gem", "jewel", "ruby", "sapphire", "amethyst", "quartz", "mineral"}
)


def _block_icon_guard_clause(user_prompt: str, profile: Optional[Dict[str, Any]]) -> str:
    tokens = _reference_tokens(user_prompt)
    needs_guard = bool(profile and profile.get("icon_guard")) or bool(tokens & _BLOCK_ICON_TRIGGER_TOKENS)
    if needs_guard:
        return (
            "Do NOT draw a gem item icon, faceted jewel, loot sprite, inventory item, sword, tool, UI icon, "
            "or cut-diamond illustration. Draw only flat square block material texture. "
        )
    return ""


def _block_face_label(face: str) -> str:
    if face == "top":
        return "top horizontal face"
    if face == "side":
        return "side vertical face"
    return "front vertical face"


_GENERIC_FACE_RULES = {
    "top": (
        "Read as one flat pixel-art material tile for the top face only. "
        "Follow the user material request literally and keep the same material family on every face. "
        "Do not draw brick grids, brick walls, masonry blocks, mortar lines, cobblestone rectangles, "
        "or tile seams unless the user explicitly asked for brick or masonry. "
        "No grass, leaves, dirt, roots, scene, inventory icon, cube preview, or unrelated biome texture. "
    ),
    "front": (
        "Read as one flat pixel-art material tile for this side/front face only. "
        "Follow the user material request literally and keep the same material family as the top face. "
        "Do not draw brick grids, brick walls, masonry blocks, mortar lines, cobblestone rectangles, "
        "or tile seams unless the user explicitly asked for brick or masonry. "
        "No grass, leaves, dirt, roots, scene, inventory icon, cube preview, or unrelated biome texture. "
    ),
}


def _block_face_rules(profile: Optional[Dict[str, Any]], face: str) -> Tuple[str, str]:
    rules = _face_table_lookup((profile or {}).get("face_rules", {}), face)
    if not rules:
        rules = _GENERIC_FACE_RULES["top" if face == "top" else "front"]
    return _block_face_label(face), rules


def _strict_block_face_description(plan: Dict[str, Any], face: str, source_width: int, source_height: int) -> str:
    descriptions = plan.get("descriptions") if isinstance(plan.get("descriptions"), dict) else {}
    user_prompt = _block_face_user_prompt(plan)
    planned_face_description = str(descriptions.get(face) or "").strip()
    profile = _block_material_profile(plan)
    profile_key = _block_profile_key(profile)
    profile_face_description = _block_profile_face_material(profile, face)
    profile_title = str(profile.get("title", "")).strip() if profile else ""
    material_parts: List[str] = []
    if profile_face_description:
        material_parts.append("Material details: %s" % profile_face_description.rstrip("."))
        if profile_title:
            material_parts.append("Block profile: %s" % profile_title)
    elif planned_face_description:
        cleaned_face_description = planned_face_description
        if "Reference image style traits to apply without copying source art verbatim:" in cleaned_face_description:
            cleaned_face_description = cleaned_face_description.split(
                "Reference image style traits to apply without copying source art verbatim:"
            )[0].strip(" .")
        material_parts.append("Face material details: %s" % cleaned_face_description.rstrip("."))
    if user_prompt:
        material_parts.append("Original user material request: %s" % user_prompt.rstrip("."))
    if not material_parts:
        material_parts.append("Material idea: game block material texture")

    style_context = plan.get("style_context") if isinstance(plan.get("style_context"), dict) else {}
    style_title = str(style_context.get("title") or style_context.get("key") or "").strip()
    has_style_target = bool(style_context.get("target_style_selected", style_title and style_title.lower() not in {"none", "no style target"}))
    style_part = " Style target: %s." % style_title if has_style_target and style_title else ""
    match_part = _block_face_match_clause(profile, face)
    face_label, face_rules = _block_face_rules(profile, face)
    icon_guard_part = _block_icon_guard_clause(user_prompt, profile)

    return (
        "Create a %sx%s seamless pixel art material texture tile. "
        "This is NOT an icon, NOT a cube drawing, and NOT a perspective object. "
        "Draw only the %s material for a game block. "
        "%s.%s "
        "%s%s%s"
        "Fill the entire canvas edge-to-edge with opaque material texture. "
        "Every pixel must be filled with solid material color; no transparency, no empty areas, no checkerboard, "
        "no gray cutout background, and no matte padding. "
        "No object silhouette, no isometric cube, no floor, no horizon, no labels, no border. "
        "Crisp pixel art, hard edges, limited palette, tileable material texture."
    ) % (
        source_width,
        source_height,
        face_label,
        ". ".join(material_parts),
        style_part,
        face_rules,
        match_part,
        icon_guard_part,
    )


def _provider_constraints(provider: str) -> str:
    normalized_provider = _normalize_generation_provider(provider)
    if normalized_provider == "pixellab":
        return "PixelLab provider. Prefer native-looking pixel art, crisp silhouettes, and no blurry edges."
    if normalized_provider == "openai_image":
        return (
            "GPT Image provider. It can handle richer reference scenes, larger compositions, and structured asset outputs "
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

    text = _message_content_text(choices[0].get("message", {}).get("content", ""))

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
    if any(token in lowered for token in (
        "spritesheet", "sprite sheet", "walk cycle", "run cycle", "animation",
        "animation frame", "animation sheet", "animated",
    )):
        return "spritesheet"
    if any(token in lowered for token in ("two-face", "two face", "top and front", "top/front", "block texture", "voxel block")):
        return "block_texture"
    if re.search(r"\bblock\b", lowered):
        return "block_texture"
    if any(token in lowered for token in ("ground atlas", "terrain atlas", "tile atlas", "atlas", "tilemap", "terrain", "ground tile", "floor tile")):
        return "ground_atlas"
    # Bare "ground"/"floor" read as tileable terrain (word boundary skips "background", "underground").
    if re.search(r"\b(ground|floor)\b", lowered):
        return "ground_atlas"
    if any(token in lowered for token in (
        "house", "building", "castle", "tower", "shop", "tavern", "hut", "cabin",
        "village", "town", "structure", "fortress", "ruin", "ruins",
        "reference scene", "concept scene", "scene concept", "background", "environment concept",
    )):
        return "reference_scene"
    return "icon"


# Words that NAME the output type. When present the user is making a deliberate
# asset_type request, so it wins over the LLM's semantic guess. Content words
# (house, city, goblin) stay LLM-overridable; only type-naming words lock here.
_EXPLICIT_ASSET_TYPE_MARKERS = (
    ("spritesheet", ("spritesheet", "sprite sheet")),
    ("ground_atlas", ("atlas", "tilemap", "tileset")),
    ("block_texture", ("block texture", "voxel block")),
)


def _explicit_asset_type(prompt: str) -> str:
    """Return a locked asset_type when the prompt explicitly names one, else ''."""
    lowered = str(prompt or "").lower()
    if re.search(r"\bblock\b", lowered):
        return "block_texture"
    for asset_type, markers in _EXPLICIT_ASSET_TYPE_MARKERS:
        if any(marker in lowered for marker in markers):
            return asset_type
    return ""


def _default_workflow_for_asset_type(asset_type: str, style_target: str = "none") -> str:
    if asset_type == "block_texture":
        return str(_block_texture_layout(style_target).get("workflow") or "block_texture_two_face")
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


def _default_postprocess_config(prompt: str, asset_type: str, style_target: str = "none") -> Dict[str, Any]:
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
        layout = _block_texture_layout(style_target)
        return {
            "compose_mode": layout.get("compose_mode", "vertical_strip"),
            "final_width": layout["final_width"],
            "top_height": layout["top_height"],
            "front_height": layout["front_height"],
            "side_height": layout.get("side_height", 0),
            "output_width": layout.get("output_width", layout["final_width"]),
            "output_height": layout.get(
                "output_height",
                layout["top_height"] + layout["front_height"] + int(layout.get("side_height") or 0),
            ),
        }

    return {}


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _workflow_expected_outputs(asset_type: str, postprocess: Dict[str, Any], workflow: str = "") -> List[str]:
    if asset_type == "block_texture":
        outputs = ["block_texture", "top_face_source", "front_face_source"]
        if workflow == "block_texture_three_face" or int(postprocess.get("side_height") or 0) > 0:
            outputs.append("side_face_source")
        return outputs
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
        config["side_height"] = _clamp_size(config.get("side_height"), fallback.get("side_height", 0))
        config["output_width"] = _clamp_size(config.get("output_width"), fallback.get("output_width", config["final_width"]))
        config["output_height"] = _clamp_size(config.get("output_height"), fallback.get("output_height", config["front_height"]))
        config["compose_mode"] = str(config.get("compose_mode") or fallback.get("compose_mode") or "vertical_strip")
    return config


def _resolve_reference_context(
    prompt: str,
    style_target: str,
    asset_type: str,
    cached: Optional[Dict[str, Any]] = None,
    cached_asset_type: str = "",
) -> Optional[Dict[str, Any]]:
    """Reference context for asset_type, reusing the cache only when the type is unchanged.

    Rebuilding when the asset_type changed is what stops a context built for one
    asset_type (e.g. an icon) from leaking into another (e.g. a block texture).
    """
    if cached is not None and _normalize_asset_type(asset_type) == _normalize_asset_type(cached_asset_type):
        return cached
    return _build_reference_context(prompt, style_target, asset_type)


def _attach_reference_and_finalize(
    plan: Dict[str, Any],
    reference_context: Optional[Dict[str, Any]],
    style_target: str,
    workflow_mode: str,
) -> Dict[str, Any]:
    """Shared pipeline tail: attach reference data, then apply block-texture layout."""
    if reference_context:
        plan["reference_context"] = reference_context
        plan["reference_images"] = reference_context.get("reference_images", [])
    return _finalize_block_texture_plan(plan, style_target, workflow_mode)


def _finalize_block_texture_plan(
    plan: Dict[str, Any],
    style_target: str,
    workflow_mode: str = "auto",
) -> Dict[str, Any]:
    if str(plan.get("asset_type") or "") != "block_texture":
        return plan

    layout = _block_texture_layout(style_target)
    finalized = dict(plan)
    postprocess = dict(finalized.get("postprocess") or {})
    postprocess = _coerce_postprocess_config(
        "block_texture",
        postprocess,
        _default_postprocess_config(
            str(finalized.get("user_prompt") or finalized.get("description") or ""),
            "block_texture",
            style_target,
        ),
    )
    if _normalize_workflow_mode(workflow_mode) == "auto":
        finalized["workflow"] = str(layout.get("workflow") or finalized.get("workflow") or "block_texture_two_face")
    finalized["postprocess"] = postprocess
    finalized["outputs_expected"] = _workflow_expected_outputs(
        "block_texture",
        postprocess,
        str(finalized.get("workflow") or ""),
    )
    return finalized


def _normalize_workflow(asset_type: str, workflow: str, style_target: str = "none") -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(workflow or "").strip().lower()).strip("_")
    allowed = {
        "single_image",
        "ground_atlas",
        "spritesheet",
        "block_texture_two_face",
        "block_texture_three_face",
        "reference_scene",
    }
    if normalized in allowed:
        return normalized
    return _default_workflow_for_asset_type(asset_type, style_target)


def _fallback_generation_plan(
    prompt: str,
    asset_type: str,
    workflow_mode: str,
    style_target: str,
    provider: str,
    note: str,
    reference_context: Optional[Dict[str, Any]] = None,
    generation_mode: str = "auto",
) -> Dict[str, Any]:
    normalized_asset_type = _infer_asset_type_from_prompt(prompt, asset_type)
    normalized_style = _normalize_style_target(style_target)
    normalized_provider = _normalize_generation_provider(provider)
    normalized_mode = _normalize_generation_mode(generation_mode)
    style_context = _style_context(normalized_style)
    if reference_context is None and _mode_uses_reference_analysis(normalized_mode):
        reference_context = _build_reference_context(prompt, normalized_style, normalized_asset_type)
    default_dimensions = _default_generation_dimensions(normalized_asset_type)
    fallback_dimensions = _parse_prompt_dimensions(
        prompt,
        default_dimensions["width"],
        default_dimensions["height"],
    )
    asset_spec = _asset_type_spec(normalized_asset_type)
    workflow = _normalize_workflow(
        normalized_asset_type,
        workflow_mode if _normalize_workflow_mode(workflow_mode) != "auto" else _default_workflow_for_asset_type(normalized_asset_type, normalized_style),
        normalized_style,
    )
    postprocess = _default_postprocess_config(prompt, normalized_asset_type, normalized_style)
    description = _enrich_description(prompt, prompt, normalized_asset_type, normalized_style, reference_context)
    notes = [note]
    if isinstance(reference_context, dict) and reference_context.get("failure"):
        notes.append("Reference image analysis unavailable: %s" % reference_context["failure"])

    plan = {
        "user_prompt": prompt,
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
        "generation_mode": normalized_mode,
        "postprocess": postprocess,
        "outputs_expected": _workflow_expected_outputs(normalized_asset_type, postprocess, workflow),
        "notes": notes,
        "planning_source": "fallback",
        "planning_note": note,
    }
    return _attach_reference_and_finalize(plan, reference_context, normalized_style, workflow_mode)


def _plan_generation_workflow(request: GenerateAssetRequest) -> Dict[str, Any]:
    requested_asset_type = _normalize_asset_type(request.asset_type, allow_auto=True)
    normalized_style = _normalize_style_target(request.style_target)
    normalized_provider = _normalize_generation_provider(request.provider)
    workflow_mode = _normalize_workflow_mode(request.workflow_mode)
    generation_mode = _normalize_generation_mode(request.generation_mode)
    fallback = _fallback_generation_plan(
        request.prompt,
        requested_asset_type,
        workflow_mode,
        normalized_style,
        normalized_provider,
        "Used fallback workflow plan before LLM planning completed.",
        generation_mode=generation_mode,
    )

    failure_reason = ""
    try:
        plan = _chat_json(
            (
                "You plan a single pixel-art game asset for image generation. "
                "Pick asset_type from {icon, block_texture, ground_atlas, spritesheet, reference_scene}:\n"
                "- block_texture: a single block's face material (input has 'block' or a clear material name).\n"
                "- reference_scene: any building/structure/environment (house, castle, tower, ruins, etc.).\n"
                "- ground_atlas: continuous tileable terrain swatch (forest ground, dungeon floor, grass field, etc.).\n"
                "- spritesheet: animation frames or a grid of cells (walk/idle/attack animation, explosion frames).\n"
                "- icon: single inventory/UI item, prop, or static character sprite (default).\n"
                "Use the corresponding workflow (single_image for icon, the block_texture_* for blocks, and so on). "
                "Honour style_context when style_target is not 'none'; otherwise stay style-neutral. "
                "If reference_context or icon_reference_profile is present, use them as anchors — don't trace them. "
                "Return JSON with asset_type, workflow, provider, style_target, description, descriptions, width, height, "
                "filename_stub, no_background, postprocess, outputs_expected, notes. Width/height in [16, 400]. "
                "Fallback plan is included; copy what's reasonable and override what's wrong."
            ),
            {
                "user_prompt": request.prompt,
                "requested_asset_type": requested_asset_type,
                "workflow_mode": workflow_mode,
                "supported_asset_types": sorted(SUPPORTED_ASSET_TYPES),
                "asset_type_constraints": {key: _asset_type_constraints(key) for key in sorted(SUPPORTED_ASSET_TYPES)},
                "target_game_style": normalized_style,
                "style_context": fallback["style_context"],
                "reference_context": fallback.get("reference_context"),
                "icon_reference_profile": _icon_reference_profile(request.prompt, normalized_style),
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
        fallback_notes = [fallback["planning_note"]]
        reference_context = fallback.get("reference_context") if isinstance(fallback.get("reference_context"), dict) else None
        if reference_context and reference_context.get("failure"):
            fallback_notes.append("Reference image analysis unavailable: %s" % reference_context["failure"])
        fallback["notes"] = fallback_notes
        return _finalize_block_texture_plan(fallback, normalized_style, workflow_mode)

    if requested_asset_type != "auto":
        planned_asset_type = _normalize_asset_type(requested_asset_type)
    else:
        # An explicit type-naming keyword in the prompt overrides the LLM's guess.
        planned_asset_type = _normalize_asset_type(_explicit_asset_type(request.prompt) or plan.get("asset_type"))
    default_dimensions = _default_generation_dimensions(planned_asset_type)
    fallback_dimensions = _parse_prompt_dimensions(request.prompt, default_dimensions["width"], default_dimensions["height"])
    asset_spec = _asset_type_spec(planned_asset_type)
    workflow = _normalize_workflow(planned_asset_type, plan.get("workflow") or fallback["workflow"], normalized_style)
    fallback_postprocess = _default_postprocess_config(request.prompt, planned_asset_type, normalized_style)
    postprocess = _coerce_postprocess_config(planned_asset_type, plan.get("postprocess"), fallback_postprocess)
    if planned_asset_type == "block_texture" and workflow_mode == "auto":
        layout = _block_texture_layout(normalized_style)
        workflow = str(layout.get("workflow") or workflow)
        postprocess = _coerce_postprocess_config(planned_asset_type, postprocess, fallback_postprocess)
    descriptions = plan.get("descriptions") if isinstance(plan.get("descriptions"), dict) else {}
    raw_description = str(plan.get("description") or descriptions.get("primary") or fallback["description"]).strip()
    if _mode_uses_reference_analysis(generation_mode):
        reference_context = _resolve_reference_context(
            request.prompt,
            normalized_style,
            planned_asset_type,
            fallback.get("reference_context") if isinstance(fallback.get("reference_context"), dict) else None,
            _normalize_asset_type(fallback.get("asset_type") or "icon"),
        )
    else:
        reference_context = None
    primary_description = _enrich_description(raw_description, request.prompt, planned_asset_type, normalized_style, reference_context)
    notes = plan.get("notes") if isinstance(plan.get("notes"), list) else ["Used LLM-generated workflow plan."]
    if reference_context and reference_context.get("failure"):
        notes = list(notes) + ["Reference image analysis unavailable: %s" % reference_context["failure"]]

    resolved_plan = {
        "user_prompt": request.prompt,
        "description": primary_description,
        "descriptions": {
            "primary": primary_description,
            "top": str(descriptions.get("top") or "%s, top face only, seamless tile material" % primary_description).strip(),
            "front": str(descriptions.get("front") or "%s, front face only, vertical side material" % primary_description).strip(),
            "side": str(descriptions.get("side") or "%s, side face only, vertical side material" % primary_description).strip(),
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
        "generation_mode": generation_mode,
        "postprocess": postprocess,
        "outputs_expected": plan.get("outputs_expected") if isinstance(plan.get("outputs_expected"), list) else _workflow_expected_outputs(planned_asset_type, postprocess, workflow),
        "notes": notes,
        "planning_source": "llm",
        "planning_note": "Used LLM-generated plan.",
    }
    return _attach_reference_and_finalize(resolved_plan, reference_context, normalized_style, workflow_mode)


def _provider_rejection_fallback_plan(
    request: GenerateAssetRequest,
    planned_asset_type: str,
    provider: str,
    reference_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return _fallback_generation_plan(
        request.prompt,
        planned_asset_type,
        request.workflow_mode,
        request.style_target,
        provider,
        "Used fallback generation plan after provider rejected the planned payload.",
        reference_context=reference_context,
        generation_mode=request.generation_mode,
    )


def _pixellab_error_detail(response: requests.Response, width: int, height: int, attempt: int) -> str:
    status_code = response.status_code
    body = _response_text_excerpt(response)
    if 500 <= status_code <= 599:
        detail = (
            "PixelLab API returned an internal server error (%s) after %s attempt%s for %sx%s. "
            "This is a provider-side generation failure, not prompt planning or dimension validation. "
            "Retry the request, or choose GPT Image / openai_image provider."
        ) % (
            status_code,
            attempt,
            "" if attempt == 1 else "s",
            width,
            height,
        )
    else:
        detail = "PixelLab API rejected image generation (%s) for %sx%s" % (status_code, width, height)
    if body:
        detail = "%s: %s" % (detail, body)
    return detail


def _generate_with_pixellab(
    description: str,
    width: int,
    height: int,
    no_background: bool,
    style_image: Optional[Image.Image] = None,
) -> bytes:
    if not PIXELLAB_API_KEY:
        raise ValueError("PIXELLAB_API_KEY is not configured")

    if style_image is not None:
        endpoint = "generate-image-bitforge"
        body = {
            "description": description,
            "image_size": {"width": width, "height": height},
            "no_background": no_background,
            "style_image": _encode_style_image(style_image, width, height),
            "style_strength": PIXELLAB_STYLE_STRENGTH,
        }
    else:
        endpoint = "generate-image-pixflux"
        body = {
            "description": description,
            "image_size": {"width": width, "height": height},
            "no_background": no_background,
        }

    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        response = requests.post(
            "https://api.pixellab.ai/v1/" + endpoint,
            headers={"Authorization": "Bearer " + PIXELLAB_API_KEY},
            json=body,
            timeout=(10, 180),
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            if response.status_code >= 500 and response.status_code <= 599 and attempt < max_attempts:
                print(
                    "PixelLab returned %s for %sx%s; retrying once."
                    % (response.status_code, width, height)
                )
                continue
            detail = _pixellab_error_detail(response, width, height, attempt)
            raise requests.HTTPError(detail, response=response, request=response.request) from exc
        break

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
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        status_code = response.status_code if response is not None else "unknown"
        body = _response_text_excerpt(response)
        detail = "OpenAI image API rejected image generation (%s)" % status_code
        if body:
            detail = "%s: %s" % (detail, body)
        if status_code in {520, 502, 503, 504}:
            detail = "%s. This is usually a temporary provider/proxy outage; retry or switch to PixelLab." % detail
        raise requests.HTTPError(detail, response=response, request=response.request) from exc

    payload = response.json()
    data = payload.get("data") or []
    if not data or not isinstance(data[0], dict):
        raise ValueError("OpenAI image API returned no image data")

    return _resize_png_bytes(_decode_openai_image_payload(data[0]), width, height)


def _generate_with_provider(
    provider: str,
    description: str,
    width: int,
    height: int,
    no_background: bool,
    style_image: Optional[Image.Image] = None,
) -> bytes:
    normalized_provider = _normalize_generation_provider(provider)
    if normalized_provider == "pixellab":
        safe_dimensions = _provider_safe_dimensions(normalized_provider, width, height)
        image_bytes = _generate_with_pixellab(
            description=description,
            width=safe_dimensions["width"],
            height=safe_dimensions["height"],
            no_background=no_background,
            style_image=style_image,
        )
        if (safe_dimensions["width"], safe_dimensions["height"]) != (width, height):
            return _resize_png_bytes(image_bytes, width, height)
        return image_bytes
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


def _snap_pixel_palette(image_bytes: bytes, colors: int) -> bytes:
    """Collapse soft AI in-between colors to a tight palette so the texture reads
    as crisp pixel art instead of a muddy gradient."""
    if colors <= 0:
        return image_bytes
    image = _png_image_from_bytes(image_bytes)
    alpha = image.getchannel("A")
    quantized = image.convert("RGB").quantize(colors=colors, method=Image.MEDIANCUT, dither=Image.NONE)
    result = quantized.convert("RGBA")
    result.putalpha(alpha)
    buffer = io.BytesIO()
    result.save(buffer, format="PNG")
    return buffer.getvalue()


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


def _texture_flatten_fallback_rgb(image: Image.Image, default: Tuple[int, int, int] = (128, 128, 128)) -> Tuple[int, int, int]:
    rgba = image.convert("RGBA")
    opaque_pixels = [rgba.getpixel((x, y))[:3] for y in range(rgba.height) for x in range(rgba.width) if rgba.getpixel((x, y))[3] > 160]
    if not opaque_pixels:
        return default
    opaque_pixels.sort(key=lambda rgb: (rgb[0], rgb[1], rgb[2]))
    return opaque_pixels[len(opaque_pixels) // 2]


def _flatten_opaque_texture(image: Image.Image, fallback_rgb: Tuple[int, int, int]) -> Image.Image:
    background = Image.new("RGBA", image.size, fallback_rgb + (255,))
    foreground = image.convert("RGBA")
    return Image.alpha_composite(background, foreground)


def _warp_top_face_isometric(top_face: Image.Image, width: int, height: int) -> Image.Image:
    source = top_face.resize((width, width), RESAMPLING.NEAREST)
    inset = max(2, width // 4)
    quad = (0, height, width, height, width - inset, 0, inset, 0)
    transform = getattr(Image, "Transform", Image)
    quad_mode = getattr(transform, "QUAD", getattr(Image, "QUAD", 0))
    return source.transform((width, height), quad_mode, quad, RESAMPLING.NEAREST)


def _paste_textured_parallelogram(
    target: Image.Image,
    source: Image.Image,
    origin: Tuple[int, int],
    x_axis: Tuple[int, int],
    y_axis: Tuple[int, int],
    shade: float = 1.0,
) -> None:
    source_rgba = source.convert("RGBA")
    det = x_axis[0] * y_axis[1] - x_axis[1] * y_axis[0]
    if det == 0:
        return
    points = (
        origin,
        (origin[0] + x_axis[0], origin[1] + x_axis[1]),
        (origin[0] + x_axis[0] + y_axis[0], origin[1] + x_axis[1] + y_axis[1]),
        (origin[0] + y_axis[0], origin[1] + y_axis[1]),
    )
    min_x = max(0, min(point[0] for point in points))
    max_x = min(target.width - 1, max(point[0] for point in points))
    min_y = max(0, min(point[1] for point in points))
    max_y = min(target.height - 1, max(point[1] for point in points))
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            px = x + 0.5 - origin[0]
            py = y + 0.5 - origin[1]
            u = (px * y_axis[1] - py * y_axis[0]) / det
            v = (x_axis[0] * py - x_axis[1] * px) / det
            if u < 0.0 or u > 1.0 or v < 0.0 or v > 1.0:
                continue
            source_x = min(source_rgba.width - 1, max(0, int(u * source_rgba.width)))
            source_y = min(source_rgba.height - 1, max(0, int(v * source_rgba.height)))
            red, green, blue, alpha = source_rgba.getpixel((source_x, source_y))
            if alpha == 0:
                continue
            if shade != 1.0:
                red = max(0, min(255, int(red * shade)))
                green = max(0, min(255, int(green * shade)))
                blue = max(0, min(255, int(blue * shade)))
            target.putpixel((x, y), (red, green, blue, alpha))


def _compose_isometric_three_face_block(
    top_bytes: bytes,
    front_bytes: bytes,
    side_bytes: bytes,
    config: Dict[str, Any],
) -> Image.Image:
    face_size = int(config.get("final_width") or 16)
    output_width = int(config.get("output_width") or face_size * 2)
    output_height = int(config.get("output_height") or face_size * 2)
    top_source = _png_image_from_bytes(top_bytes).resize((face_size, face_size), RESAMPLING.NEAREST)
    front_source = _png_image_from_bytes(front_bytes).resize((face_size, face_size), RESAMPLING.NEAREST)
    side_source = _png_image_from_bytes(side_bytes).resize((face_size, face_size), RESAMPLING.NEAREST)
    top_face = _flatten_opaque_texture(top_source, _texture_flatten_fallback_rgb(top_source))
    front_face = _flatten_opaque_texture(front_source, _texture_flatten_fallback_rgb(front_source))
    side_face = _flatten_opaque_texture(side_source, _texture_flatten_fallback_rgb(side_source))

    composed = Image.new("RGBA", (output_width, output_height), (0, 0, 0, 0))
    half_width = max(1, output_width // 2)
    top_y = max(0, (output_height - face_size * 2) // 2)
    mid_y = top_y + max(1, face_size // 2)
    center_x = output_width // 2
    body_height = max(1, output_height - mid_y)

    _paste_textured_parallelogram(
        composed,
        side_face,
        (0, mid_y),
        (center_x, face_size // 2),
        (0, body_height - face_size // 2),
        0.72,
    )
    _paste_textured_parallelogram(
        composed,
        front_face,
        (center_x, mid_y + face_size // 2),
        (half_width, -(face_size // 2)),
        (0, body_height - face_size // 2),
        0.86,
    )
    _paste_textured_parallelogram(
        composed,
        top_face,
        (center_x, top_y),
        (half_width, face_size // 2),
        (-center_x, face_size // 2),
        1.08,
    )
    return composed


def _compose_three_face_block(
    top_bytes: bytes,
    front_bytes: bytes,
    side_bytes: bytes,
    config: Dict[str, Any],
) -> Image.Image:
    final_width = int(config.get("final_width") or 16)
    top_height = int(config.get("top_height") or 16)
    front_height = int(config.get("front_height") or 16)
    side_height = int(config.get("side_height") or 16)
    top_face = _flatten_opaque_texture(
        _png_image_from_bytes(top_bytes).resize((final_width, top_height), RESAMPLING.NEAREST),
        (120, 120, 120),
    )
    front_face = _flatten_opaque_texture(
        _png_image_from_bytes(front_bytes).resize((final_width, front_height), RESAMPLING.NEAREST),
        (110, 110, 110),
    )
    side_face = _flatten_opaque_texture(
        _png_image_from_bytes(side_bytes).resize((final_width, side_height), RESAMPLING.NEAREST),
        (110, 110, 110),
    )
    composed = Image.new("RGBA", (final_width, top_height + front_height + side_height), (0, 0, 0, 255))
    composed.paste(top_face, (0, 0))
    composed.paste(front_face, (0, top_height))
    composed.paste(side_face, (0, top_height + front_height))
    return composed


# Style transfer replicates a material look, which suits textures but overwhelms
# the subject of an icon/sprite (a zombie becomes a green block). Limit it to
# material asset types; subjects keep using plain text generation.
_STYLE_IMAGE_ASSET_TYPES = {"block_texture", "ground_atlas"}


def _plan_style_image(plan: Dict[str, Any]) -> Optional[Image.Image]:
    mode = _normalize_generation_mode(plan.get("generation_mode"))
    if not _mode_uses_style_transfer(mode):
        return None
    asset_type = _normalize_asset_type(plan.get("asset_type") or "icon")
    # Auto stays conservative (material types only); an explicit style_transfer
    # request applies it to every type so the approach can be compared head to head.
    if mode == "auto" and asset_type not in _STYLE_IMAGE_ASSET_TYPES:
        return None
    return _pixellab_style_image(
        str(plan.get("style_target") or "none"),
        asset_type,
        str(plan.get("user_prompt") or plan.get("description") or ""),
    )


def _generate_block_texture_faces(
    plan: Dict[str, Any],
    provider: str,
    face_config: Dict[str, Any],
    faces: List[str],
    style_image: Optional[Image.Image] = None,
) -> Dict[str, bytes]:
    generated: Dict[str, bytes] = {}
    style_native = style_image is not None
    if not _block_requires_multi_face_generation(plan) and faces:
        lead_face = faces[0]
        source_dimensions = _block_face_source_dimensions(
            provider,
            int(face_config["final_width"]),
            int(face_config.get("%s_height" % lead_face) or face_config.get("front_height") or 16),
            style_native,
        )
        description = _strict_block_face_description(
            plan,
            lead_face,
            source_dimensions["width"],
            source_dimensions["height"],
        )
        material_bytes = _generate_with_provider(
            provider=provider,
            description=description,
            width=source_dimensions["width"],
            height=source_dimensions["height"],
            no_background=False,
            style_image=style_image,
        )
        if style_native:
            material_bytes = _snap_pixel_palette(material_bytes, STYLE_SNAP_COLORS)
        for face in faces:
            generated[face] = material_bytes
        return generated

    for face in faces:
        face_height = int(face_config.get("%s_height" % face) or face_config.get("front_height") or 16)
        source_dimensions = _block_face_source_dimensions(provider, int(face_config["final_width"]), face_height, style_native)
        generated[face] = _generate_with_provider(
            provider=provider,
            description=_strict_block_face_description(
                plan,
                face,
                source_dimensions["width"],
                source_dimensions["height"],
            ),
            width=source_dimensions["width"],
            height=source_dimensions["height"],
            no_background=False,
            style_image=style_image,
        )
        if style_native:
            generated[face] = _snap_pixel_palette(generated[face], STYLE_SNAP_COLORS)
    return generated


def _save_block_texture_outputs(
    composed: Image.Image,
    face_config: Dict[str, Any],
    target_folder: Path,
    filename_stub: str,
    faces: List[str],
    face_bytes: Optional[Dict[str, bytes]] = None,
) -> List[Dict[str, Any]]:
    outputs: List[Dict[str, Any]] = []
    final_width = int(face_config["final_width"])
    face_paths: Dict[str, Path] = {}
    compose_mode = str(face_config.get("compose_mode") or "vertical_strip")

    if compose_mode == "isometric" and isinstance(face_bytes, dict):
        for face in faces:
            raw_bytes = face_bytes.get(face)
            if not raw_bytes:
                continue
            face_path = target_folder / ("%s_%s.png" % (filename_stub, face))
            _save_generated_png(raw_bytes, face_path)
            face_paths[face] = face_path
    else:
        y_offset = 0
        for face in faces:
            face_height = int(face_config.get("%s_height" % face) or 0)
            face_image = composed.crop((0, y_offset, final_width, y_offset + face_height))
            face_path = target_folder / ("%s_%s.png" % (filename_stub, face))
            _save_png(face_image, face_path)
            face_paths[face] = face_path
            y_offset += face_height

    composed_path = target_folder / ("%s.png" % filename_stub)
    _save_png(composed, composed_path)
    _append_output(outputs, composed_path, "block_texture")
    role_map = {"top": "top_face_source", "front": "front_face_source", "side": "side_face_source"}
    for face in faces:
        _append_output(outputs, face_paths[face], role_map.get(face, "%s_face_source" % face))
    return outputs


def _compose_two_face_block(top_bytes: bytes, front_bytes: bytes, config: Dict[str, Any]) -> Image.Image:
    final_width = int(config.get("final_width") or 32)
    top_height = int(config.get("top_height") or 16)
    front_height = int(config.get("front_height") or 32)
    top_source = _png_image_from_bytes(top_bytes).resize((final_width, top_height), RESAMPLING.NEAREST)
    front_source = _png_image_from_bytes(front_bytes).resize((final_width, front_height), RESAMPLING.NEAREST)
    top_face = _flatten_opaque_texture(top_source, _texture_flatten_fallback_rgb(top_source))
    front_face = _flatten_opaque_texture(front_source, _texture_flatten_fallback_rgb(front_source))
    composed = Image.new("RGBA", (final_width, top_height + front_height), (0, 0, 0, 255))
    composed.paste(top_face, (0, 0))
    composed.paste(front_face, (0, top_height))
    return composed


def _execute_generation_workflow(plan: Dict[str, Any], target_folder: Path) -> List[Dict[str, Any]]:
    workflow = _normalize_workflow(plan["asset_type"], plan.get("workflow"), str(plan.get("style_target") or "none"))
    provider = _normalize_generation_provider(plan.get("provider"))
    filename_stub = _safe_stem(str(plan.get("filename_stub") or "generated_asset"), "generated_asset")
    postprocess = plan.get("postprocess") if isinstance(plan.get("postprocess"), dict) else {}
    style_image = _plan_style_image(plan) if provider == "pixellab" else None
    if style_image is not None:
        print("Using style reference image for PixelLab generation")
    outputs: List[Dict[str, Any]] = []

    if workflow in {"block_texture_two_face", "block_texture_three_face"}:
        style_target = str(plan.get("style_target") or "none")
        layout = _block_texture_layout(style_target)
        final_width = _clamp_size(postprocess.get("final_width"), layout["final_width"])
        top_height = _clamp_size(postprocess.get("top_height"), layout["top_height"])
        front_height = _clamp_size(postprocess.get("front_height"), layout["front_height"])
        side_height = _clamp_size(postprocess.get("side_height"), layout.get("side_height", 0))
        face_config = {
            "compose_mode": str(postprocess.get("compose_mode") or layout.get("compose_mode") or "vertical_strip"),
            "final_width": final_width,
            "top_height": top_height,
            "front_height": front_height,
            "side_height": side_height,
            "output_width": _clamp_size(postprocess.get("output_width"), layout.get("output_width", final_width * 2)),
            "output_height": _clamp_size(postprocess.get("output_height"), layout.get("output_height", top_height + front_height + side_height)),
        }
        if workflow == "block_texture_three_face":
            faces = ["top", "front", "side"]
            face_bytes = _generate_block_texture_faces(plan, provider, face_config, faces, style_image)
            if face_config["compose_mode"] == "isometric":
                composed = _compose_isometric_three_face_block(
                    face_bytes["top"],
                    face_bytes["front"],
                    face_bytes["side"],
                    face_config,
                )
            else:
                composed = _compose_three_face_block(
                    face_bytes["top"],
                    face_bytes["front"],
                    face_bytes["side"],
                    face_config,
                )
        else:
            faces = ["top", "front"]
            face_bytes = _generate_block_texture_faces(plan, provider, face_config, faces, style_image)
            composed = _compose_two_face_block(face_bytes["top"], face_bytes["front"], face_config)
        return _save_block_texture_outputs(composed, face_config, target_folder, filename_stub, faces, face_bytes)

    image_bytes = _generate_with_provider(
        provider=provider,
        description=plan["description"],
        width=plan["width"],
        height=plan["height"],
        no_background=bool(plan["no_background"]),
        style_image=style_image,
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
    log_event_id = uuid.uuid4().hex
    log_path = _generation_log_response_path()
    started_at = time.monotonic()
    plan: Optional[Dict[str, Any]] = None
    outputs: List[Dict[str, Any]] = []

    if not GODOT_PROJECT_DIR.exists():
        message = "Godot project dir not found: %s" % GODOT_PROJECT_DIR
        _record_generation_log_event(
            log_event_id,
            request,
            plan,
            "error",
            time.monotonic() - started_at,
            outputs=outputs,
            error=message,
        )
        return _error(message, log_event_id=log_event_id, log_path=log_path)

    requested_asset_type = _normalize_asset_type(request.asset_type, allow_auto=True)
    style_target = _normalize_style_target(request.style_target)
    provider = _normalize_generation_provider(request.provider)

    try:
        target_folder = _resolve_res_path(request.folder_path, expect_directory=True)
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
                print("PixelLab rejected planned payload:", _response_text_excerpt(response))
                fallback_plan = _provider_rejection_fallback_plan(
                    request,
                    plan.get("asset_type", requested_asset_type),
                    provider,
                    reference_context=plan.get("reference_context") if isinstance(plan.get("reference_context"), dict) else None,
                )
                outputs = _execute_generation_workflow(fallback_plan, target_folder)
                plan = fallback_plan
            else:
                raise

        if not outputs:
            raise ValueError("Generation workflow produced no output files")
        primary_output = outputs[0]
        _record_generation_log_event(
            log_event_id,
            request,
            plan,
            "success",
            time.monotonic() - started_at,
            outputs=outputs,
        )

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
            "log_event_id": log_event_id,
            "log_path": log_path,
        }
    except Exception as exc:
        print("Asset generation failed:", exc)
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            print("Provider error body:", _response_text_excerpt(exc.response))
        _record_generation_log_event(
            log_event_id,
            request,
            plan,
            "error",
            time.monotonic() - started_at,
            outputs=outputs,
            error=exc,
        )
        return _error(
            str(exc),
            log_event_id=log_event_id,
            log_path=log_path,
            plan=plan if isinstance(plan, dict) else {},
            workflow=plan.get("workflow") if isinstance(plan, dict) else None,
            provider=plan.get("provider") if isinstance(plan, dict) else provider,
            style_target=plan.get("style_target") if isinstance(plan, dict) else style_target,
            asset_type=plan.get("asset_type") if isinstance(plan, dict) else requested_asset_type,
            planning_source=plan.get("planning_source") if isinstance(plan, dict) else None,
        )


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


_PROVIDER_LABELS = {"pixellab": "PixelLab", "openai_image": "GPT Image"}


@app.get("/vibe/options")
async def generation_options() -> Dict[str, Any]:
    """Serve the style and provider choices the editor dropdowns should show.

    Styles come straight from the loaded packs, so dropping a new packs/<key>.json
    makes the editor offer it with no plugin code change.
    """
    styles = [{"value": "none", "label": "No Style Target"}]
    for key, profile in sorted(STYLE_MATRIX.items()):
        styles.append({"value": key, "label": str(profile.get("title") or key)})
    providers = [
        {"value": key, "label": _PROVIDER_LABELS.get(key, key.replace("_", " ").title())}
        for key in sorted(SUPPORTED_GENERATION_PROVIDERS)
    ]
    mode_order = ["auto", "plain", "reference", "style_transfer"]
    modes = [
        {"value": key, "label": GENERATION_MODE_LABELS[key], "description": GENERATION_MODE_DESCRIPTIONS[key]}
        for key in mode_order
    ]
    return {"status": "success", "styles": styles, "providers": providers, "modes": modes}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
