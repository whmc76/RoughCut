import { PageHeader } from "../components/ui/PageHeader";
import { MemoryCloudPanel } from "../features/memory/MemoryCloudPanel";
import { MemoryFieldPreferencesPanel } from "../features/memory/MemoryFieldPreferencesPanel";
import { MemoryOverviewStats } from "../features/memory/MemoryOverviewStats";
import { MemoryRecentCorrectionsPanel } from "../features/memory/MemoryRecentCorrectionsPanel";
import { useMemoryWorkspace } from "../features/memory/useMemoryWorkspace";

export function MemoryPage() {
  const workspace = useMemoryWorkspace();

  return (
    <section>
      <PageHeader
        eyebrow="Feedback Loop"
        title="行为记忆统计"
        description="页面层只负责加载和过滤，记忆概览、词云、字段偏好和最近纠正都拆成独立区块。"
        actions={
          <select className="input" value={workspace.channelProfile} onChange={(event) => workspace.setChannelProfile(event.target.value)}>
            <option value="">全部频道</option>
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
