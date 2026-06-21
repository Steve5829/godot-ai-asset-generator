import tempfile
import unittest
import requests
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

    def test_block_face_prompts_exclude_reference_checkerboard_traits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference_path = root / "core_keeper" / "block_texture" / "grass_block.png"
            _write_reference_image(reference_path)

            with patch.object(server, "REFERENCE_IMAGE_ROOT", root), patch.object(
                server,
                "_analyze_reference_images",
                return_value="gray checkerboard cutout background with green grass top and brown root front",
            ):
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
