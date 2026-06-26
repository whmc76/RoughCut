import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { MemoryCloudPanel } from "../features/memory/MemoryCloudPanel";
import { MemoryFieldPreferencesPanel } from "../features/memory/MemoryFieldPreferencesPanel";
import { MemoryLearnedHotwordsPanel } from "../features/memory/MemoryLearnedHotwordsPanel";
import { MemoryOverviewStats } from "../features/memory/MemoryOverviewStats";
import { MemoryRecentCorrectionsPanel } from "../features/memory/MemoryRecentCorrectionsPanel";
import { useMemoryWorkspace } from "../features/memory/useMemoryWorkspace";
import { useI18n } from "../i18n";

export function MemoryPage() {
  const { t } = useI18n();
  const workspace = useMemoryWorkspace();

  return (
    <section className="page-stack">
      <PageHeader
        eyebrow={t("memory.page.eyebrow")}
        title={t("memory.page.title")}
        description={t("memory.page.description")}
        actions={
          <select className="input" value={workspace.subjectDomain} onChange={(event) => workspace.setSubjectDomain(event.target.value)}>
            <option value="">{t("memory.page.allChannels")}</option>
            {workspace.stats.data?.subject_domains.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        }
      />

      {workspace.stats.data && (
        <>
          <PageSection eyebrow="概览" title="记忆概览">
            <MemoryOverviewStats stats={workspace.stats.data} />
          </PageSection>

          <PageSection eyebrow="分析" title="长期倾向">
            <div className="panel-grid two-up">
              <MemoryCloudPanel stats={workspace.stats.data} />
              <MemoryFieldPreferencesPanel stats={workspace.stats.data} />
            </div>
          </PageSection>

          <PageSection eyebrow="热词" title="自动学习热词">
            <MemoryLearnedHotwordsPanel
              hotwords={workspace.learnedHotwords.data ?? workspace.stats.data.learned_hotwords ?? []}
              isUpdating={workspace.updateLearnedHotword.isPending}
              onStatusChange={(hotwordId, status) => workspace.updateLearnedHotword.mutate({ hotwordId, body: { status } })}
            />
          </PageSection>

          <PageSection eyebrow="最近" title="最近纠错">
            <MemoryRecentCorrectionsPanel stats={workspace.stats.data} />
          </PageSection>
        </>
      )}
    </section>
  );
}
