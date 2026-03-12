import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";

type SectionKind = "subtitle" | "cover" | "title";

export function useStyleTemplatesWorkspace() {
  const queryClient = useQueryClient();
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
  const packaging = useQuery({ queryKey: ["packaging"], queryFn: api.getPackaging });

  const saveConfig = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.patchPackagingConfig(body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["packaging"] });
    },
  });

  const toggleGroup = (section: SectionKind, groupId: string) => {
    const key = `${section}:${groupId}`;
    setOpenGroups((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return {
    openGroups,
    packaging,
    saveConfig,
    toggleGroup,
  };
}
