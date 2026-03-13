import { getCurrentUiLocale, translate } from "../../i18n";

export const memoryFieldLabels: Record<string, string> = {
  subject_brand: "品牌",
  subject_model: "型号",
  subject_type: "主体类型",
  video_theme: "视频主题",
};

export function memoryFieldLabel(field: string): string {
  const key = `memory.fields.${field}`;
  const translated = translate(getCurrentUiLocale(), key);
  return translated === key ? memoryFieldLabels[field] || field : translated;
}
