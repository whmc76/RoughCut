import { useQuery } from "@tanstack/react-query";

import { api } from "../../api";
import type { Job } from "../../types";

export function useOverviewWorkspace() {
  const jobs = useQuery<Job[], Error>({ queryKey: ["jobs"], queryFn: () => api.listJobs() });
  const usageSummary = useQuery({ queryKey: ["jobs-usage-summary", 60], queryFn: () => api.getJobsUsageSummary(60) });
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
    watchRoots,
    glossary,
    services,
    stats,
  };
}
