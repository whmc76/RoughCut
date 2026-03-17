import { CheckboxField } from "../../components/forms/CheckboxField";
import { TextField } from "../../components/forms/TextField";
import { PanelHeader } from "../../components/ui/PanelHeader";
import type { Config } from "../../types";
import type { SettingsForm } from "./constants";

type BotSettingsPanelProps = {
  form: SettingsForm;
  config?: Config;
  onChange: (key: string, value: string | number | boolean) => void;
};

export function BotSettingsPanel({ form, config, onChange }: BotSettingsPanelProps) {
  const enabled = Boolean(form.telegram_remote_review_enabled);
  const chatId = String(form.telegram_bot_chat_id ?? "");

  return (
    <section className="panel">
      <PanelHeader
        title="Telegram Bot 远程审核"
        description="绑定 Bot 后，待人工审核的内容摘要和字幕纠错会完整推送到指定聊天。用户直接在 Telegram 回复意见，系统会解析修改并继续后续流程。"
      />
      <div className="form-stack">
        <CheckboxField
          label="启用 Telegram 远程审核"
          checked={enabled}
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
          <div>当前状态：{enabled ? (config?.telegram_bot_token_set && chatId ? "已启用并具备推送条件" : "已启用，但 Token / Chat ID 还不完整") : "未启用"}</div>
          <div className="muted compact-top">
            建议让目标账号先主动给 Bot 发一条消息，再把对应 chat id 填到这里。后续请直接回复 Bot 推送的审核消息，不要新开一条无上下文消息。
          </div>
        </div>
      </div>
    </section>
  );
}
