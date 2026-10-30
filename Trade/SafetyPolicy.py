"""Fail-closed execution-mode and certified-strategy policy."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from Common.ChanException import CChanException, ErrCode


DRY_RUN = "dry_run"
TESTNET = "testnet"
LIVE = "live"
_MODES = {DRY_RUN, TESTNET, LIVE}
_TESTNET_UNLOCK = "YES"
_LIVE_UNLOCK = "I_ACCEPT_REAL_ORDERS"


def _locked(message: str) -> CChanException:
    return CChanException(message, ErrCode.TRADE_UNLOCK_FAIL)


def _receipt_path(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise _locked("非 dry-run 模式需要通过的策略收据")
    path = Path(value)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    path = path.resolve()
    if not path.is_file():
        raise _locked("策略收据不存在")
    return path


def _load_candidate_receipt(
    trade_conf: Mapping[str, Any],
) -> dict[str, Any]:
    path = _receipt_path(trade_conf.get("strategy_receipt"))
    try:
        with path.open(encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, ValueError) as exc:
        raise _locked("策略收据不可读取或不是有效 JSON") from exc
    if not isinstance(value, dict) or value.get("status") != "candidate":
        raise _locked("策略收据未通过认证，status 必须为 candidate")
    strategy_id = value.get("strategy_id")
    spec_hash = value.get("spec_hash")
    if not isinstance(strategy_id, str) or not strategy_id:
        raise _locked("策略收据缺少 strategy_id")
    if (
        not isinstance(spec_hash, str)
        or len(spec_hash) != 64
        or any(char not in "0123456789abcdef" for char in spec_hash)
    ):
        raise _locked("策略收据缺少有效 spec_hash")
    expected_id = trade_conf.get("strategy_id")
    expected_hash = trade_conf.get("strategy_spec_hash")
    if expected_id and expected_id != strategy_id:
        raise _locked("策略收据 strategy_id 与交易配置不一致")
    if expected_hash and expected_hash != spec_hash:
        raise _locked("策略收据 spec_hash 与交易配置不一致")
    return {
        "path": str(path),
        "status": "candidate",
        "strategy_id": strategy_id,
        "spec_hash": spec_hash,
    }


@dataclass(frozen=True)
class TradingSafetyPolicy:
    mode: str
    strategy_receipt: dict[str, Any] | None
    environ: Mapping[str, str]

    @property
    def dry_run(self) -> bool:
        return self.mode == DRY_RUN

    def assert_order_allowed(self) -> None:
        if self.dry_run:
            return
        if self.environ.get("CHANPY_KILL_SWITCH") in {
            "1",
            "true",
            "TRUE",
            "yes",
            "YES",
        }:
            raise _locked("CHANPY_KILL_SWITCH 已启用，禁止下单")
        if self.mode == TESTNET:
            if self.environ.get("CHANPY_ENABLE_TESTNET") != _TESTNET_UNLOCK:
                raise _locked("CHANPY_ENABLE_TESTNET 未保持为 YES")
            return
        if self.environ.get("CHANPY_LIVE_TRADING_UNLOCK") != _LIVE_UNLOCK:
            raise _locked("CHANPY_LIVE_TRADING_UNLOCK 已失效")


@dataclass(frozen=True)
class QueryOnlyTradingSafetyPolicy(TradingSafetyPolicy):
    """An immutable non-sending role, never new-risk permission."""

    def assert_order_allowed(self) -> None:
        raise _locked("查单专用引擎不能创建、修改或取消订单")


@dataclass(frozen=True)
class ManagementOnlyTradingSafetyPolicy(TradingSafetyPolicy):
    """Existing-risk role, never a generic or transferable send permission."""

    def assert_order_allowed(self) -> None:
        raise _locked("原有风险管理专用引擎需要本次逐单操作证明，不能通用发送")


def _configured_mode(exchange_conf):
    mode = exchange_conf.get("mode", DRY_RUN)
    if mode not in _MODES:
        raise _locked("ccxt.mode 必须是 dry_run、testnet 或 live")
    return mode


def _assert_private_configuration(exchange_conf, mode):
    if not exchange_conf.get("api_key") or not exchange_conf.get("secret"):
        raise _locked("非 dry-run 模式缺少交易所凭据")
    if mode == TESTNET and exchange_conf.get("testnet") is not True:
        raise _locked("testnet 模式要求 ccxt.testnet=true")
    if mode == LIVE and exchange_conf.get("testnet") is not False:
        raise _locked("live 模式要求 ccxt.testnet=false")


def build_query_only_safety_policy(ccxt_conf, environ=None) -> QueryOnlyTradingSafetyPolicy:
    """Validate an explicit read route without inventing a candidate/unlock."""
    exchange_conf = ccxt_conf or {}
    mode = _configured_mode(exchange_conf)
    if mode != DRY_RUN:
        _assert_private_configuration(exchange_conf, mode)
        if (exchange_conf.get("exchange") not in {"binance", "binanceusdm", "okx"}
                or exchange_conf.get("default_type") not in {"spot", "swap", "future"}
                or any(type(exchange_conf.get(key)) is not str for key in ("api_key", "secret"))):
            raise _locked("查单专用原生路径需要明确的交易所、市场与凭据结构")
    return QueryOnlyTradingSafetyPolicy(mode, None, os.environ if environ is None else environ)


def build_management_only_safety_policy(ccxt_conf, environ=None) -> ManagementOnlyTradingSafetyPolicy:
    validated = build_query_only_safety_policy(ccxt_conf, environ)
    return ManagementOnlyTradingSafetyPolicy(validated.mode, None, validated.environ)


def build_trading_safety_policy(
    ccxt_conf: Mapping[str, Any] | None,
    trade_conf: Mapping[str, Any] | None,
    environ: Mapping[str, str] | None = None,
) -> TradingSafetyPolicy:
    exchange_conf = ccxt_conf or {}
    trading_conf = trade_conf or {}
    environment = os.environ if environ is None else environ
    mode = _configured_mode(exchange_conf)
    if mode == DRY_RUN:
        return TradingSafetyPolicy(mode, None, environment)
    receipt = _load_candidate_receipt(trading_conf)
    _assert_private_configuration(exchange_conf, mode)
    if mode == TESTNET:
        if environment.get("CHANPY_ENABLE_TESTNET") != _TESTNET_UNLOCK:
            raise _locked("testnet 模式要求 CHANPY_ENABLE_TESTNET=YES")
    else:
        if environment.get("CHANPY_LIVE_TRADING_UNLOCK") != _LIVE_UNLOCK:
            raise _locked(
                "live 模式要求 CHANPY_LIVE_TRADING_UNLOCK="
                "I_ACCEPT_REAL_ORDERS"
            )
    policy = TradingSafetyPolicy(mode, receipt, environment)
    policy.assert_order_allowed()
    return policy
