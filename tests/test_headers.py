from io import BytesIO
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from ghuzzle import ghuzzle


class PackagedHeadersTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.build = self.root / "dist"
        self.archives = {}

        for patcher in (
            patch.object(ghuzzle, "Github"),
            patch.object(ghuzzle, "_get_temp_dir", return_value=str(self.root)),
            patch.object(ghuzzle, "_find_asset", side_effect=self.find_asset),
            patch.object(ghuzzle, "_download_asset", side_effect=self.download_asset),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def package(self, repo, files, suffix=".zip", **options):
        archive = self.root / f"package-{len(self.archives)}{suffix}"
        if suffix == ".zip":
            with zipfile.ZipFile(archive, "w") as output:
                for name, content in files.items():
                    output.writestr(name, content)
        else:
            modes = {
                ".tar": "w",
                ".tar.gz": "w:gz",
                ".tgz": "w:gz",
                ".tar.bz2": "w:bz2",
                ".tar.xz": "w:xz",
            }
            with tarfile.open(archive, modes[suffix]) as output:
                for name, content in files.items():
                    member = tarfile.TarInfo(name)
                    member.size = len(content)
                    output.addfile(member, BytesIO(content))
        self.archives[repo] = archive
        return {"repo": repo, "asset-pattern": archive.name, **options}

    def find_asset(self, client, repo, tag, asset_pattern):
        return ghuzzle.FindResult(
            repo,
            asset=SimpleNamespace(name=self.archives[repo].name),
            asset_ok=True,
        )

    def download_asset(self, repo, asset, temp_dir, token):
        return str(self.archives[repo])

    def assemble(self, config, ignore_dep_error=False):
        with self.assertLogs(ghuzzle.logger, level="INFO"):
            return ghuzzle.download_and_extract(
                config, str(self.build), None, ignore_dep_error
            )

    def seed_headers(self, content):
        self.build.mkdir(parents=True, exist_ok=True)
        (self.build / "_headers").write_bytes(content)

    def test_subdirectory_package_preserves_rules_and_assets(self):
        headers = (
            "# Café headers\r\n/cgf/*\r\n    Cache-Control: no-cache\r\n"
            "https://example.com/*\n    X-Test: unchanged\n"
        ).encode()
        config = self.package(
            "owner/app",
            {
                "_headers": headers,
                "index.html": b"<html>App</html>",
                "assets/app.js": b"console.log('app');",
            },
            dest="apps/cgf",
        )

        results = self.assemble([config])

        self.assertEqual((self.build / "_headers").read_bytes(), headers)
        self.assertFalse((self.build / "apps/cgf/_headers").exists())
        self.assertEqual(
            (self.build / "apps/cgf/index.html").read_bytes(), b"<html>App</html>"
        )
        self.assertEqual(
            (self.build / "apps/cgf/assets/app.js").read_bytes(), b"console.log('app');"
        )
        self.assertTrue(results[0][ghuzzle.SUMMARY_KEY_DOWNLOAD_OK])

    def test_all_supported_tar_formats(self):
        for suffix in (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz"):
            with self.subTest(suffix=suffix):
                self.build = self.root / f"dist-{suffix}"
                headers = b"/app/*\n    X-Test: tar\n"
                config = self.package(
                    f"owner/app-{suffix}",
                    {"_headers": headers, "index.html": b"app"},
                    suffix=suffix,
                    dest="app",
                )

                self.assemble([config])

                self.assertEqual((self.build / "_headers").read_bytes(), headers)
                self.assertFalse((self.build / "app/_headers").exists())
                self.assertEqual((self.build / "app/index.html").read_bytes(), b"app")

    def test_existing_root_preserved_with_blank_line_separator(self):
        for existing, separator in (
            (b"", b""),
            (b"# Existing", b"\n\n"),
            (b"# Existing\n", b"\n"),
            (b"# Existing\n\n", b""),
            (b"# Existing\r\n", b"\r\n"),
            (b"# Existing\r\n\r\n", b""),
        ):
            with self.subTest(existing=existing):
                self.seed_headers(existing)
                headers = b"/app/*\n    X-Test: package"
                config = self.package(
                    f"owner/app-{len(self.archives)}", {"_headers": headers}, dest="app"
                )

                self.assemble([config])

                self.assertEqual(
                    (self.build / "_headers").read_bytes(),
                    existing + separator + headers,
                )

    def test_multiple_packages_keep_order_and_duplicate_rules(self):
        existing = b"/*\n    X-Test: existing"
        first = b"/*\n    X-Test: package"
        second = first + b"\n# Second package\n"
        self.seed_headers(existing)
        config = [
            self.package("owner/first", {"_headers": first}, dest="first"),
            self.package("owner/second", {"_headers": second}, dest="second"),
        ]

        self.assemble(config)

        self.assertEqual(
            (self.build / "_headers").read_bytes(),
            existing + b"\n\n" + first + b"\n\n" + second,
        )

    def test_root_destination_does_not_overwrite_existing_headers(self):
        for destination in (None, "."):
            with self.subTest(destination=destination):
                existing = b"# Existing root rules\n"
                headers = b"/*\n    X-Test: root\n"
                self.seed_headers(existing)
                config = self.package(
                    f"owner/root-{len(self.archives)}",
                    {"_headers": headers, "index.html": b"root app"},
                    **({"dest": destination} if destination else {}),
                )

                self.assemble([config])

                self.assertEqual(
                    (self.build / "_headers").read_bytes(), existing + b"\n" + headers
                )
                self.assertEqual((self.build / "index.html").read_bytes(), b"root app")

    def test_dir_content_collects_headers_after_flattening(self):
        headers = b"/app/*\n    X-Test: flattened\n"
        config = self.package(
            "owner/wrapped",
            {"release/_headers": headers, "release/index.html": b"wrapped app"},
            dest="app",
            **{"dir-content": True},
        )

        self.assemble([config])

        self.assertEqual((self.build / "_headers").read_bytes(), headers)
        self.assertFalse((self.build / "app/_headers").exists())
        self.assertFalse((self.build / "app/release").exists())
        self.assertEqual((self.build / "app/index.html").read_bytes(), b"wrapped app")

    def test_missing_or_empty_headers_leave_root_untouched(self):
        for package_headers in (None, b""):
            for existing in (None, b"# Root rules without a newline"):
                with self.subTest(package_headers=package_headers, existing=existing):
                    self.build = self.root / f"dist-{len(self.archives)}"
                    if existing is not None:
                        self.seed_headers(existing)
                    files = {"index.html": b"app"}
                    if package_headers is not None:
                        files["_headers"] = package_headers
                    config = self.package(
                        f"owner/app-{len(self.archives)}", files, dest="app"
                    )

                    self.assemble([config])

                    if existing is None:
                        self.assertFalse((self.build / "_headers").exists())
                    else:
                        self.assertEqual(
                            (self.build / "_headers").read_bytes(), existing
                        )
                    self.assertFalse((self.build / "app/_headers").exists())

    def test_nested_headers_are_copied_without_promotion(self):
        headers = b"/nested/*\n    X-Test: nested\n"
        config = self.package(
            "owner/nested",
            {"release/_headers": headers, "release/index.html": b"nested app"},
            dest="app",
        )

        self.assemble([config])

        self.assertFalse((self.build / "_headers").exists())
        self.assertEqual((self.build / "app/release/_headers").read_bytes(), headers)

    def test_extract_false_copies_archive_without_collecting_headers(self):
        existing = b"# Root rules\n"
        self.seed_headers(existing)
        config = self.package(
            "owner/archive",
            {"_headers": b"/*\n    X-Test: archive\n"},
            dest="downloads",
            extract=False,
        )
        archive = self.archives[config["repo"]]

        self.assemble([config])

        self.assertEqual((self.build / "_headers").read_bytes(), existing)
        self.assertEqual(
            (self.build / "downloads" / archive.name).read_bytes(), archive.read_bytes()
        )

    def test_repeated_runs_append_rules_again(self):
        headers = b"/app/*\n    X-Test: repeated\n"
        config = self.package("owner/app", {"_headers": headers}, dest="app")

        self.assemble([config])
        self.assemble([config])

        self.assertEqual(
            (self.build / "_headers").read_bytes(), headers + b"\n" + headers
        )

    def test_header_read_failure_aborts_dependency(self):
        existing = b"# Existing rules\n"
        self.seed_headers(existing)
        config = self.package("owner/app", {"_headers": b"# Package"}, dest="app")

        with patch.object(
            Path, "read_bytes", side_effect=PermissionError("read denied")
        ):
            with self.assertRaisesRegex(ghuzzle.FatalDependencyError, "read denied"):
                self.assemble([config])

        self.assertEqual((self.build / "_headers").read_bytes(), existing)

    def test_header_write_failure_aborts_dependency(self):
        self.build.mkdir()
        (self.build / "_headers").mkdir()
        config = self.package("owner/app", {"_headers": b"# Package"}, dest="app")

        with self.assertRaises(ghuzzle.FatalDependencyError) as caught:
            self.assemble([config])

        self.assertIsInstance(caught.exception.__cause__, IsADirectoryError)

    def test_ignored_merge_failure_records_failure_and_continues(self):
        existing = b"# Root\n"
        good_headers = b"/good/*\n    X-Test: good\n"
        self.seed_headers(existing)
        config = [
            self.package("owner/bad", {"_headers": b"# Bad"}, dest="bad"),
            self.package("owner/good", {"_headers": good_headers}, dest="good"),
        ]
        original_read = Path.read_bytes
        reads = 0

        def fail_first_read(path):
            nonlocal reads
            reads += 1
            if reads == 1:
                raise PermissionError("read denied")
            return original_read(path)

        with patch.object(Path, "read_bytes", fail_first_read):
            results = self.assemble(config, ignore_dep_error=True)

        self.assertFalse(results[0][ghuzzle.SUMMARY_KEY_DOWNLOAD_OK])
        self.assertTrue(results[1][ghuzzle.SUMMARY_KEY_DOWNLOAD_OK])
        self.assertEqual(
            (self.build / "_headers").read_bytes(), existing + b"\n" + good_headers
        )

    def test_copy_failure_does_not_merge_package_headers(self):
        existing = b"# Existing rules\n"
        self.seed_headers(existing)
        config = self.package(
            "owner/app", {"_headers": b"# Package", "index.html": b"app"}, dest="app"
        )

        with patch.object(ghuzzle.shutil, "copy2", side_effect=OSError("copy failed")):
            with self.assertRaisesRegex(ghuzzle.FatalDependencyError, "copy failed"):
                self.assemble([config])

        self.assertEqual((self.build / "_headers").read_bytes(), existing)


if __name__ == "__main__":
    unittest.main()
