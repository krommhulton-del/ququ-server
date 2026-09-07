"""专家模型封装:OpenAI SDK → DeepSeek(EXPERT_MODEL,默认 deepseek-v4-pro)。

deepseek-v4-pro 必须显式开启深度思考(thinking + reasoning_effort),否则能力大幅下降。
本模块为非流式调用,只取最终回复 content;若将来改流式,需同时处理 reasoning_content 与 content。

职责:
- generate_plan:需求 → 结构化计划 dict(步骤列表 + 指令 + 验收标准)
- review:执行结果 → 审查意见 {verdict: pass|changes, comments}
- 渲染:plan dict → plan.md / review dict → review.md
"""
import logging

from openai import OpenAI

from .config import settings
from .utils import extract_json

logger = logging.getLogger(__name__)

_client: OpenAI | None = None

# 成本熔断:最近一次「生成/复审」调用的 token 用量(nodes 在调用前后用 last_usage 读取)
_usage: list[int] = [0, 0]


def _reset_usage() -> None:
    _usage[0] = _usage[1] = 0


def _record_usage(u) -> None:
    if u is None:
        return
    _usage[0] += int(getattr(u, "prompt_tokens", 0) or 0)
    _usage[1] += int(getattr(u, "completion_tokens", 0) or 0)


def last_usage() -> tuple[int, int]:
    """最近一次 generate_plan/review 累计的 (input_tokens, output_tokens)。"""
    return _usage[0], _usage[1]


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置(检查项目根 .env)")
        _client = OpenAI(api_key=settings.deepseek_api_key, base_url="https://api.deepseek.com")
    return _client


PLAN_SYSTEM_PROMPT = """你是一名资深软件架构师与项目经理。用户会提出一个软件需求,你要把它拆解成一个编码智能体可逐步执行的计划。

只输出一个 JSON 对象,不要任何解释文字或代码块围栏,格式:
{
  "title": "任务标题",
  "summary": "一句话概述",
  "steps": [
    {
      "id": 1,
      "name": "步骤名称",
      "instruction": "给执行智能体的具体指令(写明要创建的文件路径、技术选型、关键逻辑,具体到无需追问)",
      "acceptance": ["该步骤的验收标准(可验证)"]
    }
  ],
  "acceptance_criteria": ["整体验收标准"]
}

要求:步骤 2~6 个,每个步骤一个编码智能体可在几分钟内完成;instruction 必须写清文件路径与要点;每条 acceptance 都要能实际验证。
若需求中附有「可参考的开源项目」,各步骤 instruction 应写明如何借鉴(直接使用或参考其设计),避免从零造轮子;与需求无关的忽略即可。"""

REVIEW_SYSTEM_PROMPT = """你是一名资深代码审查专家。下面是一个任务的计划与执行结果(执行日志摘要、产出文件清单)。审查执行结果是否达成计划要求。

只输出一个 JSON 对象,不要任何解释文字或代码块围栏,格式:
{
  "verdict": "pass 或 changes",
  "summary": "一句话结论",
  "comments": ["意见1", "意见2"]
}

全部达成且无明显缺陷 → "pass";存在未达成、缺陷或需修改之处 → "changes",并在 comments 逐条写明。"""

DISCUSS_SYSTEM_PROMPT = """你是 AI Orchestrator 平台的驻场专家,与用户讨论任务与计划(阶段 4 全局讨论区)。

职责:
1. 解答用户关于任务、执行结果、技术方案的问题;
2. 把模糊想法细化成结构清晰、可执行的任务计划;
3. 关联任务时,结合任务状态、日志与计划给出务实判断。

要求:回答直接、有干货;若用户的诉求可以落地成任务计划,给出带步骤与验收标准的计划建议(用户可一键转为计划);不要寒暄凑字数。"""


def _chat(
    system: str, user: str, max_tokens: int = 16384, model: str | None = None,
    reasoning_effort: str = "max",
) -> tuple[str, str]:
    """返回 (content, reasoning_content);reasoning 可能为空串(阶段 3b:专家思考可见)。

    model 缺省用 settings.expert_model;成本熔断降级时传入便宜模型(去掉 deep thinking 收益换省钱)。
    reasoning_effort:max(默认,规划/复审用) / high(对话/解读用,思考更短、正文更足)。
    """
    resp = _get_client().chat.completions.create(
        model=model or settings.expert_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens,
        # 显式开启深度思考:reasoning_effort 是顶层参数(与 model 平级);
        # thinking 在 extra_body(实测两种写法 DeepSeek 都接受,顶层为标准位置)
        reasoning_effort=reasoning_effort,
        extra_body={"thinking": {"type": "enabled"}},
    )
    _record_usage(resp.usage)
    msg = resp.choices[0].message
    return (msg.content or ""), (getattr(msg, "reasoning_content", None) or "")


def discuss_stream(system: str, user: str, max_tokens: int = 16384, reasoning_effort: str = "max"):
    """流式讨论(阶段 4):逐块产出 {"kind": "thinking"|"text", "delta": str}。

    先 reasoning_content(思考),后 content(回答);供 SSE 逐块推送。
    max_tokens 默认 16384:实测 4096 时思考内容会耗尽预算,最终回答为空
    (2026-08-22 验收发现,复杂规划问题 7675 字符思考 → 正文 0 字节)。
    reasoning_effort:"high" 可显著缩短思考、给正文留足预算(对话/解读场景更不易"转圈不出字")。
    """
    resp = _get_client().chat.completions.create(
        model=settings.expert_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        extra_body={"thinking": {"type": "enabled"}},
        stream=True,
    )
    for chunk in resp:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        rc = getattr(delta, "reasoning_content", None)
        if rc:
            yield {"kind": "thinking", "delta": rc}
        c = getattr(delta, "content", None)
        if c:
            yield {"kind": "text", "delta": c}


def _chat_json(
    system: str, user: str, max_tokens: int = 8192, model: str | None = None
) -> tuple[dict, str]:
    """调模型并要求 JSON 输出,返回 (dict, 思考内容);解析失败时带纠错提示重试一次。"""
    _reset_usage()
    last_err: Exception | None = None
    reasoning_parts: list[str] = []
    for _attempt in range(2):
        content, reasoning = _chat(system, user, max_tokens, model=model)
        if reasoning:
            reasoning_parts.append(reasoning)
        try:
            return extract_json(content), "\n".join(reasoning_parts)
        except ValueError as e:
            last_err = e
            user += "\n\n(上一轮输出无法解析为 JSON,请只输出一个合法的 JSON 对象,不要任何解释文字或代码块围栏)"
    raise RuntimeError(f"专家模型输出无法解析为 JSON: {last_err}")


def generate_plan(
    user_message: str, references: list[dict] | None = None, model: str | None = None
) -> tuple[dict, str]:
    """需求 → (标准化计划 dict, 专家思考内容)(字段缺失时给安全默认值)。

    阶段 5:references 为规划前搜到的参考项目摘要,注入 prompt 供专家借鉴;
    计划 dict 同步携带 references,render_plan_md 渲染为「参考项目」节。
    """
    prompt = f"用户需求:\n{user_message}"
    if references:
        lines = [
            "",
            "规划前已搜索到的可参考开源项目(借鉴其设计/实现,避免重复造轮子;与需求无关可忽略):",
        ]
        for i, r in enumerate(references, 1):
            lines.append(
                f"{i}. {r['name']}(★{r['stars']}, {r['language']}): {r['description']}"
            )
            if r.get("readme_excerpt"):
                lines.append(f"   README 摘要: {r['readme_excerpt']}")
        prompt += "\n" + "\n".join(lines)
    plan, reasoning = _chat_json(PLAN_SYSTEM_PROMPT, prompt, model=model)
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        raise RuntimeError("专家输出缺少 steps 字段")
    normalized = []
    for i, s in enumerate(steps, 1):
        normalized.append(
            {
                "id": int(s.get("id", i)),
                "name": str(s.get("name") or f"步骤{i}"),
                "instruction": str(s.get("instruction") or ""),
                "acceptance": [str(a) for a in (s.get("acceptance") or [])],
            }
        )
    return {
        "title": str(plan.get("title") or "未命名任务"),
        "summary": str(plan.get("summary") or ""),
        "steps": normalized,
        "acceptance_criteria": [str(a) for a in (plan.get("acceptance_criteria") or [])],
        "references": references or [],
    }, reasoning


def render_plan_md(plan: dict) -> str:
    """计划 dict → 人类可读 plan.md。"""
    lines = [f"# {plan['title']}", "", plan["summary"], ""]
    for s in plan["steps"]:
        lines += [
            f"## 步骤 {s['id']}:{s['name']}",
            "",
            "**指令**:",
            s["instruction"],
            "",
            "**验收标准**:",
        ]
        lines += [f"- {a}" for a in s["acceptance"]] + [""]
    if plan["acceptance_criteria"]:
        lines += ["## 整体验收标准"] + [f"- {a}" for a in plan["acceptance_criteria"]] + [""]
    # 阶段 5:参考项目节(规划前 GitHub 搜索所得;无搜索结果则无此节)
    refs = plan.get("references") or []
    if refs:
        lines += ["## 参考项目", ""]
        lines += [
            f"- [{r['name']}]({r['url']})(★{r['stars']}, {r['language']}) — {r['description']}"
            for r in refs
        ]
        lines += [""]
    return "\n".join(lines)


def review(
    plan: dict,
    user_message: str,
    log_tail: list[str],
    files: list[str],
    model: str | None = None,
) -> tuple[dict, str]:
    """审查执行结果,返回 ({verdict: pass|changes, summary, comments}, 专家思考内容)。"""
    files_str = "\n".join(f"- {f}" for f in files) if files else "(无产出文件)"
    user = (
        f"用户需求:\n{user_message}\n\n"
        f"计划:\n{render_plan_md(plan)}\n\n"
        f"执行日志(尾部 {len(log_tail)} 行):\n"
        + "\n".join(log_tail)
        + "\n\n"
        f"产出文件清单:\n{files_str}"
    )
    verdict, reasoning = _chat_json(REVIEW_SYSTEM_PROMPT, user, max_tokens=4096, model=model)
    verdict["verdict"] = verdict.get("verdict", "changes")
    verdict["summary"] = str(verdict.get("summary") or "")
    verdict["comments"] = [str(c) for c in (verdict.get("comments") or [])]
    return verdict, reasoning


def render_review_md(verdict: dict) -> str:
    """审查意见 dict → review.md。"""
    passed = verdict["verdict"] == "pass"
    lines = [
        f"# 复审结论:{'通过' if passed else '不通过'}",
        "",
        f"**结论**:{verdict['summary']}",
        "",
    ]
    if verdict["comments"]:
        lines += ["**意见**:"]
        lines += [f"- {c}" for c in verdict["comments"]]
        lines += [""]
    return "\n".join(lines)
