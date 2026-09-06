import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


try:
    from fastapi.testclient import TestClient
    import dashboard.server as dashboard
except ImportError:  # pragma: no cover - exercised by the dependency-minimal CI job
    TestClient = None
    dashboard = None


@unittest.skipUnless(TestClient is not None, "fastapi test dependencies not installed")
class DashboardUploadSecurityTests(unittest.TestCase):
    def _authenticated_server(self, base: Path):
        base.mkdir(parents=True, exist_ok=True)
        with patch.object(dashboard, "BASE_DIR", base):
            server = dashboard.DashboardServer()
        server._uploads_dir = base / "uploads"
        server._uploads_dir.mkdir()
        client = TestClient(server.app)
        pin = server.new_key()
        token = client.post("/login", json={"pin": pin}).json()["token"]
        return server, client, {"Authorization": f"Bearer {token}"}

    def test_existing_name_is_never_overwritten_by_upload(self):
        if not dashboard._UPLOAD_OK:
            self.skipTest("python-multipart not installed")
        with tempfile.TemporaryDirectory() as tmp:
            server, client, headers = self._authenticated_server(Path(tmp))
            original = server._uploads_dir / "report.txt"
            original.write_bytes(b"original")

            response = client.post(
                "/api/upload",
                headers=headers,
                files={"file": ("report.txt", b"replacement", "text/plain")},
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["name"], "report_1.txt")
            self.assertEqual(original.read_bytes(), b"original")
            self.assertEqual(
                (server._uploads_dir / "report_1.txt").read_bytes(), b"replacement"
            )
            self.assertEqual(
                list(server._uploads_dir.glob(f"{dashboard._UPLOAD_TEMP_PREFIX}*")), []
            )

    def test_concurrent_publications_with_same_name_keep_both_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "uploads"
            root.mkdir()
            barrier = threading.Barrier(2)

            def publish(payload: bytes):
                root_info = dashboard._verified_upload_root(root)
                temp_path, fd, temp_info = dashboard._open_upload_temp(root, root_info)
                try:
                    with os.fdopen(fd, "wb", closefd=True) as handle:
                        handle.write(payload)
                        handle.flush()
                        os.fsync(handle.fileno())
                        written = os.fstat(handle.fileno())
                        barrier.wait(timeout=5)
                        result = dashboard._publish_upload_no_replace(
                            root, root_info, temp_path, written, "same.txt"
                        )
                    return result.name
                finally:
                    dashboard._unlink_if_same(temp_path, temp_info)

            with ThreadPoolExecutor(max_workers=2) as pool:
                names = list(pool.map(publish, (b"first", b"second")))

            self.assertSetEqual(set(names), {"same.txt", "same_1.txt"})
            self.assertSetEqual(
                {(root / name).read_bytes() for name in names}, {b"first", b"second"}
            )

    def test_list_and_download_skip_symlinks_and_stream_regular_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            server, client, headers = self._authenticated_server(base)
            regular = server._uploads_dir / "safe.txt"
            regular.write_bytes(b"safe")
            outside = base / "outside-secret.txt"
            outside.write_bytes(b"secret")
            linked = server._uploads_dir / "linked.txt"
            dangling = server._uploads_dir / "dangling.txt"
            try:
                linked.symlink_to(outside)
                dangling.symlink_to(base / "missing-secret.txt")
            except OSError as exc:
                self.skipTest(f"file symlinks unavailable: {exc}")

            listing = client.get("/api/files", headers=headers)
            self.assertEqual(listing.status_code, 200)
            self.assertEqual(listing.json()["files"], [{"name": "safe.txt", "size": 4}])
            self.assertEqual(
                client.get("/uploads/linked.txt", headers=headers).status_code, 404
            )
            self.assertEqual(
                client.get("/uploads/dangling.txt", headers=headers).status_code, 404
            )
            response = client.get("/uploads/safe.txt", headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"safe")
            self.assertEqual(response.headers["content-length"], "4")

    def test_symlink_upload_root_fails_closed_for_every_endpoint(self):
        if not dashboard._UPLOAD_OK:
            self.skipTest("python-multipart not installed")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            server, client, headers = self._authenticated_server(base)
            real_root = base / "real-uploads"
            real_root.mkdir()
            linked_root = base / "linked-uploads"
            try:
                linked_root.symlink_to(real_root, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")
            server._uploads_dir = linked_root

            self.assertEqual(client.get("/api/files", headers=headers).json(), {"files": []})
            self.assertEqual(
                client.get("/uploads/anything.txt", headers=headers).status_code, 404
            )
            upload = client.post(
                "/api/upload",
                headers=headers,
                files={"file": ("anything.txt", b"blocked", "text/plain")},
            )
            self.assertEqual(upload.status_code, 409)
            self.assertEqual(list(real_root.iterdir()), [])

    def test_windows_reparse_attribute_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actual = os.lstat(root)
            reparse = SimpleNamespace(
                st_mode=actual.st_mode,
                st_dev=actual.st_dev,
                st_ino=actual.st_ino,
                st_file_attributes=dashboard._FILE_ATTRIBUTE_REPARSE_POINT,
            )
            with patch.object(dashboard.os, "lstat", return_value=reparse):
                with self.assertRaises(dashboard._UnsafeUploadPath):
                    dashboard._verified_upload_root(root)

    def test_download_rejects_lstat_fstat_identity_race(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "uploads"
            root.mkdir()
            target = root / "target.txt"
            attacker = root / "attacker.txt"
            target.write_bytes(b"approved")
            attacker.write_bytes(b"attacker")
            real_lstat = os.lstat
            path_calls = 0

            def raced_lstat(path):
                nonlocal path_calls
                if Path(path) == target:
                    path_calls += 1
                    if path_calls > 1:
                        return real_lstat(attacker)
                return real_lstat(path)

            with patch.object(dashboard.os, "lstat", side_effect=raced_lstat):
                with self.assertRaises(dashboard._UnsafeUploadPath):
                    dashboard._open_verified_download(root, target.name)

    def test_download_stream_uses_verified_handle_not_the_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "uploads"
            root.mkdir()
            target = root / "target.txt"
            target.write_bytes(b"verified bytes")
            handle, _ = dashboard._open_verified_download(root, target.name)

            # The path is no longer consulted after the verified handle is returned.
            payload = b"".join(dashboard._stream_file_handle(handle, chunk_size=3))
            self.assertEqual(payload, b"verified bytes")
            self.assertTrue(handle.closed)

    def test_exclusive_temp_open_does_not_follow_an_existing_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "uploads"
            root.mkdir()
            root_info = dashboard._verified_upload_root(root)
            real_open = dashboard.os.open
            observed_flags = []

            def recording_open(path, flags, mode=0o777):
                observed_flags.append(flags)
                return real_open(path, flags, mode)

            with patch.object(dashboard.os, "open", side_effect=recording_open):
                temp_path, fd, temp_info = dashboard._open_upload_temp(root, root_info)
            os.close(fd)
            dashboard._unlink_if_same(temp_path, temp_info)

            self.assertTrue(observed_flags[0] & os.O_EXCL)
            if hasattr(os, "O_NOFOLLOW"):
                self.assertTrue(observed_flags[0] & os.O_NOFOLLOW)


if __name__ == "__main__":
    unittest.main()
