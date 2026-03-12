import type { ContentProfileMemoryStats } from "../../types";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { memoryFieldLabels } from "./constants";

type MemoryRecentCorrectionsPanelProps = {
  stats: ContentProfileMemoryStats;
};

export function MemoryRecentCorrectionsPanel({ stats }: MemoryRecentCorrectionsPanelProps) {
  return (
    <section className="panel top-gap">
      <PanelHeader title="最近纠正" description="原型阶段直接按原始结构展示最近行为。" />
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>字段</th>
              <th>原值</th>
              <th>修正后</th>
              <th>来源任务</th>
            </tr>
          </thead>
          <tbody>
            {stats.recent_corrections.map((item, index) => (
              <tr key={`${item.field_name}-${index}`}>
                <td>{memoryFieldLabels[String(item.field_name)] || String(item.field_name)}</td>
                <td>{String(item.original_value || "空")}</td>
                <td>{String(item.corrected_value || "—")}</td>
                <td>{String(item.source_name || "—")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
