"""Command-line entry point for repository-owned research workflows."""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from .baseline import compare_reference, run_baseline
from .boundary import require_is_window
from .conservative_baseline import (
    compare_conservative_reference,
    run_conservative_comparison,
)
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
    compare = commands.add_parser("compare", help="运行保守口径并对比旧基线")
    compare.add_argument("--spec", type=Path, required=True)
    compare.add_argument("--research-root", type=Path, required=True)
    compare.add_argument("--market-data-root", type=Path, required=True)
    compare.add_argument("--legacy-reference", type=Path, required=True)
    compare.add_argument("--conservative-reference", type=Path)
    compare.add_argument("--output", type=Path, required=True)
    migrate = commands.add_parser(
        "migrate-candidate", help="把受信 IS pickle 迁移为候选 JSON"
    )
    migrate.add_argument("--input-pickle", type=Path, required=True)
    migrate.add_argument("--output", type=Path, required=True)
    migrate.add_argument("--symbol", required=True)
    migrate.add_argument("--stack", required=True)
    migrate.add_argument(
        "--entry-kind",
        choices=("strategy_fill", "signal_intent"),
        required=True,
    )
    migrate.add_argument("--begin", required=True)
    migrate.add_argument("--end-exclusive", required=True)
    migrate.add_argument(
        "--timestamp-offset-seconds", type=int, required=True
    )
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


def _run_compare(args: argparse.Namespace) -> int:
    legacy_reference = _load_reference(args.legacy_reference)
    report = run_conservative_comparison(
        args.spec,
        research_root=args.research_root,
        market_data_root=args.market_data_root,
        legacy_reference=legacy_reference,
    )
    if args.conservative_reference is not None:
        conservative_reference = _load_reference(
            args.conservative_reference
        )
        mismatches = compare_conservative_reference(
            report, conservative_reference
        )
        if mismatches:
            details = json.dumps(
                mismatches, ensure_ascii=False, sort_keys=True
            )
            raise ValueError(f"保守参考不一致: {details}")
    _write_atomic(args.output, canonical_json_bytes(report))
    result = report["conservative"]
    print(
        "保守回测通过: "
        f"{report['strategy_id']} {report['execution_model']} "
        f"risk={result['risk_pct']:.4f} "
        f"CAGR={result['is_2125']['cagr']:.6f} "
        f"DD={result['is_2125']['full_dd']:.6f} "
        f"报告={args.output}"
    )
    return 0


def _run_migrate_candidate(args: argparse.Namespace) -> int:
    from .migrate_candidate import migrate_candidate_pickle

    begin_ts, end_ts = require_is_window(args.begin, args.end_exclusive)
    envelope = migrate_candidate_pickle(
        args.input_pickle,
        args.output,
        symbol=args.symbol,
        stack=args.stack,
        entry_kind=args.entry_kind,
        begin_ts=begin_ts,
        end_ts=end_ts,
        timestamp_offset_seconds=args.timestamp_offset_seconds,
    )
    print(
        "候选迁移通过: "
        f"{args.symbol} {args.stack} "
        f"rows={len(envelope['trades'])} "
        f"offset={args.timestamp_offset_seconds}s 报告={args.output}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "baseline":
            return _run_baseline(args)
        if args.command == "compare":
            return _run_compare(args)
        if args.command == "migrate-candidate":
            return _run_migrate_candidate(args)
        raise ValueError(f"unsupported command: {args.command}")
    except Exception as exc:
        print(f"研究基线失败: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
