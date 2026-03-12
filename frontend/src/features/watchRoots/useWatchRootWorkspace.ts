import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import { EMPTY_ROOT_FORM, type RootForm } from "./constants";

export function useWatchRootWorkspace() {
  const queryClient = useQueryClient();
  const [selectedRootId, setSelectedRootId] = useState<string | null>(null);
  const [form, setForm] = useState<RootForm>(EMPTY_ROOT_FORM);
  const [selectedPending, setSelectedPending] = useState<string[]>([]);

  const roots = useQuery({ queryKey: ["watch-roots"], queryFn: api.listWatchRoots });
  const selectedRoot = roots.data?.find((root) => root.id === selectedRootId) ?? null;
  const inventory = useQuery({
    queryKey: ["watch-root-inventory", selectedRootId],
    queryFn: () => api.getInventoryStatus(selectedRootId!, true),
    enabled: Boolean(selectedRootId),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2000 : false),
  });

  useEffect(() => {
    if (!selectedRoot && roots.data?.length) {
      setSelectedRootId(roots.data[0].id);
    }
  }, [roots.data, selectedRoot]);

  useEffect(() => {
    if (selectedRoot) {
      setForm({
        path: selectedRoot.path,
        channel_profile: selectedRoot.channel_profile || "",
        enabled: selectedRoot.enabled,
        scan_mode: selectedRoot.scan_mode,
      });
    } else {
      setForm(EMPTY_ROOT_FORM);
    }
    setSelectedPending([]);
  }, [selectedRoot]);

  const refreshRoots = () => {
    void queryClient.invalidateQueries({ queryKey: ["watch-roots"] });
    if (selectedRootId) {
      void queryClient.invalidateQueries({ queryKey: ["watch-root-inventory", selectedRootId] });
    }
  };

  const createRoot = useMutation({
    mutationFn: () => api.createWatchRoot(form),
    onSuccess: (root) => {
      setSelectedRootId(root.id);
      refreshRoots();
    },
  });

  const updateRoot = useMutation({
    mutationFn: () => api.updateWatchRoot(selectedRootId!, form),
    onSuccess: refreshRoots,
  });

  const deleteRoot = useMutation({
    mutationFn: () => api.deleteWatchRoot(selectedRootId!),
    onSuccess: async () => {
      setSelectedRootId(null);
      await queryClient.invalidateQueries({ queryKey: ["watch-roots"] });
    },
  });

  const scan = useMutation({
    mutationFn: (force: boolean) => api.startInventoryScan(selectedRootId!, force),
    onSuccess: refreshRoots,
  });

  const enqueue = useMutation({
    mutationFn: (enqueueAll: boolean) => api.enqueueInventory(selectedRootId!, selectedPending, enqueueAll),
    onSuccess: () => {
      setSelectedPending([]);
      refreshRoots();
    },
  });

  return {
    selectedRootId,
    setSelectedRootId,
    form,
    setForm,
    selectedPending,
    setSelectedPending,
    roots,
    selectedRoot,
    inventory,
    refreshRoots,
    createRoot,
    updateRoot,
    deleteRoot,
    scan,
    enqueue,
  };
}
