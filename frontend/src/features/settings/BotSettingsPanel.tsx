import { CheckboxField } from "../../components/forms/CheckboxField";
import { SelectField } from "../../components/forms/SelectField";
import { TextField } from "../../components/forms/TextField";
import { PanelHeader } from "../../components/ui/PanelHeader";
import type { Config } from "../../types";
import { ACP_BRIDGE_BACKEND_OPTIONS, type SettingsForm } from "./constants";

type BotSettingsPanelProps = {
  form: SettingsForm;
  config?: Config;
  onChange: (key: string, value: string | number | boolean) => void;
};

export function BotSettingsPanel({ form, config, onChange }: BotSettingsPanelProps) {
  const reviewEnabled = Boolean(form.telegram_remote_review_enabled);
  const agentEnabled = Boolean(form.telegram_agent_enabled);
  const claudeEnabled = Boolean(form.telegram_agent_claude_enabled);
  const chatId = String(form.telegram_bot_chat_id ?? "");

  return (
    <div className="form-stack">
      <section className="panel">
        <PanelHeader
          title="Telegram Bot 远程审核"
          description="绑定 Bot 后，待人工审核的内容摘要和字幕纠错会完整推送到指定聊天。用户直接在 Telegram 回复意见，系统会解析修改并继续后续流程。"
        />
        <div className="form-stack">
          <CheckboxField
            label="启用 Telegram 远程审核"
            checked={reviewEnabled}
            onChange={(event) => onChange("telegram_remote_review_enabled", event.target.checked)}
          />
          <TextField
            label="Telegram Bot API Base URL"
            value={String(form.telegram_bot_api_base_url ?? "https://api.telegram.org")}
            onChange={(event) => onChange("telegram_bot_api_base_url", event.target.value)}
            placeholder="https://api.telegram.org"
          />
          <TextField
            label="Bot Token"
            type="password"
            value={String(form.telegram_bot_token ?? "")}
            onChange={(event) => onChange("telegram_bot_token", event.target.value)}
            placeholder={config?.telegram_bot_token_set ? "已设置，留空则不更新" : "留空则不更新"}
          />
          <TextField
            label="审核接收 Chat ID"
            value={chatId}
            onChange={(event) => onChange("telegram_bot_chat_id", event.target.value)}
            placeholder="例如 123456789 或 -100xxxxxxxxxx"
          />
          <div className="notice">
            <div>
              当前状态：
              {reviewEnabled ? (config?.telegram_bot_token_set && chatId ? "已启用并具备推送条件" : "已启用，但 Token / Chat ID 还不完整") : "未启用"}
            </div>
            <div className="muted compact-top">
              建议让目标账号先主动给 Bot 发一条消息，再把对应 chat id 填到这里。后续请直接回复 Bot 推送的审核消息，不要新开一条无上下文消息。
            </div>
          </div>
        </div>
      </section>

      <section className="panel">
        <PanelHeader
          title="Telegram Agent 工程任务"
          description="控制未知命令、链路分析和工程实现任务如何通过 ACP、Codex、Claude 执行。当前默认推荐 Codex + gpt-5.4-mini。"
        />
        <div className="form-stack">
          <CheckboxField
            label="启用 Telegram Agent 分流"
            checked={agentEnabled}
            onChange={(event) => onChange("telegram_agent_enabled", event.target.checked)}
          />
          <CheckboxField
            label="启用 Claude CLI 执行器"
            checked={claudeEnabled}
            onChange={(event) => onChange("telegram_agent_claude_enabled", event.target.checked)}
          />
          <div className="field-row">
            <TextField
              label="Claude Command"
              value={String(form.telegram_agent_claude_command ?? "claude")}
              onChange={(event) => onChange("telegram_agent_claude_command", event.target.value)}
            />
            <TextField
              label="Claude Model"
              value={String(form.telegram_agent_claude_model ?? "opus")}
              onChange={(event) => onChange("telegram_agent_claude_model", event.target.value)}
            />
          </div>
          <div className="field-row">
            <TextField
              label="Codex Command"
              value={String(form.telegram_agent_codex_command ?? "codex")}
              onChange={(event) => onChange("telegram_agent_codex_command", event.target.value)}
            />
            <TextField
              label="Codex Model"
              value={String(form.telegram_agent_codex_model ?? "gpt-5.4-mini")}
              onChange={(event) => onChange("telegram_agent_codex_model", event.target.value)}
            />
          </div>
          <TextField
            label="ACP Bridge Command"
            value={String(form.telegram_agent_acp_command ?? "")}
            onChange={(event) => onChange("telegram_agent_acp_command", event.target.value)}
            placeholder='留空则使用内置 bridge，例如 "python scripts/acp_bridge.py"'
          />
          <div className="field-row">
            <SelectField
              label="ACP 主后端"
              value={String(form.acp_bridge_backend ?? "codex")}
              onChange={(event) => onChange("acp_bridge_backend", event.target.value)}
              options={ACP_BRIDGE_BACKEND_OPTIONS.map((backend) => ({ value: backend, label: backend }))}
            />
            <SelectField
              label="ACP 回退后端"
              value={String(form.acp_bridge_fallback_backend ?? "claude")}
              onChange={(event) => onChange("acp_bridge_fallback_backend", event.target.value)}
              options={ACP_BRIDGE_BACKEND_OPTIONS.map((backend) => ({ value: backend, label: backend }))}
            />
          </div>
          <div className="field-row">
            <TextField
              label="ACP Claude Model"
              value={String(form.acp_bridge_claude_model ?? "opus")}
              onChange={(event) => onChange("acp_bridge_claude_model", event.target.value)}
            />
            <TextField
              label="ACP Codex Command"
              value={String(form.acp_bridge_codex_command ?? "codex")}
              onChange={(event) => onChange("acp_bridge_codex_command", event.target.value)}
            />
          </div>
          <div className="field-row">
            <TextField
              label="ACP Codex Model"
              value={String(form.acp_bridge_codex_model ?? "gpt-5.4-mini")}
              onChange={(event) => onChange("acp_bridge_codex_model", event.target.value)}
            />
            <TextField
              label="Agent 状态目录"
              value={String(form.telegram_agent_state_dir ?? "data/telegram-agent")}
              onChange={(event) => onChange("telegram_agent_state_dir", event.target.value)}
            />
          </div>
          <div className="field-row">
            <TextField
              label="任务超时秒数"
              type="number"
              value={String(form.telegram_agent_task_timeout_sec ?? 900)}
              onChange={(event) => onChange("telegram_agent_task_timeout_sec", Number(event.target.value))}
            />
            <TextField
              label="结果摘要字符数"
              type="number"
              value={String(form.telegram_agent_result_max_chars ?? 3500)}
              onChange={(event) => onChange("telegram_agent_result_max_chars", Number(event.target.value))}
            />
          </div>
        </div>
      </section>
    </div>
  );
}
