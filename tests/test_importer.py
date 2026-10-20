import importlib.util
import pathlib
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("importer", pathlib.Path(__file__).parents[1] / "blender" / "import_unbound_batch.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ManifestTests(unittest.TestCase):
    def test_only_exported(self):
        rows = [{"Id": "ok", "Status": "exported"}, {"Id": "bad", "Status": "failed"}, {"Id": "skip", "Status": "skipped"}]
        self.assertEqual([r["Id"] for r in module.exported_records({"Schema": 1, "Meshes": rows})], ["ok"])

    def test_duplicates(self):
        with self.assertRaises(ValueError):
            list(module.exported_records({"Schema": 1, "Meshes": [{"Id": "a", "Status": "exported"}] * 2}))

    def test_schema(self):
        with self.assertRaises(ValueError):
            list(module.exported_records({"Schema": 2}))

    def test_path_containment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            (root / "mesh.fbx").write_bytes(b"fixture")
            self.assertEqual(module.safe_fbx(root, "mesh.fbx"), root / "mesh.fbx")
            with self.assertRaises(ValueError):
                module.safe_fbx(root, "../outside.fbx")
            with self.assertRaises(ValueError):
                module.safe_fbx(root, "mesh.exe")
            with self.assertRaises(FileNotFoundError):
                module.safe_fbx(root, "missing.fbx")


if __name__ == "__main__":
    unittest.main()
