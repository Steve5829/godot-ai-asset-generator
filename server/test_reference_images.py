import tempfile
import unittest
import requests
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import server


class MockPixelLabResponse:
    def __init__(self, status_code, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}
        self.request = None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError("mock pixellab error", response=self, request=self.request)

    def json(self):
        return self._payload


def _write_reference_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(path)


def _image_bytes(color) -> bytes:
    buffer = BytesIO()
    Image.new("RGBA", (16, 16), color).save(buffer, format="PNG")
    return buffer.getvalue()


class ReferenceImageTests(unittest.TestCase):
    def test_select_reference_images_from_style_asset_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference_path = root / "core_keeper" / "icon" / "potion.png"
            _write_reference_image(reference_path)

            with patch.object(server, "REFERENCE_IMAGE_ROOT", root):
                selected = server._select_reference_images("Core Keeper", "icon")

            self.assertEqual(selected, [reference_path])

    def test_select_reference_images_prioritizes_prompt_filename_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference_dir = root / "core_keeper" / "icon"
            sword_path = reference_dir / "01_sword.png"
            ore_path = reference_dir / "02_ore.png"
            potion_path = reference_dir / "03_potion.png"
            for path in (sword_path, ore_path, potion_path):
                _write_reference_image(path)

            with patch.object(server, "REFERENCE_IMAGE_ROOT", root):
                selected = server._select_reference_images("core_keeper", "icon", "healing potion icon")

            self.assertEqual(selected, [potion_path, sword_path, ore_path])

    def test_select_reference_images_uses_conservative_synonyms(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference_dir = root / "core_keeper" / "icon"
            sword_path = reference_dir / "01_sword.png"
            ore_path = reference_dir / "02_ore.png"
            potion_path = reference_dir / "03_potion.png"
            for path in (sword_path, ore_path, potion_path):
                _write_reference_image(path)

            with patch.object(server, "REFERENCE_IMAGE_ROOT", root):
                selected = server._select_reference_images("core_keeper", "icon", "healing bottle icon")

            self.assertEqual(selected, [potion_path, sword_path, ore_path])

    def test_select_reference_images_without_prompt_match_uses_sorted_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference_dir = root / "core_keeper" / "icon"
            sword_path = reference_dir / "01_sword.png"
            ore_path = reference_dir / "02_ore.png"
            potion_path = reference_dir / "03_potion.png"
            for path in (sword_path, ore_path, potion_path):
                _write_reference_image(path)

            with patch.object(server, "REFERENCE_IMAGE_ROOT", root):
                selected = server._select_reference_images("core_keeper", "icon", "lantern icon")

            self.assertEqual(selected, [sword_path, ore_path, potion_path])

    def test_vision_helper_uses_chat_completion_and_returns_text(self) -> None:
        class MockResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self):
                return {"choices": [{"message": {"content": "chunky outline, warm red palette"}}]}

        with tempfile.TemporaryDirectory() as tmpdir:
            reference_path = Path(tmpdir) / "potion.png"
            _write_reference_image(reference_path)

            with patch.object(server, "OPENAI_API_KEY", "test-key"), patch.object(server.requests, "post", return_value=MockResponse()) as post:
                analysis = server._analyze_reference_images([reference_path], "healing potion icon", "core_keeper", "icon")

            self.assertIn("chunky outline", analysis)
            payload = post.call_args[1]["json"]
            self.assertEqual(payload["model"], server.OPENAI_VISION_MODEL)
            self.assertEqual(payload["messages"][1]["content"][1]["type"], "image_url")
            self.assertTrue(payload["messages"][1]["content"][1]["image_url"]["url"].startswith("data:"))

    def test_fallback_plan_includes_reference_context_and_traits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference_path = root / "core_keeper" / "icon" / "potion.png"
            _write_reference_image(reference_path)
            request = server.GenerateAssetRequest(
                prompt="healing potion icon",
                asset_type="auto",
                style_target="core_keeper",
                provider="pixellab",
            )

            with patch.object(server, "REFERENCE_IMAGE_ROOT", root), patch.object(
                server,
                "_analyze_reference_images",
                return_value="rounded bottle silhouette, bright red liquid",
            ), patch.object(server, "_chat_json", side_effect=ValueError("planner unavailable")):
                plan = server._plan_generation_workflow(request)

            self.assertEqual(plan["planning_source"], "fallback")
            self.assertEqual(plan["reference_context"]["status"], "analyzed")
            self.assertIn("rounded bottle silhouette", plan["description"])
            self.assertTrue(plan["reference_context"]["reference_images"][0]["path"].endswith("core_keeper/icon/potion.png"))
            self.assertNotIn("base64", str(plan["reference_context"]))

    def test_llm_planner_payload_receives_reference_context(self) -> None:
        captured_payload = {}

        def fake_chat_json(system_prompt, user_payload):
            captured_payload.update(user_payload)
            return {
                "asset_type": "icon",
                "workflow": "single_image",
                "description": "A healing potion icon",
                "descriptions": {},
                "width": 128,
                "height": 128,
                "filename_stub": "healing_potion",
                "no_background": True,
                "postprocess": {},
                "outputs_expected": ["full_image"],
                "notes": ["planned"],
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference_path = root / "core_keeper" / "icon" / "potion.png"
            _write_reference_image(reference_path)
            request = server.GenerateAssetRequest(
                prompt="healing potion icon",
                asset_type="auto",
                style_target="core_keeper",
                provider="pixellab",
            )

            with patch.object(server, "REFERENCE_IMAGE_ROOT", root), patch.object(
                server,
                "_analyze_reference_images",
                return_value="thick dark outline, glossy red contents",
            ), patch.object(server, "_chat_json", side_effect=fake_chat_json):
                plan = server._plan_generation_workflow(request)

        self.assertIn("reference_context", captured_payload)
        self.assertEqual(captured_payload["reference_context"]["status"], "analyzed")
        self.assertIn("thick dark outline", plan["description"])

    def test_pixellab_500_retries_once_then_succeeds(self) -> None:
        image_payload = {"image": {"base64": "cGl4ZWxz"}}
        responses = [
            MockPixelLabResponse(500, "Internal Server Error"),
            MockPixelLabResponse(200, payload=image_payload),
        ]

        with patch.object(server, "PIXELLAB_API_KEY", "test-key"), patch.object(server.requests, "post", side_effect=responses) as post:
            image_bytes = server._generate_with_pixellab("test icon", 128, 128, True)

        self.assertEqual(image_bytes, b"pixels")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0][1]["json"], post.call_args_list[1][1]["json"])

    def test_pixellab_repeated_500_has_clear_bounded_error(self) -> None:
        responses = [
            MockPixelLabResponse(500, "Internal Server Error"),
            MockPixelLabResponse(500, "Internal Server Error"),
        ]

        with patch.object(server, "PIXELLAB_API_KEY", "test-key"), patch.object(server.requests, "post", side_effect=responses) as post:
            with self.assertRaises(requests.HTTPError) as raised:
                server._generate_with_pixellab("test icon", 128, 128, True)

        message = str(raised.exception)
        self.assertEqual(post.call_count, 2)
        self.assertIn("internal server error (500) after 2 attempts", message)
        self.assertIn("provider-side generation failure", message)
        self.assertIn("GPT Image / openai_image provider", message)

    def test_minecraft_stone_block_uses_three_face_layout(self) -> None:
        plan = server._fallback_generation_plan(
            "stone block",
            "block_texture",
            "auto",
            "minecraft",
            "pixellab",
            "test",
        )
        self.assertEqual(plan["workflow"], "block_texture_three_face")
        self.assertEqual(plan["postprocess"]["final_width"], 16)
        self.assertEqual(plan["postprocess"]["top_height"], 16)
        self.assertEqual(plan["postprocess"]["front_height"], 16)
        self.assertEqual(plan["postprocess"]["side_height"], 16)
        self.assertEqual(plan["postprocess"]["compose_mode"], "isometric")
        self.assertEqual(plan["postprocess"]["output_width"], 32)
        self.assertEqual(plan["postprocess"]["output_height"], 32)
        profile = server._block_material_profile(plan)
        self.assertTrue(server._block_profile_is_uniform(profile))

    def test_iron_block_uses_metal_profile_uniform(self) -> None:
        plan = server._fallback_generation_plan(
            "iron block",
            "block_texture",
            "auto",
            "minecraft",
            "pixellab",
            "test",
        )
        profile = server._block_material_profile(plan)
        self.assertEqual(server._block_profile_key(profile), "metal")
        self.assertTrue(server._block_profile_is_uniform(profile))
        side_prompt = server._strict_block_face_description(plan, "side", 64, 64).lower()
        self.assertIn("silver-gray", side_prompt)
        self.assertNotIn("mossy green fringe", side_prompt)
        self.assertNotIn("dirt, soil, roots", side_prompt)

    def test_gold_block_uses_gold_metal_prompt_not_rock_or_silver(self) -> None:
        plan = server._fallback_generation_plan(
            "gold block",
            "block_texture",
            "auto",
            "minecraft",
            "pixellab",
            "test",
        )
        profile = server._block_material_profile(plan)
        self.assertEqual(server._block_profile_key(profile), "metal")
        front_prompt = server._strict_block_face_description(plan, "front", 64, 64).lower()
        self.assertIn("for gold block, use yellow-gold", front_prompt)
        self.assertIn("no gray rock", front_prompt)
        self.assertNotIn("flat stone", front_prompt)

    def test_unknown_block_defaults_to_shared_material_generation(self) -> None:
        plan = server._fallback_generation_plan(
            "obsidian block",
            "block_texture",
            "auto",
            "minecraft",
            "pixellab",
            "test",
        )
        self.assertIsNone(server._block_material_profile(plan))
        self.assertFalse(server._block_requires_multi_face_generation(plan))
        front_prompt = server._strict_block_face_description(plan, "front", 64, 64).lower()
        self.assertIn("cross-face consistency", front_prompt)
        self.assertIn("exact same material palette", front_prompt)

        call_count = {"value": 0}

        def _mock_generate(**kwargs):
            call_count["value"] += 1
            return b"\x89PNG\r\n\x1a\n"

        face_config = {
            "final_width": 16,
            "front_height": 16,
            "top_height": 16,
            "side_height": 16,
        }
        with patch.object(server, "_generate_with_provider", side_effect=_mock_generate):
            face_bytes = server._generate_block_texture_faces(plan, "pixellab", face_config, ["top", "front", "side"])

        self.assertEqual(call_count["value"], 1)
        self.assertEqual(face_bytes["top"], face_bytes["front"])
        self.assertEqual(face_bytes["front"], face_bytes["side"])

    def test_isometric_three_face_composition_connects_faces(self) -> None:
        composed = server._compose_isometric_three_face_block(
            _image_bytes((255, 220, 60, 255)),
            _image_bytes((210, 160, 30, 255)),
            _image_bytes((150, 110, 20, 255)),
            {
                "final_width": 16,
                "output_width": 32,
                "output_height": 32,
            },
        )
        self.assertEqual(composed.size, (32, 32))
        self.assertEqual(composed.getpixel((0, 0))[3], 0)
        self.assertGreater(composed.getpixel((16, 1))[3], 0)
        self.assertGreater(composed.getpixel((8, 16))[3], 0)
        self.assertGreater(composed.getpixel((24, 16))[3], 0)
        self.assertGreater(composed.getpixel((16, 31))[3], 0)

    def test_grass_block_still_uses_multi_face_generation(self) -> None:
        plan = server._fallback_generation_plan(
            "grass block with leafy top and root front face",
            "block_texture",
            "auto",
            "core_keeper",
            "pixellab",
            "test",
        )
        self.assertEqual(server._block_profile_key(server._block_material_profile(plan)), "forest")
        self.assertTrue(server._block_requires_multi_face_generation(plan))

        call_count = {"value": 0}

        def _mock_generate(**kwargs):
            call_count["value"] += 1
            return b"\x89PNG\r\n\x1a\n"

        face_config = {
            "final_width": 32,
            "front_height": 32,
            "top_height": 16,
        }
        with patch.object(server, "_generate_with_provider", side_effect=_mock_generate):
            server._generate_block_texture_faces(plan, "pixellab", face_config, ["top", "front"])

        self.assertEqual(call_count["value"], 2)

    def test_diamond_block_uses_gem_profile_uniform(self) -> None:
        plan = server._fallback_generation_plan(
            "diamond block",
            "block_texture",
            "auto",
            "minecraft",
            "pixellab",
            "test",
        )
        profile = server._block_material_profile(plan)
        self.assertEqual(server._block_profile_key(profile), "gem")
        self.assertTrue(server._block_profile_is_uniform(profile))
        front_prompt = server._strict_block_face_description(plan, "front", 64, 64).lower()
        self.assertIn("do not draw a gem item icon", front_prompt)
        self.assertIn("flat mineral block", front_prompt)
        self.assertIn("cross-face consistency", front_prompt)

    def test_non_minecraft_block_prompt_does_not_inherit_minecraft_material_name(self) -> None:
        plan = server._fallback_generation_plan(
            "diamond block",
            "block_texture",
            "auto",
            "core_keeper",
            "pixellab",
            "test",
        )
        front_prompt = server._strict_block_face_description(plan, "front", 64, 64).lower()
        self.assertNotIn("minecraft", front_prompt)
        self.assertIn("core keeper-like", front_prompt)
        self.assertIn("flat mineral block", front_prompt)

    def test_wood_block_uses_wood_profile(self) -> None:
        plan = server._fallback_generation_plan(
            "wood block",
            "block_texture",
            "auto",
            "minecraft",
            "pixellab",
            "test",
        )
        profile = server._block_material_profile(plan)
        self.assertEqual(server._block_profile_key(profile), "wood")
        front_prompt = server._strict_block_face_description(plan, "front", 64, 64).lower()
        self.assertIn("bark", front_prompt)
        self.assertNotIn("mossy green fringe", front_prompt)

    def test_core_keeper_block_keeps_two_face_layout(self) -> None:
        plan = server._fallback_generation_plan(
            "stone block",
            "block_texture",
            "auto",
            "core_keeper",
            "pixellab",
            "test",
        )
        self.assertEqual(plan["workflow"], "block_texture_two_face")
        self.assertEqual(plan["postprocess"]["final_width"], 32)

    def test_block_texture_reference_ranking_prioritizes_material_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference_dir = root / "core_keeper" / "block_texture"
            for name in ("dirt.png", "root grass.png", "sand front.png", "sand top.png"):
                _write_reference_image(reference_dir / name)

            with patch.object(server, "REFERENCE_IMAGE_ROOT", root):
                selected = server._select_reference_images("core_keeper", "block_texture", "sand block")

            self.assertEqual(selected[0].name, "sand front.png")
            self.assertEqual(selected[1].name, "sand top.png")
            self.assertNotIn("dirt.png", [path.name for path in selected[:2]])

    def test_block_texture_skips_reference_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference_path = root / "core_keeper" / "block_texture" / "sand front.png"
            _write_reference_image(reference_path)

            with patch.object(server, "REFERENCE_IMAGE_ROOT", root):
                context = server._build_reference_context("sand block", "core_keeper", "block_texture")

            self.assertIsNone(context)

    def test_desert_block_front_prompt_forbids_brick(self) -> None:
        plan = server._fallback_generation_plan(
            "sand block",
            "block_texture",
            "auto",
            "core_keeper",
            "pixellab",
            "test",
        )
        front_prompt = server._strict_block_face_description(plan, "front", 64, 64).lower()
        self.assertIn("not brick masonry", front_prompt)
        self.assertIn("cross-face consistency", front_prompt)

    def test_block_face_prompts_exclude_reference_checkerboard_traits(self) -> None:
        plan = server._fallback_generation_plan(
            "grass block with leafy top and root front face",
            "block_texture",
            "auto",
            "core_keeper",
            "pixellab",
            "test",
        )
        top_prompt = server._strict_block_face_description(plan, "top", 64, 32)
        front_prompt = server._strict_block_face_description(plan, "front", 64, 64)

        self.assertNotIn("Reference image style traits", top_prompt)
        self.assertNotIn("Reference image style traits", front_prompt)
        self.assertNotIn("gray checkerboard cutout background", top_prompt.lower())
        self.assertIn("Cross-face consistency", top_prompt)
        self.assertIn("Cross-face consistency", front_prompt)
        self.assertIn("opaque material texture", top_prompt.lower())

    def test_prepare_reference_image_for_vision_replaces_gray_matte(self) -> None:
        image = Image.new("RGBA", (4, 4), (247, 247, 247, 255))
        image.putpixel((1, 1), (120, 180, 90, 255))
        prepared = server._prepare_reference_image_for_vision(image)
        self.assertEqual(prepared.getpixel((0, 0)), (34, 36, 42, 255))
        self.assertEqual(prepared.getpixel((1, 1)), (120, 180, 90, 255))


if __name__ == "__main__":
    unittest.main()
