import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";

import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { GlossaryBuiltinPanel } from "../features/glossary/GlossaryBuiltinPanel";
import { GlossaryFormPanel } from "../features/glossary/GlossaryFormPanel";
import { GlossaryListPanel } from "../features/glossary/GlossaryListPanel";
import { useGlossaryWorkspace } from "../features/glossary/useGlossaryWorkspace";
import { MemoryCloudPanel } from "../features/memory/MemoryCloudPanel";
import { MemoryFieldPreferencesPanel } from "../features/memory/MemoryFieldPreferencesPanel";
import { MemoryLearnedHotwordsPanel } from "../features/memory/MemoryLearnedHotwordsPanel";
import { MemoryOverviewStats } from "../features/memory/MemoryOverviewStats";
import { MemoryRecentCorrectionsPanel } from "../features/memory/MemoryRecentCorrectionsPanel";
import { useMemoryWorkspace } from "../features/memory/useMemoryWorkspace";

type TermsMemoryTab = "glossary" | "memory" | "hotwords" | "recent";

function tabFromSearch(search: string): TermsMemoryTab {
  const tab = new URLSearchParams(search).get("tab");
  if (tab === "memory" || tab === "hotwords" || tab === "recent") return tab;
  return "glossary";
}

export function TermsMemoryPage() {
  const location = useLocation();
  const [activeTab, setActiveTab] = useState<TermsMemoryTab>(() => tabFromSearch(location.search));
  const glossary = useGlossaryWorkspace();
  const memory = useMemoryWorkspace();
  useEffect(() => {
    const nextTab = tabFromSearch(location.search);
    setActiveTab((current) => (current === nextTab ? current : nextTab));
  }, [location.search]);
  const handleDeleteTerm = (termId: string) => {
    const term = (glossary.glossary.data ?? []).find((item) => item.id === termId);
    const label = term?.correct_form ?? termId;
    if (window.confirm(`确认删除术语「${label}」？`)) {
      glossary.deleteTerm.mutate(termId);
    }
  };

  return (
    <section className="page-stack terms-memory-page">
      <PageHeader
        eyebrow="资产库"
        title="术语与记忆"
        description="统一维护术语表、行为记忆、自动学习热词和最近纠错反馈。"
      />

      <nav className="operator-tabs" role="tablist" aria-label="术语与记忆视图">
        {[
          ["glossary", "术语表"],
          ["memory", "记忆统计"],
          ["hotwords", "热词"],
          ["recent", "最近纠错"],
        ].map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={activeTab === key}
            className={activeTab === key ? "operator-tab active" : "operator-tab"}
            onClick={() => setActiveTab(key as TermsMemoryTab)}
          >
            {label}
          </button>
        ))}
      </nav>

      {activeTab === "glossary" ? (
        <>
          <PageSection eyebrow="维护" title="手工术语维护">
            <div className="panel-grid two-up">
              <GlossaryFormPanel
                editing={glossary.editing}
                form={glossary.form}
                isSaving={glossary.createTerm.isPending}
                autosaveState={glossary.saveState}
                autosaveError={glossary.saveError}
                onChange={glossary.setForm}
                onSubmit={glossary.submit}
                onReset={glossary.resetForm}
              />
              <GlossaryListPanel
                terms={glossary.glossary.data ?? []}
                scopeFilter={glossary.scopeFilter}
                onScopeFilterChange={glossary.setScopeFilter}
                isDeleting={glossary.deleteTerm.isPending}
                onEdit={glossary.startEdit}
                onDelete={handleDeleteTerm}
              />
            </div>
          </PageSection>
          <PageSection eyebrow="补充" title="内置词包导入">
            <GlossaryBuiltinPanel
              packs={glossary.builtinPacks.data ?? []}
              filter={glossary.builtinFilter}
              onFilterChange={glossary.setBuiltinFilter}
              importMode={glossary.builtinImportMode}
              onImportModeChange={glossary.setBuiltinImportMode}
              onImportTerm={(pack, correctForm) => {
                const term = pack.terms.find((item) => item.correct_form === correctForm);
                if (term) void glossary.importOneBuiltinTerm(term);
              }}
              onImportPack={(pack) => void glossary.importBuiltinPack(pack)}
              isImported={glossary.hasBuiltinTermImported}
              isImportingTerm={(correctForm) => glossary.importingTerms.includes(correctForm)}
              importingPackDomain={glossary.importingPackDomain}
            />
          </PageSection>
        </>
      ) : null}

      {activeTab === "memory" && memory.stats.data ? (
        <>
          <PageSection eyebrow="概览" title="记忆概览">
            <MemoryOverviewStats stats={memory.stats.data} />
          </PageSection>
          <PageSection eyebrow="分析" title="长期倾向">
            <div className="panel-grid two-up">
              <MemoryCloudPanel stats={memory.stats.data} />
              <MemoryFieldPreferencesPanel stats={memory.stats.data} />
            </div>
          </PageSection>
        </>
      ) : null}

      {activeTab === "hotwords" && memory.stats.data ? (
        <PageSection eyebrow="热词" title="自动学习热词">
          <MemoryLearnedHotwordsPanel
            hotwords={memory.learnedHotwords.data ?? memory.stats.data.learned_hotwords ?? []}
            isUpdating={memory.updateLearnedHotword.isPending}
            onStatusChange={(hotwordId, status) => memory.updateLearnedHotword.mutate({ hotwordId, body: { status } })}
          />
        </PageSection>
      ) : null}

      {activeTab === "recent" && memory.stats.data ? (
        <PageSection eyebrow="最近" title="最近纠错">
          <MemoryRecentCorrectionsPanel stats={memory.stats.data} />
        </PageSection>
      ) : null}
    </section>
  );
}
