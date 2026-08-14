from __future__ import annotations

import unittest

import main


class MainUrlTests(unittest.TestCase):
    def test_main_window_uses_plain_local_file_url(self) -> None:
        url = main.build_ui_url()

        self.assertTrue(url.startswith("file:///"))
        self.assertTrue(url.endswith("/modern_terminal/ui/index.html"))
        self.assertNotIn("?", url)
        self.assertNotIn("#", url)

    def test_floating_window_uses_fragment_not_query(self) -> None:
        url = main.build_ui_url(floating=True)

        self.assertTrue(url.endswith("/modern_terminal/ui/index.html#view=floating"))
        self.assertNotIn("?", url)


if __name__ == "__main__":
    unittest.main()
