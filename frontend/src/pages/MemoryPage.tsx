import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { MemoryCloudPanel } from "../features/memory/MemoryCloudPanel";
import { MemoryFieldPreferencesPanel } from "../features/memory/MemoryFieldPreferencesPanel";
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
        summary={[
          { label: "看什么", value: "纠错积累与字段偏好", detail: "这页用来校准系统长期记忆，而不是处理单个任务" },
          { label: "怎么筛", value: "按频道查看", detail: "频道切换后更容易看出某类内容的长期偏差" },
          { label: "怎么用", value: "先看统计，再调偏好", detail: "先确认问题集中在哪，再决定要不要改规则" },
        ]}
        actions={
          <select className="input" value={workspace.channelProfile} onChange={(event) => workspace.setChannelProfile(event.target.value)}>
            <option value="">{t("memory.page.allChannels")}</option>
            {workspace.stats.data?.channel_profiles.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        }
      />

      {workspace.stats.data && (
        <>
          <PageSection
            eyebrow="概览"
            title="先看整体记忆状态"
            description="这一段只回答系统积累了多少纠错，以及当前筛选范围下记忆是否足够稳定。"
          >
            <MemoryOverviewStats stats={workspace.stats.data} />
          </PageSection>

          <PageSection
            eyebrow="分析"
            title="再判断偏好和长期倾向"
            description="词云和字段偏好用于观察长期偏差，不建议和最近纠错混在一起看。"
          >
            <div className="panel-grid two-up">
              <MemoryCloudPanel stats={workspace.stats.data} />
              <MemoryFieldPreferencesPanel stats={workspace.stats.data} />
            </div>
          </PageSection>

          <PageSection
            eyebrow="最近"
            title="最后处理近期纠错"
            description="近期纠错保留在单独区域，方便确认最近是不是出现了新的偏差趋势。"
          >
            <MemoryRecentCorrectionsPanel stats={workspace.stats.data} />
          </PageSection>
        </>
      )}
    </section>
  );
}
