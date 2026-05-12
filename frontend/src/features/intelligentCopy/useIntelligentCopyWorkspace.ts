import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { api } from "../../api";
import type {
  AvatarMaterialLibrary,
  IntelligentCopyInspect,
  IntelligentCopyResult,
  PublicationPlatformPublishOptions,
} from "../../types";

const PUBLISHABLE_CREDENTIAL_STATUSES = new Set(["logged_in", "available", "verified"]);

export type PublishPlatformOptionDraft = {
  scheduled_publish_at: string;
  collection_id: string;
  collection_name: string;
  category: string;
  visibility_or_publish_mode: string;
};

export function publicationAttemptStatusLabel(status: string) {
  if (status === "queued") return "已排队";
  if (status === "submitted") return "已提交";
  if (status === "processing") return "发布中";
  if (status === "draft_created") return "草稿已创建";
  if (status === "scheduled_pending") return "已预约";
  if (status === "published") return "已发布";
  if (status === "needs_human") return "需人工处理";
  if (status === "failed") return "失败";
  return status || "待处理";
}

function hasActivePublicationCredential(profile: NonNullable<AvatarMaterialLibrary["profiles"]>[number]): boolean {
  const credentials = profile.creator_profile?.publishing?.platform_credentials ?? [];
  return credentials.some(
    (item) =>
      item.enabled !== false &&
      (item.adapter ?? "browser_agent") === "browser_agent" &&
      PUBLISHABLE_CREDENTIAL_STATUSES.has(item.status),
  );
}

function createEmptyPublicationPlatformOption(): PublishPlatformOptionDraft {
  return {
    scheduled_publish_at: "",
    collection_id: "",
    collection_name: "",
    category: "",
    visibility_or_publish_mode: "",
  };
}

function buildPublicationPlatformOptions(
  draft: Record<string, PublishPlatformOptionDraft>,
): Record<string, PublicationPlatformPublishOptions> {
  const entries = Object.entries(draft)
    .map(([platform, value]) => {
      const option: PublicationPlatformPublishOptions = {};
      const scheduledAt = value.scheduled_publish_at.trim();
      const collectionId = value.collection_id.trim();
      const collectionName = value.collection_name.trim();
      const category = value.category.trim();
      const visibility = value.visibility_or_publish_mode.trim();
      if (scheduledAt) option.scheduled_publish_at = scheduledAt;
      if (collectionId) option.collection_id = collectionId;
      if (collectionName) option.collection_name = collectionName;
      if (category) option.category = category;
      if (visibility) option.visibility_or_publish_mode = visibility;
      return [platform, option] as const;
    })
    .filter(([, option]) => Object.keys(option).length > 0);
  return Object.fromEntries(entries);
}

export function useIntelligentCopyWorkspace() {
  const queryClient = useQueryClient();
  const [folderPath, setFolderPath] = useState("");
  const [copyStyle, setCopyStyle] = useState("attention_grabbing");
  const [inspection, setInspection] = useState<IntelligentCopyInspect | null>(null);
  const [result, setResult] = useState<IntelligentCopyResult | null>(null);
  const [copyFeedback, setCopyFeedback] = useState("");
  const [selectedPublicationProfileId, setSelectedPublicationProfileId] = useState("");
  const [selectedPlatformIds, setSelectedPlatformIds] = useState<string[]>([]);
  const [publicationPlatformOptions, setPublicationPlatformOptions] = useState<Record<string, PublishPlatformOptionDraft>>({});

  const avatarMaterials = useQuery({
    queryKey: ["avatar-materials", "intelligent-publish"],
    queryFn: api.getAvatarMaterials,
  });
  const publicationProfiles = useMemo(
    () => (avatarMaterials.data?.profiles ?? []).filter((profile) => hasActivePublicationCredential(profile)),
    [avatarMaterials.data?.profiles],
  );

  useEffect(() => {
    if (!publicationProfiles.length) {
      setSelectedPublicationProfileId("");
      return;
    }
    setSelectedPublicationProfileId((current) =>
      publicationProfiles.some((profile) => profile.id === current) ? current : publicationProfiles[0]?.id ?? "",
    );
  }, [publicationProfiles]);

  const inspect = useMutation({
    mutationFn: (path: string) => api.inspectIntelligentCopyFolder(path),
    onSuccess: (payload) => {
      setInspection(payload);
      setResult(null);
      setSelectedPlatformIds([]);
    },
  });

  const generate = useMutation({
    mutationFn: (payload: { folderPath: string; copyStyle: string }) =>
      api.generateIntelligentCopy(payload.folderPath, payload.copyStyle),
    onSuccess: (payload) => {
      setInspection(payload.inspection);
      setResult(payload);
      setSelectedPlatformIds([]);
      void queryClient.invalidateQueries({ queryKey: ["intelligent-publication-plan"] });
    },
  });

  const openFolder = useMutation({
    mutationFn: (path: string) => api.openIntelligentCopyFolder(path),
  });

  const publicationQueryKey = [
    "intelligent-publication-plan",
    result?.json_path ?? "",
    inspection?.folder_path ?? folderPath,
    selectedPublicationProfileId,
  ] as const;
  const publicationPlan = useQuery({
    queryKey: publicationQueryKey,
    queryFn: () =>
      api.getIntelligentPublishPlan(inspection?.folder_path || folderPath, {
        creator_profile_id: selectedPublicationProfileId || null,
      }),
    enabled: Boolean((result || inspection) && (inspection?.folder_path || folderPath).trim()),
  });

  useEffect(() => {
    const targetPlatforms = (publicationPlan.data?.targets ?? []).map((target) => target.platform);
    if (!targetPlatforms.length) {
      setSelectedPlatformIds([]);
      setPublicationPlatformOptions({});
      return;
    }
    setSelectedPlatformIds((current) => {
      const filtered = current.filter((platform) => targetPlatforms.includes(platform));
      return filtered.length ? filtered : targetPlatforms;
    });
    setPublicationPlatformOptions((current) => {
      const next = Object.fromEntries(Object.entries(current).filter(([platform]) => targetPlatforms.includes(platform)));
      return Object.keys(next).length === Object.keys(current).length ? current : next;
    });
  }, [publicationPlan.data?.targets]);

  const updatePublicationPlatformOption = (platform: string, patch: Partial<PublishPlatformOptionDraft>) => {
    setPublicationPlatformOptions((current) => {
      const currentOption = current[platform] ?? createEmptyPublicationPlatformOption();
      return {
        ...current,
        [platform]: { ...currentOption, ...patch },
      };
    });
  };

  const togglePlatform = (platform: string) => {
    setSelectedPlatformIds((current) =>
      current.includes(platform) ? current.filter((item) => item !== platform) : [...current, platform],
    );
  };

  const publish = useMutation({
    mutationFn: () =>
      api.publishIntelligentFolder(inspection?.folder_path || folderPath, {
        creator_profile_id: selectedPublicationProfileId || null,
        platforms: selectedPlatformIds,
        platform_options: buildPublicationPlatformOptions(publicationPlatformOptions),
      }),
    onSuccess: async (payload) => {
      queryClient.setQueryData(publicationQueryKey, payload);
      await queryClient.invalidateQueries({ queryKey: ["intelligent-publication-plan"] });
    },
  });

  async function copyText(text: string, successLabel: string) {
    if (!text.trim()) {
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setCopyFeedback(successLabel);
    } catch {
      setCopyFeedback("复制失败，请检查系统剪贴板权限。");
    }
    window.setTimeout(() => setCopyFeedback(""), 1800);
  }

  return {
    folderPath,
    setFolderPath,
    copyStyle,
    setCopyStyle,
    inspection,
    result,
    inspect,
    generate,
    openFolder,
    avatarMaterials,
    publicationProfiles,
    selectedPublicationProfileId,
    setSelectedPublicationProfileId,
    selectedPlatformIds,
    togglePlatform,
    publicationPlatformOptions,
    updatePublicationPlatformOption,
    publicationPlan,
    publish,
    copyText,
    copyFeedback,
  };
}
