from generate.plan import Plan
from reference.select import select_reference
from reference.analyze import analyze_reference
from text import tokens, slug

BLOCK_MATERIALS = {
    "grass": {"top": "grass", "front": "dirt"},
}

def match_material(prompt):
    words = tokens(prompt)                 
    for name, faces in BLOCK_MATERIALS.items():
        if name in words:
            return faces
    return None
class Asset:
    no_background = True
    workflow = "icon"
    reference_dir = "icon"
    reference_mode = "none"
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
            reference_image = reference_image
        )
    def faces_for(self, request):
        return None

class IconAsset(Asset):
    reference_mode = "analyze"
    
class BlockAsset(Asset):
    no_background = False
    workflow = "block"
    reference_dir = "block_texture"
    def faces_for(self, request):
        material = match_material(request.prompt)
        if not material:
            return None
        return {face: f"{request.prompt}, {mat} material, {face} face" 
                for face, mat in material.items()}

class SpriteSheetAsset(Asset):
     workflow = "spritesheet"

class GroundAtlasAsset(Asset):
     no_background = False
     workflow = "ground_atlas"
     reference_mode = "style"
     reference_dir = "ground_atlas"
        

    
