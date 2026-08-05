#!/usr/bin/env python3
"""Safely migrate and snapshot private order objects without destructive sync."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.transaction.object_storage import (
    ObjectAlreadyExistsError,
    ObjectNotFoundError,
    get_order_object_store,
)


class ObjectStore(Protocol):
    provider_name: str

    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def read(self, key: str) -> bytes: ...

    def iter_keys(self) -> list[str]: ...


@dataclass(frozen=True)
class ObjectResult:
    key: str
    size: int
    sha256: str
    status: str
    detail: str = ""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_key_path(root: Path, key: str) -> Path:
    pure = PurePosixPath(key)
    if not key or pure.is_absolute() or ".." in pure.parts or "." in pure.parts:
        raise ValueError(f"不安全的对象键：{key!r}")
    target = (root / Path(*pure.parts)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"对象键超出目标目录：{key!r}")
    return target


def migrate_local_objects(source_dir: Path, store: ObjectStore, *, execute: bool) -> dict[str, object]:
    source_dir = source_dir.expanduser().resolve()
    if not source_dir.is_dir():
        raise ValueError(f"源对象目录不存在：{source_dir}")
    results: list[ObjectResult] = []
    for path in sorted(source_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"源对象目录禁止包含符号链接：{path}")
        if not path.is_file():
            continue
        key = path.relative_to(source_dir).as_posix()
        payload = path.read_bytes()
        digest = _digest(payload)
        try:
            remote = store.read(key)
        except ObjectNotFoundError:
            if not execute:
                results.append(ObjectResult(key, len(payload), digest, "planned"))
                continue
            try:
                store.put(key, payload, "application/octet-stream")
            except ObjectAlreadyExistsError:
                remote = store.read(key)
                if remote != payload:
                    results.append(
                        ObjectResult(key, len(payload), digest, "conflict", "remote changed during upload")
                    )
                    continue
            else:
                remote = store.read(key)
            if remote != payload:
                results.append(ObjectResult(key, len(payload), digest, "conflict", "upload hash mismatch"))
            else:
                results.append(ObjectResult(key, len(payload), digest, "uploaded"))
        else:
            status = "unchanged" if remote == payload else "conflict"
            detail = "" if status == "unchanged" else "remote object has different content"
            results.append(ObjectResult(key, len(payload), digest, status, detail))
    return _report("migrate", store.provider_name, execute, results)


def snapshot_objects(store: ObjectStore, target_dir: Path) -> dict[str, object]:
    target_dir = target_dir.expanduser().resolve()
    if target_dir.exists() and any(target_dir.iterdir()):
        raise ValueError(f"快照目标必须不存在或为空：{target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)
    results: list[ObjectResult] = []
    for key in store.iter_keys():
        target = _safe_key_path(target_dir, key)
        payload = store.read(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(payload)
        results.append(ObjectResult(key, len(payload), _digest(payload), "snapshotted"))
    return _report("snapshot", store.provider_name, True, results)


def _report(
    operation: str,
    provider: str,
    executed: bool,
    results: list[ObjectResult],
) -> dict[str, object]:
    conflicts = sum(item.status == "conflict" for item in results)
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "operation": operation,
        "provider": provider,
        "executed": executed,
        "passed": conflicts == 0,
        "objectCount": len(results),
        "totalBytes": sum(item.size for item in results),
        "statusCounts": {
            status: sum(item.status == status for item in results)
            for status in sorted({item.status for item in results})
        },
        "objects": [asdict(item) for item in results],
    }


def _write_report(report: dict[str, object], output: Path | None) -> None:
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output:
        output = output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.tmp")
        temporary.write_text(payload)
        temporary.replace(output)
    print(payload, end="")


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移或快照开工吧私有订单对象")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    migrate = subparsers.add_parser("migrate", help="本地目录幂等迁移到已配置对象存储")
    migrate.add_argument("--source-dir", type=Path, required=True)
    migrate.add_argument("--execute", action="store_true")
    migrate.add_argument("--output", type=Path)
    snapshot = subparsers.add_parser("snapshot", help="将已配置对象存储下载为可校验快照")
    snapshot.add_argument("--target-dir", type=Path, required=True)
    snapshot.add_argument("--output", type=Path)
    args = parser.parse_args()

    settings = get_settings()
    if settings.order_object_storage_provider != "s3":
        parser.error("ORDER_OBJECT_STORAGE_PROVIDER 必须为 s3")
    store = get_order_object_store()
    try:
        if args.operation == "migrate":
            report = migrate_local_objects(args.source_dir, store, execute=args.execute)
        else:
            report = snapshot_objects(store, args.target_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"对象存储操作失败：{exc}", file=sys.stderr)
        return 2
    _write_report(report, args.output)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
