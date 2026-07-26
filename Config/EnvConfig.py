import os
import sys
from typing import Any, Dict, Optional

if __package__ in (None, ""):  # 直接以脚本方式运行时,把仓库根目录加进 sys.path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from Common.ChanException import CChanException, ErrCode


class CEnv:
    """全局配置环境:读取 config.yaml,提供各模块配置访问

    查找顺序:
    1. 显式传入的 conf_path
    2. 环境变量 CHANPY_CONFIG
    3. Config/config.yaml(用户配置,已 gitignore)
    4. Config/config_demo.yaml(demo 配置,保证开箱可用)
    """

    _instance: Optional['CEnv'] = None

    def __init__(self, conf_path: Optional[str] = None):
        self.conf_path = self._resolve_path(conf_path)
        self.conf: Dict[str, Any] = self._load_yaml(self.conf_path)

    @staticmethod
    def _resolve_path(conf_path: Optional[str]) -> str:
        if conf_path is not None:
            if not os.path.exists(conf_path):
                raise CChanException(f"配置文件不存在: {conf_path}", ErrCode.ENV_CONF_ERR)
            return conf_path
        env_path = os.environ.get("CHANPY_CONFIG")
        if env_path:
            if not os.path.exists(env_path):
                raise CChanException(f"环境变量CHANPY_CONFIG指向的配置文件不存在: {env_path}", ErrCode.ENV_CONF_ERR)
            return env_path
        cur_dir = os.path.dirname(os.path.realpath(__file__))
        for name in ("config.yaml", "config_demo.yaml"):
            path = os.path.join(cur_dir, name)
            if os.path.exists(path):
                return path
        raise CChanException("找不到任何配置文件(config.yaml/config_demo.yaml)", ErrCode.ENV_CONF_ERR)

    @staticmethod
    def _load_yaml(path: str) -> Dict[str, Any]:
        try:
            import yaml  # 懒加载,核心缠论计算不依赖
        except ImportError as e:
            raise CChanException("读取配置需要 pyyaml,请先 pip install pyyaml", ErrCode.ENV_CONF_ERR) from e
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise CChanException(f"配置文件格式错误(顶层应为字典): {path}", ErrCode.ENV_CONF_ERR)
        return data

    @classmethod
    def get_instance(cls) -> 'CEnv':
        if cls._instance is None:
            cls._instance = CEnv()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        # 测试或切换配置文件时使用
        cls._instance = None

    def get(self, key: str, default: Any = None) -> Any:
        # 支持 "db.type" 这类点路径访问
        node: Any = self.conf
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def get_section(self, name: str) -> Dict[str, Any]:
        res = self.get(name, {})
        return res if isinstance(res, dict) else {}

    # ===== 各模块配置访问入口 =====
    @property
    def db_conf(self) -> Dict[str, Any]:
        return self.get_section("db")

    @property
    def offline_data_conf(self) -> Dict[str, Any]:
        return self.get_section("offline_data")

    @property
    def snapshot_engine(self) -> str:
        return self.get("snapshot_engine", "sina")

    @property
    def notify_conf(self) -> Dict[str, Any]:
        return self.get_section("notify")

    @property
    def ccxt_conf(self) -> Dict[str, Any]:
        return self.get_section("ccxt")

    @property
    def futu_conf(self) -> Dict[str, Any]:
        return self.get_section("futu")

    @property
    def cos_conf(self) -> Dict[str, Any]:
        return self.get_section("cos")

    @property
    def model_conf(self) -> Dict[str, Any]:
        return self.get_section("model")

    def abs_path(self, path: str) -> str:
        # 配置里的相对路径统一相对仓库根目录解析(跨平台)
        if os.path.isabs(path):
            return path
        repo_root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        return os.path.normpath(os.path.join(repo_root, path))


if __name__ == "__main__":
    # 供 config.sh / config.ps1 调用: python EnvConfig.py db.type
    if len(sys.argv) < 2:
        print("usage: python EnvConfig.py <dot.path.key>", file=sys.stderr)
        sys.exit(1)
    val = CEnv().get(sys.argv[1], "")
    print(val if val is not None else "")
