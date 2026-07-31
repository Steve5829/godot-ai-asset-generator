from plan import Plan
import re
from reference import select_reference
# slug filename for path
def slug(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")

class Asset:
    no_background = True
    workflow = "icon"
    use_style = False
    reference_dir = "icon"
    def build_plan(self, request):
        use_style_transfer = False
        reference_image = None
        if self.use_style and request.style != "none":
            ref = select_reference(request.style, self.reference_dir, request.prompt)
            if ref:
                reference_image = str(ref)
                use_style_transfer = True    
        return Plan(
            description = request.prompt,
            width = request.width,
            height = request.height,
            output_folder = request.folder,
            filename = slug(request.prompt),
            no_background = self.no_background,
            workflow = self.workflow,
            use_style_transfer = use_style_transfer,
            reference_image = reference_image
        )

class IconAsset(Asset):
    pass
    
class BlockAsset(Asset):
    no_background = False
    workflow = "block"
    use_style = True
    reference_dir = "block_texture"

class SpriteSheetAsset(Asset):
     workflow = "spritesheet"

class GroundAtlasAsset(Asset):
     no_background = False
     workflow = "ground_atlas"
     use_style = True
     reference_dir = "ground_atlas"
        

    
