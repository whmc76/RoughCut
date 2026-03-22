import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../api";

export function useOverviewWorkspace() {
  const [usageTrendDays, setUsageTrendDays] = useState(7);
  const [usageTrendFocusType, setUsageTrendFocusType] = useState("all");
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs });
  const usageSummary = useQuery({ queryKey: ["jobs-usage-summary", 60], queryFn: () => api.getJobsUsageSummary(60) });
  const usageTrend = useQuery({
    queryKey: ["jobs-usage-trend", usageTrendDays, 120, usageTrendFocusType, ""],
    queryFn: () => api.getJobsUsageTrend(usageTrendDays, 120, usageTrendFocusType !== "all" ? usageTrendFocusType : undefined),
  });
  const watchRoots = useQuery({ queryKey: ["watch-roots"], queryFn: api.listWatchRoots });
  const glossary = useQuery({ queryKey: ["glossary"], queryFn: () => api.listGlossary() });
  const services = useQuery({ queryKey: ["control-status"], queryFn: api.getControlStatus, refetchInterval: 10_000 });

  const stats = {
    jobs: jobs.data?.length ?? 0,
    running: jobs.data?.filter((job) => job.status === "running" || job.status === "processing").length ?? 0,
    watchRoots: watchRoots.data?.length ?? 0,
    glossary: glossary.data?.length ?? 0,
  };

  return {
    jobs,
    usageSummary,
    usageTrend,
    usageTrendDays,
    setUsageTrendDays,
    usageTrendFocusType,
    setUsageTrendFocusType,
    watchRoots,
    glossary,
    services,
    stats,
  };
}
