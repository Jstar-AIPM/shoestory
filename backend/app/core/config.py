"""应用配置：全部来自环境变量 / .env，代码不硬编码任何模型名或密钥。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 仓库根目录：backend/app/core/config.py -> parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]
# 风格模板与 Prompt 目录
PROMPTS_DIR = Path(__file__).resolve().parents[1] / "services" / "prompts"
STYLES_DIR = PROMPTS_DIR / "styles"


class Settings(BaseSettings):
    """「履历」运行配置。字段名 == 环境变量名（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 服务 ----------
    env: Literal["dev", "prod"] = "dev"
    app_host: str = "127.0.0.1"
    app_port: int = 8787
    app_log_level: str = "INFO"
    data_dir: str = "./data"
    version: str = "0.1.0-stage1"

    # ---------- 存储 ----------
    storage_provider: Literal["local", "s3"] = "local"
    s3_endpoint: str = "https://tos-s3-cn-beijing.volces.com"
    s3_bucket: str = ""
    s3_region: str = "cn-beijing"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # ---------- 身份 / 邀请码（阶段 4）----------
    invite_codes: str = ""
    admin_code: str = ""
    global_daily_generate_limit: int | None = None
    dev_owner_id: str = "owner"
    #: 会话签名密钥；留空时首次启动自动生成并存到存储（system/secret.json）
    session_secret: str = ""
    #: 会话有效期（天）：额度用完/过期后仍可查看，因此会话长于邀请码有效期
    session_ttl_days: int = 30
    #: 普通邀请码：最多生成次数（1 次 = 1 次点击生成，手动重新生成也算）
    invite_code_max_uses: int = 20
    #: 普通邀请码：有效期（天）
    invite_code_ttl_days: int = 30
    #: 是否强制登录（prod 一律强制；dev 可用 true 打开以便本地测试）
    force_auth: bool = False

    # ---------- 火山方舟 ----------
    ark_api_key: str = ""
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    ark_text_model: str = ""
    ark_vision_model: str = ""
    ark_image_model: str = ""
    ark_timeout_seconds: float = 180.0
    ark_max_retries: int = 2
    #: 型号校对/画稿质检都是确定性任务，关掉“深度思考”可大幅降低延迟与成本
    ark_disable_thinking: bool = True
    #: 送给视觉质检前把图片缩到长边不超过这个像素（太大又慢又贵，对质检无益）
    ark_max_image_edge: int = 1024
    #: 是否把“边缘骨架图”作为第二张参考图传给图生图模型（锁结构、防止自由创作）
    enable_structure_reference: bool = True
    #: 送给图生图模型的参考图长边上限（原图太大只会拖慢上传与推理）
    image_reference_max_edge: int = 1024
    #: 提示词优化模式（官方参数 optimize_prompt_options.mode）
    #: standard=质量更好耗时更长；fast=耗时更短效果略低（Seedream 5.0 pro 支持，lite/4.5 不支持）
    image_prompt_optimize_mode: Literal["standard", "fast"] = "fast"

    # ---------- 火山 · 豆包搜索（文搜图）----------
    search_provider: Literal["volc_doubao", "mock"] = "volc_doubao"
    #: 豆包搜索 Custom 版（文搜图）。官方地址已核对；留空即用默认值
    volc_search_endpoint: str = "https://open.feedcoopapi.com/search_api/web_search"
    volc_search_api_key: str = ""
    volc_accesskey: str = ""
    volc_secretkey: str = ""
    search_max_images: int = 5
    search_region: str = "cn-north-1"
    #: 文搜图过滤：最小宽度与形状（横长方形 = 正侧面概率更高）
    search_image_width_min: int = 800
    search_image_shape: str = "横长方形"
    #: 候选图的最小边长（小于它的图当参考图没意义，直接丢弃）
    search_image_min_edge: int = 400
    #: 严格过滤返回 0 张时，自动放宽一次再搜（避免小众品牌被误判成"没这双鞋"）
    search_relax_on_empty: bool = True

    # ---------- 生成与质检 ----------
    style_id: str = "bw_lineart"
    #: 每轮自动生成张数。PM 已确认「用户只看到 1 张」——这项控制的是**内部**最多画几张：
    #: 设为 2 时，若第 1 张被质检判不合格（fast 模式偶发 Logo 崩坏），会自动补画 1 张再交付，
    #: 用户感知不到、也不额外消耗额度；极端情况（且第 1 张已达标）不会多花钱。
    gen_max_attempts: int = 2
    quality_min_score: float = 0.80
    artwork_width: int = 1536
    artwork_height: int = 1024
    task_max_upstream_calls: int = 10
    enable_vision_rank: bool = False
    #: 是否对候选源图做可用性预筛（单只/正侧面/背景干净），决定“推荐哪张”：
    #: 文搜图常返回“两只鞋合影/3"/4 角度”的资讯配图，不筛会直接把坏输入推给用户
    enable_source_screening: bool = True
    source_screen_max_candidates: int = 3
    # 说明："可用性判定"用的是布尔硬条件（单只鞋 & 正侧面 & 背景干净 & 清晰，四项全真），
    # 不用 0-1 分数阈值 —— 实测分数有波动（同一张图时而 0.25、时而过 0.6），布尔判断更稳。
    #: 型号置信度 >= 此值 -> 源图确认只展示 1 张推荐图（“就是这双”）；低于此值才展开多张让用户挑
    source_confirm_confidence: float = 0.75

    # ---------- 自预热（省掉预留实例后的折中，见 services/warmup.py 的取舍说明）----------
    #: 是否开启：线上为 true；本地开发不用（本地无网关长连接问题）
    enable_warmup: bool = False
    #: 要预热的 URL（逗号分隔，通常是“自己的公网地址”，含前端与后端）
    warmup_urls: str = ""
    #: 间隔秒数：不宜太短，默认 180（与 veFaaS 定时触发器同频）
    warmup_interval_seconds: int = 180
    #: 单次预热的超时（秒）：失败就认输，不拖累业务
    warmup_timeout_seconds: float = 15.0

    # ---------- 降级与调试 ----------
    enable_manual_source: bool = True
    enable_mock_provider: bool = True
    force_mock_provider: bool = False
    mock_quality: Literal["good", "low"] = "good"
    allowed_source_dirs: str = "./tmp/sources,./data/inbox"
    pipeline_inline: bool = False

    # ---------- 上游单价（人民币，仅用于轨迹里的成本估算）----------
    cost_per_image_call: float = 0.30
    cost_per_vision_call: float = 0.02
    cost_per_text_call: float = 0.01

    # ---------- 派生属性 ----------

    @field_validator("global_daily_generate_limit", mode="before")
    @classmethod
    def _blank_number_means_unset(cls, value: object) -> object:
        """.env 里写成 `KEY=`（空值）时应视为“未设置”，而不是报解析错误。"""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def data_root(self) -> Path:
        """数据根目录（相对路径按仓库根解析，避免受启动目录影响）。"""
        p = Path(self.data_dir).expanduser()
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()

    @property
    def allowed_source_dir_list(self) -> list[Path]:
        out: list[Path] = []
        for raw in self.allowed_source_dirs.split(","):
            raw = raw.strip()
            if not raw:
                continue
            p = Path(raw).expanduser()
            out.append(p if p.is_absolute() else (REPO_ROOT / p).resolve())
        return out

    @property
    def missing_ark_config(self) -> list[str]:
        """方舟配置还缺哪些项（用于界面/日志如实提示，而不是启动就崩）。"""
        missing: list[str] = []
        if not self.ark_api_key:
            missing.append("ARK_API_KEY")
        if not self.ark_text_model:
            missing.append("ARK_TEXT_MODEL")
        if not self.ark_vision_model:
            missing.append("ARK_VISION_MODEL")
        if not self.ark_image_model:
            missing.append("ARK_IMAGE_MODEL")
        return missing

    @property
    def real_mode_ready(self) -> bool:
        return not self.force_mock_provider and not self.missing_ark_config

    @property
    def use_mock_providers(self) -> bool:
        """是否使用 mock 上游。

        规则（对应内部工程笔记 4.7(4) 与阶段文档 4.2）：
        - 配置齐全且未强制 mock -> 真实上游；
        - 配置不齐（含“只填了 Key”）时，若 ENABLE_MOCK_PROVIDER=true（演示模式）-> mock，
          并在界面/健康检查里明确告知还给哪些项；
        - 配置不齐且 ENABLE_MOCK_PROVIDER=false -> 如实报错（不假装成功）。
        """
        if self.force_mock_provider:
            return True
        if self.missing_ark_config:
            return self.enable_mock_provider
        return False

    @property
    def ark_key_present(self) -> bool:
        return bool(self.ark_api_key)

    @field_validator("global_daily_generate_limit", mode="before")
    @classmethod
    def _blank_number_means_unset_guard(cls, value: object) -> object:  # pragma: no cover
        return value

    @property
    def search_credentials_present(self) -> bool:
        return bool(self.volc_search_api_key or (self.volc_accesskey and self.volc_secretkey))

    @property
    def auth_required(self) -> bool:
        """是否需要登录：prod 一律需要；dev 可用 FORCE_AUTH=true 打开以便测试。"""
        return self.env == "prod" or self.force_auth

    def redaction_values(self) -> list[str]:
        """需要从日志中抹掉的敏感值。"""
        return [
            v
            for v in (
                self.ark_api_key,
                self.volc_search_api_key,
                self.volc_accesskey,
                self.volc_secretkey,
                self.s3_access_key,
                self.s3_secret_key,
                self.invite_codes,
                self.admin_code,
            )
            if v
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
