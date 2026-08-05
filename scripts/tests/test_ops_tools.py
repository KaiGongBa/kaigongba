from __future__ import annotations

import hashlib
import http.server
import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


backup_verify = load_script("ops_backup_verify.py")
ops_preflight = load_script("ops_preflight.py")
ops_order_objects = load_script("ops_order_objects.py")


class _MemoryObjectStore:
    provider_name = "memory_private"

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = dict(objects or {})

    def put(self, key: str, data: bytes, _content_type: str) -> None:
        if key in self.objects:
            raise ops_order_objects.ObjectAlreadyExistsError(key)
        self.objects[key] = data

    def read(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError as exc:
            raise ops_order_objects.ObjectNotFoundError(key) from exc

    def iter_keys(self) -> list[str]:
        return sorted(self.objects)


class OrderObjectOperationsTests(unittest.TestCase):
    def test_migration_is_dry_run_idempotent_and_never_overwrites_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            (source / "same.txt").write_bytes(b"same")
            (source / "new.txt").write_bytes(b"new")
            store = _MemoryObjectStore({"same.txt": b"same"})

            report = ops_order_objects.migrate_local_objects(source, store, execute=False)
            self.assertTrue(report["passed"])
            self.assertEqual(report["statusCounts"], {"planned": 1, "unchanged": 1})
            self.assertNotIn("new.txt", store.objects)

            report = ops_order_objects.migrate_local_objects(source, store, execute=True)
            self.assertTrue(report["passed"])
            self.assertEqual(store.objects["new.txt"], b"new")

            (source / "new.txt").write_bytes(b"changed-local")
            report = ops_order_objects.migrate_local_objects(source, store, execute=True)
            self.assertFalse(report["passed"])
            self.assertEqual(store.objects["new.txt"], b"new")

    def test_snapshot_rejects_unsafe_keys_and_writes_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "snapshot"
            report = ops_order_objects.snapshot_objects(
                _MemoryObjectStore({"tenant/order/file.txt": b"evidence"}), target
            )
            self.assertTrue(report["passed"])
            self.assertEqual((target / "tenant/order/file.txt").read_bytes(), b"evidence")

            with self.assertRaisesRegex(ValueError, "不安全"):
                ops_order_objects.snapshot_objects(
                    _MemoryObjectStore({"../outside.txt": b"unsafe"}), Path(directory) / "unsafe"
                )


class BackupVerificationTests(unittest.TestCase):
    def make_set(self, root: Path) -> Path:
        backup_set = root / "set"
        (backup_set / "postgres").mkdir(parents=True)
        (backup_set / "files").mkdir()
        (backup_set / "postgres" / "kgbapp.dump").write_bytes(b"PGDMP-test")
        with tarfile.open(backup_set / "files" / "order-objects.tar.gz", "w:gz") as archive:
            payload = b"verified object"
            info = tarfile.TarInfo("order-objects/example.txt")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        (backup_set / "manifest.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "profile": "all-in-one",
                    "createdAt": datetime.now(UTC).isoformat(),
                }
            )
        )
        lines = []
        for path in sorted(item for item in backup_set.rglob("*") if item.is_file()):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  ./{path.relative_to(backup_set).as_posix()}")
        (backup_set / "SHA256SUMS").write_text("\n".join(lines) + "\n")
        return backup_set

    def test_accepts_complete_fresh_set_and_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            backup_verify.shutil, "which", return_value=None
        ):
            backup_set = self.make_set(Path(directory))
            report = backup_verify.verify(backup_set, 1)
            self.assertTrue(report["passed"])

            report = backup_verify.verify(backup_set, 1, require_redis=True)
            self.assertFalse(report["passed"])
            self.assertTrue(
                any(item["name"] == "redis-rdb" and not item["passed"] for item in report["checks"])
            )

            (backup_set / "postgres" / "kgbapp.dump").write_bytes(b"tampered")
            report = backup_verify.verify(backup_set, 1)
            self.assertFalse(report["passed"])
            self.assertTrue(
                any(item["name"].startswith("sha256:") and not item["passed"] for item in report["checks"])
            )

    def test_rejects_failed_or_unsafe_file_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            backup_verify.shutil, "which", return_value=None
        ):
            backup_set = self.make_set(Path(directory))
            with tarfile.open(backup_set / "files" / "order-objects.tar.gz", "w:gz") as archive:
                payload = b"unsafe"
                info = tarfile.TarInfo("../outside.txt")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            (backup_set / "FAILED").write_text("failed")
            report = backup_verify.verify(backup_set, 1)
            self.assertFalse(report["passed"])
            self.assertTrue(any(item["name"] == "backup-completed" and not item["passed"] for item in report["checks"]))
            self.assertTrue(any(item["name"] == "files-archive" and not item["passed"] for item in report["checks"]))


class _PreflightHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        headers = {
            "Strict-Transport-Security": "max-age=31536000",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "SAMEORIGIN",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "X-Request-ID": "test-request-id",
        }
        if self.path == "/api/health":
            self.respond(200, {"status": "ok"}, headers)
        elif self.path == "/api/ready":
            self.respond(
                200,
                {"status": "ready", "dependencies": {"database": "ok", "redis": "ok", "objects": "ok"}},
                headers,
            )
        elif self.path.startswith("/api/internal/"):
            self.respond(404, {"detail": "not found"}, headers)
        else:
            body = b"<html><body>ok</body></html>"
            self.send_response(200)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def respond(self, status: int, payload: dict[str, object], headers: dict[str, str]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class PreflightTests(unittest.TestCase):
    def test_split_preflight_passes_with_all_dependencies_and_headers(self) -> None:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _PreflightHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            report = ops_preflight.run(
                f"http://127.0.0.1:{server.server_port}", "split", 2, 21
            )
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
        self.assertTrue(report["passed"])
        self.assertEqual(report["errorCount"], 0)

    def test_combined_worker_requires_configured_runtime_dependencies(self) -> None:
        headers = {
            "Strict-Transport-Security": "max-age=31536000",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "SAMEORIGIN",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "X-Request-ID": "request-id",
            "Content-Type": "application/json",
        }

        def fake_request(_base_url: str, path: str, _timeout: float):
            if path == "/api/health":
                return 200, headers, json.dumps({"status": "ok"}).encode()
            if path == "/api/ready":
                return 200, headers, json.dumps(
                    {"status": "ready", "dependencies": {"database": "ok", "redis": "not_configured"}}
                ).encode()
            if path.startswith("/api/internal/"):
                return 404, headers, b"{}"
            root_headers = {**headers, "Content-Type": "text/html"}
            return 200, root_headers, b"<html></html>"

        with patch.object(ops_preflight, "_request", side_effect=fake_request):
            report = ops_preflight.run("http://127.0.0.1:9999", "combined-worker", 2, 21)
        self.assertFalse(report["passed"])
        self.assertTrue(
            any(item["name"] == "dependency-redis" and not item["passed"] for item in report["checks"])
        )


if __name__ == "__main__":
    unittest.main()
