"""Versioned research-spec loading and validation."""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .boundary import require_is_window
from .provenance import canonical_json_bytes, sha256_bytes


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _relative_path(value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a relative path")
    path = Path(value)
    if path.is_absolute() or path.drive or ".." in path.parts:
        raise ValueError(f"{name} must be a relative path inside the research root")
    return path


def _finite_number(value: Any, name: str, *, positive: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{name} must be a finite positive number")
    return result


@dataclass(frozen=True)
class ResearchSpec:
    source_path: Path
    raw: dict[str, Any]
    strategy_id: str
    execution_model: str
    begin_ts: float
    end_ts: float
    inputs: dict[str, Path]
    risk_grid: tuple[float, ...]
    portfolio: dict[str, Any]
    conviction: dict[str, Any]
    zlimit: dict[str, Any]
    execution: dict[str, Any]
    splits: dict[str, tuple[float, float]]

    @property
    def spec_hash(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.raw))


def load_spec(path: str | Path) -> ResearchSpec:
    source_path = Path(path)
    with source_path.open(encoding="utf-8") as stream:
        raw = json.load(stream)
    top = _mapping(raw, "spec")
    if top.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")

    strategy_id = top.get("strategy_id")
    if not isinstance(strategy_id, str) or not strategy_id:
        raise ValueError("strategy_id must be a non-empty string")
    execution_model = top.get("execution_model")
    if execution_model not in {"legacy-v1", "conservative-v2"}:
        raise ValueError(
            "execution_model must be legacy-v1 or conservative-v2"
        )

    window = _mapping(top.get("window"), "window")
    begin_ts, end_ts = require_is_window(
        str(window.get("begin")), str(window.get("end_exclusive"))
    )

    input_values = _mapping(top.get("inputs"), "inputs")
    required_inputs = ("s1_trades", "s2_trades", "bars_db")
    if execution_model == "conservative-v2":
        required_inputs += ("funding_rates",)
    if set(input_values) != set(required_inputs):
        raise ValueError(
            f"inputs keys must be exactly {sorted(required_inputs)}"
        )
    inputs = {
        name: _relative_path(input_values.get(name), f"inputs.{name}")
        for name in required_inputs
    }

    risk_value = top.get("risk_grid")
    if not isinstance(risk_value, list) or not risk_value:
        raise ValueError("risk_grid must be a non-empty list")
    risk_grid = tuple(
        _finite_number(value, "risk_grid", positive=True) for value in risk_value
    )
    if any(left >= right for left, right in zip(risk_grid, risk_grid[1:])):
        raise ValueError("risk_grid must be strictly increasing")

    portfolio_raw = _mapping(top.get("portfolio"), "portfolio")
    portfolio = {
        "taker_fee": _finite_number(portfolio_raw.get("taker_fee"), "taker_fee"),
        "maker_fee": _finite_number(portfolio_raw.get("maker_fee"), "maker_fee"),
        "max_concurrent": int(portfolio_raw.get("max_concurrent")),
        "max_leverage": _finite_number(
            portfolio_raw.get("max_leverage"), "max_leverage", positive=True
        ),
        "max_pos_leverage": _finite_number(
            portfolio_raw.get("max_pos_leverage"),
            "max_pos_leverage",
            positive=True,
        ),
        "target_max_drawdown": _finite_number(
            portfolio_raw.get("target_max_drawdown"),
            "target_max_drawdown",
            positive=True,
        ),
    }
    if portfolio["max_concurrent"] <= 0:
        raise ValueError("max_concurrent must be positive")

    conviction_raw = _mapping(top.get("conviction"), "conviction")
    bs_mults_raw = _mapping(conviction_raw.get("bs_mults"), "conviction.bs_mults")
    conviction = {
        "co_dir_mult": _finite_number(
            conviction_raw.get("co_dir_mult"), "co_dir_mult", positive=True
        ),
        "opp_dir_mult": _finite_number(
            conviction_raw.get("opp_dir_mult"), "opp_dir_mult", positive=True
        ),
        "bs_mults": {
            str(name): _finite_number(value, f"bs_mults.{name}", positive=True)
            for name, value in bs_mults_raw.items()
        },
        "mult_cap": _finite_number(
            conviction_raw.get("mult_cap"), "mult_cap", positive=True
        ),
    }

    zlimit_raw = _mapping(top.get("zlimit"), "zlimit")
    zlimit = {
        "patience": int(zlimit_raw.get("patience")),
        "s1_level": str(zlimit_raw.get("s1_level")),
        "s1_ms": int(zlimit_raw.get("s1_ms")),
        "s2_level": str(zlimit_raw.get("s2_level")),
        "s2_ms": int(zlimit_raw.get("s2_ms")),
    }
    if zlimit["patience"] <= 0 or zlimit["s1_ms"] <= 0 or zlimit["s2_ms"] <= 0:
        raise ValueError("zlimit patience and interval lengths must be positive")

    execution: dict[str, Any] = {}
    execution_value = top.get("execution")
    if execution_model == "legacy-v1":
        if execution_value is not None:
            raise ValueError("legacy-v1 must not define execution")
    else:
        execution_raw = _mapping(execution_value, "execution")
        execution_keys = {
            "mark_level",
            "mark_ms",
            "entry_patience",
            "stop_slippage",
            "same_bar_policy",
            "funding_order",
        }
        if set(execution_raw) != execution_keys:
            raise ValueError(
                f"execution keys must be exactly {sorted(execution_keys)}"
            )
        mark_level = execution_raw.get("mark_level")
        if not isinstance(mark_level, str) or not mark_level:
            raise ValueError("execution.mark_level must be a non-empty string")
        mark_ms = execution_raw.get("mark_ms")
        entry_patience = execution_raw.get("entry_patience")
        if type(mark_ms) is not int or mark_ms <= 0:
            raise ValueError("execution.mark_ms must be a positive integer")
        if type(entry_patience) is not int or entry_patience <= 0:
            raise ValueError(
                "execution.entry_patience must be a positive integer"
            )
        if entry_patience != zlimit["patience"]:
            raise ValueError(
                "execution.entry_patience must match zlimit.patience"
            )
        stop_slippage = _finite_number(
            execution_raw.get("stop_slippage"), "execution.stop_slippage"
        )
        if stop_slippage < 0 or stop_slippage >= 1:
            raise ValueError(
                "execution.stop_slippage must be at least zero and below one"
            )
        if execution_raw.get("same_bar_policy") != "adverse_first":
            raise ValueError(
                "execution.same_bar_policy must be adverse_first"
            )
        if execution_raw.get("funding_order") != "before_close":
            raise ValueError("execution.funding_order must be before_close")
        execution = {
            "mark_level": mark_level,
            "mark_ms": mark_ms,
            "entry_patience": entry_patience,
            "stop_slippage": stop_slippage,
            "same_bar_policy": "adverse_first",
            "funding_order": "before_close",
        }

    split_values = _mapping(top.get("splits"), "splits")
    splits = {}
    for name, value in split_values.items():
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError(f"split {name} must contain begin and end")
        split_begin, split_end = require_is_window(str(value[0]), str(value[1]))
        if split_begin < begin_ts or split_end > end_ts:
            raise ValueError(f"split {name} must be inside the main window")
        splits[str(name)] = (split_begin, split_end)
    if not splits:
        raise ValueError("splits must not be empty")

    return ResearchSpec(
        source_path=source_path,
        raw=dict(top),
        strategy_id=strategy_id,
        execution_model=execution_model,
        begin_ts=begin_ts,
        end_ts=end_ts,
        inputs=inputs,
        risk_grid=risk_grid,
        portfolio=portfolio,
        conviction=conviction,
        zlimit=zlimit,
        execution=execution,
        splits=splits,
    )
