"""Check the built frontend at FRONTEND_URL (defaults to localhost:8091)."""
import hashlib
from html.parser import HTMLParser
import os
import unittest
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import urlopen


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.assets.append(attrs["href"])
        if tag == "script" and "src" in attrs:
            self.assets.append(attrs["src"])


class ServingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = os.getenv("FRONTEND_URL", "http://127.0.0.1:8091/").rstrip("/") + "/"
        with urlopen(cls.base, timeout=10) as response:
            cls.html = response.read().decode()
            cls.headers = response.headers
        parser = AssetParser()
        parser.feed(cls.html)
        cls.assets = parser.assets

    def test_html_revalidates(self):
        self.assertIn("no-cache", self.headers.get("Cache-Control", ""))

    def test_html_references_hashed_css_and_js(self):
        self.assertEqual(len(self.assets), 2)
        self.assertEqual({asset.rsplit(".", 1)[-1] for asset in self.assets}, {"css", "js"})
        for asset in self.assets:
            self.assertRegex(asset, r"^\./assets/(styles|app)\.[a-f0-9]{16}\.(css|js)$")

    def test_asset_hashes_types_and_caching(self):
        for asset in self.assets:
            with self.subTest(asset=asset):
                with urlopen(urljoin(self.base, asset), timeout=10) as response:
                    content = response.read()
                    digest = hashlib.sha256(content).hexdigest()[:16]
                    self.assertIn(f".{digest}.", asset)
                    expected = "text/css" if asset.endswith(".css") else "application/javascript"
                    self.assertEqual(response.headers.get_content_type(), expected)
                    self.assertIn("immutable", response.headers.get("Cache-Control", ""))

    def test_missing_asset_returns_404(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(urljoin(self.base, "assets/missing.0000000000000000.css"), timeout=10)
        self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
