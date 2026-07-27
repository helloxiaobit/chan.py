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
    if execution_model != "legacy-v1":
        raise ValueError("execution_model must be legacy-v1")

    window = _mapping(top.get("window"), "window")
    begin_ts, end_ts = require_is_window(
        str(window.get("begin")), str(window.get("end_exclusive"))
    )

    input_values = _mapping(top.get("inputs"), "inputs")
    required_inputs = ("s1_trades", "s2_trades", "bars_db")
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
        splits=splits,
    )
