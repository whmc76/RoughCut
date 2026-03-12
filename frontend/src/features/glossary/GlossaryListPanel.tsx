import type { GlossaryTerm } from "../../types";
import { EmptyState } from "../../components/ui/EmptyState";
import { ListActions } from "../../components/ui/ListActions";
import { ListCard } from "../../components/ui/ListCard";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { formatDate } from "../../utils";

type GlossaryListPanelProps = {
  terms: GlossaryTerm[];
  isDeleting: boolean;
  onEdit: (term: GlossaryTerm) => void;
  onDelete: (termId: string) => void;
};

export function GlossaryListPanel({ terms, isDeleting, onEdit, onDelete }: GlossaryListPanelProps) {
  return (
    <section className="panel">
      <PanelHeader title="规则列表" description={`${terms.length} 条规则`} />
      <div className="list-stack">
        {terms.map((term) => (
          <ListCard key={term.id}>
            <div>
              <div className="row-title">{term.correct_form}</div>
              <div className="muted">{term.wrong_forms.join(" / ")}</div>
              <div className="muted compact-top">
                {term.category || "未分类"} · {formatDate(term.created_at)}
              </div>
            </div>
            <ListActions>
              <button className="button ghost" onClick={() => onEdit(term)}>
                编辑
              </button>
              <button className="button danger" onClick={() => onDelete(term.id)} disabled={isDeleting}>
                删除
              </button>
            </ListActions>
          </ListCard>
        ))}
        {!terms.length && <EmptyState message="暂无术语规则" />}
      </div>
    </section>
  );
}
