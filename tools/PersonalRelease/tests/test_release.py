import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release


class ReleaseTests(unittest.TestCase):
    def test_beta_channel_moves_to_final(self):
        data = [{"tag_name": tag} for tag in ("v6.20.1", "v6.21.0-beta.2", "v6.21.0")]
        self.assertEqual(release.select_versions(data), ["v6.21.0"])

    def test_beta_and_stable_are_independent(self):
        data = [
            {"tag_name": tag}
            for tag in ("v6.21.1", "v6.22.0-beta.2", "v6.22.0-beta.10", "alpha/v6.23.0")
        ]
        self.assertEqual(release.select_versions(data), ["v6.21.1", "v6.22.0-beta.10"])

    def test_draft_and_nightly_not_published(self):
        data = [
            {"tag_name": "v6.21.1"},
            {"tag_name": "v6.22.0", "draft": True},
            {"tag_name": "v6.23.0-alpha.1"},
            {"tag_name": "nightly"},
        ]
        self.assertEqual(release.select_versions(data), ["v6.21.1"])

    def test_missing_series_must_not_build_official_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "Patch series missing"):
                release.patch_paths(Path(temp))

    def test_patch_series_cannot_escape_maintenance_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "personal/patches").mkdir(parents=True)
            (root / "personal/patches/series").write_text("../../outside.patch\n")
            (root / "outside.patch").write_text("not a patch")
            with self.assertRaisesRegex(ValueError, "Invalid patch"):
                release.patch_paths(root)

    def test_corrupt_archive_path_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with zipfile.ZipFile(root / "bad.zip", "w") as archive:
                archive.writestr("repo/../../outside", "bad")
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                release.extract_repository(root / "bad.zip", root / "expanded")
            self.assertFalse((root / "outside").exists())

    def test_incomplete_application_never_packages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release.write(root / "job.json", {"kind": "app"})
            release.write(root / "personal-build.json", {})
            with self.assertRaisesRegex(ValueError, "Incomplete install"):
                release.package(root)
            self.assertEqual(list((root / "artifacts").iterdir()), [])

    def test_missing_artifacts_never_create_release_or_push_tag(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "artifacts").mkdir()
            release.write(root / "job.json", {"kind": "app"})
            with (
                patch.object(release, "git") as git,
                patch.object(release.subprocess, "run") as run,
            ):
                with self.assertRaisesRegex(ValueError, "Expected ZIP"):
                    release.publish(root, {}, root)
                git.assert_not_called()
                run.assert_not_called()

    def test_complete_package_hash_and_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            identity = {"schemaVersion": 1, "upstreamVersion": "v6.21.1", "revision": 1}
            release.write(root / "job.json", {"kind": "app"})
            release.write(root / "personal-build.json", identity)
            install = root / "install"
            for name in (
                "MAA.exe",
                "MAA.dll",
                "MaaCore.dll",
                "MAA.Updater.exe",
                "MaaAdbControlUnit.dll",
                "MaaWin32ControlUnit.dll",
                "resource/tasks/tasks.json",
                "resource/version.json",
                "personal/resource/cultivation.json",
            ):
                path = install / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("test")
            release.package(root)
            manifest = release.read(root / "artifacts/personal-release.json")
            package = manifest["packages"]["win-x64"]
            archive_path = root / "artifacts" / package["fileName"]
            self.assertEqual(release.sha256(archive_path), package["sha256"])
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(
                    json.loads(archive.read("personal-build.json")), identity
                )
                self.assertIn("personal/resource/cultivation.json", archive.namelist())
                self.assertNotIn("config/gui.json", archive.namelist())

    def test_published_revision_cannot_silently_change_patches(self):
        config = {
            "upstreamRepository": "upstream/repo",
            "releaseRepository": "me/repo",
            "resourceRepository": "upstream/resources",
            "gameDataRepository": "data/repo",
            "revision": 1,
        }
        with (
            patch.object(release, "patch_digest", return_value="new"),
            patch.object(release, "request_json", return_value={"sha": "a" * 40}),
            patch.object(
                release,
                "releases",
                side_effect=[
                    [{"tag_name": "v6.21.1"}],
                    [{"tag_name": "personal/v6.21.1-r1"}],
                ],
            ),
            patch.object(
                release, "release_asset", return_value={"patchsetHash": "old"}
            ),
        ):
            with self.assertRaisesRegex(ValueError, "Bump revision"):
                release.discover(Path("."), config)

    def test_resource_only_update_keeps_program_identity(self):
        config = {
            "upstreamRepository": "upstream/repo",
            "releaseRepository": "me/repo",
            "resourceRepository": "upstream/resources",
            "gameDataRepository": "data/repo",
            "revision": 3,
        }
        app = {"patchsetHash": "same", "resourceCommit": "old", "gameDataCommit": "old"}
        with (
            patch.object(release, "patch_digest", return_value="same"),
            patch.object(release, "request_json", return_value={"sha": "a" * 40}),
            patch.object(
                release,
                "releases",
                side_effect=[
                    [{"tag_name": "v6.21.1"}],
                    [{"tag_name": "personal/v6.21.1-r3"}],
                ],
            ),
            patch.object(release, "release_asset", return_value=app),
            patch.object(release, "optional_json", return_value=None),
        ):
            jobs = release.discover(Path("."), config)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["kind"], "resource")
        self.assertEqual(jobs[0]["revision"], 3)
        self.assertEqual(jobs[0]["resourceRevision"], 1)

    def test_orphan_tag_resumes_pinned_inputs(self):
        job = {
            "tag": "personal/v6.21.1-r1",
            "patchsetHash": "same",
            "resourceCommit": "new",
        }
        previous = {**job, "resourceCommit": "old"}
        content = base64.b64encode(json.dumps({"buildJob": previous}).encode()).decode()
        with (
            patch.object(
                release, "optional_json", return_value={"object": {"sha": "a" * 40}}
            ),
            patch.object(release, "request_json", return_value={"content": content}),
        ):
            result = release.resume_pending_job({"releaseRepository": "me/repo"}, job)
        self.assertEqual(result["resourceCommit"], "old")
        self.assertEqual(result["resumeSourceTag"], job["tag"])

    def test_upload_retry_reuses_draft(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "artifacts").mkdir()
            for name in ("app.zip", "personal-release.json", "SHA256SUMS"):
                (root / "artifacts" / name).write_text("test")
            release.write(
                root / "job.json",
                {
                    "tag": "personal/v6.21.1-r1",
                    "upstreamVersion": "v6.21.1",
                    "revision": 1,
                    "kind": "app",
                },
            )
            with (
                patch.object(release, "optional_json", return_value={"draft": True}),
                patch.object(release, "git", return_value="a" * 40),
                patch.object(release.subprocess, "run") as run,
            ):
                release.publish(root, {"releaseRepository": "me/repo"}, root)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual([command[2] for command in commands], ["upload", "edit"])
            self.assertIn("--clobber", commands[0])
            self.assertIn("--draft=false", commands[1])

    def test_published_release_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "artifacts").mkdir()
            for name in ("app.zip", "personal-release.json", "SHA256SUMS"):
                (root / "artifacts" / name).write_text("test")
            release.write(root / "job.json", {"tag": "personal/v6.21.1-r1"})
            with (
                patch.object(release, "optional_json", return_value={"draft": False}),
                patch.object(release, "git") as git,
            ):
                with self.assertRaisesRegex(ValueError, "already published"):
                    release.publish(root, {"releaseRepository": "me/repo"}, root)
                git.assert_not_called()


if __name__ == "__main__":
    unittest.main()
