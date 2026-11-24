"""程序说明：验证 ComfyUI 历史输出恢复和空输出错误处理。"""
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

from utils.comfyui_history import history_output_urls, require_generation_outputs


class ComfyUIHistoryOutputTests(unittest.TestCase):
    def test_extracts_image_and_gif_views_from_history(self):
        history_record = {
            "outputs": {
                "9": {
                    "images": [
                        {
                            "filename": "moss_image_t2i_00096_.png",
                            "subfolder": "moss",
                            "type": "output",
                        }
                    ]
                },
                "12": {
                    "gifs": [
                        {
                            "filename": "preview.gif",
                            "subfolder": "moss",
                            "type": "output",
                        }
                    ]
                },
            }
        }

        urls = history_output_urls(history_record, "https://comfy.example/")

        self.assertEqual(len(urls), 2)
        self.assertEqual(
            parse_qs(urlsplit(urls[0]).query),
            {
                "filename": ["moss_image_t2i_00096_.png"],
                "subfolder": ["moss"],
                "type": ["output"],
            },
        )
        self.assertEqual(
            parse_qs(urlsplit(urls[1]).query)["filename"],
            ["preview.gif"],
        )

    def test_missing_history_outputs_returns_empty_list(self):
        self.assertEqual(history_output_urls({}, "https://comfy.example"), [])

    def test_empty_generation_outputs_raise_instead_of_success(self):
        with self.assertRaisesRegex(RuntimeError, "未返回图像或视频文件"):
            require_generation_outputs([])

    def test_generation_outputs_are_preserved(self):
        outputs = [("image/png", 1024, 1024, "image.png")]
        self.assertIs(require_generation_outputs(outputs), outputs)


if __name__ == "__main__":
    unittest.main()
