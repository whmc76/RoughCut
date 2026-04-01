import { CheckboxField } from "../../components/forms/CheckboxField";
import { SelectField } from "../../components/forms/SelectField";
import { TextField } from "../../components/forms/TextField";
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
  const transportEnabled = reviewEnabled || agentEnabled;
  const chatId = String(form.telegram_bot_chat_id ?? "");
  const botTokenReady = Boolean(config?.telegram_bot_token_set);
  const reviewStatus = reviewEnabled ? (botTokenReady && chatId ? "就绪" : "待补全") : "关闭";
  const agentStatus = agentEnabled ? "在线" : "关闭";

  return (
    <section className="settings-module-panel settings-bot-panel">
      <div className="settings-module-summary-strip">
        <article className="settings-module-chip">
          <span className="settings-overview-label">远程审核</span>
          <strong>{reviewStatus}</strong>
          <div className="muted">{reviewEnabled ? "摘要 / 字幕 / 成片通知" : "未发送审核通知"}</div>
        </article>
        <article className="settings-module-chip">
          <span className="settings-overview-label">Agent</span>
          <strong>{agentStatus}</strong>
          <div className="muted">{agentEnabled ? "接收 Telegram 工程命令" : "不接管 Telegram 命令"}</div>
        </article>
        <article className="settings-module-chip">
          <span className="settings-overview-label">传输凭据</span>
          <strong>{botTokenReady ? "Bot Token 已就绪" : "Bot Token 未配置"}</strong>
          <div className="muted">{chatId ? `Chat ID ${chatId}` : "Chat ID 待填写"}</div>
        </article>
      </div>

      <div className="settings-module-dual-grid">
        <section className="settings-tool-card settings-tool-card-review">
          <div className="settings-tool-card-head">
            <div>
              <strong>Telegram Bot 远程审核</strong>
              <div className="muted">只控制内容摘要、字幕、成片这些审核通知。</div>
            </div>
          </div>
        <div className="form-stack">
          <CheckboxField
            label="启用 Telegram 远程审核"
            checked={reviewEnabled}
            onChange={(event) => onChange("telegram_remote_review_enabled", event.target.checked)}
          />
          {transportEnabled ? (
            <>
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
              {reviewEnabled ? (
                <>
                  <TextField
                    label="审核接收 Chat ID"
                    value={chatId}
                    onChange={(event) => onChange("telegram_bot_chat_id", event.target.value)}
                    placeholder="例如 123456789 或 -100xxxxxxxxxx"
                  />
                  <div className="notice">
                    <div>当前状态：{botTokenReady && chatId ? "已启用并具备推送条件" : "已启用，但 Token / Chat ID 还不完整"}</div>
                    <div className="muted compact-top">建议先让目标账号给 Bot 发一条消息，再回填 chat id。</div>
                  </div>
                </>
              ) : agentEnabled ? (
                <div className="notice">
                  <div>当前状态：{botTokenReady ? "Agent 已具备 Telegram 轮询条件" : "Agent 已启用，但 Bot Token 还未配置"}</div>
                  <div className="muted compact-top">远程审核关闭时不会发送审核消息，但 Agent 仍需要 Bot Token 来接收 Telegram 命令。</div>
                </div>
              ) : null}
            </>
          ) : (
            <div className="muted">
              {agentEnabled ? "远程审核关闭；即使下方 Agent 开启，也不会推送内容摘要 / 字幕 / 成片审核。" : "远程审核关闭，不会推送内容摘要 / 字幕 / 成片审核。"}
            </div>
          )}
        </div>
        </section>

        <section className="settings-tool-card settings-tool-card-agent">
          <div className="settings-tool-card-head">
            <div>
              <strong>Telegram Agent 工程任务</strong>
              <div className="muted">只控制 Telegram 命令、工程任务分流和结果回推。</div>
            </div>
          </div>
        <div className="form-stack">
          <CheckboxField
            label="启用 Telegram Agent 分流"
            checked={agentEnabled}
            onChange={(event) => onChange("telegram_agent_enabled", event.target.checked)}
          />
          {agentEnabled ? (
            <>
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
              <details className="settings-disclosure" open={claudeEnabled}>
                <summary className="settings-disclosure-trigger">
                  <div>
                    <strong>执行器与 ACP 细节</strong>
                    <div className="muted">执行器、Bridge、超时和状态目录</div>
                  </div>
                </summary>
                <div className="settings-disclosure-body">
                  <div className="form-stack">
                    <CheckboxField
                      label="启用 Claude CLI 执行器"
                      checked={claudeEnabled}
                      onChange={(event) => onChange("telegram_agent_claude_enabled", event.target.checked)}
                    />
                    <div className="muted">关闭后不仅不能直连 `/run claude`，ACP 主后端或回退后端里的 Claude 也会被一并禁用。</div>
                    {claudeEnabled && (
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
                    )}
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
                </div>
              </details>
            </>
          ) : (
            <div className="muted">
              {reviewEnabled ? "Agent 关闭；仍可使用上方 Telegram 远程审核。" : "Agent 关闭，不会接管 Telegram 命令或工程任务。"}
            </div>
          )}
        </div>
        </section>
      </div>
    </section>
  );
}
