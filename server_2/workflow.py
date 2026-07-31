from composer import COMPOSER_CLASSES
from save import save_image
import io
from PIL import Image

class Workflow:
    def execute(self, plan, provider):
        raise NotImplementedError


class IconWorkflow(Workflow):
    def execute(self, plan, provider):
        image = provider.generate(plan)
        record = save_image(image, plan, role = "single_image")
        return [record]

class BlockWorkflow(Workflow):
    def execute(self, plan, provider):
        image = provider.generate(plan)
        composed = COMPOSER_CLASSES["two_face"]().compose(image, image)
        record = save_image(composed, plan, role = "block_texture")
        return [record]

class SpriteSheetWorkflow(Workflow):
    columns = 4
    rows = 4
    def execute(self, plan, provider):
        image = provider.generate(plan)
        outputs = [save_image(image, plan, role = "full_image")]
        for cell_bytes, r, c in crop_grid(image, self.columns, self.rows):
            rec = save_image(cell_bytes, plan, role = "cell", suffix = f"_r{r:02d}_c{c:02d}")
            outputs.append(rec)
        return outputs

class GroundAtlasWorkflow(Workflow):
    tile_width = 32
    tile_height = 32
    def execute(self, plan, provider):
        image = provider.generate(plan)
        sheet = Image.open(io.BytesIO(image))
        columns = sheet.width//self.tile_width
        rows = sheet.height//self.tile_height
        outputs = [save_image(image, plan, role = "full_image")]
        for tile_bytes, r, c in crop_grid(image, columns, rows):
            rec = save_image(tile_bytes, plan, role = "atlas_tile", suffix = f"_r{r:02d}_c{c:02d}")
            outputs.append(rec)
        return outputs

def crop_grid(image_bytes, columns, rows):
        sheet = Image.open(io.BytesIO(image_bytes))
        cell_w = sheet.width//columns
        cell_h = sheet.height//rows
        cells = []
        for r in range(rows):
            for c in range (columns):
                cell = sheet.crop ((c*cell_w, r*cell_h, (c+1)*cell_w, (r+1)*cell_h) )
                buf = io.BytesIO()
                cell.save(buf, format = "PNG")
                cells.append((buf.getvalue(),r,c))
        return cells

WORKFLOW_CLASSES = {
    "icon": IconWorkflow,
    "block": BlockWorkflow,
    "spritesheet": SpriteSheetWorkflow,
    "ground_atlas": GroundAtlasWorkflow
}
