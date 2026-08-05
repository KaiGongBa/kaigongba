#!/usr/bin/env python3
"""Offline integrity verification for Kai Gong Ba backup sets."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True)
class Verification:
    name: str
    passed: bool
    detail: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checksum_entries(backup_set: Path) -> dict[Path, str]:
    checksum_file = backup_set / "SHA256SUMS"
    entries: dict[Path, str] = {}
    for line in checksum_file.read_text().splitlines():
        if not line.strip():
            continue
        digest, separator, raw_path = line.partition("  ")
        if not separator:
            raise ValueError(f"invalid SHA256SUMS line: {line!r}")
        relative = Path(raw_path.removeprefix("./"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe checksum path: {raw_path}")
        entries[relative] = digest
    return entries


def _safe_tar(path: Path) -> Verification:
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            for member in members:
                name = PurePosixPath(member.name)
                if name.is_absolute() or ".." in name.parts or member.issym() or member.islnk():
                    return Verification("files-archive", False, f"unsafe member: {member.name}")
    except (OSError, tarfile.TarError) as exc:
        return Verification("files-archive", False, str(exc))
    return Verification("files-archive", bool(members), f"members={len(members)}")


def _pg_dump(path: Path) -> Verification:
    with path.open("rb") as stream:
        header = stream.read(5)
    if header != b"PGDMP":
        return Verification(f"postgres-{path.stem}", False, "not a PostgreSQL custom dump")
    executable = shutil.which("pg_restore")
    if not executable:
        return Verification(f"postgres-{path.stem}", True, "PGDMP header valid; pg_restore unavailable")
    result = subprocess.run(
        [executable, "--list", str(path)], capture_output=True, text=True, check=False
    )
    return Verification(
        f"postgres-{path.stem}",
        result.returncode == 0,
        f"pg_restore_exit={result.returncode}",
    )


def _redis_rdb(path: Path) -> Verification:
    with path.open("rb") as stream:
        header = stream.read(5)
    if header != b"REDIS":
        return Verification("redis-rdb", False, "missing REDIS header")
    executable = shutil.which("redis-check-rdb")
    if not executable:
        return Verification("redis-rdb", True, "REDIS header valid; redis-check-rdb unavailable")
    result = subprocess.run([executable, str(path)], capture_output=True, text=True, check=False)
    return Verification("redis-rdb", result.returncode == 0, f"redis-check-rdb_exit={result.returncode}")


def verify(backup_set: Path, max_age_hours: float, require_redis: bool = False) -> dict[str, Any]:
    backup_set = backup_set.resolve()
    checks: list[Verification] = []
    checksum_file = backup_set / "SHA256SUMS"
    checks.append(Verification("checksum-manifest-present", checksum_file.is_file(), str(checksum_file)))
    checks.append(
        Verification("backup-completed", not (backup_set / "FAILED").exists(), "FAILED marker absent")
    )
    if not checksum_file.is_file():
        return _report(backup_set, checks)

    try:
        entries = _checksum_entries(backup_set)
    except (OSError, ValueError) as exc:
        checks.append(Verification("checksum-manifest-parse", False, str(exc)))
        return _report(backup_set, checks)
    checks.append(Verification("checksum-manifest-parse", bool(entries), f"entries={len(entries)}"))
    symlinks = [path.relative_to(backup_set) for path in backup_set.rglob("*") if path.is_symlink()]
    checks.append(
        Verification("backup-has-no-symlinks", not symlinks, f"symlinks={len(symlinks)}")
    )
    actual_files = {
        path.relative_to(backup_set)
        for path in backup_set.rglob("*")
        if path.is_file() and path.name not in {"SHA256SUMS", "FAILED"}
    }
    checks.append(
        Verification(
            "checksum-coverage",
            set(entries) == actual_files,
            f"listed={len(entries)} actual={len(actual_files)}",
        )
    )
    for relative, expected in entries.items():
        path = backup_set / relative
        checks.append(
            Verification(
                f"sha256:{relative.as_posix()}",
                path.is_file() and not path.is_symlink() and _sha256(path) == expected,
                "ok" if path.is_file() else "missing",
            )
        )

    manifest_path = backup_set / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text())
            manifest = loaded if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            manifest = {}
    checks.append(Verification("metadata-manifest", bool(manifest), str(manifest_path)))
    created_at = manifest.get("createdAt")
    try:
        created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        age_hours = (datetime.now(UTC) - created.astimezone(UTC)).total_seconds() / 3600
        fresh = age_hours <= max_age_hours
        detail = f"age_hours={age_hours:.2f} max={max_age_hours:.2f}"
    except (TypeError, ValueError):
        fresh = False
        detail = f"invalid createdAt={created_at!r}"
    checks.append(Verification("backup-freshness", fresh, detail))

    postgres_dumps = sorted((backup_set / "postgres").glob("*.dump"))
    checks.append(Verification("postgres-dump-present", bool(postgres_dumps), f"count={len(postgres_dumps)}"))
    checks.extend(_pg_dump(path) for path in postgres_dumps)

    archives = sorted((backup_set / "files").glob("*.tar.gz"))
    if archives:
        checks.extend(_safe_tar(path) for path in archives)
    objects_dir = backup_set / "objects"
    object_files = [path for path in objects_dir.rglob("*") if path.is_file()] if objects_dir.is_dir() else []
    checks.append(
        Verification(
            "file-or-object-backup-present",
            bool(archives) or objects_dir.is_dir(),
            f"archives={len(archives)} objects={len(object_files)}",
        )
    )
    rdb = backup_set / "redis" / "dump.rdb"
    if rdb.is_file():
        checks.append(_redis_rdb(rdb))
    elif manifest.get("profile") == "split" or manifest.get("redis") or require_redis:
        checks.append(Verification("redis-rdb", False, "required but missing"))

    return _report(backup_set, checks)


def _report(backup_set: Path, checks: list[Verification]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "backupSet": str(backup_set),
        "passed": all(item.passed for item in checks),
        "checks": [asdict(item) for item in checks],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证开工吧备份集完整性与可恢复格式")
    parser.add_argument("backup_set", type=Path)
    parser.add_argument("--max-age-hours", type=float, default=30.0)
    parser.add_argument("--require-redis", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.backup_set, args.max_age_hours, args.require_redis)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    print(payload, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
