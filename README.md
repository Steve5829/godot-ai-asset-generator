# Godot Vibe Plugin

> ⚠️ **Archived branch (v0).** The latest version lives on the [`v2`](../../tree/v2) branch.

An AI-powered editor automation tool for Godot, powered by pocketpy.

Godot Vibe Plugin brings prompt-driven asset generation, asset modification, and editor automation into the Godot editor. The project combines a GDScript editor plugin with a local FastAPI backend that plans structured actions through an OpenAI-compatible model and generates images through PixelLab.

## Status

This repository is the upstreamed codebase for the current prototype. The core plugin and backend logic are present here, while setup and packaging are still being polished as the project is integrated into the pocketpy ecosystem.

## Features

- Generate new assets from text prompts directly from the FileSystem dock.
- Modify existing image assets with structured operations such as resize, aspect-ratio canvas changes, and rotation.
- Automate scene editing tasks from natural-language prompts in the Scene dock.
- Use structured planning instead of arbitrary code execution for safer editor actions.
- Dispatch supported node operations through a guarded, reflection-style action layer in the plugin.

## Repository Layout

- `addons/vibe_agent/`: Godot editor plugin written in GDScript.
- `server/server.py`: FastAPI backend for planning, image generation, and image editing.
- `server/requirements.txt`: Python dependencies for the backend.

## Architecture

The plugin adds editor context menu actions for three workflows:

- `Vibe: Generate Asset`
- `Vibe: Modify Asset`
- `Vibe: Automation`

Each workflow sends the user prompt and editor context to the local backend at `http://127.0.0.1:8000/vibe`. The backend converts the request into a structured plan:

- Asset generation requests are turned into PixelLab generation settings.
- Asset modification requests are normalized into a single image operation such as `resize_image`, `resize_canvas`, or `rotate`.
- Automation requests are converted into structured action objects. The Godot plugin then routes those actions through explicit handlers such as `create_node` and `rename_children`, or through an allowlisted node-method dispatcher for supported editor operations.

This design keeps the integration predictable and auditable while still allowing natural-language workflows inside the editor.

## Requirements

- Python 3.7+
- Godot 4.x
- PixelLab API key
- OpenAI-compatible API key for prompt planning

## Development Setup

Install the backend dependencies:

```bash
python3 -m pip install -r server/requirements.txt
```

Create `server/.env` with the required environment variables:

```dotenv
PIXELLAB_API_KEY=your-pixellab-api-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4o-mini
```

Start the backend from the repository root:

```bash
python3 server/server.py
```

The Godot editor plugin source lives in `addons/vibe_agent/`. The current repository layout reflects the prototype code import, and broader project packaging will be refined in follow-up changes.

## Usage

### Generate Asset

In the FileSystem dock, right click a folder or empty space in the current folder and choose `Vibe: Generate Asset`.

Example prompt:

```text
I want a 32x32 pixel style pickaxe icon
```

### Modify Asset

In the FileSystem dock, right click an existing image asset and choose `Vibe: Modify Asset`.

Example prompt:

```text
Resize the image into 16:9
```

### Editor Automation

In the Scene dock, right click a node and choose `Vibe: Automation`.

Example prompt:

```text
Rename all children start from 0 with "child_%d" format
```

## Troubleshooting

If menu items do not appear:

- Make sure the plugin is enabled in Godot.
- Reopen the project after updating plugin scripts.

If requests fail:

- Make sure `python3 server/server.py` is running.
- Check the Godot output panel.
- Check the backend terminal logs.

If model-backed features do not respond as expected:

- Verify `PIXELLAB_API_KEY`.
- Verify `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL`.
- Confirm the machine can reach the configured provider endpoints.

Developed by Steve Chen as part of the pocketpy ecosystem.
