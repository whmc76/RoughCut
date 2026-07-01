import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api";
import { PageHeader } from "../components/ui/PageHeader";
import type { AvatarMaterialFile, AvatarMaterialLibrary, CreatorAsset, CreatorCard, PackagingAsset, PackagingLibrary } from "../types";

const MAX_CREATOR_CARDS = 10;
const CREATOR_ASSET_CATEGORIES = [
  { key: "logo", label: "Logo / 水印", hint: "品牌标识、透明底 logo、水印、角标素材" },
  { key: "digital_human_closeup", label: "面部特写数字人", hint: "口播头像、半身近景、面部表情和口型样片" },
  { key: "digital_human_full_body", label: "全身数字人", hint: "全身出镜、站姿动作、舞台/讲解型数字人样片" },
  { key: "avatar", label: "头像", hint: "账号头像、创作者头像、人物形象图" },
  { key: "voice_reference", label: "参考语音", hint: "声音样本、口播语气、音色参考" },
  { key: "intro", label: "片头", hint: "开场动画、品牌片头、开场包装" },
  { key: "outro", label: "片尾", hint: "收尾动画、关注引导、结尾包装" },
  { key: "music_library", label: "音乐库", hint: "BGM、音效、转场音乐" },
  { key: "other", label: "其他素材", hint: "补充图文、授权文件、其它参考素材" },
] as const;
type CreatorAssetCategoryKey = (typeof CREATOR_ASSET_CATEGORIES)[number]["key"];
type CreatorAssetDisplayItem = {
  id: string;
  category: CreatorAssetCategoryKey;
  title: string;
  subtitle: string;
  path: string;
  previewUrl?: string;
  mediaKind: "image" | "video" | "audio" | "file";
  metadata?: Record<string, unknown> | null;
  source: "creator" | "packaging" | "avatar";
  creatorId?: string;
  assetId?: string;
  packagingAssetId?: string;
  avatarProfileId?: string;
  avatarFileId?: string;
};
const CREATOR_POSITIONING_OPTIONS = [
  { value: "垂直测评型", label: "垂直测评型", desc: "围绕固定品类做长期评测、体验和复盘" },
  { value: "购买决策顾问", label: "购买决策顾问", desc: "帮助用户做选购判断、避坑和替代方案比较" },
  { value: "硬核参数解析", label: "硬核参数解析", desc: "重视规格、结构、性能、数据和专业判断" },
  { value: "玩家收藏人设", label: "玩家收藏人设", desc: "以个人审美、收藏经验和稀缺货品形成记忆点" },
  { value: "场景解决方案", label: "场景解决方案", desc: "从通勤、户外、桌搭、车载等场景给方案" },
  { value: "新品情报站", label: "新品情报站", desc: "快速跟进新品、趋势、首发信息和市场变化" },
  { value: "教程避坑型", label: "教程避坑型", desc: "用步骤、清单、错误示范帮助用户少踩坑" },
  { value: "对比横评型", label: "对比横评型", desc: "同价位、同功能、同场景产品集中比较" },
  { value: "品牌官方号", label: "品牌官方号", desc: "适合品牌资产沉淀、产品发布和信任背书" },
  { value: "老板/主理人口播", label: "老板/主理人口播", desc: "强化真人判断、品牌态度和专业可信度" },
  { value: "轻知识科普", label: "轻知识科普", desc: "把复杂概念讲成短视频用户能快速理解的内容" },
  { value: "生活方式种草", label: "生活方式种草", desc: "用审美、氛围和使用体验带动兴趣转化" },
  { value: "娱乐反应型", label: "娱乐反应型", desc: "围绕热点、人物、事件做反应、吐槽和情绪共鸣" },
  { value: "剧情短剧型", label: "剧情短剧型", desc: "用人设、冲突、反转和连续剧情制造追更" },
  { value: "综艺整活型", label: "综艺整活型", desc: "靠游戏感、挑战、互动和强节奏制造观看爽感" },
  { value: "陪伴人格型", label: "陪伴人格型", desc: "强化松弛感、陪伴感、日常感和稳定人格记忆" },
  { value: "二创混剪型", label: "二创混剪型", desc: "围绕影视、游戏、动漫、体育等素材做再创作" },
];
const CREATOR_DOMAIN_OPTIONS = [
  "EDC",
  "数码",
  "潮玩",
  "户外",
  "工具装备",
  "汽车",
  "影像摄影",
  "桌面生活",
  "收藏文化",
  "消费电子",
  "家居生活",
  "生活方式",
  "娱乐搞笑",
  "剧情短剧",
  "影视综艺",
  "游戏动漫",
  "音乐舞蹈",
  "明星热点",
  "体育赛事",
  "情感关系",
  "知识科普",
  "品牌商业",
  "本地生活",
  "运动健康",
  "亲子家庭",
  "美学设计",
];
const CREATOR_AUDIENCE_OPTIONS = [
  { value: "入门选购用户", label: "入门选购用户", desc: "不懂参数，需要直接告诉买什么、为什么" },
  { value: "进阶玩家", label: "进阶玩家", desc: "有基础认知，关注体验差异、做工和长期使用" },
  { value: "硬核参数党", label: "硬核参数党", desc: "看重数据、结构、性能边界和专业术语准确性" },
  { value: "价格敏感用户", label: "价格敏感用户", desc: "关心预算、平替、优惠和性价比结论" },
  { value: "收藏爱好者", label: "收藏爱好者", desc: "关心稀缺性、设计语言、版本差异和情绪价值" },
  { value: "场景刚需用户", label: "场景刚需用户", desc: "从通勤、户外、维修、车载等真实任务出发" },
  { value: "泛兴趣用户", label: "泛兴趣用户", desc: "适合起号冷启动，需要更强钩子和低门槛解释" },
  { value: "娱乐消遣用户", label: "娱乐消遣用户", desc: "刷视频放松，偏好强节奏、反转、笑点和情绪释放" },
  { value: "追热点人群", label: "追热点人群", desc: "关注新梗、明星、影视综艺、事件讨论和即时态度" },
  { value: "剧情追更人群", label: "剧情追更人群", desc: "喜欢连续人设、关系张力、冲突升级和下一集悬念" },
  { value: "游戏动漫圈层", label: "游戏动漫圈层", desc: "有圈层语言和角色认知，关注梗、战力、剧情和二创" },
  { value: "情绪陪伴用户", label: "情绪陪伴用户", desc: "需要共鸣、陪伴、松弛表达和稳定人格关系" },
  { value: "品牌/渠道客户", label: "品牌/渠道客户", desc: "关注专业形象、交付稳定性和商业合作表达" },
  { value: "行业从业者", label: "行业从业者", desc: "能接受更专业的术语、供应链和市场判断" },
];
const CREATOR_PLATFORM_OPTIONS = [
  "bilibili",
  "xiaohongshu",
  "douyin",
  "kuaishou",
  "wechat-channels",
  "toutiao",
  "youtube",
  "x",
];
const CREATOR_PLATFORM_LABELS: Record<string, string> = {
  bilibili: "B 站",
  xiaohongshu: "小红书",
  douyin: "抖音",
  kuaishou: "快手",
  "wechat-channels": "视频号",
  toutiao: "头条",
  youtube: "YouTube",
  x: "X",
};
const CREATOR_PLATFORM_HINTS: Record<string, string> = {
  bilibili: "横版长内容",
  xiaohongshu: "种草图文/短视频",
  douyin: "竖版短视频",
  kuaishou: "社区短视频",
  "wechat-channels": "私域可信表达",
  toutiao: "资讯分发",
  youtube: "国际长短视频",
  x: "短文案传播",
};
type CreatorDraft = {
  name: string;
  primaryPositioning: string;
  secondaryPositionings: string[];
  audiences: string[];
  contentDomains: string[];
  defaultPlatforms: string[];
  naturalLanguageProfile: string;
};

const EMPTY_CREATOR_DRAFT: CreatorDraft = {
  name: "",
  primaryPositioning: "",
  secondaryPositionings: [],
  audiences: [],
  contentDomains: [],
  defaultPlatforms: [],
  naturalLanguageProfile: "",
};

function compactCreatorText(value: string | null | undefined, fallback: string) {
  return String(value || "").replace(/\s+/g, " ").trim() || fallback;
}

function creatorPlatformSummary(platforms: string[]) {
  if (!platforms.length) return "未设置平台";
  if (platforms.length <= 2) return platforms.join(" / ");
  return `${platforms.slice(0, 2).join(" / ")} +${platforms.length - 2}`;
}

function creatorDomainSummary(domains: string[]) {
  if (!domains.length) return "未定义领域";
  if (domains.length <= 2) return domains.join(" / ");
  return `${domains.slice(0, 2).join(" / ")} +${domains.length - 2}`;
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "未记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function formatList(values: string[]) {
  return values.length ? values.join(" / ") : "未设置";
}

function creatorPlatformLabel(platform: string) {
  return CREATOR_PLATFORM_LABELS[platform] ?? platform;
}

function formatPlatformList(values: string[]) {
  return values.length ? values.map(creatorPlatformLabel).join(" / ") : "未设置";
}

function assetCategoryLabel(assetType: string) {
  const normalizedType =
    assetType === "watermark"
      ? "logo"
      : ["voice_sample", "voice", "reference_voice", "reference_audio"].includes(assetType)
        ? "voice_reference"
        : assetType === "music"
          ? "music_library"
          : assetType;
  return CREATOR_ASSET_CATEGORIES.find((category) => category.key === normalizedType)?.label ?? assetType;
}

function normalizeCreatorAssetCategory(assetType: string): CreatorAssetCategoryKey {
  if (assetType === "digital_human_sample") return "digital_human_closeup";
  if (assetType === "watermark") return "logo";
  if (["voice_sample", "voice", "reference_voice", "reference_audio"].includes(assetType)) return "voice_reference";
  if (assetType === "music") return "music_library";
  return CREATOR_ASSET_CATEGORIES.some((category) => category.key === assetType)
    ? (assetType as CreatorAssetCategoryKey)
    : "other";
}

function packagingAssetCategory(assetType: string): CreatorAssetCategoryKey {
  if (assetType === "intro") return "intro";
  if (assetType === "outro") return "outro";
  if (assetType === "watermark") return "logo";
  if (assetType === "music") return "music_library";
  return "other";
}

function avatarFileCategory(file: AvatarMaterialFile): CreatorAssetCategoryKey {
  const mediaKind = mediaKindFromContentType(file.content_type, file.path || file.original_name);
  const role = `${file.role} ${file.role_label} ${file.pipeline_target} ${file.original_name}`.toLowerCase();
  if (mediaKind === "audio") return "voice_reference";
  if (mediaKind === "image") return "avatar";
  if (mediaKind !== "video") return "other";
  if (
    role.includes("full_body") ||
    role.includes("full-body") ||
    role.includes("whole_body") ||
    role.includes("全身") ||
    role.includes("站姿")
  ) {
    return "digital_human_full_body";
  }
  return "digital_human_closeup";
}

function mediaKindFromContentType(contentType: string | null | undefined, path = ""): CreatorAssetDisplayItem["mediaKind"] {
  const value = `${contentType || ""} ${path}`.toLowerCase();
  if (value.includes("image/") || /\.(png|jpe?g|webp|gif|bmp|svg)(\?|$)/.test(value)) return "image";
  if (value.includes("video/") || /\.(mp4|mov|mkv|avi|webm)(\?|$)/.test(value)) return "video";
  if (value.includes("audio/") || /\.(mp3|wav|m4a|aac|ogg|flac)(\?|$)/.test(value)) return "audio";
  return "file";
}

function selectedPackagingAssetIds(packaging: PackagingLibrary | undefined) {
  const config = packaging?.config;
  if (!config) return new Set<string>();
  return new Set([
    config.intro_asset_id,
    config.outro_asset_id,
    config.watermark_asset_id,
    ...(config.music_asset_ids || []),
    ...(config.insert_asset_ids || []),
  ].filter(Boolean) as string[]);
}

function packagingDisplayItems(packaging: PackagingLibrary | undefined): CreatorAssetDisplayItem[] {
  if (!packaging) return [];
  const selectedIds = selectedPackagingAssetIds(packaging);
  return Object.values(packaging.assets || {}).flat().map((asset: PackagingAsset) => ({
    id: `packaging:${asset.id}`,
    category: packagingAssetCategory(asset.asset_type),
    title: asset.original_name,
    subtitle: `${assetCategoryLabel(packagingAssetCategory(asset.asset_type))} · 旧包装素材库${
      selectedIds.has(asset.id) ? " · 当前绑定" : ""
    }`,
    path: asset.path,
    previewUrl: api.packagingAssetUrl(asset.id),
    mediaKind: mediaKindFromContentType(asset.content_type, asset.path),
    metadata: {
      content_type: asset.content_type,
      size_bytes: asset.size_bytes,
      asset_id: asset.id,
      selected: selectedIds.has(asset.id),
      watermark_preprocessed: asset.watermark_preprocessed,
    },
    source: "packaging",
    packagingAssetId: asset.id,
  }));
}

function legacyAvatarProfileIds(creator: CreatorCard | null | undefined) {
  return new Set(
    (creator?.preferences || [])
      .filter((preference) => preference.source === "legacy_avatar_profile")
      .map((preference) => String(preference.structured_payload?.legacy_profile_id || "").trim())
      .filter(Boolean),
  );
}

function avatarDisplayItems(library: AvatarMaterialLibrary | undefined, creator?: CreatorCard | null): CreatorAssetDisplayItem[] {
  if (!library) return [];
  const legacyIds = legacyAvatarProfileIds(creator);
  return (library.profiles || [])
    .filter((profile) => !legacyIds.size || legacyIds.has(profile.id))
    .flatMap((profile) =>
    (profile.files || []).map((file) => ({
      id: `avatar:${profile.id}:${file.id}`,
      category: avatarFileCategory(file),
      title: file.original_name,
      subtitle: `${file.role_label || file.role || "数字人素材"} · ${profile.display_name || profile.presenter_alias || "数字人档案"}`,
      path: file.path,
      previewUrl: api.avatarMaterialFileUrl(profile.id, file.id),
      mediaKind: mediaKindFromContentType(file.content_type, file.path),
      metadata: {
        profile_id: profile.id,
        profile_name: profile.display_name,
        presenter_alias: profile.presenter_alias,
        role: file.role,
        pipeline_target: file.pipeline_target,
        content_type: file.content_type,
        size_bytes: file.size_bytes,
      },
      source: "avatar",
      avatarProfileId: profile.id,
      avatarFileId: file.id,
    })),
  );
}

function creatorDisplayItems(assets: CreatorAsset[]): CreatorAssetDisplayItem[] {
  return assets.map((asset) => ({
    id: `creator:${asset.id}`,
    category: normalizeCreatorAssetCategory(asset.asset_type),
    title: asset.original_name,
    subtitle: `${assetCategoryLabel(asset.asset_type)} · 创作者专属素材 · ${formatDateTime(asset.created_at)}`,
    path: asset.stored_path,
    previewUrl: api.creatorAssetUrl(asset.creator_card_id, asset.id),
    mediaKind: mediaKindFromContentType(String(asset.metadata_json?.content_type || ""), asset.stored_path),
    metadata: asset.metadata_json,
    source: "creator",
    creatorId: asset.creator_card_id,
    assetId: asset.id,
  }));
}

function CreatorAssetPreview({ asset }: { asset: CreatorAssetDisplayItem }) {
  if (!asset.previewUrl || asset.mediaKind === "file") {
    return <div className="creator-asset-preview fallback">{assetCategoryLabel(asset.category)}</div>;
  }
  if (asset.mediaKind === "image") {
    return (
      <img
        className="creator-asset-preview"
        src={asset.previewUrl}
        alt={asset.title}
        loading="lazy"
        onLoad={(event) => {
          const image = event.currentTarget;
          if (image.naturalWidth && image.naturalHeight) {
            image.style.aspectRatio = `${image.naturalWidth} / ${image.naturalHeight}`;
          }
        }}
      />
    );
  }
  if (asset.mediaKind === "video") {
    return (
      <video
        className="creator-asset-preview"
        src={asset.previewUrl}
        controls
        preload="metadata"
        onLoadedMetadata={(event) => {
          const video = event.currentTarget;
          if (video.videoWidth && video.videoHeight) {
            video.style.aspectRatio = `${video.videoWidth} / ${video.videoHeight}`;
          }
        }}
      />
    );
  }
  return <audio className="creator-asset-audio" src={asset.previewUrl} controls preload="metadata" />;
}

function assetsByCategory(assets: CreatorAssetDisplayItem[]) {
  return CREATOR_ASSET_CATEGORIES.map((category, index) => ({
    ...category,
    index,
    assets: assets.filter((asset) => asset.category === category.key),
  })).sort((left, right) => {
    const leftHasAssets = left.assets.length > 0;
    const rightHasAssets = right.assets.length > 0;
    if (leftHasAssets !== rightHasAssets) return leftHasAssets ? -1 : 1;
    return left.index - right.index;
  });
}

function toggleValue(values: string[], value: string) {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

function composePositioning(primary: string, secondary: string[]) {
  if (!primary) return "";
  return secondary.length ? `主定位：${primary}；副定位：${secondary.join(" / ")}` : `主定位：${primary}`;
}

function composeAudience(audiences: string[]) {
  return audiences.join(" / ");
}

function parsePositioning(value: string | null | undefined) {
  const text = String(value || "").trim();
  const match = text.match(/^主定位：([^；]+)(?:；副定位：(.+))?$/);
  if (!match) return { primary: "", secondary: [] as string[], unparsed: text };
  return {
    primary: match[1].trim(),
    secondary: match[2]?.split("/").map((item) => item.trim()).filter(Boolean).slice(0, 2) ?? [],
    unparsed: "",
  };
}

function draftFromCreator(creator: CreatorCard): CreatorDraft {
  const parsedPositioning = parsePositioning(creator.positioning);
  const audienceValues = CREATOR_AUDIENCE_OPTIONS.map((option) => option.value);
  const parsedAudiences = String(creator.audience || "")
    .split("/")
    .map((item) => item.trim())
    .filter((item) => audienceValues.includes(item))
    .slice(0, 3);
  const audienceUnparsed = creator.audience && !parsedAudiences.length ? creator.audience : "";
  const moreDescription = [
    creator.natural_language_profile || "",
    parsedPositioning.unparsed ? `原定位：${parsedPositioning.unparsed}` : "",
    audienceUnparsed ? `原受众：${audienceUnparsed}` : "",
  ].filter(Boolean).join("\n");
  return {
    name: creator.name,
    primaryPositioning: parsedPositioning.primary,
    secondaryPositionings: parsedPositioning.secondary,
    audiences: parsedAudiences,
    contentDomains: creator.content_domains,
    defaultPlatforms: creator.default_platforms,
    naturalLanguageProfile: moreDescription,
  };
}

function CreatorField({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="creator-field">
      <span>{label}</span>
      <strong>{value || "未设置"}</strong>
    </div>
  );
}

export function CreatorCardsPage() {
  const queryClient = useQueryClient();
  const creators = useQuery({ queryKey: ["creator-cards"], queryFn: api.listCreatorCards });
  const packaging = useQuery({ queryKey: ["packaging"], queryFn: api.getPackaging });
  const avatarMaterials = useQuery({ queryKey: ["avatar-materials"], queryFn: api.getAvatarMaterials });
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [editingCreatorId, setEditingCreatorId] = useState("");
  const [selectedCreatorId, setSelectedCreatorId] = useState("");
  const [selectedAssetId, setSelectedAssetId] = useState("");
  const [draft, setDraft] = useState<CreatorDraft>(EMPTY_CREATOR_DRAFT);
  const [refinePrompt, setRefinePrompt] = useState("");

  const creatorItems = creators.data?.items ?? [];
  const selectedCreator = useMemo(
    () => creatorItems.find((item) => item.id === selectedCreatorId) ?? creatorItems[0] ?? null,
    [creatorItems, selectedCreatorId],
  );
  const reachedCreatorLimit = creatorItems.length >= MAX_CREATOR_CARDS;
  const selectedCreatorQueryKey = selectedCreator?.id ?? "";
  const taskStrategies = useQuery({
    queryKey: ["creator-task-strategies", selectedCreatorQueryKey],
    queryFn: () => api.listTaskStrategies(selectedCreatorQueryKey),
    enabled: Boolean(selectedCreatorQueryKey),
  });
  const visualPlans = useQuery({
    queryKey: ["creator-visual-plans", selectedCreatorQueryKey],
    queryFn: () => api.listVisualPlans(selectedCreatorQueryKey),
    enabled: Boolean(selectedCreatorQueryKey),
  });
  const publicationProfile = useQuery({
    queryKey: ["creator-publication-profile", selectedCreatorQueryKey],
    queryFn: () => api.getPublicationProfile(selectedCreatorQueryKey),
    enabled: Boolean(selectedCreatorQueryKey),
  });
  const activeTaskStrategy = taskStrategies.data?.items.find((item) => item.is_active) ?? null;
  const activeVisualPlan = visualPlans.data?.items.find((item) => item.is_active) ?? null;
  const displayedAssets = selectedCreator
    ? [
        ...creatorDisplayItems(selectedCreator.assets),
        ...packagingDisplayItems(packaging.data),
        ...avatarDisplayItems(avatarMaterials.data, selectedCreator),
      ]
    : [];
  const groupedAssets = assetsByCategory(displayedAssets);
  const selectedAsset = displayedAssets.find((asset) => asset.id === selectedAssetId) ?? displayedAssets[0] ?? null;
  const editingCreator = editingCreatorId ? creatorItems.find((creator) => creator.id === editingCreatorId) ?? null : null;
  const creatorModalMode = editingCreator ? "edit" : "create";
  const modalDomainOptions = Array.from(new Set([...CREATOR_DOMAIN_OPTIONS, ...draft.contentDomains]));
  const modalPlatformOptions = Array.from(new Set([...CREATOR_PLATFORM_OPTIONS, ...draft.defaultPlatforms]));
  const visiblePlatformOptions = Array.from(new Set([...CREATOR_PLATFORM_OPTIONS, ...(selectedCreator?.default_platforms ?? [])]));

  useEffect(() => {
    if (!creatorItems.length) {
      if (selectedCreatorId) setSelectedCreatorId("");
      return;
    }
    if (!selectedCreatorId || !creatorItems.some((item) => item.id === selectedCreatorId)) {
      setSelectedCreatorId(creatorItems[0].id);
    }
  }, [creatorItems, selectedCreatorId]);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["creator-cards"] });
  };

  const closeCreatorModal = () => {
    setCreateModalOpen(false);
    setEditingCreatorId("");
    setDraft(EMPTY_CREATOR_DRAFT);
  };

  const openCreateCreatorModal = () => {
    setEditingCreatorId("");
    setDraft(EMPTY_CREATOR_DRAFT);
    setCreateModalOpen(true);
  };

  const openEditCreatorModal = (creator: CreatorCard) => {
    setEditingCreatorId(creator.id);
    setDraft(draftFromCreator(creator));
    setCreateModalOpen(true);
  };

  const createCreator = useMutation({
    mutationFn: () =>
      api.createCreatorCard({
        name: draft.name,
        positioning: composePositioning(draft.primaryPositioning, draft.secondaryPositionings) || null,
        audience: composeAudience(draft.audiences) || null,
        content_domains: draft.contentDomains,
        default_platforms: draft.defaultPlatforms,
        natural_language_profile: draft.naturalLanguageProfile || null,
      }),
    onSuccess: async (creator) => {
      setSelectedCreatorId(creator.id);
      closeCreatorModal();
      await refresh();
    },
  });

  const updateCreator = useMutation({
    mutationFn: () =>
      api.patchCreatorCard(editingCreatorId, {
        name: draft.name,
        positioning: composePositioning(draft.primaryPositioning, draft.secondaryPositionings) || null,
        audience: composeAudience(draft.audiences) || null,
        content_domains: draft.contentDomains,
        default_platforms: draft.defaultPlatforms,
        natural_language_profile: draft.naturalLanguageProfile || null,
      }),
    onSuccess: async (creator) => {
      setSelectedCreatorId(creator.id);
      closeCreatorModal();
      await refresh();
    },
  });

  const refineCreator = useMutation({
    mutationFn: () => {
      const targetCreatorId = selectedCreator?.id || selectedCreatorId;
      if (!targetCreatorId) throw new Error("请选择创作者");
      return api.refineCreatorCard(targetCreatorId, refinePrompt);
    },
    onSuccess: async () => {
      setRefinePrompt("");
      await refresh();
    },
  });

  const updateCreatorPlatforms = useMutation({
    mutationFn: ({ creator, platforms }: { creator: CreatorCard; platforms: string[] }) =>
      api.patchCreatorCard(creator.id, { default_platforms: platforms }),
    onSuccess: async (creator) => {
      setSelectedCreatorId(creator.id);
      await refresh();
    },
  });

  const uploadAsset = useMutation({
    mutationFn: ({ assetType, file }: { assetType: string; file: File }) => {
      const targetCreatorId = selectedCreator?.id || selectedCreatorId;
      if (!targetCreatorId) throw new Error("请选择创作者");
      return api.uploadCreatorAsset(targetCreatorId, file, assetType);
    },
    onSuccess: async () => {
      await refresh();
    },
  });

  const toggleCreatorPlatform = (platform: string) => {
    if (!selectedCreator || updateCreatorPlatforms.isPending) return;
    updateCreatorPlatforms.mutate({
      creator: selectedCreator,
      platforms: toggleValue(selectedCreator.default_platforms, platform),
    });
  };

  const uploadCategoryFile = (assetType: string, file: File | null | undefined) => {
    if (!file || uploadAsset.isPending) return;
    uploadAsset.mutate({ assetType, file });
  };

  const deleteAsset = useMutation<unknown, Error, CreatorAssetDisplayItem>({
    mutationFn: (asset: CreatorAssetDisplayItem) => {
      if (asset.source === "creator" && asset.creatorId && asset.assetId) {
        return api.deleteCreatorAsset(asset.creatorId, asset.assetId);
      }
      if (asset.source === "packaging" && asset.packagingAssetId) {
        return api.deletePackagingAsset(asset.packagingAssetId);
      }
      if (asset.source === "avatar" && asset.avatarProfileId && asset.avatarFileId) {
        return api.deleteAvatarMaterialFile(asset.avatarProfileId, asset.avatarFileId);
      }
      throw new Error("无法删除素材");
    },
    onSuccess: async () => {
      await Promise.all([
        refresh(),
        queryClient.invalidateQueries({ queryKey: ["packaging"] }),
        queryClient.invalidateQueries({ queryKey: ["avatar-materials"] }),
      ]);
    },
  });

  return (
    <section className="page-stack creator-cards-workspace">
      <PageHeader
        eyebrow="资产库"
        title="创作者卡片"
        description="管理创作者身份、平台绑定、素材、偏好和默认策略关系。"
      />

      <div className="creator-card-shell">
        <aside className="creator-card-rail" aria-label="创作者列表">
          <div className="creator-card-rail-head">
            <div>
              <strong>创作者</strong>
              <span>{creatorItems.length}/{MAX_CREATOR_CARDS}</span>
            </div>
            <button
              type="button"
              className="button primary creator-card-new"
              disabled={reachedCreatorLimit}
              onClick={openCreateCreatorModal}
            >
              新建
            </button>
          </div>
          <div className="creator-card-rail-scroll">
            {creatorItems.map((creator) => {
              const active = selectedCreator?.id === creator.id;
              const summary = compactCreatorText(creator.positioning || creator.natural_language_profile, "暂无定位描述");
              const platformSummary = creatorPlatformSummary(creator.default_platforms);
              const domainSummary = creatorDomainSummary(creator.content_domains);
              const displayAssetCount =
                creator.assets.length + packagingDisplayItems(packaging.data).length + avatarDisplayItems(avatarMaterials.data, creator).length;
              return (
                <button
                  key={creator.id}
                  type="button"
                  className={`creator-card-chip${active ? " selected" : ""}`}
                  onClick={() => setSelectedCreatorId(creator.id)}
                  title={summary}
                >
                  <span className="creator-card-chip-top">
                    <strong title={creator.name}>{creator.name}</strong>
                    <span className="creator-card-state">
                      <span aria-hidden="true" />
                      {creator.status}
                    </span>
                  </span>
                  <span className="creator-card-chip-summary">{summary}</span>
                  <span className="creator-card-chip-meta">
                    <span title={platformSummary}>{platformSummary}</span>
                    <span title={domainSummary}>{domainSummary}</span>
                    <span>{displayAssetCount} 素材</span>
                  </span>
                </button>
              );
            })}
            {!creatorItems.length ? <div className="creator-card-chip creator-card-chip-empty">还没有创作者</div> : null}
          </div>
        </aside>

        {selectedCreator ? (
          <>
            <main className="creator-card-detail">
              <form
                className="creator-command-bar"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (refinePrompt.trim() && !refineCreator.isPending) refineCreator.mutate();
                }}
              >
                <span>快速修改档案</span>
                <input
                  className="input"
                  value={refinePrompt}
                  onChange={(event) => setRefinePrompt(event.target.value)}
                  placeholder="例如：公开名称改为 FAS 机神圣殿 x 潮玩 EDC，定位改为 EDC 测评创作者"
                />
                <button
                  type="submit"
                  className="button primary"
                  disabled={!refinePrompt.trim() || refineCreator.isPending}
                >
                  {refineCreator.isPending ? "发送中" : "发送"}
                </button>
              </form>

              <section className="creator-identity-panel">
                <div className="creator-detail-header">
                  <div>
                    <strong>{selectedCreator.name}</strong>
                    <div className="muted top-gap">
                      {selectedCreator.positioning || selectedCreator.natural_language_profile || "暂无定位描述"}
                    </div>
                  </div>
                  <div className="toolbar">
                    <span className="status-pill">{selectedCreator.status}</span>
                    <button type="button" className="button ghost" onClick={() => openEditCreatorModal(selectedCreator)}>
                      编辑选项
                    </button>
                  </div>
                </div>
                <div className="creator-positioning-grid">
                  <CreatorField label="内容领域" value={formatList(selectedCreator.content_domains)} />
                  <CreatorField label="受众定位" value={selectedCreator.audience || "未设置"} />
                  <CreatorField label="创作者定位" value={selectedCreator.positioning || "未设置"} />
                  <CreatorField label="档案补充" value={selectedCreator.natural_language_profile || "未设置"} />
                </div>
              </section>

              <section className="creator-platform-panel">
                <div className="creator-detail-block-head">
                  <div>
                    <div className="creator-detail-block-label">平台默认值</div>
                    <span className="muted">勾选默认发布平台，生成与排产流程会优先使用。</span>
                  </div>
                  <span className="status-pill pending">已选 {selectedCreator.default_platforms.length}/{visiblePlatformOptions.length}</span>
                </div>
                <div className="creator-platform-grid">
                  {visiblePlatformOptions.map((platform) => {
                    const selected = selectedCreator.default_platforms.includes(platform);
                    return (
                      <button
                        key={platform}
                        type="button"
                        className={`creator-platform-tile${selected ? " selected" : ""}`}
                        disabled={updateCreatorPlatforms.isPending}
                        onClick={() => toggleCreatorPlatform(platform)}
                      >
                        <span>
                          <strong>{creatorPlatformLabel(platform)}</strong>
                          <em>{CREATOR_PLATFORM_HINTS[platform] ?? platform}</em>
                        </span>
                        <b>{selected ? "已选" : "可选"}</b>
                      </button>
                    );
                  })}
                </div>
              </section>

              <section className="creator-detail-block creator-assets-block">
                <div className="creator-detail-block-head">
                  <div>
                    <div className="creator-detail-block-label">素材库</div>
                    <span className="muted">{displayedAssets.length} 个素材，含旧包装库和数字人库。</span>
                  </div>
                  <span className="status-pill">{groupedAssets.filter((category) => category.assets.length).length} 类有素材</span>
                </div>
                <div className="creator-assets-layout">
                  <div className="creator-asset-category-grid">
                    {groupedAssets.map((category) => {
                      const primaryAsset = category.assets[0] ?? null;
                      const isMusicLibrary = category.key === "music_library";
                      return (
                        <section key={category.key} className={`creator-asset-category${isMusicLibrary ? " music-library" : ""}`}>
                          <div className="creator-asset-category-head">
                            <div>
                              <strong>{category.label}</strong>
                              <span>{category.hint}</span>
                            </div>
                            <span className="status-pill pending">
                              {isMusicLibrary ? category.assets.length : primaryAsset ? "已配置" : "0"}
                            </span>
                          </div>
                          {isMusicLibrary ? (
                            <div className="creator-asset-list creator-asset-music-list">
                              {category.assets.length ? category.assets.map((asset) => (
                                <article
                                  key={asset.id}
                                  className={`creator-asset-row${selectedAsset?.id === asset.id ? " selected" : ""}`}
                                  title={asset.path}
                                >
                                  <button
                                    type="button"
                                    className="creator-asset-select"
                                    onClick={() => setSelectedAssetId(asset.id)}
                                  >
                                    <span className={`creator-asset-kind ${asset.mediaKind}`}>{asset.mediaKind}</span>
                                    <span className="creator-asset-row-copy">
                                      <strong>{asset.title}</strong>
                                      <span>{asset.subtitle}</span>
                                    </span>
                                  </button>
                                  <button
                                    type="button"
                                    className="creator-asset-delete"
                                    disabled={deleteAsset.isPending}
                                    onClick={() => deleteAsset.mutate(asset)}
                                  >
                                    删除
                                  </button>
                                </article>
                              )) : <div className="muted compact-text">未上传</div>}
                            </div>
                          ) : (
                            <button
                              type="button"
                              className={`creator-asset-slot${primaryAsset && selectedAsset?.id === primaryAsset.id ? " selected" : ""}`}
                              disabled={!primaryAsset}
                              title={primaryAsset?.path || category.hint}
                              onClick={() => {
                                if (primaryAsset) setSelectedAssetId(primaryAsset.id);
                              }}
                            >
                              <span className={`creator-asset-kind ${primaryAsset?.mediaKind || "file"}`}>
                                {primaryAsset?.mediaKind || "empty"}
                              </span>
                              <span className="creator-asset-row-copy">
                                <strong>{primaryAsset?.title || "未上传"}</strong>
                                <span>{primaryAsset ? primaryAsset.subtitle : category.hint}</span>
                              </span>
                            </button>
                          )}
                          <div className="creator-asset-category-actions">
                            <label
                              className={`creator-upload-zone${uploadAsset.isPending ? " uploading" : ""}`}
                              onDragOver={(event) => {
                                event.preventDefault();
                                event.dataTransfer.dropEffect = "copy";
                              }}
                              onDrop={(event) => {
                                event.preventDefault();
                                uploadCategoryFile(category.key, event.dataTransfer.files?.[0]);
                              }}
                            >
                              <input
                                type="file"
                                disabled={uploadAsset.isPending}
                                onChange={(event) => {
                                  uploadCategoryFile(category.key, event.target.files?.[0]);
                                  event.currentTarget.value = "";
                                }}
                              />
                              <strong>{uploadAsset.isPending ? "上传中" : primaryAsset && !isMusicLibrary ? "替换" : "上传"}</strong>
                              <span>{isMusicLibrary ? "可上传多首 BGM" : `${category.label} 素材`}</span>
                            </label>
                            {primaryAsset && !isMusicLibrary ? (
                              <button
                                type="button"
                                className="creator-asset-delete"
                                disabled={deleteAsset.isPending}
                                onClick={() => deleteAsset.mutate(primaryAsset)}
                              >
                                删除
                              </button>
                            ) : null}
                          </div>
                        </section>
                      );
                    })}
                  </div>
                  <aside className="creator-live-preview" aria-label="素材实时预览">
                    <div className="creator-live-preview-head">
                      <div>
                        <strong>实时预览</strong>
                        <span>{selectedAsset ? assetCategoryLabel(selectedAsset.category) : "选择素材后预览"}</span>
                      </div>
                      {selectedAsset ? <span className="status-pill pending">{selectedAsset.mediaKind}</span> : null}
                    </div>
                    {selectedAsset ? (
                      <>
                        <div className="creator-live-preview-stage">
                          <CreatorAssetPreview asset={selectedAsset} />
                        </div>
                        <div className="creator-live-preview-meta">
                          <strong title={selectedAsset.title}>{selectedAsset.title}</strong>
                          <span title={selectedAsset.subtitle}>{selectedAsset.subtitle}</span>
                          <code title={selectedAsset.path}>{selectedAsset.path}</code>
                        </div>
                        <button
                          type="button"
                          className="creator-asset-delete"
                          disabled={deleteAsset.isPending}
                          onClick={() => deleteAsset.mutate(selectedAsset)}
                        >
                          删除当前素材
                        </button>
                      </>
                    ) : (
                      <div className="creator-live-preview-empty">还没有可预览素材</div>
                    )}
                  </aside>
                </div>
              </section>
            </main>

            <aside className="creator-inspector-panel">
              <section className="creator-detail-block">
                <div className="creator-detail-block-head">
                  <div className="creator-detail-block-label">默认关系</div>
                  <span className="muted">当前卡片关联</span>
                </div>
                <div className="creator-linked-grid">
                  <CreatorField
                    label="任务策略"
                    value={`${taskStrategies.data?.items.length ?? 0} 套${activeTaskStrategy ? `，启用：${activeTaskStrategy.name}` : ""}`}
                  />
                  <CreatorField
                    label="视觉方案"
                    value={`${visualPlans.data?.items.length ?? 0} 套${activeVisualPlan ? `，启用：${activeVisualPlan.name}` : ""}`}
                  />
                  <CreatorField label="发布配置" value={publicationProfile.data?.status || "未生成"} />
                  <CreatorField label="平台凭证绑定" value={`${publicationProfile.data?.bindings.length ?? 0} 个`} />
                </div>
              </section>
              <section className="creator-detail-block">
                <div className="creator-detail-block-head">
                  <div className="creator-detail-block-label">元信息</div>
                  <span className="muted">辅助信息</span>
                </div>
                <div className="creator-linked-grid">
                  <CreatorField label="卡片 ID" value={selectedCreator.id} />
                  <CreatorField label="公开名称" value={selectedCreator.name} />
                  <CreatorField label="状态" value={selectedCreator.status} />
                  <CreatorField label="默认平台" value={formatPlatformList(selectedCreator.default_platforms)} />
                  <CreatorField label="创建时间" value={formatDateTime(selectedCreator.created_at)} />
                  <CreatorField label="更新时间" value={formatDateTime(selectedCreator.updated_at)} />
                </div>
              </section>
            </aside>
          </>
        ) : (
          <main className="panel creator-card-empty-state">
            <div className="creator-detail-header">
              <div>
                <strong>还没有创作者卡片</strong>
                <div className="muted top-gap">新建后可维护创作者身份、平台绑定、素材和默认策略关系。</div>
              </div>
              <button
                type="button"
                className="button primary"
                disabled={reachedCreatorLimit}
                onClick={openCreateCreatorModal}
              >
                新建创作者
              </button>
            </div>
          </main>
        )}
      </div>

      {createModalOpen ? (
        <div className="floating-modal-backdrop" onClick={closeCreatorModal} role="presentation">
          <div
            className="floating-modal-shell watch-root-editor-modal-shell"
            role="dialog"
            aria-modal="true"
            aria-label={creatorModalMode === "edit" ? "编辑创作者选项" : "新建创作者"}
            onClick={(event) => event.stopPropagation()}
          >
            <button
              className="button ghost floating-modal-close"
              type="button"
              onClick={closeCreatorModal}
              aria-label="关闭创作者弹窗"
            >
              关闭
            </button>
            <section className="watch-root-editor-modal-content">
              <div className="muted">
                {creatorModalMode === "edit" ? "调整已有创作者的起号选项和基础档案" : "最多保存 10 个创作者"}
              </div>

              <div className="form-grid top-gap">
                <label>
                  <span>名称</span>
                  <input
                    className="input"
                    value={draft.name}
                    onChange={(event) => setDraft((prev) => ({ ...prev, name: event.target.value }))}
                  />
                </label>
              </div>

              <div className="creator-create-option-section top-gap">
                <div className="creator-create-option-head">
                  <strong>创作者定位</strong>
                  <span>必须选 1 个主定位，可再选最多 2 个副定位</span>
                </div>
                <div className="creator-create-option-grid rich">
                  {CREATOR_POSITIONING_OPTIONS.map((option) => (
                    <div
                      key={option.value}
                      className={`creator-create-option positioning-card${
                        draft.primaryPositioning === option.value ? " selected primary" : ""
                      }${draft.secondaryPositionings.includes(option.value) ? " selected secondary" : ""}`}
                    >
                      <strong>{option.label}</strong>
                      <span>{option.desc}</span>
                      <div className="creator-positioning-actions">
                        <button
                          type="button"
                          className="button ghost"
                          onClick={() =>
                            setDraft((prev) => ({
                              ...prev,
                              primaryPositioning: option.value,
                              secondaryPositionings: prev.secondaryPositionings.filter((item) => item !== option.value),
                            }))
                          }
                        >
                          设为主
                        </button>
                        <button
                          type="button"
                          className="button ghost"
                          disabled={
                            draft.primaryPositioning === option.value ||
                            (!draft.secondaryPositionings.includes(option.value) && draft.secondaryPositionings.length >= 2)
                          }
                          onClick={() =>
                            setDraft((prev) => ({
                              ...prev,
                              secondaryPositionings: toggleValue(prev.secondaryPositionings, option.value),
                            }))
                          }
                        >
                          {draft.secondaryPositionings.includes(option.value) ? "取消副" : "设为副"}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="creator-create-option-section top-gap">
                <div className="creator-create-option-head">
                  <strong>内容领域</strong>
                  <span>可多选，后续策略生成会优先参考</span>
                </div>
                <div className="creator-create-option-grid compact">
                  {modalDomainOptions.map((option) => (
                    <button
                      key={option}
                      type="button"
                      className={`creator-create-option${draft.contentDomains.includes(option) ? " selected" : ""}`}
                      onClick={() =>
                        setDraft((prev) => ({ ...prev, contentDomains: toggleValue(prev.contentDomains, option) }))
                      }
                    >
                      {option}
                    </button>
                  ))}
                </div>
              </div>

              <div className="creator-create-option-section top-gap">
                <div className="creator-create-option-head">
                  <strong>受众定位</strong>
                  <span>最多选 3 个，用来约束表达深度、圈层语言和情绪方向</span>
                </div>
                <div className="creator-create-option-grid rich">
                  {CREATOR_AUDIENCE_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      className={`creator-create-option${draft.audiences.includes(option.value) ? " selected" : ""}`}
                      disabled={!draft.audiences.includes(option.value) && draft.audiences.length >= 3}
                      onClick={() =>
                        setDraft((prev) => ({
                          ...prev,
                          audiences: toggleValue(prev.audiences, option.value).slice(0, 3),
                        }))
                      }
                    >
                      <strong>{option.label}</strong>
                      <span>{option.desc}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="creator-create-option-section top-gap">
                <div className="creator-create-option-head">
                  <strong>默认平台</strong>
                  <span>可多选，用来生成发布和物料策略</span>
                </div>
                <div className="creator-create-option-grid compact">
                  {modalPlatformOptions.map((option) => (
                    <button
                      key={option}
                      type="button"
                      className={`creator-create-option${draft.defaultPlatforms.includes(option) ? " selected" : ""}`}
                      onClick={() =>
                        setDraft((prev) => ({ ...prev, defaultPlatforms: toggleValue(prev.defaultPlatforms, option) }))
                      }
                    >
                      {option}
                    </button>
                  ))}
                </div>
              </div>

              <label className="top-gap">
                <span>更多描述</span>
                <textarea
                  className="input"
                  rows={5}
                  value={draft.naturalLanguageProfile}
                  onChange={(event) => setDraft((prev) => ({ ...prev, naturalLanguageProfile: event.target.value }))}
                />
              </label>

              <div className="toolbar top-gap">
                <button type="button" className="button ghost" onClick={closeCreatorModal}>
                  取消
                </button>
                <button
                  type="button"
                  className="button primary"
                  disabled={
                    (creatorModalMode === "create" && reachedCreatorLimit) ||
                    !draft.name.trim() ||
                    !draft.primaryPositioning ||
                    createCreator.isPending ||
                    updateCreator.isPending
                  }
                  onClick={() => (creatorModalMode === "edit" ? updateCreator.mutate() : createCreator.mutate())}
                >
                  {createCreator.isPending || updateCreator.isPending
                    ? "保存中"
                    : creatorModalMode === "edit"
                      ? "保存修改"
                      : "创建创作者卡片"}
                </button>
              </div>
            </section>
          </div>
        </div>
      ) : null}
    </section>
  );
}
