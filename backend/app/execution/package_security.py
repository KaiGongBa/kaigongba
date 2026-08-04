from __future__ import annotations

import re
import stat
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from zipfile import BadZipFile, ZipFile

from app.config import get_settings

TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".sh",
    ".ps1",
}
BLOCKED_BINARY_SUFFIXES = {".exe", ".dll", ".dylib", ".so", ".class", ".jar"}
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "generic_api_key": re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}"
    ),
}
CODE_SIGNALS = {
    "process_spawn": re.compile(r"\b(?:subprocess\.|os\.system\(|child_process\.|execSync\()"),
    "network_access": re.compile(r"\b(?:requests\.|httpx\.|fetch\(|axios\.|socket\.)"),
    "dynamic_code": re.compile(r"\b(?:eval\(|exec\(|Function\()"),
}


@dataclass(frozen=True)
class PackageScanResult:
    passed: bool
    risk_level: str
    report: dict[str, Any]


def classify_permission_risk(permissions: dict[str, Any]) -> str:
    values = " ".join(_active_permission_tokens(permissions)).lower()
    high = (
        "shell",
        "process",
        "secret",
        "credential",
        "delete",
        "payment",
        "contract",
        "production",
        "message:send",
    )
    medium = ("network", "filesystem:write", "file:write", "webhook", "email")
    if any(token in values for token in high):
        return "high"
    if any(token in values for token in medium):
        return "medium"
    return "low"


def scan_skill_package(
    data: bytes,
    *,
    filename: str,
    runtime: str,
    entrypoint: str,
    permissions: dict[str, Any],
) -> PackageScanResult:
    settings = get_settings()
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    signals: list[dict[str, str]] = []
    files: list[dict[str, Any]] = []
    if not filename.lower().endswith(".zip"):
        errors.append({"code": "archive_type", "message": "托管 Skill 包必须为 .zip"})
    if len(data) > settings.skill_package_max_bytes:
        errors.append({"code": "archive_size", "message": "压缩包超过平台大小上限"})
    try:
        archive = ZipFile(BytesIO(data))
    except BadZipFile:
        errors.append({"code": "invalid_zip", "message": "文件不是有效 ZIP 压缩包"})
        return PackageScanResult(
            passed=False,
            risk_level=classify_permission_risk(permissions),
            report=_report(filename, files, errors, warnings, signals, 0),
        )

    infos = archive.infolist()
    if len(infos) > settings.skill_package_max_files:
        errors.append({"code": "too_many_files", "message": "压缩包文件数量超过上限"})
    total_uncompressed = sum(item.file_size for item in infos)
    if total_uncompressed > settings.skill_package_max_uncompressed_bytes:
        errors.append({"code": "uncompressed_size", "message": "解压后总大小超过上限"})

    normalized_names: set[str] = set()
    for info in infos:
        raw_name = info.filename.replace("\\", "/")
        path = PurePosixPath(raw_name)
        normalized = str(path)
        if path.is_absolute() or ".." in path.parts or normalized.startswith("/"):
            errors.append({"code": "zip_slip", "message": f"非法归档路径：{raw_name}"})
            continue
        if _is_symlink(info):
            errors.append({"code": "symlink", "message": f"压缩包不得包含符号链接：{raw_name}"})
            continue
        if info.is_dir():
            continue
        normalized_names.add(normalized)
        suffix = path.suffix.lower()
        if suffix in BLOCKED_BINARY_SUFFIXES:
            errors.append({"code": "binary", "message": f"不允许的可执行/二进制文件：{raw_name}"})
        if info.flag_bits & 0x1:
            errors.append({"code": "encrypted", "message": f"不允许加密文件：{raw_name}"})
        if info.compress_size and info.file_size > 1_048_576:
            ratio = info.file_size / max(1, info.compress_size)
            if ratio > 200:
                errors.append({"code": "compression_bomb", "message": f"异常压缩比：{raw_name}"})
        files.append(
            {
                "path": normalized,
                "size": info.file_size,
                "compressed_size": info.compress_size,
            }
        )
        is_sensitive_text_name = path.name.lower() in {".env", ".npmrc", ".pypirc"}
        if (suffix not in TEXT_SUFFIXES and not is_sensitive_text_name) or info.file_size > 1_048_576:
            continue
        try:
            text = archive.read(info).decode("utf-8", errors="replace")
        except RuntimeError:
            continue
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append({"code": "secret_detected", "message": f"{raw_name} 疑似包含 {name}"})
        for name, pattern in CODE_SIGNALS.items():
            if pattern.search(text):
                signals.append({"code": name, "path": normalized})

    lowered = {name.lower() for name in normalized_names}
    if not any(name == "skill.md" or name.endswith("/skill.md") for name in lowered):
        errors.append({"code": "missing_skill_md", "message": "压缩包必须包含 SKILL.md"})
    clean_entrypoint = str(PurePosixPath(entrypoint.replace("\\", "/")))
    if runtime in {"python", "node"} and clean_entrypoint not in normalized_names:
        errors.append({"code": "missing_entrypoint", "message": f"入口文件不存在：{entrypoint}"})

    declared = " ".join(_permission_tokens(permissions)).lower()
    if any(item["code"] == "network_access" for item in signals) and (
        "network" not in declared or "deny" in declared
    ):
        errors.append({"code": "undeclared_network", "message": "代码包含网络访问，但权限未声明允许"})
    if any(item["code"] == "process_spawn" for item in signals) and "shell" not in declared:
        warnings.append({"code": "undeclared_process", "message": "代码包含子进程调用，需人工复核"})

    risk_level = classify_permission_risk(permissions)
    if any(item["code"] in {"process_spawn", "dynamic_code"} for item in signals):
        risk_level = "high"
    elif signals and risk_level == "low":
        risk_level = "medium"
    return PackageScanResult(
        passed=not errors,
        risk_level=risk_level,
        report=_report(filename, files, errors, warnings, signals, total_uncompressed),
    )


def _permission_tokens(value: Any) -> list[str]:
    if isinstance(value, dict):
        result: list[str] = []
        for key, item in value.items():
            result.append(str(key))
            result.extend(_permission_tokens(item))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_permission_tokens(item))
        return result
    return [str(value)]


def _active_permission_tokens(value: Any) -> list[str]:
    if isinstance(value, dict):
        result: list[str] = []
        for key, item in value.items():
            inactive = item is None or item is False or item in ("", "deny", "denied", "none")
            inactive = inactive or (isinstance(item, (list, dict)) and not item)
            if inactive:
                continue
            result.append(str(key))
            result.extend(_active_permission_tokens(item))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_active_permission_tokens(item))
        return result
    return [str(value)]


def _is_symlink(info: Any) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_IFMT(mode) == stat.S_IFLNK


def _report(
    filename: str,
    files: list[dict[str, Any]],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
    signals: list[dict[str, str]],
    total_uncompressed: int,
) -> dict[str, Any]:
    return {
        "scanner_version": "3j-static-v1",
        "filename": filename,
        "file_count": len(files),
        "uncompressed_bytes": total_uncompressed,
        "files": files,
        "errors": errors,
        "warnings": warnings,
        "signals": signals,
    }
