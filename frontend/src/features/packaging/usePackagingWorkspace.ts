import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";

export function usePackagingWorkspace(assetTypes: ReadonlyArray<{ key: string }>) {
  const queryClient = useQueryClient();
  const packaging = useQuery({ queryKey: ["packaging"], queryFn: api.getPackaging });

  const saveConfig = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.patchPackagingConfig(body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["packaging"] });
    },
  });

  const deleteAsset = useMutation({
    mutationFn: (assetId: string) => api.deletePackagingAsset(assetId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["packaging"] });
    },
  });

  const uploaders = useMemo(
    () =>
      Object.fromEntries(
        assetTypes.map((item) => [
          item.key,
          (files: FileList | null) => {
            if (!files?.length) return;
            void (async () => {
              for (const file of Array.from(files)) {
                await api.uploadPackagingAsset(item.key, file);
              }
              await queryClient.invalidateQueries({ queryKey: ["packaging"] });
            })();
          },
        ]),
      ),
    [assetTypes, queryClient],
  ) as Record<string, (files: FileList | null) => void>;

  const togglePool = (key: "insert_asset_ids" | "music_asset_ids", assetId: string, checked: boolean) => {
    const config = packaging.data?.config;
    if (!config) return;
    const values = new Set(config[key] ?? []);
    if (checked) values.add(assetId);
    else values.delete(assetId);
    saveConfig.mutate({ [key]: Array.from(values) });
  };

  return {
    packaging,
    saveConfig,
    deleteAsset,
    uploaders,
    togglePool,
  };
}
