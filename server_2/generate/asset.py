import json
from pathlib import Path
from generate.plan import Plan
from reference.select import select_reference
from reference.analyze import analyze_reference
from text import tokens, slug

MATERIALS_PATH = Path(__file__).parent / "data" / "materials.json"
BLOCK_MATERIALS = json.loads(MATERIALS_PATH.read_text())

def match_material(prompt):
    words = tokens(prompt)
    for material in BLOCK_MATERIALS.values():
        if any(keyword in words for keyword in material["keywords"]):
            return material
    return None
class Asset:
    no_background = True
    workflow = "icon"
    reference_dir = "icon"
    reference_mode = "none"
    snap_colors = 0
    compose_mode = "two_face"
    def build_plan(self, request):
        description = request.prompt
        reference_image = None
        if self.reference_mode != "none" and request.style != "none":
            ref = select_reference(request.style, self.reference_dir, request.prompt)
            if ref:
                if self.reference_mode == "style":
                    reference_image = str(ref)
                elif self.reference_mode == "analyze":
                    traits = analyze_reference(ref, request.prompt)
                    if traits:
                        description = f"{description}. {traits}"

        description = self.describe(request, description)
        return Plan(
            description = description,
            width = request.width,
            height = request.height,
            output_folder = request.folder,
            filename = slug(request.prompt),
            no_background = self.no_background,
            workflow = self.workflow,
            faces = self.faces_for(request),
            reference_mode = self.reference_mode,
            reference_image = reference_image,
            snap_colors = self.snap_colors,
            compose_mode = self.compose_mode
        )
    def faces_for(self, request):
        return None
    def describe(self, request, description):
        return description

class IconAsset(Asset):
    reference_mode = "analyze"
    
class BlockAsset(Asset):
    no_background = False
    workflow = "block"
    reference_dir = "block_texture"
    snap_colors = 32
    block_faces = ("top", "front")
    def faces_for(self, request):
        material = match_material(request.prompt)
        if not material:
            return None
        return {face: f"{request.prompt}, {material[face]}, {face} face"
                for face in self.block_faces}

class IsometricBlockAsset(BlockAsset):
    compose_mode = "isometric"
    block_faces = ("top", "front", "side")

class NativeIsometricBlockAsset(BlockAsset):
    workflow = "isometric_native"
    def describe(self, request, description):
        material = match_material(request.prompt)
        if material:
            return f"{material['top']} on top of {material['front']}"
        return request.prompt

class SpriteSheetAsset(Asset):
     workflow = "spritesheet"

class GroundAtlasAsset(Asset):
     no_background = False
     workflow = "ground_atlas"
     reference_mode = "style"
     reference_dir = "ground_atlas"
     snap_colors = 32
        

    
