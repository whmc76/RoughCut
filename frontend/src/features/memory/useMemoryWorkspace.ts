import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import type { LearnedHotword } from "../../types";

export function useMemoryWorkspace() {
  const [subjectDomain, setSubjectDomain] = useState("");
  const queryClient = useQueryClient();
  const stats = useQuery({
    queryKey: ["memory-stats", subjectDomain],
    queryFn: () => api.getMemoryStats(subjectDomain || undefined),
  });
  const learnedHotwords = useQuery({
    queryKey: ["learned-hotwords", subjectDomain],
    queryFn: () => api.listLearnedHotwords({ subject_domain: subjectDomain || undefined, status: "all", limit: 80 }),
  });
  const updateLearnedHotword = useMutation({
    mutationFn: ({ hotwordId, body }: { hotwordId: string; body: Partial<Pick<LearnedHotword, "aliases" | "confidence" | "status">> }) =>
      api.updateLearnedHotword(hotwordId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["learned-hotwords", subjectDomain] });
      queryClient.invalidateQueries({ queryKey: ["memory-stats", subjectDomain] });
    },
  });

  return {
    subjectDomain,
    setSubjectDomain,
    stats,
    learnedHotwords,
    updateLearnedHotword,
  };
}
