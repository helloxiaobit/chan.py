"""Command-line entry point for repository-owned research workflows."""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from .baseline import compare_reference, run_baseline
from .provenance import canonical_json_bytes
from .spec import load_spec


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="chan.py 可复现研究入口")
    commands = parser.add_subparsers(dest="command", required=True)
    baseline = commands.add_parser("baseline", help="复现样本内冻结基线")
    baseline.add_argument("--spec", type=Path, required=True)
    baseline.add_argument("--research-root", type=Path, required=True)
    baseline.add_argument("--reference", type=Path, required=True)
    baseline.add_argument("--output", type=Path, required=True)
    return parser


def _load_reference(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("reference must contain a JSON object")
    return value


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _run_baseline(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    report = run_baseline(spec, args.research_root)
    reference = _load_reference(args.reference)
    mismatches = compare_reference(report, reference)
    if mismatches:
        details = json.dumps(mismatches, ensure_ascii=False, sort_keys=True)
        raise ValueError(f"基线参考不一致: {details}")
    _write_atomic(args.output, canonical_json_bytes(report))
    result = report["result"]
    print(
        "基线复现通过: "
        f"{report['strategy_id']} {report['execution_model']} "
        f"risk={result['risk_pct']:.4f} "
        f"CAGR={result['is_2125']['cagr']:.6f} "
        f"报告={args.output}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "baseline":
            return _run_baseline(args)
        raise ValueError(f"unsupported command: {args.command}")
    except Exception as exc:
        print(f"研究基线失败: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
