"""Required metadata-declared notices must survive packaging."""

from email.message import Message
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.collect_legal import collect


class LegalCollectionTests(unittest.TestCase):
    def test_declared_authors_notice_is_retained_without_unrelated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            info = root / "example.dist-info" / "licenses"
            info.mkdir(parents=True)
            for name in ("AUTHORS.md", "LICENSE", "unrelated.md"):
                (info / name).write_text(name, encoding="utf-8")
            metadata = Message()
            metadata["Name"] = "example"
            metadata["License-File"] = "AUTHORS.md"
            distribution = SimpleNamespace(metadata=metadata, version="1", files=[
                Path("example.dist-info/licenses") / name for name in ("AUTHORS.md", "LICENSE", "unrelated.md")
            ], locate_file=lambda file: root / file)
            output = root / "output"
            with patch("tools.collect_legal.importlib.metadata.distributions", return_value=[distribution]):
                collect(output)
            self.assertEqual((output / "example-1/licenses/AUTHORS.md").read_text(), "AUTHORS.md")
            self.assertTrue((output / "example-1/licenses/LICENSE").is_file())
            self.assertFalse((output / "example-1/licenses/unrelated.md").exists())
