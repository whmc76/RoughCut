import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import { EMPTY_ROOT_FORM, type RootForm } from "./constants";
import type { WatchInventorySmartMergeGroup, WatchInventoryStatus, WatchRoot } from "../../types";

type InventoryEnqueueRequest = {
  relativePaths?: string[];
  enqueueAll?: boolean;
};

function serializeRootForm(form: RootForm): string {
  return JSON.stringify({
    path: form.path,
    config_profile_id: form.config_profile_id,
    workflow_template: form.workflow_template,
    output_dir: form.output_dir,
    enabled: form.enabled,
    recursive: form.recursive,
    scan_mode: form.scan_mode,
    ingest_mode: form.ingest_mode,
  });
}

function markInventoryItemsDispatched(
  current: WatchInventoryStatus | undefined,
  relativePaths: string[],
  options: {
    enqueueAll?: boolean;
    dedupeReason: string;
  },
): WatchInventoryStatus | undefined {
  if (!current) return current;
  const pending = current.inventory.pending ?? [];
  const enqueueAll = options.enqueueAll ?? false;
  const selectedPathSet = new Set(relativePaths);
  const selectedItems = enqueueAll ? pending : pending.filter((item) => selectedPathSet.has(item.relative_path));
  if (!selectedItems.length) return current;

  const selectedAbsolutePaths = new Set(selectedItems.map((item) => item.path));
  const remainingPending = pending.filter((item) => !selectedAbsolutePaths.has(item.path));
  const dispatchedItems = selectedItems.map((item) => ({
    ...item,
    status: "deduped",
    dedupe_reason: options.dedupeReason,
    matched_job_id: item.matched_job_id ?? null,
  }));

  return {
    ...current,
    status: current.status || "done",
    updated_at: new Date().toISOString(),
    pending_count: remainingPending.length,
    deduped_count: (current.inventory.deduped ?? []).length + dispatchedItems.length,
    inventory: {
      pending: remainingPending,
      deduped: [...(current.inventory.deduped ?? []), ...dispatchedItems],
    },
  };
}

export function useWatchRootWorkspace() {
  const queryClient = useQueryClient();
  const [selectedRootId, setSelectedRootId] = useState<string | null>(null);
  const [isCreatingRoot, setIsCreatingRoot] = useState(false);
  const [form, setForm] = useState<RootForm>(EMPTY_ROOT_FORM);
  const [selectedPending, setSelectedPending] = useState<string[]>([]);
  const [smartMergeGroups, setSmartMergeGroups] = useState<WatchInventorySmartMergeGroup[]>([]);
  const [updateState, setUpdateState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [updateError, setUpdateError] = useState<string | null>(null);
  const [listActionRootId, setListActionRootId] = useState<string | null>(null);
  const lastPersistedRef = useRef<string>(serializeRootForm(EMPTY_ROOT_FORM));
  const updateVersionRef = useRef(0);
  const preserveSavedStateRef = useRef(false);

  const roots = useQuery({ queryKey: ["watch-roots"], queryFn: api.listWatchRoots });
  const options = useQuery({ queryKey: ["config-options"], queryFn: api.getConfigOptions });
  const configProfiles = useQuery({ queryKey: ["config-profiles"], queryFn: api.getConfigProfiles });
  const selectedRoot = roots.data?.find((root) => root.id === selectedRootId) ?? null;
  const inventory = useQuery({
    queryKey: ["watch-root-inventory", selectedRootId],
    queryFn: () => api.getInventoryStatus(selectedRootId!, true),
    enabled: Boolean(selectedRootId),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2000 : false),
  });

  useEffect(() => {
    if (!isCreatingRoot && !selectedRoot && roots.data?.length) {
      setSelectedRootId(roots.data[0].id);
    }
  }, [isCreatingRoot, roots.data, selectedRoot]);

  useEffect(() => {
    if (isCreatingRoot) {
      lastPersistedRef.current = serializeRootForm(EMPTY_ROOT_FORM);
      setForm(EMPTY_ROOT_FORM);
      setUpdateState("idle");
      setUpdateError(null);
    } else if (selectedRoot) {
      const nextForm = {
        path: selectedRoot.path,
        config_profile_id: selectedRoot.config_profile_id || "",
        workflow_template: selectedRoot.workflow_template || "",
        output_dir: selectedRoot.output_dir || "",
        enabled: selectedRoot.enabled,
        recursive: selectedRoot.recursive ?? true,
        scan_mode: selectedRoot.scan_mode,
        ingest_mode: selectedRoot.ingest_mode,
      };
      lastPersistedRef.current = serializeRootForm(nextForm);
      setForm(nextForm);
      setUpdateState(preserveSavedStateRef.current ? "saved" : "idle");
      preserveSavedStateRef.current = false;
      setUpdateError(null);
    } else {
      lastPersistedRef.current = serializeRootForm(EMPTY_ROOT_FORM);
      setForm(EMPTY_ROOT_FORM);
      setUpdateState("idle");
      setUpdateError(null);
    }
    if (!isCreatingRoot) {
      setSelectedPending([]);
      setSmartMergeGroups([]);
    }
  }, [isCreatingRoot, selectedRoot]);

  const refreshRoots = () => {
    void queryClient.invalidateQueries({ queryKey: ["watch-roots"] });
    if (selectedRootId) {
      void queryClient.invalidateQueries({ queryKey: ["watch-root-inventory", selectedRootId] });
    }
  };

  const createRoot = useMutation({
    mutationFn: () => api.createWatchRoot(form),
    onSuccess: (root) => {
      setIsCreatingRoot(false);
      setSelectedRootId(root.id);
      refreshRoots();
    },
  });

  const updateRoot = useMutation({
    mutationFn: ({ rootId, nextForm }: { rootId: string; nextForm: RootForm }) => api.updateWatchRoot(rootId, nextForm),
  });

  const deleteRoot = useMutation({
    mutationFn: () => api.deleteWatchRoot(selectedRootId!),
    onSuccess: async () => {
      setSelectedRootId(null);
      await queryClient.invalidateQueries({ queryKey: ["watch-roots"] });
    },
  });

  const toggleRootEnabled = useMutation({
    mutationFn: async (root: WatchRoot) => {
      setListActionRootId(root.id);
      return api.updateWatchRoot(root.id, {
        path: root.path,
        config_profile_id: root.config_profile_id ?? "",
        workflow_template: root.workflow_template ?? "",
        output_dir: root.output_dir ?? "",
        enabled: !root.enabled,
        recursive: root.recursive ?? true,
        scan_mode: root.scan_mode,
        ingest_mode: root.ingest_mode,
      });
    },
    onSuccess: (updatedRoot) => {
      queryClient.setQueryData(["watch-roots"], (current: typeof roots.data) =>
        (current ?? []).map((root) => (root.id === updatedRoot.id ? updatedRoot : root)),
      );
      if (selectedRootId === updatedRoot.id) {
        preserveSavedStateRef.current = true;
      }
    },
    onSettled: () => {
      setListActionRootId(null);
    },
  });

  const deleteRootById = useMutation({
    mutationFn: async (rootId: string) => {
      setListActionRootId(rootId);
      await api.deleteWatchRoot(rootId);
      return rootId;
    },
    onSuccess: async (deletedRootId) => {
      if (selectedRootId === deletedRootId) {
        setSelectedRootId(null);
      }
      await queryClient.invalidateQueries({ queryKey: ["watch-roots"] });
    },
    onSettled: () => {
      setListActionRootId(null);
    },
  });

  const scan = useMutation({
    mutationFn: (force: boolean) => api.startInventoryScan(selectedRootId!, force),
    onSuccess: async (status) => {
      setSelectedPending([]);
      setSmartMergeGroups([]);
      queryClient.setQueryData(["watch-root-inventory", selectedRootId], (current: typeof inventory.data) => ({
        ...(current ?? {
          inventory: { pending: [], deduped: [] },
        }),
        ...status,
      }));
      refreshRoots();
      await queryClient.invalidateQueries({ queryKey: ["watch-root-inventory", selectedRootId] });
    },
  });

  const enqueue = useMutation({
    mutationFn: ({ relativePaths, enqueueAll = false }: InventoryEnqueueRequest) =>
      api.enqueueInventory(selectedRootId!, relativePaths ?? selectedPending, enqueueAll),
    onMutate: async ({ relativePaths, enqueueAll = false }) => {
      const inventoryKey = ["watch-root-inventory", selectedRootId];
      await queryClient.cancelQueries({ queryKey: inventoryKey });
      const previousInventory = queryClient.getQueryData<WatchInventoryStatus>(inventoryKey);
      const selectedPaths = relativePaths ?? selectedPending;
      queryClient.setQueryData<WatchInventoryStatus | undefined>(inventoryKey, (current) =>
        markInventoryItemsDispatched(current, selectedPaths, {
          enqueueAll,
          dedupeReason: "job:pending",
        }),
      );
      return { previousInventory };
    },
    onSuccess: () => {
      setSelectedPending([]);
      refreshRoots();
    },
    onError: (_error, _variables, context) => {
      if (context?.previousInventory) {
        queryClient.setQueryData(["watch-root-inventory", selectedRootId], context.previousInventory);
      }
    },
  });

  const merge = useMutation({
    mutationFn: () => api.mergeInventory(selectedRootId!, selectedPending),
    onMutate: async () => {
      const inventoryKey = ["watch-root-inventory", selectedRootId];
      await queryClient.cancelQueries({ queryKey: inventoryKey });
      const previousInventory = queryClient.getQueryData<WatchInventoryStatus>(inventoryKey);
      queryClient.setQueryData<WatchInventoryStatus | undefined>(inventoryKey, (current) =>
        markInventoryItemsDispatched(current, selectedPending, {
          dedupeReason: "job:merged",
        }),
      );
      return { previousInventory };
    },
    onSuccess: () => {
      setSelectedPending([]);
      setSmartMergeGroups([]);
      refreshRoots();
    },
    onError: (_error, _variables, context) => {
      if (context?.previousInventory) {
        queryClient.setQueryData(["watch-root-inventory", selectedRootId], context.previousInventory);
      }
    },
  });

  const suggestMerge = useMutation({
    mutationFn: () => api.getSmartMergeGroups(selectedRootId!),
    onSuccess: (result) => {
      setSmartMergeGroups(result.groups);
    },
    onError: () => {
      setSmartMergeGroups([]);
    },
  });

  const mergeSuggested = useMutation({
    mutationFn: (relativePaths: string[]) => api.mergeInventory(selectedRootId!, relativePaths),
    onMutate: async (relativePaths) => {
      const inventoryKey = ["watch-root-inventory", selectedRootId];
      await queryClient.cancelQueries({ queryKey: inventoryKey });
      const previousInventory = queryClient.getQueryData<WatchInventoryStatus>(inventoryKey);
      queryClient.setQueryData<WatchInventoryStatus | undefined>(inventoryKey, (current) =>
        markInventoryItemsDispatched(current, relativePaths, {
          dedupeReason: "job:merged",
        }),
      );
      return { previousInventory };
    },
    onSuccess: () => {
      setSelectedPending([]);
      setSmartMergeGroups([]);
      refreshRoots();
    },
    onError: (_error, _variables, context) => {
      if (context?.previousInventory) {
        queryClient.setQueryData(["watch-root-inventory", selectedRootId], context.previousInventory);
      }
    },
  });

  useEffect(() => {
    if (isCreatingRoot || !selectedRootId || !selectedRoot) return;
    const signature = serializeRootForm(form);
    if (signature === lastPersistedRef.current) {
      return;
    }

    const requestVersion = updateVersionRef.current + 1;
    updateVersionRef.current = requestVersion;
    const timer = window.setTimeout(() => {
      setUpdateState("saving");
      setUpdateError(null);
      const formToSave = { ...form };
      updateRoot.mutate({ rootId: selectedRootId, nextForm: formToSave }, {
        onSuccess: async (updatedRoot) => {
          if (requestVersion !== updateVersionRef.current) return;
          const updatedForm = {
            path: updatedRoot.path,
            config_profile_id: updatedRoot.config_profile_id || "",
            workflow_template: updatedRoot.workflow_template || "",
            output_dir: updatedRoot.output_dir || "",
            enabled: updatedRoot.enabled,
            recursive: updatedRoot.recursive ?? true,
            scan_mode: updatedRoot.scan_mode,
            ingest_mode: updatedRoot.ingest_mode,
          };
          lastPersistedRef.current = serializeRootForm(updatedForm);
          preserveSavedStateRef.current = true;
          queryClient.setQueryData(["watch-roots"], (current: typeof roots.data) =>
            (current ?? []).map((root) => (root.id === updatedRoot.id ? updatedRoot : root)),
          );
          setForm(updatedForm);
          setUpdateState("saved");
          setUpdateError(null);
          await queryClient.invalidateQueries({ queryKey: ["watch-root-inventory", selectedRootId] });
        },
        onError: (error) => {
          if (requestVersion !== updateVersionRef.current) return;
          setUpdateState("error");
          setUpdateError(error instanceof Error ? error.message : String(error));
        },
      });
    }, 500);

    return () => window.clearTimeout(timer);
  }, [form, isCreatingRoot, queryClient, selectedRoot, selectedRootId]);

  const openCreateRoot = () => {
    setIsCreatingRoot(true);
  };

  const closeCreateRoot = () => {
    setIsCreatingRoot(false);
  };

  return {
    isCreatingRoot,
    openCreateRoot,
    closeCreateRoot,
    selectedRootId,
    setSelectedRootId,
    form,
    setForm,
    selectedPending,
    setSelectedPending,
    roots,
    options,
    configProfiles,
    selectedRoot,
    inventory,
    refreshRoots,
    createRoot,
    updateRoot,
    deleteRoot,
    deleteRootById,
    scan,
    enqueue,
    merge,
    suggestMerge,
    mergeSuggested,
    smartMergeGroups,
    toggleRootEnabled,
    listActionRootId,
    updateState,
    updateError,
  };
}
