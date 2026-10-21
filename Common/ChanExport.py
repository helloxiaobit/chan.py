"""明确当前结构视图与 C2 原发布事件；不从端点补造确认/可交易时刻。"""
import hashlib
import json

from Common.ChanException import CChanException, ErrCode
from Common.CEnum import KL_TYPE
from Common.KLineTime import bar_close_ms, containing_bar_open_ms
from CustomBuySellPoint.Decision import canonical_bytes, read_decision


SCHEMA = "chan-api-v2"


def _fail():
    raise CChanException("Chan API 结构/来源/时钟/事件证据无效，不能补造输出", ErrCode.FEATURE_ERROR) from None


def _sha(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _clock(value):
    if type(value) is not int or not 0 <= value < 2**63:
        _fail()
    return value


def _source(unit):
    value = getattr(unit, "source_identity", None)
    if value is not None:
        from OfflineData.offline_data_util import validate_source_identity
        return validate_source_identity(value)
    return None


def _reference(unit):
    return None if unit is None else {"level": None if unit.kl_type is None else unit.kl_type.name, "klu_idx": unit.idx}


def _validate_relations(chan, units_by_level):
    locations = {id(unit): index for index, level in enumerate(chan.lv_list) for unit in units_by_level[level]}
    for index, level in enumerate(chan.lv_list):
        units = units_by_level[level]
        indices = [unit.idx for unit in units]
        if any(type(idx) is not int or idx < 0 for idx in indices) or len(set(indices)) != len(indices):
            _fail()
        containers = list(chan.kl_datas[level])
        container_indices = [klc.idx for klc in containers]
        if (any(type(idx) is not int or idx < 0 for idx in container_indices)
                or len(set(container_indices)) != len(container_indices)):
            _fail()
        owners = {id(unit): klc for klc in containers for unit in klc}
        for unit in units:
            if unit.kl_type != level or owners.get(id(unit)) is not unit.klc:
                _fail()
            parent = unit.sup_kl
            if parent is not None and (locations.get(id(parent)) != index-1
                    or sum(child is unit for child in parent.sub_kl_list) != 1):
                _fail()
            children = unit.sub_kl_list
            if len({id(child) for child in children}) != len(children):
                _fail()
            for child in children:
                if locations.get(id(child)) != index+1 or child.sup_kl is not unit:
                    _fail()


def _bar_clock(unit, level):
    names = ("open_ms", "close_ms", "available_at_ms")
    if not any(hasattr(unit, name) for name in names):
        return dict(time_basis="legacy_unspecified", open_ms=None, close_ms=None, available_at_ms=None, is_final=None)
    opened, closed, available = (_clock(getattr(unit, name)) for name in names)
    final = getattr(unit, "is_final", None)
    if (type(final) is not bool or containing_bar_open_ms(opened, level) != opened
            or bar_close_ms(opened, level) != closed
            or int(unit.time.ts*1000) != closed or available < closed):
        _fail()
    return dict(time_basis="utc_closed_bar", open_ms=opened, close_ms=closed,
        available_at_ms=available if final else None, is_final=final)


def _bar(unit, level):
    return {"idx": unit.idx, "time": unit.time.to_str(), "open": unit.open, "high": unit.high,
        "low": unit.low, "close": unit.close, "trade_info": dict(unit.trade_info.metric),
        "clock": _bar_clock(unit, level), "source": _source(unit), "klc_idx": unit.klc.idx,
        "parent": _reference(unit.sup_kl), "children": [_reference(child) for child in unit.sub_kl_list]}


def _view(code, level, source, kind, body):
    return {**body, "availability": "not_recorded", "available_at_ms": None,
        "snapshot_id": _sha({"code": code, "level": level, "source": source, "kind": kind, "body": body})}


def _line(line):
    return {"idx": line.idx, "dir": line.dir.name, "is_sure": line.is_sure, "used_to_be_sure": line.used_to_be_sure,
        "begin_klu_idx": line.get_begin_klu().idx, "end_klu_idx": line.get_end_klu().idx,
        "begin_val": line.get_begin_val(), "end_val": line.get_end_val(), "parent_seg_idx": line.seg_idx}


def _center(center, parents=()):
    if id(center) in parents:
        _fail()
    return {"begin_line_idx": center.begin_bi.idx, "end_line_idx": center.end_bi.idx,
        "begin_klu_idx": center.begin.idx, "end_klu_idx": center.end.idx,
        "low": center.low, "high": center.high, "mid": center.mid,
        "peak_low": center.peak_low, "peak_high": center.peak_high, "is_sure": center.is_sure,
        "in_line_idx": None if center.bi_in is None else center.bi_in.idx,
        "out_line_idx": None if center.bi_out is None else center.bi_out.idx,
        "sub_centers": [_center(child, (*parents, id(center))) for child in center.sub_zs_lst]}


def _point(point):
    return {"klu_idx": point.klu.idx, "time": point.klu.time.to_str(), "line_idx": point.bi.idx,
        "is_buy": point.is_buy, "type": point.type2str(), "is_segbsp": point.is_segbsp,
        "features": dict(point.features.items()),
        "relate_bsp1_klu_idx": None if point.relate_bsp1 is None else point.relate_bsp1.klu.idx}


def _decisions(strategy, code, level, source):
    if strategy is None:
        return []
    result, known, last = [], {}, -1
    for index, raw in enumerate(strategy.decision_records):
        record = read_decision(raw)
        identity = record["identity"]
        key, at = record["event_id"], identity["decision_ms"]
        if (key in known or identity["code"] != code or identity["level"] != level or at < last
                or (source is not None and identity["market"] is not None and identity["market"] != source)):
            _fail()
        if identity["kind"] == "exit":
            parent = known.get(identity["parent_event_id"])
            if (parent is None or parent["identity"]["kind"] != "open"
                    or any(identity[key] != parent["identity"][key] for key in
                        ("is_buy", "bs_type", "is_segbsp", "anchor_ms", "market"))):
                _fail()
        bar = record["payload"]["bar"]
        if _clock(bar["time_ms"]) > at or bar.get("market") != identity["market"]:
            _fail()
        clocks = [name in bar for name in ("open_ms", "close_ms", "available_at_ms")]
        if any(clocks) and not all(clocks):
            _fail()
        utc = all(clocks)
        if utc and not (containing_bar_open_ms(_clock(bar["open_ms"]), KL_TYPE[level]) == bar["open_ms"]
                        and bar_close_ms(bar["open_ms"], KL_TYPE[level]) == _clock(bar["close_ms"]) == bar["time_ms"]
                        and bar["close_ms"] <= _clock(bar["available_at_ms"]) <= at):
            _fail()
        result.append({"ordinal": index, "time_basis": "utc_closed_bar" if utc else "legacy_unspecified",
                       "available_at_ms": at if utc else None, "record": record})
        known[key], last = record, at
    return result


def export_chan_v2(chan):
    try:
        units_by_level = {level: list(chan.kl_datas[level].klu_iter()) for level in chan.lv_list}
        _validate_relations(chan, units_by_level)
        sources_by_level = {level: [_source(unit) for unit in units] for level, units in units_by_level.items()}
        markets = [source for sources in sources_by_level.values() for source in sources if source is not None]
        if any(source != markets[0] for source in markets):
            _fail()
        levels = {}
        for level in chan.lv_list:
            name, data = level.name, chan.kl_datas[level]
            units = units_by_level[level]
            sources = sources_by_level[level]
            known = [source for source in sources if source is not None]
            source_status = "known" if known and len(known) == len(sources) else "partial" if known else "unknown"
            bars = [_bar(unit, level) for unit in units]
            clocks = [bar["clock"] for bar in bars]
            complete_clock = clocks and all(clock["time_basis"] == "utc_closed_bar" and clock["is_final"] is True for clock in clocks)
            source_context = {"status": source_status, "identity": known[0] if known else None}
            wrap = lambda kind, body: _view(chan.code, name, source_context, kind, body)
            view = {"source": known[0] if source_status == "known" else None, "source_status": source_status,
                "observed_through_ms": max(clock["available_at_ms"] for clock in clocks) if complete_clock else None,
                "klu": bars,
                "klc": [wrap("klc", {"idx": klc.idx, "dir": klc.dir.name, "fx": klc.fx.name,
                    "low": klc.low, "high": klc.high, "klu_indices": [unit.idx for unit in klc]}) for klc in data],
                "bi": [wrap("bi", _line(line)) for line in data.bi_list],
                "seg": [wrap("seg", {**_line(line), "begin_line_idx": line.start_bi.idx,
                    "end_line_idx": line.end_bi.idx, "reason": line.reason}) for line in data.seg_list],
                "segseg": [wrap("segseg", {**_line(line), "begin_line_idx": line.start_bi.idx,
                    "end_line_idx": line.end_bi.idx, "reason": line.reason}) for line in data.segseg_list],
                "zs": [wrap("zs", _center(center)) for center in data.zs_list],
                "segzs": [wrap("segzs", _center(center)) for center in data.segzs_list],
                "bsp": [wrap("bsp", _point(point)) for point in data.bs_point_lst.getSortedBspList()],
                "segbsp": [wrap("segbsp", _point(point)) for point in data.seg_bs_point_lst.getSortedBspList()],
                "cbsp": [], "decisions": _decisions(data.cbsp_strategy, chan.code, name, markets[0] if markets else None)}
            if data.cbsp_strategy is not None:
                published = {item["record"]["event_id"]: item["record"] for item in view["decisions"]}
                for point in data.cbsp_strategy:
                    opening = None
                    if point.open_decision is not None:
                        original = read_decision(point.open_decision)
                        opening = original["event_id"]
                        if (published.get(opening) != original or original["identity"]["kind"] != "open"
                                or original["identity"]["anchor_ms"] != int(point.klu.time.ts*1000)):
                            _fail()
                    exits = []
                    for index, action in enumerate(point.close_actions):
                        key = None
                        if action.decision is not None:
                            original = read_decision(action.decision)
                            key = original["event_id"]
                            if (published.get(key) != original or original["identity"]["kind"] != "exit"
                                    or original["identity"]["parent_event_id"] != opening
                                    or original["identity"]["sequence"] != index):
                                _fail()
                        exits.append(key)
                    view["cbsp"].append(wrap("cbsp", {"klu_idx": point.klu.idx, "time": point.klu.time.to_str(),
                        "is_buy": point.is_buy, "type": point.type2str(), "is_segbsp": point.is_segbsp,
                        "open_price": point.open_price, "sl_price": point.sl_price, "score": point.score,
                        "is_cover": point.is_cover, "profit": point.profit, "features": dict(point.features.items()),
                        "open_event_id": opening, "close_event_ids": exits,
                        "close_actions": [{"price": action.price, "quota": action.quota, "reason": action.reason,
                            "klu_idx": action.klu.idx} for action in point.close_actions]}))
            levels[name] = view
        payload = {"code": chan.code, "level_order": [level.name for level in chan.lv_list],
            "structure_semantics": "current_view_not_historical_publication", "levels": levels}
        document = {"schema": SCHEMA, "schema_version": 2, "payload": payload, "payload_sha256": _sha(payload)}
        return json.loads(canonical_bytes(document))  # 全对象有限，返回值不共享可变内部状态。
    except Exception:
        _fail()
