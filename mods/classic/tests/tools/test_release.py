"""Tests for tools/release.py. Run: python -m unittest discover -s mods/classic/tests/tools"""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tools"))
import release  # noqa: E402

CHANGELOG = """# Thing changelog

## 0.2.0 (2026-11-01)

- Second thing.

## 0.1.0 (2026-10-25)

First release.

- One thing.
"""


def make_addon(root, name="Thing", version="0.1.0", interface="11509", project_id="123456"):
    d = root / name
    d.mkdir()
    lines = [f"## Interface: {interface}", f"## Title: {name}", f"## Version: {version}"]
    if project_id:
        lines.append(f"## X-Curse-Project-ID: {project_id}")
    lines.append(f"{name}.lua")
    (d / f"{name}.toc").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (d / f"{name}.lua").write_text("-- code\n", encoding="utf-8")
    (d / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (root / "dist").mkdir(exist_ok=True)
    (root / "dist" / f"{name}-{version}.zip").write_bytes(b"PK fake zip")
    return d


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, versions):
        self.versions = versions
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if req.full_url.endswith("/game/versions"):
            return FakeResponse(self.versions)
        return FakeResponse({"id": 999})


class Pure(unittest.TestCase):
    def test_interface_to_version(self):
        self.assertEqual(release.interface_to_version("11509"), "1.15.9")
        self.assertEqual(release.interface_to_version("20505"), "2.5.5")
        self.assertEqual(release.interface_to_version("120105"), "12.1.5")
        with self.assertRaises(release.ReleaseError):
            release.interface_to_version("abc")

    def test_parse_tag(self):
        self.assertEqual(release.parse_tag("Hawker/v0.1.0"), ("Hawker", "0.1.0"))
        self.assertEqual(release.parse_tag("Downcast/v1.2.3-beta1"), ("Downcast", "1.2.3-beta1"))
        for bad in ("v0.1.0", "Hawker-0.1.0", "Hawker/0.1.0", "/v1"):
            with self.assertRaises(release.ReleaseError, msg=bad):
                release.parse_tag(bad)

    def test_changelog_section(self):
        self.assertEqual(release.changelog_section(CHANGELOG, "0.1.0"), "First release.\n\n- One thing.")
        self.assertEqual(release.changelog_section(CHANGELOG, "0.2.0"), "- Second thing.")
        self.assertIsNone(release.changelog_section(CHANGELOG, "0.3.0"))

    def test_release_type(self):
        self.assertEqual(release.release_type("1.0.0"), "release")
        self.assertEqual(release.release_type("1.0.0-beta2"), "beta")
        self.assertEqual(release.release_type("1.0.0-alpha"), "alpha")

    def test_resolve_game_version(self):
        versions = [{"id": 1, "name": "1.15.8"}, {"id": 2, "name": "1.15.9"}, {"id": 3, "name": "12.1.5"}]
        self.assertEqual(release.resolve_game_version(versions, "1.15.9"), 2)
        with self.assertRaises(release.ReleaseError):
            release.resolve_game_version(versions, "1.15.10")
        with self.assertRaises(release.ReleaseError):
            release.resolve_game_version(versions + [{"id": 4, "name": "1.15.9"}], "1.15.9")

    def test_multipart(self):
        body, ctype = release.multipart({"metadata": '{"a": 1}'}, "file", "x.zip", b"ZIPDATA")
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        boundary = ctype.split("boundary=")[1].encode()
        self.assertIn(b'name="metadata"', body)
        self.assertIn(b'{"a": 1}', body)
        self.assertIn(b'name="file"; filename="x.zip"', body)
        self.assertIn(b"ZIPDATA", body)
        self.assertTrue(body.rstrip().endswith(b"--" + boundary + b"--"))


class WithAddon(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load(self):
        make_addon(self.root)
        r = release.load("Thing", root=self.root)
        self.assertEqual((r.version, r.game_versions, r.project_id), ("0.1.0", ["1.15.9"], "123456"))
        self.assertEqual(r.changelog, "First release.\n\n- One thing.")
        self.assertEqual(r.zip_path.name, "Thing-0.1.0.zip")

    def test_multiple_interfaces(self):
        make_addon(self.root, interface="11509, 20505")
        self.assertEqual(release.load("Thing", root=self.root).game_versions, ["1.15.9", "2.5.5"])

    def test_check_tag_must_match_toc(self):
        make_addon(self.root)
        release.check("Thing", "0.1.0", root=self.root)
        release.check("Thing", "0.1.0\r", root=self.root)  # Windows shells leave a trailing CR
        with self.assertRaises(release.ReleaseError) as e:
            release.check("Thing", "0.1.1", root=self.root)
        self.assertIn("0.1.0", str(e.exception))

    def test_check_needs_changelog_section(self):
        make_addon(self.root, version="0.3.0")
        with self.assertRaises(release.ReleaseError) as e:
            release.check("Thing", "0.3.0", root=self.root)
        self.assertIn("CHANGELOG", str(e.exception))

    def test_upload_needs_project_id(self):
        make_addon(self.root, project_id=None)
        with self.assertRaises(release.ReleaseError) as e:
            release.upload("Thing", token="t", root=self.root, opener=FakeOpener([]))
        self.assertIn("X-Curse-Project-ID", str(e.exception))

    def test_upload_needs_token(self):
        make_addon(self.root)
        with self.assertRaises(release.ReleaseError) as e:
            release.upload("Thing", token="", root=self.root, opener=FakeOpener([]))
        self.assertIn("CF_API_TOKEN", str(e.exception))

    def test_upload_sends_file(self):
        make_addon(self.root)
        opener = FakeOpener([{"id": 7, "name": "1.15.9"}, {"id": 8, "name": "1.15.8"}])
        file_id = release.upload("Thing", token="secret", root=self.root, opener=opener)
        self.assertEqual(file_id, 999)
        versions_req, upload_req = opener.requests
        self.assertEqual(versions_req.full_url, "https://wow.curseforge.com/api/game/versions")
        self.assertEqual(upload_req.full_url, "https://wow.curseforge.com/api/projects/123456/upload-file")
        self.assertEqual(upload_req.get_header("X-api-token"), "secret")
        body = upload_req.data
        meta = json.loads(body.split(b'name="metadata"\r\n\r\n')[1].split(b"\r\n--")[0])
        self.assertEqual(meta, {
            "changelog": "First release.\n\n- One thing.",
            "changelogType": "markdown",
            "displayName": "Thing 0.1.0",
            "gameVersions": [7],
            "releaseType": "release",
        })
        self.assertIn(b"PK fake zip", body)

    def test_dry_run_sends_nothing(self):
        make_addon(self.root)
        opener = FakeOpener([])
        meta = release.upload("Thing", token="", root=self.root, opener=opener, dry_run=True)
        self.assertEqual(opener.requests, [])
        self.assertEqual(meta["displayName"], "Thing 0.1.0")
        self.assertEqual(meta["gameVersionNames"], ["1.15.9"])


if __name__ == "__main__":
    unittest.main()
