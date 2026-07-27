"""Deterministic serialization and input provenance for research reports."""

import hashlib
import json
import platform
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON deterministically for hashing and stable report output."""
    text = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return f"{text}\n".encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_manifest(path: str | Path) -> dict[str, Any]:
    resolved = Path(path)
    stat = resolved.stat()
    return {
        "size": stat.st_size,
        "sha256": sha256_file(resolved),
    }


def sqlite_kline_manifest(
    path: str | Path,
    symbol: str,
    level: str,
    begin_ms: int,
    end_exclusive_ms: int,
) -> dict[str, Any]:
    """Hash only the selected logical kline rows, never later/OOS rows."""
    db_path = Path(path)
    if not db_path.is_file():
        raise FileNotFoundError(db_path)

    digest = hashlib.sha256()
    row_count = 0
    first_ts = None
    last_ts = None
    with sqlite3.connect(db_path) as connection:
        cursor = connection.execute(
            "select ts, o, h, l, c from kline "
            "where symbol = ? and lv = ? and ts >= ? and ts < ? order by ts",
            (symbol, level, begin_ms, end_exclusive_ms),
        )
        for row in cursor:
            ts = int(row[0])
            if first_ts is None:
                first_ts = ts
            last_ts = ts
            row_count += 1
            digest.update(canonical_json_bytes(list(row)))

    return {
        "symbol": symbol,
        "level": level,
        "begin_ms": begin_ms,
        "end_exclusive_ms": end_exclusive_ms,
        "row_count": row_count,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "sha256": digest.hexdigest(),
    }


def git_provenance(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root)
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = None, None
    return {"commit": commit, "dirty": dirty}


def runtime_provenance() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": sys.platform,
    }
