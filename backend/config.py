"""环境变量与路径配置(全部从项目根 .env 读取,见 .env.example)。"""
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 密钥
    deepseek_api_key: str = ""
    github_token: str = ""

    # 模型
    expert_model: str = "deepseek-v4-pro"   # 专家模型(规划 / 复审,带 thinking)
    executor_model: str = "deepseek-v4-flash"  # 执行者模型(注入 claude CLI 的 ANTHROPIC_MODEL;flash 首包快,工具调用稳)

    # claude CLI(直接注入环境变量直连 DeepSeek,不用 claude-code-router)
    claude_cli_path: str = "claude"
    anthropic_base_url: str = "https://api.deepseek.com/anthropic"
    # 权限策略:skip = --dangerously-skip-permissions;whitelist = --allowedTools 白名单
    executor_permission_mode: str = "skip"
    # 阶段 3:执行超时(秒),超时 kill 子进程并判失败
    executor_timeout_seconds: int = 1800
    # 阶段 3 预留:auto / manual(3a 仅解析不启用;3b 实现 manual 门禁)
    executor_confirm_mode: str = "auto"
    # 阶段 W1:引擎开关;true=旧引擎(默认,现状),false=LangGraph 新引擎(骨架,Mock 节点)
    use_legacy_engine: bool = True
    # 阶段 W2:节点数据源开关;true=Mock 节点(默认,W3 断点恢复测试用),false=真实 expert/executor 调用
    use_mock: bool = True

    # 成本熔断(每任务):累计 token 计量 + 超限熔断 + 专家模型降级
    token_budget: int = 300000  # 累计 token 达此上限 → 熔断(任务判失败,不再烧钱)
    cost_downgrade_threshold: int = 150000  # 累计 token 达此值 → 专家降级为便宜模型
    cost_downgrade_model: str = "deepseek-v4-flash"  # 降级目标模型(执行者同款,便宜)

    # 专家介入(阶段 8):gate 门禁模式;manual = 规划后 interrupt() 暂停等专家确认/反馈
    gate_mode: str = "auto"  # auto | manual

    # 分级路由(阶段 11):按任务难度事前选专家模型;off = 关,heuristic = 免费关键词启发式
    tier_mode: str = "heuristic"  # off | heuristic
    easy_tier_model: str = "deepseek-v4-flash"  # 简单任务直接用的便宜模型

    # 目录
    plans_dir: Path = ROOT / "plans"
    reviews_dir: Path = ROOT / "reviews"
    logs_dir: Path = ROOT / "logs"
    discussions_dir: Path = ROOT / "discussions"  # 阶段 4:专家讨论记录(jsonl)
    events_dir: Path = ROOT / "events"  # 阶段 7a:任务事件源(jsonl)
    workspace_base: Path = ROOT / "workspaces"  # env: WORKSPACE_BASE(相对路径按项目根解析)
    db_path: Path = ROOT / "data" / "app.db"

    @field_validator("workspace_base", mode="after")
    @classmethod
    def _resolve_workspace_base(cls, v: Path) -> Path:
        return v if v.is_absolute() else ROOT / v


settings = Settings()
