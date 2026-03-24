from __future__ import annotations

from pathlib import Path

import yaml


DEFAULT_CRYPTO_CONFIG_PATH = Path("config/crypto_settings.yaml")


def load_crypto_config(path: str | Path = DEFAULT_CRYPTO_CONFIG_PATH) -> dict:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"crypto config not found: {config_path}")

    with config_path.open() as f:
        cfg = yaml.safe_load(f) or {}

    cfg.setdefault("exchanges", {})
    cfg.setdefault("arbitrage", {})
    cfg.setdefault("position", {})
    cfg.setdefault("monitor", {})
    cfg.setdefault("backtest", {})
    return cfg


def enabled_exchange_names(cfg: dict) -> list[str]:
    exchanges = cfg.get("exchanges", {})
    return [name for name, ex_cfg in exchanges.items() if ex_cfg.get("enabled")]
