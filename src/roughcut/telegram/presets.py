from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramAgentPreset:
    name: str
    provider: str
    description: str
    requires_task: bool
    requires_confirmation: bool
    allow_edits: bool
    isolated_workspace: bool
    prompt_template: str


_PRESETS = {
    ("claude", "inspect"): TelegramAgentPreset(
        name="inspect",
        provider="claude",
        description="阅读代码并总结相关实现，不修改文件。",
        requires_task=True,
        requires_confirmation=False,
        allow_edits=False,
        isolated_workspace=False,
        prompt_template=(
            "请检查当前 RoughCut 仓库并完成下列分析任务。\n"
            "只做阅读和总结，不要修改文件。\n"
            "任务：{task}\n"
            "{scope_block}"
            "{job_block}"
            "输出要求：先给结论，再给关键文件和实现路径。"
        ),
    ),
    ("claude", "review"): TelegramAgentPreset(
        name="review",
        provider="claude",
        description="做代码审查，优先指出 bug、风险和缺测。",
        requires_task=False,
        requires_confirmation=False,
        allow_edits=False,
        isolated_workspace=False,
        prompt_template=(
            "你在 RoughCut 仓库里做代码审查。\n"
            "优先输出 bug、行为回归、风险点和缺失测试；不要修改文件。\n"
            "{task_block}"
            "{scope_block}"
            "{job_block}"
            "输出要求：先列 findings，再列 open questions。"
        ),
    ),
    ("claude", "plan"): TelegramAgentPreset(
        name="plan",
        provider="claude",
        description="产出结构化实施计划，不修改文件。",
        requires_task=True,
        requires_confirmation=False,
        allow_edits=False,
        isolated_workspace=False,
        prompt_template=(
            "请为 RoughCut 仓库中的需求生成可执行计划。\n"
            "只输出实施方案和风险，不要修改文件。\n"
            "任务：{task}\n"
            "{scope_block}"
            "{job_block}"
            "输出要求：目标、步骤、风险、验证方式。"
        ),
    ),
    ("claude", "implement"): TelegramAgentPreset(
        name="implement",
        provider="claude",
        description="在仓库内实现指定改动，需二次确认。",
        requires_task=True,
        requires_confirmation=True,
        allow_edits=True,
        isolated_workspace=True,
        prompt_template=(
            "请在 RoughCut 仓库中直接实现以下改动，并在结束时说明修改内容和验证结果。\n"
            "任务：{task}\n"
            "{scope_block}"
            "{job_block}"
            "要求：改动保持收敛；优先最小可行实现；如果能跑测试就执行相关测试。"
        ),
    ),
    ("claude", "build"): TelegramAgentPreset(
        name="build",
        provider="claude",
        description="在隔离工作区执行构建/测试诊断，不修改主工作树。",
        requires_task=True,
        requires_confirmation=False,
        allow_edits=False,
        isolated_workspace=True,
        prompt_template=(
            "请在 RoughCut 仓库的隔离工作区中完成构建或验证任务。\n"
            "不要修改主工作树；优先复用现有脚本和命令。\n"
            "任务：{task}\n"
            "{scope_block}"
            "{job_block}"
            "输出要求：必须包含构建状态、执行过的命令、失败原因或产物位置。"
        ),
    ),
    ("codex", "inspect"): TelegramAgentPreset(
        name="inspect",
        provider="codex",
        description="阅读代码并总结相关实现，不修改文件。",
        requires_task=True,
        requires_confirmation=False,
        allow_edits=False,
        isolated_workspace=False,
        prompt_template=(
            "请检查当前 RoughCut 仓库并完成下列分析任务。\n"
            "只做阅读和总结，不要修改文件。\n"
            "任务：{task}\n"
            "{scope_block}"
            "{job_block}"
            "输出要求：先给结论，再给关键文件和实现路径。"
        ),
    ),
    ("codex", "review"): TelegramAgentPreset(
        name="review",
        provider="codex",
        description="做代码审查，优先指出 bug、风险和缺测。",
        requires_task=False,
        requires_confirmation=False,
        allow_edits=False,
        isolated_workspace=False,
        prompt_template=(
            "你在 RoughCut 仓库里做代码审查。\n"
            "优先输出 bug、行为回归、风险点和缺失测试；不要修改文件。\n"
            "{task_block}"
            "{scope_block}"
            "{job_block}"
            "输出要求：先列 findings，再列 open questions。"
        ),
    ),
    ("codex", "plan"): TelegramAgentPreset(
        name="plan",
        provider="codex",
        description="产出结构化实施计划，不修改文件。",
        requires_task=True,
        requires_confirmation=False,
        allow_edits=False,
        isolated_workspace=False,
        prompt_template=(
            "请为 RoughCut 仓库中的需求生成可执行计划。\n"
            "只输出实施方案和风险，不要修改文件。\n"
            "任务：{task}\n"
            "{scope_block}"
            "{job_block}"
            "输出要求：目标、步骤、风险、验证方式。"
        ),
    ),
    ("codex", "implement"): TelegramAgentPreset(
        name="implement",
        provider="codex",
        description="在仓库内实现指定改动，需二次确认。",
        requires_task=True,
        requires_confirmation=True,
        allow_edits=True,
        isolated_workspace=True,
        prompt_template=(
            "请在 RoughCut 仓库中直接实现以下改动，并在结束时说明修改内容和验证结果。\n"
            "任务：{task}\n"
            "{scope_block}"
            "{job_block}"
            "要求：改动保持收敛；优先最小可行实现；如果能跑测试就执行相关测试。"
        ),
    ),
    ("codex", "build"): TelegramAgentPreset(
        name="build",
        provider="codex",
        description="在隔离工作区执行构建/测试诊断，不修改主工作树。",
        requires_task=True,
        requires_confirmation=False,
        allow_edits=False,
        isolated_workspace=True,
        prompt_template=(
            "请在 RoughCut 仓库的隔离工作区中完成构建或验证任务。\n"
            "不要修改主工作树；优先复用现有脚本和命令。\n"
            "任务：{task}\n"
            "{scope_block}"
            "{job_block}"
            "输出要求：必须包含构建状态、执行过的命令、失败原因或产物位置。"
        ),
    ),
    ("acp", "triage"): TelegramAgentPreset(
        name="triage",
        provider="acp",
        description="通过 ACP 分析复杂请求、错误或未知命令，不修改文件。",
        requires_task=True,
        requires_confirmation=False,
        allow_edits=False,
        isolated_workspace=False,
        prompt_template=(
            "你在处理来自 Telegram agent 的复杂请求或未知命令。\n"
            "先判断是否已有现成功能或命令可以满足；如果没有，再指出最小改动方案。\n"
            "只做诊断、归因、方案和命令建议，不要修改文件。\n"
            "任务：{task}\n"
            "{scope_block}"
            "{job_block}"
            "输出要求：结论、原因、建议命令/链路、需要改动的文件。"
        ),
    ),
    ("acp", "delegate"): TelegramAgentPreset(
        name="delegate",
        provider="acp",
        description="调用外部 ACP bridge 执行结构化任务。",
        requires_task=True,
        requires_confirmation=True,
        allow_edits=True,
        isolated_workspace=True,
        prompt_template=(
            "任务：{task}\n"
            "{scope_block}"
            "{job_block}"
            "请按 preset 约束执行，并返回摘要、产出和失败原因。"
        ),
    ),
    ("acp", "extend"): TelegramAgentPreset(
        name="extend",
        provider="acp",
        description="通过 ACP 扩展 Telegram agent 能力或修复复杂链路，需二次确认。",
        requires_task=True,
        requires_confirmation=True,
        allow_edits=True,
        isolated_workspace=True,
        prompt_template=(
            "你在 RoughCut 仓库里扩展 Telegram agent 能力，或修复复杂错误、结构问题、链路问题。\n"
            "如果请求对应未知命令，优先把它沉淀成可复用的命令、路由或兜底能力。\n"
            "请直接完成最小可行实现，并在结束时说明修改内容、影响范围和验证结果。\n"
            "任务：{task}\n"
            "{scope_block}"
            "{job_block}"
            "要求：改动收敛、优先复用现有组件、必要时补测试。"
        ),
    ),
    ("acp", "build"): TelegramAgentPreset(
        name="build",
        provider="acp",
        description="通过 ACP 在隔离工作区执行构建/测试诊断。",
        requires_task=True,
        requires_confirmation=False,
        allow_edits=False,
        isolated_workspace=True,
        prompt_template=(
            "你在 RoughCut 仓库的隔离工作区里执行构建或验证任务。\n"
            "不要修改主工作树；优先用仓库现有脚本和命令定位问题。\n"
            "任务：{task}\n"
            "{scope_block}"
            "{job_block}"
            "输出要求：必须包含构建状态、执行命令、失败原因或产物位置。"
        ),
    ),
}


def get_preset(provider: str, name: str) -> TelegramAgentPreset | None:
    key = (str(provider or "").strip().lower(), str(name or "").strip().lower())
    return _PRESETS.get(key)


def list_presets() -> list[TelegramAgentPreset]:
    return list(_PRESETS.values())
