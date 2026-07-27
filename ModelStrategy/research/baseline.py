"""Deterministic freeze-v4 IS baseline assembly for the legacy-v1 model."""

import bisect
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ModelStrategy.parameterEvaluate.conviction import stamp_conviction
from ModelStrategy.parameterEvaluate.portfolio_eval import (
    CPortfolioConfig,
    portfolio_eval,
)

from .boundary import require_is_timestamp
from .provenance import (
    file_manifest,
    git_provenance,
    runtime_provenance,
    sqlite_kline_manifest,
)
from .schema import ResearchTrade, load_trades
from .spec import ResearchSpec


@dataclass(frozen=True)
class BarSeries:
    """The subset of bar fields required by the historical z-limit replay."""

    end_timestamps: tuple[float, ...]
    low_high: tuple[tuple[float, float], ...]
    close_by_end: dict[float, float]


def _raw_bar_window(spec: ResearchSpec, level_ms: int) -> tuple[int, int]:
    return (
        int(spec.begin_ts * 1000) - level_ms,
        int(spec.end_ts * 1000) - level_ms,
    )


def load_bars(
    db_path: str | Path,
    symbol: str,
    level: str,
    level_ms: int,
    begin_ts: float,
    end_ts: float,
) -> BarSeries:
    """Read bars whose end timestamps fall inside the half-open IS window."""
    raw_begin = int(begin_ts * 1000) - level_ms
    raw_end = int(end_ts * 1000) - level_ms
    rows = []
    with sqlite3.connect(Path(db_path)) as connection:
        rows = connection.execute(
            "select ts, l, h, c from kline "
            "where symbol = ? and lv = ? and ts >= ? and ts < ? order by ts",
            (symbol, level, raw_begin, raw_end),
        ).fetchall()
    if not rows:
        raise ValueError(f"no IS bars found for {symbol} {level}")

    end_timestamps = []
    low_high = []
    close_by_end = {}
    for raw_ts, low, high, close in rows:
        bar_end = (int(raw_ts) + level_ms) / 1000.0
        require_is_timestamp(bar_end)
        end_timestamps.append(bar_end)
        low_high.append((float(low), float(high)))
        close_by_end[bar_end] = float(close)
    return BarSeries(tuple(end_timestamps), tuple(low_high), close_by_end)


def apply_zlimit(
    trades: Iterable[ResearchTrade],
    bars: BarSeries,
    patience: int,
) -> list[ResearchTrade]:
    """Replay the corrected legacy z-limit fee classification in place."""
    result = list(trades)
    for trade in result:
        if trade.is_pyramid or str(trade.bs_type).startswith("z"):
            continue
        limit_price = bars.close_by_end.get(trade.open_ts)
        if limit_price is None:
            continue
        start = bisect.bisect_right(bars.end_timestamps, trade.open_ts)
        for index in range(start, min(start + patience, len(bars.end_timestamps))):
            low, high = bars.low_high[index]
            if (trade.is_buy and low <= limit_price) or (
                not trade.is_buy and high >= limit_price
            ):
                trade.bs_type = f"z{trade.bs_type}"
                break
    return result


def _input_path(research_root: Path, relative: Path) -> Path:
    root = research_root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"input escapes research root: {relative}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _require_trade_window(
    trades: Iterable[ResearchTrade], spec: ResearchSpec, input_name: str
) -> None:
    for index, trade in enumerate(trades):
        if not (
            spec.begin_ts <= trade.open_ts < spec.end_ts
            and spec.begin_ts <= trade.close_ts < spec.end_ts
        ):
            raise ValueError(
                f"{input_name} trade {index} is outside declared window"
            )


def _load_components(
    spec: ResearchSpec, research_root: Path
) -> tuple[
    list[ResearchTrade],
    list[ResearchTrade],
    dict[str, BarSeries],
    dict[str, Path],
]:
    paths = {
        name: _input_path(research_root, relative)
        for name, relative in spec.inputs.items()
    }
    s1 = load_trades(paths["s1_trades"], is_only=True)
    s2 = load_trades(paths["s2_trades"], is_only=True)
    _require_trade_window(s1, spec, "s1_trades")
    _require_trade_window(s2, spec, "s2_trades")
    bars = {
        spec.zlimit["s1_level"]: load_bars(
            paths["bars_db"],
            "BTC/USDT",
            spec.zlimit["s1_level"],
            spec.zlimit["s1_ms"],
            spec.begin_ts,
            spec.end_ts,
        ),
        spec.zlimit["s2_level"]: load_bars(
            paths["bars_db"],
            "BTC/USDT",
            spec.zlimit["s2_level"],
            spec.zlimit["s2_ms"],
            spec.begin_ts,
            spec.end_ts,
        ),
    }
    return s1, s2, bars, paths


def _merge_components(
    spec: ResearchSpec,
    s1: list[ResearchTrade],
    s2: list[ResearchTrade],
    bars: dict[str, BarSeries],
) -> list[ResearchTrade]:
    apply_zlimit(s1, bars[spec.zlimit["s1_level"]], spec.zlimit["patience"])
    apply_zlimit(s2, bars[spec.zlimit["s2_level"]], spec.zlimit["patience"])
    merged = sorted(s1 + s2, key=lambda trade: trade.open_ts)
    stamp_conviction(merged, **spec.conviction)
    return merged


def assemble_trades(spec: ResearchSpec, research_root: str | Path) -> list[ResearchTrade]:
    root = Path(research_root)
    s1, s2, bars, _ = _load_components(spec, root)
    return _merge_components(spec, s1, s2, bars)


def _portfolio_config(spec: ResearchSpec, risk_pct: float) -> CPortfolioConfig:
    return CPortfolioConfig(
        risk_pct=risk_pct,
        taker_fee=spec.portfolio["taker_fee"],
        maker_fee=spec.portfolio["maker_fee"],
        max_concurrent=spec.portfolio["max_concurrent"],
        max_leverage=spec.portfolio["max_leverage"],
        max_pos_leverage=spec.portfolio["max_pos_leverage"],
    )


def calibrate_risk(
    trades: list[ResearchTrade], spec: ResearchSpec
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Evaluate the fixed grid and select its highest drawdown-compliant risk."""
    rows = []
    selected = None
    for risk_pct in spec.risk_grid:
        config = _portfolio_config(spec, risk_pct)
        full = portfolio_eval(trades, config)
        split_metrics = {}
        for name, (begin_ts, end_ts) in spec.splits.items():
            split_trades = [
                trade for trade in trades if begin_ts <= trade.open_ts < end_ts
            ]
            result = portfolio_eval(split_trades, config)
            split_metrics[name] = {
                "cagr": round(result.cagr, 3),
                "dd": round(result.max_drawdown, 3),
                "calmar": (
                    round(result.calmar, 2)
                    if math.isfinite(result.calmar)
                    else None
                ),
            }
        worst_dd = max(
            full.max_drawdown,
            max(metrics["dd"] for metrics in split_metrics.values()),
        )
        row = {
            "risk_pct": risk_pct,
            "cagr": full.cagr,
            "full_dd": full.max_drawdown,
            "worst_dd": worst_dd,
            "splits": split_metrics,
            "passed": worst_dd <= spec.portfolio["target_max_drawdown"],
        }
        rows.append(row)
        if row["passed"]:
            selected = row
    if selected is None:
        raise ValueError("no risk_grid value satisfies target_max_drawdown")
    return rows, selected


def _trade_manifest(
    path: Path, relative: Path, trades: list[ResearchTrade]
) -> dict[str, Any]:
    result = {
        "path": relative.as_posix(),
        **file_manifest(path),
        "trade_count": len(trades),
        "first_open_ts": min((trade.open_ts for trade in trades), default=None),
        "last_close_ts": max((trade.close_ts for trade in trades), default=None),
    }
    return result


def run_baseline(
    spec: ResearchSpec,
    research_root: str | Path,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run an IS-only baseline and return a deterministic, auditable report."""
    root = Path(research_root)
    if not root.is_dir():
        raise FileNotFoundError(root)
    s1, s2, bars, paths = _load_components(spec, root)
    trades = _merge_components(spec, s1, s2, bars)
    rows, selected = calibrate_risk(trades, spec)

    bar_manifests = {}
    for level_key, interval_key in (("s1_level", "s1_ms"), ("s2_level", "s2_ms")):
        level = spec.zlimit[level_key]
        interval = spec.zlimit[interval_key]
        raw_begin, raw_end = _raw_bar_window(spec, interval)
        bar_manifests[level] = sqlite_kline_manifest(
            paths["bars_db"], "BTC/USDT", level, raw_begin, raw_end
        )
    report_provenance = {
        **git_provenance(Path(__file__).resolve().parents[2]),
        "runtime": runtime_provenance(),
    }
    if provenance is not None:
        report_provenance.update(provenance)

    return {
        "schema_version": 1,
        "strategy_id": spec.strategy_id,
        "execution_model": spec.execution_model,
        "window": {
            "begin_ts": spec.begin_ts,
            "end_exclusive_ts": spec.end_ts,
        },
        "spec_hash": spec.spec_hash,
        "inputs": {
            "s1_trades": _trade_manifest(
                paths["s1_trades"], spec.inputs["s1_trades"], s1
            ),
            "s2_trades": _trade_manifest(
                paths["s2_trades"], spec.inputs["s2_trades"], s2
            ),
            "bars_db": {"path": spec.inputs["bars_db"].as_posix()},
            "bars": bar_manifests,
        },
        "provenance": report_provenance,
        "risk_calibration": rows,
        "result": {
            "risk_pct": selected["risk_pct"],
            "is_2125": {
                "cagr": selected["cagr"],
                "full_dd": selected["full_dd"],
                "worst_dd": selected["worst_dd"],
                "splits": selected["splits"],
            },
        },
    }


def compare_reference(
    report: dict[str, Any], reference: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return every authoritative reference value that the report mismatches."""
    actual = {
        "schema_version": report.get("schema_version"),
        "strategy_id": report.get("strategy_id"),
        "execution_model": report.get("execution_model"),
        **report.get("result", {}),
    }
    mismatches = []

    def visit(path: str, expected: Any, observed: Any) -> None:
        if isinstance(expected, dict):
            if not isinstance(observed, dict):
                mismatches.append(
                    {"path": path, "expected": expected, "actual": observed}
                )
                return
            for key, value in expected.items():
                child = f"{path}.{key}" if path else key
                visit(child, value, observed.get(key))
            return
        equal = expected == observed
        if isinstance(expected, float) and isinstance(observed, (int, float)):
            equal = math.isclose(
                expected, float(observed), rel_tol=0.0, abs_tol=1e-12
            )
        if not equal:
            mismatches.append(
                {"path": path, "expected": expected, "actual": observed}
            )

    visit("", reference, actual)
    return mismatches
