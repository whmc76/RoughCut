import { PageHeader } from "../components/ui/PageHeader";
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
    <section>
      <PageHeader
        eyebrow={t("memory.page.eyebrow")}
        title={t("memory.page.title")}
        description={t("memory.page.description")}
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
          <MemoryOverviewStats stats={workspace.stats.data} />
          <div className="panel-grid two-up">
            <MemoryCloudPanel stats={workspace.stats.data} />
            <MemoryFieldPreferencesPanel stats={workspace.stats.data} />
          </div>
          <MemoryRecentCorrectionsPanel stats={workspace.stats.data} />
        </>
      )}
    </section>
  );
}
