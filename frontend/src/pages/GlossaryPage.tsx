import { PageHeader } from "../components/ui/PageHeader";
import { GlossaryFormPanel } from "../features/glossary/GlossaryFormPanel";
import { GlossaryListPanel } from "../features/glossary/GlossaryListPanel";
import { useGlossaryWorkspace } from "../features/glossary/useGlossaryWorkspace";

export function GlossaryPage() {
  const workspace = useGlossaryWorkspace();

  return (
    <section>
      <PageHeader eyebrow="Normalization" title="术语词表" description="页面层只负责状态协调，术语表单和规则列表已经拆成独立区块。" />

      <div className="panel-grid two-up">
        <GlossaryFormPanel
          editing={workspace.editing}
          form={workspace.form}
          isSaving={workspace.createTerm.isPending || workspace.updateTerm.isPending}
          onChange={workspace.setForm}
          onSubmit={workspace.submit}
          onReset={workspace.resetForm}
        />
        <GlossaryListPanel
          terms={workspace.glossary.data ?? []}
          isDeleting={workspace.deleteTerm.isPending}
          onEdit={workspace.startEdit}
          onDelete={(termId) => workspace.deleteTerm.mutate(termId)}
        />
      </div>
    </section>
  );
}
