"""Minimal example: call the Vibe backend directly from Python.
"""
import requests

BACKEND_URL = "http://127.0.0.1:8000/vibe"


def generate_asset(
    prompt,
    folder_path="res://",
    style_target="none",
    provider="pixellab",
    generation_mode="auto",
):
    
    payload = {
        "prompt": prompt,
        "folder_path": folder_path,      
        "asset_type": "auto",            
        "workflow_mode": "auto",
        "generation_mode": generation_mode,  
        "style_target": style_target,        
        "provider": provider,                
    }
    response = requests.post(BACKEND_URL + "/generate", json=payload, timeout=300)
    response.raise_for_status()
    return response.json()


def list_options():
    response = requests.get(BACKEND_URL + "/options", timeout=30)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    options = list_options()
    print("styles:   ", [s["value"] for s in options["styles"]])
    print("providers:", [p["value"] for p in options["providers"]])
    print("modes:    ", [m["value"] for m in options["modes"]])
    print()

    # Generate one asset. Change these arguments to try other.
    result = generate_asset(
        prompt="a 32x32 pixel healing potion icon",
        style_target="core_keeper",
        provider="pixellab",
        generation_mode="auto",
    )

    if result.get("status") == "success":
        print("saved:   ", result["file_path"])
        print("type:    ", result["asset_type"], "/", result["workflow"])
        print("outputs: ", [o["file_path"] for o in result.get("outputs", [])])
    else:
        print("failed:  ", result.get("message"))
