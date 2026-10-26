"""Release provenance checks must reject altered or unsafe source snapshots."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "lwns_release_builder", Path(__file__).resolve().parents[1] / "packaging/linux/build.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ReleaseSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.root = self.directory / "source"
        self.root.mkdir()
        self.archive = self.directory / "source.tar.gz"

    def write_archive(self, entries):
        with tarfile.open(self.archive, "w:gz") as archive:
            for name, data in entries:
                item = tarfile.TarInfo(name)
                item.size = len(data)
                archive.addfile(item, io.BytesIO(data))

    def test_original_source_matches_and_generated_outputs_are_allowed(self):
        (self.root / "main.py").write_bytes(b"original source\n")
        (self.root / "generated.js").write_bytes(b"compiled frontend\n")
        self.write_archive([("lwns/main.py", b"original source\n")])
        self.assertEqual(builder.verify_source_archive(self.archive, self.root), 1)

    def test_modified_source_cannot_be_labeled_as_original_tag(self):
        (self.root / "main.py").write_bytes(b"modified source\n")
        self.write_archive([("lwns/main.py", b"original source\n")])
        with self.assertRaisesRegex(ValueError, "changed after snapshot"):
            builder.verify_source_archive(self.archive, self.root)

    def test_missing_source_file_is_rejected(self):
        self.write_archive([("lwns/main.py", b"source\n")])
        with self.assertRaisesRegex(ValueError, "missing or replaced"):
            builder.verify_source_archive(self.archive, self.root)

    def test_traversal_and_absolute_archive_paths_are_rejected(self):
        for name in ("lwns/../outside", "/tmp/outside"):
            with self.subTest(name=name):
                self.write_archive([(name, b"bad")])
                with self.assertRaisesRegex(ValueError, "Unsafe source archive"):
                    builder.verify_source_archive(self.archive, self.root)

    def test_multiple_roots_or_duplicate_entries_are_rejected(self):
        (self.root / "main.py").write_bytes(b"source")
        for entries in (
            [("lwns/main.py", b"source"), ("other/main.py", b"source")],
            [("lwns/main.py", b"source"), ("lwns/main.py", b"source")],
        ):
            with self.subTest(entries=entries):
                self.write_archive(entries)
                with self.assertRaisesRegex(ValueError, "unique top-level directory"):
                    builder.verify_source_archive(self.archive, self.root)

    def test_empty_archive_cannot_prove_provenance(self):
        self.write_archive([])
        with self.assertRaisesRegex(ValueError, "contains no files"):
            builder.verify_source_archive(self.archive, self.root)

    def test_special_archive_entries_are_rejected(self):
        with tarfile.open(self.archive, "w:gz") as archive:
            item = tarfile.TarInfo("lwns/pipe")
            item.type = tarfile.FIFOTYPE
            archive.addfile(item)
        with self.assertRaisesRegex(ValueError, "Unsupported source archive"):
            builder.verify_source_archive(self.archive, self.root)


if __name__ == "__main__":
    unittest.main()
