"""ETF 日K下载(baostock;A股研究用,低优先)

用法: python -m OfflineData.etf_download sh.510300 ...
"""
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from .bao_download import download_codes  # ETF 走同一 baostock 接口

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m OfflineData.etf_download <etf_code> [etf_code ...]")
        sys.exit(1)
    download_codes(sys.argv[1:])
