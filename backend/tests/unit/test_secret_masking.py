"""诊断输出必须掩码密钥（真实踩过的坑：用户误把 Key 填到“模型 ID”位置）。"""

from __future__ import annotations

from app.core.logging import mask_secret, setup_logging


def test_mask_secret_hides_api_keys(tmp_path) -> None:
    setup_logging(tmp_path / "app.jsonl", secrets=[])
    key = "ark-" + "0000dead-beef-0000-0000-000000000000" + "-test"
    masked = mask_secret(key)
    assert key not in masked
    assert "掩码" in masked
    assert masked.startswith("ark-")


def test_mask_secret_keeps_normal_config_values() -> None:
    assert mask_secret("doubao-seed-2-1-pro-260915") == "doubao-seed-2-1-pro-260915"
    assert mask_secret("doubao-seedream-5-0-pro-260628").startswith("doubao-seedream")
    assert mask_secret("") == "（空）"
    assert mask_secret(None) == "（空）"


def test_mask_secret_catches_other_key_shapes() -> None:
    assert "sk-" in mask_secret("sk-" + "abcdefghijklmnopqrstuvwxyz")
    assert mask_secret("sk-" + "abcdefghijklmnopqrstuvwxyz").endswith("（疑似密钥，已掩码）")
