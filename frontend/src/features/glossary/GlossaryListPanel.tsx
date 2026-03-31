import type { GlossaryTerm } from "../../types";
import { EmptyState } from "../../components/ui/EmptyState";
import { ListActions } from "../../components/ui/ListActions";
import { ListCard } from "../../components/ui/ListCard";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";
import { formatDate } from "../../utils";

type GlossaryListPanelProps = {
  terms: GlossaryTerm[];
  scopeFilter: string;
  onScopeFilterChange: (value: string) => void;
  isDeleting: boolean;
  onEdit: (term: GlossaryTerm) => void;
  onDelete: (termId: string) => void;
};

export function GlossaryListPanel({ terms, scopeFilter, onScopeFilterChange, isDeleting, onEdit, onDelete }: GlossaryListPanelProps) {
  const { t } = useI18n();

  return (
    <section className="panel">
      <PanelHeader
        title={t("glossary.list.title")}
        description={`${terms.length} ${t("glossary.list.count")}`}
        actions={
          <select className="input" value={scopeFilter} onChange={(event) => onScopeFilterChange(event.target.value)}>
            <option value="all">{t("glossary.list.scope.all")}</option>
            <option value="global">{t("glossary.list.scope.global")}</option>
            <option value="domain:gear">{t("glossary.list.scope.domainGear")}</option>
            <option value="domain:tech">{t("glossary.list.scope.domainTech")}</option>
            <option value="domain:ai">{t("glossary.list.scope.domainAi")}</option>
            <option value="domain:coding">{t("glossary.list.scope.domainCoding")}</option>
            <option value="workflow_template:edc_tactical">{t("glossary.list.scope.channelEdc")}</option>
            <option value="workflow_template:tutorial_standard">{t("glossary.list.scope.channelScreen")}</option>
          </select>
        }
      />
      <div className="list-stack">
        {terms.map((term) => (
          <ListCard key={term.id}>
            <div>
              <div className="row-title">{term.correct_form}</div>
              <div className="muted">{term.wrong_forms.join(" / ")}</div>
              <div className="muted compact-top">
                {term.scope_type}:{term.scope_value || "global"} · {term.category || t("glossary.list.uncategorized")} · {formatDate(term.created_at)}
              </div>
            </div>
            <ListActions>
              <button className="button ghost" onClick={() => onEdit(term)}>
                {t("glossary.list.edit")}
              </button>
              <button className="button danger" onClick={() => onDelete(term.id)} disabled={isDeleting}>
                {t("glossary.list.delete")}
              </button>
            </ListActions>
          </ListCard>
        ))}
        {!terms.length && <EmptyState message={t("glossary.list.empty")} />}
      </div>
    </section>
  );
}
