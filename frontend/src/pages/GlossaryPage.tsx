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

  return (
    <section className="page-stack">
      <PageHeader
        eyebrow={t("glossary.page.eyebrow")}
        title={t("glossary.page.title")}
        description={t("glossary.page.description")}
        summary={[
          { label: "先维护", value: "术语表单", detail: "新增和修正都应先经过左侧表单" },
          { label: "再管理", value: "范围与词条列表", detail: "右侧列表更适合查重、筛选和继续编辑" },
          { label: "最后补全", value: "内置词包导入", detail: "内置包用来提速，不替代针对频道的精修" },
        ]}
      />

      <PageSection
        eyebrow="维护"
        title="手工术语维护"
        description="左侧负责新增和改写，右侧负责查找、筛选和继续编辑，避免导入操作干扰日常修正。"
      >
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
            onDelete={(termId) => workspace.deleteTerm.mutate(termId)}
          />
        </div>
      </PageSection>

      <PageSection
        eyebrow="补充"
        title="内置词包导入"
        description="内置词包放在后段，只在需要批量补齐行业词时再处理，避免抢占主操作区。"
      >
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
