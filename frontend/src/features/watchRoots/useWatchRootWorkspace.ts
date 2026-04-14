import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import { EMPTY_ROOT_FORM, type RootForm } from "./constants";
import type { WatchInventorySmartMergeGroup } from "../../types";

function serializeRootForm(form: RootForm): string {
  return JSON.stringify({
    path: form.path,
    config_profile_id: form.config_profile_id,
    workflow_template: form.workflow_template,
    output_dir: form.output_dir,
    enabled: form.enabled,
    scan_mode: form.scan_mode,
    ingest_mode: form.ingest_mode,
  });
}

export function useWatchRootWorkspace() {
  const queryClient = useQueryClient();
  const [selectedRootId, setSelectedRootId] = useState<string | null>(null);
  const [form, setForm] = useState<RootForm>(EMPTY_ROOT_FORM);
  const [selectedPending, setSelectedPending] = useState<string[]>([]);
  const [smartMergeGroups, setSmartMergeGroups] = useState<WatchInventorySmartMergeGroup[]>([]);
  const [updateState, setUpdateState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [updateError, setUpdateError] = useState<string | null>(null);
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
    if (!selectedRoot && roots.data?.length) {
      setSelectedRootId(roots.data[0].id);
    }
  }, [roots.data, selectedRoot]);

  useEffect(() => {
    if (selectedRoot) {
      const nextForm = {
        path: selectedRoot.path,
        config_profile_id: selectedRoot.config_profile_id || "",
        workflow_template: selectedRoot.workflow_template || "",
        output_dir: selectedRoot.output_dir || "",
        enabled: selectedRoot.enabled,
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
    setSelectedPending([]);
    setSmartMergeGroups([]);
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
    mutationFn: (nextForm: RootForm) => api.updateWatchRoot(selectedRootId!, nextForm),
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

  const merge = useMutation({
    mutationFn: () => api.mergeInventory(selectedRootId!, selectedPending),
    onSuccess: () => {
      setSelectedPending([]);
      setSmartMergeGroups([]);
      refreshRoots();
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
    onSuccess: () => {
      setSelectedPending([]);
      setSmartMergeGroups([]);
      refreshRoots();
    },
  });

  useEffect(() => {
    if (!selectedRootId || !selectedRoot) return;
    const signature = serializeRootForm(form);
    if (signature === lastPersistedRef.current) {
      return;
    }

    const requestVersion = updateVersionRef.current + 1;
    updateVersionRef.current = requestVersion;
    const timer = window.setTimeout(() => {
      setUpdateState("saving");
      setUpdateError(null);
      updateRoot.mutate(form, {
        onSuccess: async (updatedRoot) => {
          if (requestVersion !== updateVersionRef.current) return;
          lastPersistedRef.current = serializeRootForm({
            path: updatedRoot.path,
            config_profile_id: updatedRoot.config_profile_id || "",
            workflow_template: updatedRoot.workflow_template || "",
            output_dir: updatedRoot.output_dir || "",
            enabled: updatedRoot.enabled,
            scan_mode: updatedRoot.scan_mode,
            ingest_mode: updatedRoot.ingest_mode,
          });
          preserveSavedStateRef.current = true;
          queryClient.setQueryData(["watch-roots"], (current: typeof roots.data) =>
            (current ?? []).map((root) => (root.id === updatedRoot.id ? updatedRoot : root)),
          );
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
  }, [form, queryClient, selectedRoot, selectedRootId, updateRoot, roots.data]);

  return {
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
    scan,
    enqueue,
    merge,
    suggestMerge,
    mergeSuggested,
    smartMergeGroups,
    updateState,
    updateError,
  };
}
