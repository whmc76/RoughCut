import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../../api";

export function useMemoryWorkspace() {
  const [subjectDomain, setSubjectDomain] = useState("");
  const stats = useQuery({
    queryKey: ["memory-stats", subjectDomain],
    queryFn: () => api.getMemoryStats(subjectDomain || undefined),
  });

  return {
    subjectDomain,
    setSubjectDomain,
    stats,
  };
}
