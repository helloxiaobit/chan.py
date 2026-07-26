"""资金费率序列(加密货币永续合约,8小时结算):拥挤度信息源

csv 格式(binance 导出):symbol,fundingTime,fundingRate,markPrice
查询语义:query(ts) 返回严格早于 ts 的最近一期费率(结算时刻已知,无未来函数)。
"""
import bisect
from datetime import datetime
from typing import List, Optional, Tuple

from Common.ChanException import CChanException, ErrCode

_CACHE = {}


class CFundingRate:
    def __init__(self, csv_path: str):
        self.series: List[Tuple[float, float]] = []  # (ts, rate) 升序
        try:
            with open(csv_path, encoding="utf-8") as f:
                header = f.readline().strip().lower().split(",")
                t_idx = header.index("fundingtime")
                r_idx = header.index("fundingrate")
                for line in f:
                    parts = line.strip().split(",")
                    if len(parts) <= max(t_idx, r_idx) or not parts[r_idx]:
                        continue
                    ts = datetime.fromisoformat(parts[t_idx]).timestamp()
                    self.series.append((ts, float(parts[r_idx])))
        except (OSError, ValueError, IndexError) as e:
            raise CChanException(f"资金费率文件解析失败: {csv_path}: {e}", ErrCode.SRC_DATA_FORMAT_ERROR) from e
        self.series.sort()
        self._ts_list = [ts for ts, _ in self.series]

    @classmethod
    def get(cls, csv_path: str) -> 'CFundingRate':
        # 模块级缓存:同一文件只加载一次(策略每根K线查询)
        if csv_path not in _CACHE:
            _CACHE[csv_path] = cls(csv_path)
        return _CACHE[csv_path]

    def query(self, ts: float) -> Optional[float]:
        """严格早于 ts 的最近一期费率;无数据返回 None"""
        idx = bisect.bisect_left(self._ts_list, ts) - 1
        return self.series[idx][1] if idx >= 0 else None

    def query_mean(self, ts: float, periods: int = 9) -> Optional[float]:
        """ts 之前最近 periods 期(默认9期=3天)的均值,平滑单期噪声"""
        idx = bisect.bisect_left(self._ts_list, ts)
        if idx == 0:
            return None
        window = self.series[max(0, idx - periods):idx]
        return sum(r for _, r in window) / len(window)
