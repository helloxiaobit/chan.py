"""Strict preregistered specification for v5 certification."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .boundary import parse_utc, require_is_window
from .provenance import canonical_json_bytes, sha256_bytes


COMPONENTS = (
    "S1bz[4H,1H,15M]",
    "S2py10[1D,4H]",
    "conviction#14",
    "z-limit(S2 non-pyramid)",
    "z-exit",
)
SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT")
SPLITS = {
    "A(21-23)": ("2021-01-01", "2024-01-01"),
    "B(2024)": ("2024-01-01", "2025-01-01"),
    "C(2025)": ("2025-01-01", "2026-01-01"),
}
STACKS = {
    "s1": {
        "name": "S1bz[4H,1H,15M]",
        "entry_kind": "strategy_fill",
        "level": "K_60M",
        "interval_ms": 3600000,
    },
    "s2": {
        "name": "S2py10[1D,4H]",
        "entry_kind": "signal_intent",
        "level": "K_4H",
        "interval_ms": 14400000,
    },
}
EXIT_POLICY = {
    "eligible_reasons": ("reverse_bsp", "trend_flip", "time_stop"),
    "patience": 8,
}
GATES = {
    "btc": {
        "full_calmar_min": 2.0,
        "split_cagr_min_exclusive": 0.0,
        "max_drawdown": 0.25,
    },
    "robustness": {
        "full_cagr_min_exclusive": 0.0,
        "split_cagr_min": -0.01,
        "max_drawdown": 0.35,
    },
    "multi": {
        "cagr_min_exclusive": 0.0,
        "max_drawdown": 0.25,
        "calmar_min": 1.0,
        "max_concurrent": 16,
    },
    "oos": {
        "cagr_min_exclusive": 0.5,
        "max_drawdown_exclusive": 0.25,
        "calmar_min": 2.0,
    },
}
RISK_GRID = (0.005, 0.0075, 0.01, 0.0125, 0.015)
PORTFOLIO = {
    "taker_fee": 0.0005,
    "maker_fee": 0.0002,
    "max_concurrent": 4,
    "max_leverage": 3.0,
    "max_pos_leverage": 1.5,
    "target_max_drawdown": 0.25,
}
CONVICTION = {
    "co_dir_mult": 1.5,
    "opp_dir_mult": 1.0,
    "bs_mults": {"1": 0.8, "1p": 1.2},
    "mult_cap": 2.0,
}
EXECUTION = {
    "source_timestamp_offset_seconds": 0,
    "mark_level": "K_60M",
    "mark_ms": 3600000,
    "entry_patience": 8,
    "stop_slippage": 0.0005,
    "same_bar_policy": "adverse_first",
    "funding_order": "before_close",
    "funding_interval_ms": 28800000,
    "market_gap_policy": "carry_forward",
    "max_mark_gap_intervals": 16,
}
_TOP_KEYS = {
    "schema_version",
    "strategy_id",
    "execution_model",
    "window",
    "oos_window",
    "components",
    "symbols",
    "inputs",
    "stacks",
    "exit",
    "risk_grid",
    "portfolio",
    "conviction",
    "execution",
    "splits",
    "gates",
}


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{name} keys must be exactly {sorted(expected)}")


def _relative_path(value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a relative path")
    path = Path(value)
    if path.is_absolute() or path.drive or ".." in path.parts:
        raise ValueError(f"{name} must be a relative path")
    return path


def _require_exact(value: Any, expected: Any, name: str) -> None:
    if value != expected:
        raise ValueError(f"{name} must match the preregistered value")


def _require_nested_exact(value: Any, expected: Any, name: str) -> None:
    if isinstance(expected, Mapping) and isinstance(value, Mapping):
        _exact_keys(value, set(expected), name)
        for key, expected_child in expected.items():
            _require_nested_exact(value[key], expected_child, f"{name}.{key}")
        return
    _require_exact(value, expected, name)


@dataclass(frozen=True)
class CertificationSpec:
    source_path: Path
    raw: dict[str, Any]
    strategy_id: str
    execution_model: str
    begin_ts: float
    end_ts: float
    oos_begin_ts: float
    oos_end_ts: float
    components: tuple[str, ...]
    symbols: tuple[str, ...]
    bars_db: Path
    symbol_inputs: dict[str, dict[str, Path]]
    stacks: dict[str, dict[str, Any]]
    exit_policy: dict[str, Any]
    risk_grid: tuple[float, ...]
    portfolio: dict[str, Any]
    conviction: dict[str, Any]
    execution: dict[str, Any]
    splits: dict[str, tuple[float, float]]
    gates: dict[str, dict[str, Any]]

    @property
    def spec_hash(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.raw))


def load_certification_spec(path: str | Path) -> CertificationSpec:
    source = Path(path)
    with source.open(encoding="utf-8") as stream:
        raw_value = json.load(stream)
    top = _mapping(raw_value, "spec")
    _exact_keys(top, _TOP_KEYS, "spec")
    if top.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    _require_exact(top.get("strategy_id"), "freeze_v5_candidate_v1", "strategy_id")
    _require_exact(top.get("execution_model"), "conservative-v2", "execution_model")

    window = _mapping(top.get("window"), "window")
    _exact_keys(window, {"begin", "end_exclusive"}, "window")
    _require_exact(dict(window), {"begin": "2021-01-01", "end_exclusive": "2026-01-01"}, "window")
    begin_ts, end_ts = require_is_window(window["begin"], window["end_exclusive"])

    oos_window = _mapping(top.get("oos_window"), "oos_window")
    _exact_keys(oos_window, {"begin", "end_exclusive"}, "oos_window")
    expected_oos = {"begin": "2026-01-01", "end_exclusive": "2026-07-27"}
    _require_exact(dict(oos_window), expected_oos, "oos_window")
    oos_begin_ts = parse_utc(oos_window["begin"])
    oos_end_ts = parse_utc(oos_window["end_exclusive"])

    components = tuple(top.get("components", ()))
    symbols = tuple(top.get("symbols", ()))
    _require_exact(components, COMPONENTS, "components")
    _require_exact(symbols, SYMBOLS, "symbols")

    inputs = _mapping(top.get("inputs"), "inputs")
    _exact_keys(inputs, {"bars_db", "symbols"}, "inputs")
    bars_db = _relative_path(inputs.get("bars_db"), "inputs.bars_db")
    input_symbols = _mapping(inputs.get("symbols"), "inputs.symbols")
    _require_exact(set(input_symbols), set(SYMBOLS), "inputs.symbols")
    symbol_inputs = {}
    for symbol in SYMBOLS:
        values = _mapping(input_symbols[symbol], f"inputs.symbols.{symbol}")
        keys = {"s1_trades", "s2_trades", "funding_rates"}
        _exact_keys(values, keys, f"inputs.symbols.{symbol}")
        symbol_inputs[symbol] = {
            name: _relative_path(value, f"inputs.symbols.{symbol}.{name}")
            for name, value in values.items()
        }

    stacks = _mapping(top.get("stacks"), "stacks")
    normalized_stacks = {name: dict(_mapping(value, f"stacks.{name}")) for name, value in stacks.items()}
    _require_nested_exact(normalized_stacks, STACKS, "stacks")
    exit_value = dict(_mapping(top.get("exit"), "exit"))
    if isinstance(exit_value.get("eligible_reasons"), list):
        exit_value["eligible_reasons"] = tuple(exit_value["eligible_reasons"])
    _require_exact(exit_value, EXIT_POLICY, "exit")

    risk_grid = tuple(top.get("risk_grid", ()))
    _require_exact(risk_grid, RISK_GRID, "risk_grid")
    portfolio = dict(_mapping(top.get("portfolio"), "portfolio"))
    conviction = dict(_mapping(top.get("conviction"), "conviction"))
    execution = dict(_mapping(top.get("execution"), "execution"))
    gates = {
        name: dict(_mapping(value, f"gates.{name}"))
        for name, value in _mapping(top.get("gates"), "gates").items()
    }
    _require_nested_exact(portfolio, PORTFOLIO, "portfolio")
    _require_nested_exact(conviction, CONVICTION, "conviction")
    _require_nested_exact(execution, EXECUTION, "execution")
    _require_nested_exact(gates, GATES, "gates")

    split_value = _mapping(top.get("splits"), "splits")
    normalized_splits = {
        name: tuple(value) if isinstance(value, list) else value
        for name, value in split_value.items()
    }
    _require_exact(normalized_splits, SPLITS, "splits")
    splits = {
        name: require_is_window(values[0], values[1])
        for name, values in SPLITS.items()
    }
    return CertificationSpec(
        source_path=source,
        raw=dict(top),
        strategy_id="freeze_v5_candidate_v1",
        execution_model="conservative-v2",
        begin_ts=begin_ts,
        end_ts=end_ts,
        oos_begin_ts=oos_begin_ts,
        oos_end_ts=oos_end_ts,
        components=COMPONENTS,
        symbols=SYMBOLS,
        bars_db=bars_db,
        symbol_inputs=symbol_inputs,
        stacks={name: dict(value) for name, value in STACKS.items()},
        exit_policy={
            "eligible_reasons": EXIT_POLICY["eligible_reasons"],
            "patience": EXIT_POLICY["patience"],
        },
        risk_grid=RISK_GRID,
        portfolio=dict(PORTFOLIO),
        conviction={**CONVICTION, "bs_mults": dict(CONVICTION["bs_mults"])},
        execution=dict(EXECUTION),
        splits=splits,
        gates={name: dict(value) for name, value in GATES.items()},
    )
