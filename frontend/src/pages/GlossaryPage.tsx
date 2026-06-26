import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { GlossaryBuiltinPanel } from "../features/glossary/GlossaryBuiltinPanel";
import { GlossaryFormPanel } from "../features/glossary/GlossaryFormPanel";
import { GlossaryListPanel } from "../features/glossary/GlossaryListPanel";
import { useGlossaryWorkspace } from "../features/glossary/useGlossaryWorkspace";
import { useI18n } from "../i18n";

export function GlossaryPage() {
  const { t } = useI18n();
  const workspace = useGlossaryWorkspace();
  const handleDeleteTerm = (termId: string) => {
    const term = (workspace.glossary.data ?? []).find((item) => item.id === termId);
    const label = term?.correct_form ?? termId;
    if (window.confirm(`确认删除术语「${label}」？`)) {
      workspace.deleteTerm.mutate(termId);
    }
  };

  return (
    <section className="page-stack">
      <PageHeader
        eyebrow={t("glossary.page.eyebrow")}
        title={t("glossary.page.title")}
        description={t("glossary.page.description")}
      />

      <PageSection eyebrow="维护" title="手工术语维护">
        <div className="panel-grid two-up">
          <GlossaryFormPanel
            editing={workspace.editing}
            form={workspace.form}
            isSaving={workspace.createTerm.isPending}
            autosaveState={workspace.saveState}
            autosaveError={workspace.saveError}
            onChange={workspace.setForm}
            onSubmit={workspace.submit}
            onReset={workspace.resetForm}
          />
          <GlossaryListPanel
            terms={workspace.glossary.data ?? []}
            scopeFilter={workspace.scopeFilter}
            onScopeFilterChange={workspace.setScopeFilter}
            isDeleting={workspace.deleteTerm.isPending}
            onEdit={workspace.startEdit}
            onDelete={handleDeleteTerm}
          />
        </div>
      </PageSection>

      <PageSection eyebrow="补充" title="内置词包导入">
        <GlossaryBuiltinPanel
          packs={workspace.builtinPacks.data ?? []}
          filter={workspace.builtinFilter}
          onFilterChange={workspace.setBuiltinFilter}
          importMode={workspace.builtinImportMode}
          onImportModeChange={workspace.setBuiltinImportMode}
          onImportTerm={(pack, correctForm) => {
            const term = pack.terms.find((item) => item.correct_form === correctForm);
            if (term) void workspace.importOneBuiltinTerm(term);
          }}
          onImportPack={(pack) => void workspace.importBuiltinPack(pack)}
          isImported={workspace.hasBuiltinTermImported}
          isImportingTerm={(correctForm) => workspace.importingTerms.includes(correctForm)}
          importingPackDomain={workspace.importingPackDomain}
        />
      </PageSection>
    </section>
  );
}
