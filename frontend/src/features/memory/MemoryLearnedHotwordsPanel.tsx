import type { LearnedHotword } from "../../types";
import { EmptyState } from "../../components/ui/EmptyState";
import { ListActions } from "../../components/ui/ListActions";
import { ListCard } from "../../components/ui/ListCard";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";
import { formatDate } from "../../utils";

type MemoryLearnedHotwordsPanelProps = {
  hotwords: LearnedHotword[];
  isUpdating: boolean;
  onStatusChange: (hotwordId: string, status: LearnedHotword["status"]) => void;
};

function statusClassName(status: string): string {
  if (status === "active") return "status-pill done";
  if (status === "suppressed") return "status-pill running";
  return "status-pill failed";
}

function confidencePercent(value: number): string {
  return `${Math.round(Math.max(0, Math.min(1, Number(value) || 0)) * 100)}%`;
}

export function MemoryLearnedHotwordsPanel({ hotwords, isUpdating, onStatusChange }: MemoryLearnedHotwordsPanelProps) {
  const { t } = useI18n();

  return (
    <section className="panel">
      <PanelHeader title={t("memory.hotwords.title")} description={`${hotwords.length} ${t("memory.hotwords.count")}`} />
      <div className="list-stack">
        {hotwords.map((item) => (
          <ListCard key={item.id}>
            <div>
              <div className="row-title">{item.canonical_form || item.term}</div>
              <div className="muted">
                {item.term !== item.canonical_form ? `${item.term} · ` : ""}
                {item.aliases.length ? item.aliases.join(" / ") : t("memory.hotwords.noAliases")}
              </div>
              <div className="muted compact-top">
                {item.subject_domain || "global"} · {item.source} · {t("memory.hotwords.confidence")} {confidencePercent(item.confidence)} · {t("memory.hotwords.evidence")} {item.evidence_count} · {formatDate(item.last_seen_at || item.created_at)}
              </div>
              <div className="compact-top">
                <span className={statusClassName(item.status)}>{t(`memory.hotwords.status.${item.status}`)}</span>
              </div>
            </div>
            <ListActions>
              <button className="button ghost" type="button" disabled={isUpdating || item.status === "active"} onClick={() => onStatusChange(item.id, "active")}>
                {t("memory.hotwords.activate")}
              </button>
              <button className="button ghost" type="button" disabled={isUpdating || item.status === "suppressed"} onClick={() => onStatusChange(item.id, "suppressed")}>
                {t("memory.hotwords.suppress")}
              </button>
              <button className="button danger" type="button" disabled={isUpdating || item.status === "rejected"} onClick={() => onStatusChange(item.id, "rejected")}>
                {t("memory.hotwords.reject")}
              </button>
            </ListActions>
          </ListCard>
        ))}
        {!hotwords.length && <EmptyState message={t("memory.hotwords.empty")} />}
      </div>
    </section>
  );
}
