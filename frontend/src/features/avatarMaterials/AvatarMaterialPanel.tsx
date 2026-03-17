import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../../api";
import { PanelHeader } from "../../components/ui/PanelHeader";
import type { AvatarCreatorProfile, AvatarMaterialFile, AvatarMaterialProfile } from "../../types";

type CreatorProfileFormState = {
  public_name: string;
  real_name: string;
  title: string;
  organization: string;
  location: string;
  bio: string;
  creator_focus: string;
  expertise: string;
  audience: string;
  style: string;
  tone_keywords: string;
  primary_platform: string;
  active_platforms: string;
  signature: string;
  default_call_to_action: string;
  description_strategy: string;
  contact: string;
  collaboration_notes: string;
  availability: string;
  archive_notes: string;
};

export function AvatarMaterialPanel() {
  const queryClient = useQueryClient();
  const [displayName, setDisplayName] = useState("");
  const [presenterAlias, setPresenterAlias] = useState("");
  const [notes, setNotes] = useState("");
  const [creatorProfile, setCreatorProfile] = useState<CreatorProfileFormState>(() => emptyCreatorProfileFormState());
  const [speakingVideos, setSpeakingVideos] = useState<File[]>([]);
  const [portraitPhotos, setPortraitPhotos] = useState<File[]>([]);
  const [voiceSamples, setVoiceSamples] = useState<File[]>([]);
  const [replaceFileId, setReplaceFileId] = useState<string | null>(null);
  const [replaceError, setReplaceError] = useState<string | null>(null);
  const [previewErrors, setPreviewErrors] = useState<Record<string, string | null>>({});
  const library = useQuery({ queryKey: ["avatar-materials"], queryFn: api.getAvatarMaterials });

  const selectedFileCount = speakingVideos.length + portraitPhotos.length + voiceSamples.length;
  const upload = useMutation({
    mutationFn: () =>
      api.uploadAvatarMaterialProfile(
        displayName,
        presenterAlias,
        notes,
        buildCreatorProfilePayload(creatorProfile),
        speakingVideos,
        portraitPhotos,
        voiceSamples,
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(["avatar-materials"], data);
      setDisplayName("");
      setPresenterAlias("");
      setNotes("");
      setCreatorProfile(emptyCreatorProfileFormState());
      setSpeakingVideos([]);
      setPortraitPhotos([]);
      setVoiceSamples([]);
    },
  });
  const remove = useMutation({
    mutationFn: (profileId: string) => api.deleteAvatarMaterialProfile(profileId),
    onSuccess: (data) => {
      queryClient.setQueryData(["avatar-materials"], data);
    },
  });
  const preview = useMutation({
    mutationFn: ({ profileId, script }: { profileId: string; script: string }) => api.generateAvatarMaterialPreview(profileId, script),
    onMutate: ({ profileId }) => {
      setPreviewErrors((prev) => ({ ...prev, [profileId]: null }));
      return { profileId };
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["avatar-materials"], data);
    },
    onError: (error, variables) => {
      setPreviewErrors((prev) => ({
        ...prev,
        [variables.profileId]: error instanceof Error ? error.message : String(error),
      }));
    },
  });
  const replaceMaterial = useMutation({
    mutationFn: ({ profileId, fileId, file }: { profileId: string; fileId: string; file: File }) =>
      api.replaceAvatarMaterialFile(profileId, fileId, file),
    onMutate: ({ fileId }) => {
      setReplaceFileId(fileId);
      setReplaceError(null);
      return { fileId };
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["avatar-materials"], data);
      setReplaceError(null);
    },
    onError: (error) => {
      setReplaceError(error instanceof Error ? error.message : String(error));
    },
    onSettled: () => {
      setReplaceFileId(null);
    },
  });
  const updateProfile = useMutation({
    mutationFn: ({
      profileId,
      displayName,
      presenterAlias,
      notes,
      creatorProfile,
    }: {
      profileId: string;
      displayName: string;
      presenterAlias: string;
      notes: string;
      creatorProfile: AvatarCreatorProfile;
    }) => api.updateAvatarMaterialProfile(profileId, displayName, presenterAlias, notes, creatorProfile),
    onSuccess: (data) => {
      queryClient.setQueryData(["avatar-materials"], data);
    },
  });

  const payload = library.data;
  const readyCount = (payload?.profiles ?? []).filter((item) => item.profile_dashboard?.section_status?.materials).length;

  return (
    <section className="panel top-gap">
      <PanelHeader
        title="创作者档案"
        description="把作者身份、内容定位、渠道策略、商务备注和数字人口播素材放进同一个档案，后续文案生成、模板复用和数字人预览都从这里取数。"
      />

      {library.error ? <div className="notice">{String(library.error)}</div> : null}

      <div className="avatar-creator-summary-grid">
        <article className="avatar-material-card">
          <div className="stat-label">档案说明</div>
          <p className="muted compact-top">{payload?.summary ?? "加载中..."}</p>
          <div className="avatar-stat-grid compact-top">
            <div className="activity-card">
              <strong>{payload?.profiles?.length ?? 0}</strong>
              <div className="muted compact-top">创作者档案</div>
            </div>
            <div className="activity-card">
              <strong>{readyCount}</strong>
              <div className="muted compact-top">可直接生成数字人预览</div>
            </div>
          </div>
          <div className="list-stack compact-top">
            {(payload?.sections ?? []).map((section) => (
              <section key={section.title} className="avatar-requirement-block">
                <strong>{section.title}</strong>
                <div className="list-stack compact-top">
                  {section.rules.map((rule) => (
                    <div key={`${section.title}-${rule.title}`} className="avatar-rule-row">
                      <span className={`status-pill ${rule.severity === "required" ? "failed" : rule.severity === "recommended" ? "running" : ""}`}>
                        {rule.severity === "required" ? "必须" : rule.severity === "recommended" ? "建议" : "说明"}
                      </span>
                      <div>
                        <div>{rule.title}</div>
                        <div className="muted compact-top">{rule.detail}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </article>

        <article className="avatar-material-card">
          <div className="stat-label">新建创作者档案</div>
          <div className="form-stack compact-top">
            <label>
              <span>档案名称</span>
              <input className="input" value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="例如：赛博迪克朗 / FAS潮玩" />
            </label>
            <label>
              <span>出镜 / 口播名</span>
              <input className="input" value={presenterAlias} onChange={(event) => setPresenterAlias(event.target.value)} placeholder="可选，用于数字人口播或前台展示" />
            </label>
            <label>
              <span>内部备注</span>
              <textarea className="input avatar-textarea" value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="例如：人物来源、录制环境、希望保留的语气" />
            </label>
            <CreatorProfileFields value={creatorProfile} onChange={setCreatorProfile} />
            <div className="avatar-file-grid top-gap">
              <AvatarFileField
                label="讲话视频片段"
                hint="HeyGem 数字人训练 / 口型参考。建议单人出镜、20 到 120 秒。"
                accept=".mp4,.mov,.mkv,.avi"
                files={speakingVideos}
                onChange={setSpeakingVideos}
              />
              <AvatarFileField
                label="肖像照"
                hint="人物核验和模板管理。建议 3 到 10 张正脸图片。"
                accept=".jpg,.jpeg,.png"
                files={portraitPhotos}
                onChange={setPortraitPhotos}
              />
              <AvatarFileField
                label="声音采样"
                hint="声音克隆 / AI 导演重配音。建议单说话人干净人声。"
                accept=".wav,.mp3,.m4a"
                files={voiceSamples}
                onChange={setVoiceSamples}
              />
            </div>
            <div className="muted">本次共选 {selectedFileCount} 个素材文件。</div>
            <button className="button primary" type="button" disabled={upload.isPending || !displayName.trim() || selectedFileCount === 0} onClick={() => upload.mutate()}>
              {upload.isPending ? "创建中..." : "创建创作者档案"}
            </button>
            {upload.error ? <div className="notice">{String(upload.error)}</div> : null}
          </div>
        </article>
      </div>

      <div className="list-stack top-gap">
        {(payload?.profiles ?? []).map((profile) => (
          <CreatorArchiveCard
            key={profile.id}
            profile={profile}
            removing={remove.isPending}
            previewing={preview.isPending}
            onRemove={() => remove.mutate(profile.id)}
            onPreview={(script) => preview.mutate({ profileId: profile.id, script })}
            onPreviewUnavailable={(message) => setPreviewErrors((prev) => ({ ...prev, [profile.id]: message }))}
            onReplace={(fileId, file) => replaceMaterial.mutate({ profileId: profile.id, fileId, file })}
            replacingFileId={replaceFileId}
            previewError={previewErrors[profile.id] ?? null}
            onUpdateProfile={(nextDisplayName, nextPresenterAlias, nextNotes, nextCreatorProfile) =>
              updateProfile.mutate({
                profileId: profile.id,
                displayName: nextDisplayName,
                presenterAlias: nextPresenterAlias,
                notes: nextNotes,
                creatorProfile: nextCreatorProfile,
              })
            }
            updating={updateProfile.isPending}
          />
        ))}
        {replaceError ? <div className="notice top-gap">{replaceError}</div> : null}
        {!payload?.profiles?.length ? <div className="empty-state">还没有创作者档案，先建一个完整的人设与素材档案。</div> : null}
      </div>
    </section>
  );
}

function emptyCreatorProfileFormState(): CreatorProfileFormState {
  return {
    public_name: "",
    real_name: "",
    title: "",
    organization: "",
    location: "",
    bio: "",
    creator_focus: "",
    expertise: "",
    audience: "",
    style: "",
    tone_keywords: "",
    primary_platform: "",
    active_platforms: "",
    signature: "",
    default_call_to_action: "",
    description_strategy: "",
    contact: "",
    collaboration_notes: "",
    availability: "",
    archive_notes: "",
  };
}

function creatorProfileFormStateFromValue(value?: AvatarCreatorProfile | null): CreatorProfileFormState {
  return {
    public_name: value?.identity?.public_name ?? "",
    real_name: value?.identity?.real_name ?? "",
    title: value?.identity?.title ?? "",
    organization: value?.identity?.organization ?? "",
    location: value?.identity?.location ?? "",
    bio: value?.identity?.bio ?? "",
    creator_focus: value?.positioning?.creator_focus ?? "",
    expertise: (value?.positioning?.expertise ?? []).join("、"),
    audience: value?.positioning?.audience ?? "",
    style: value?.positioning?.style ?? "",
    tone_keywords: (value?.positioning?.tone_keywords ?? []).join("、"),
    primary_platform: value?.publishing?.primary_platform ?? "",
    active_platforms: (value?.publishing?.active_platforms ?? []).join("、"),
    signature: value?.publishing?.signature ?? "",
    default_call_to_action: value?.publishing?.default_call_to_action ?? "",
    description_strategy: value?.publishing?.description_strategy ?? "",
    contact: value?.business?.contact ?? "",
    collaboration_notes: value?.business?.collaboration_notes ?? "",
    availability: value?.business?.availability ?? "",
    archive_notes: value?.archive_notes ?? "",
  };
}

function buildCreatorProfilePayload(value: CreatorProfileFormState): AvatarCreatorProfile {
  return {
    identity: {
      public_name: trimToNull(value.public_name),
      real_name: trimToNull(value.real_name),
      title: trimToNull(value.title),
      organization: trimToNull(value.organization),
      location: trimToNull(value.location),
      bio: trimToNull(value.bio),
    },
    positioning: {
      creator_focus: trimToNull(value.creator_focus),
      expertise: splitTags(value.expertise),
      audience: trimToNull(value.audience),
      style: trimToNull(value.style),
      tone_keywords: splitTags(value.tone_keywords),
    },
    publishing: {
      primary_platform: trimToNull(value.primary_platform),
      active_platforms: splitTags(value.active_platforms),
      signature: trimToNull(value.signature),
      default_call_to_action: trimToNull(value.default_call_to_action),
      description_strategy: trimToNull(value.description_strategy),
    },
    business: {
      contact: trimToNull(value.contact),
      collaboration_notes: trimToNull(value.collaboration_notes),
      availability: trimToNull(value.availability),
    },
    archive_notes: trimToNull(value.archive_notes),
  };
}

function trimToNull(value: string) {
  const text = value.trim();
  return text ? text : null;
}

function splitTags(value: string) {
  return value
    .split(/[\n,，、;/；]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function CreatorProfileFields({
  value,
  onChange,
}: {
  value: CreatorProfileFormState;
  onChange: (value: CreatorProfileFormState) => void;
}) {
  const updateField = (key: keyof CreatorProfileFormState, nextValue: string) => {
    onChange({ ...value, [key]: nextValue });
  };

  return (
    <div className="list-stack compact-top">
      <section className="avatar-requirement-block">
        <strong>身份信息</strong>
        <div className="avatar-creator-field-grid compact-top">
          <label>
            <span>作者名 / 对外称呼</span>
            <input className="input" value={value.public_name} onChange={(event) => updateField("public_name", event.target.value)} />
          </label>
          <label>
            <span>真实姓名</span>
            <input className="input" value={value.real_name} onChange={(event) => updateField("real_name", event.target.value)} />
          </label>
          <label>
            <span>身份标题</span>
            <input className="input" value={value.title} onChange={(event) => updateField("title", event.target.value)} placeholder="例如：EDC评测作者" />
          </label>
          <label>
            <span>机构 / 品牌</span>
            <input className="input" value={value.organization} onChange={(event) => updateField("organization", event.target.value)} />
          </label>
          <label>
            <span>所在地</span>
            <input className="input" value={value.location} onChange={(event) => updateField("location", event.target.value)} />
          </label>
          <label className="avatar-creator-field-span">
            <span>作者简介</span>
            <textarea className="input avatar-textarea" value={value.bio} onChange={(event) => updateField("bio", event.target.value)} />
          </label>
        </div>
      </section>

      <section className="avatar-requirement-block">
        <strong>内容定位</strong>
        <div className="avatar-creator-field-grid compact-top">
          <label>
            <span>内容定位</span>
            <input className="input" value={value.creator_focus} onChange={(event) => updateField("creator_focus", event.target.value)} placeholder="例如：手电开箱、EDC装备、工具体验" />
          </label>
          <label>
            <span>擅长领域</span>
            <input className="input" value={value.expertise} onChange={(event) => updateField("expertise", event.target.value)} placeholder="多个用顿号分隔" />
          </label>
          <label>
            <span>目标受众</span>
            <input className="input" value={value.audience} onChange={(event) => updateField("audience", event.target.value)} />
          </label>
          <label>
            <span>表达风格 / 人设</span>
            <input className="input" value={value.style} onChange={(event) => updateField("style", event.target.value)} />
          </label>
          <label className="avatar-creator-field-span">
            <span>语气关键词</span>
            <input className="input" value={value.tone_keywords} onChange={(event) => updateField("tone_keywords", event.target.value)} placeholder="例如：理性、真实、克制、有梗" />
          </label>
        </div>
      </section>

      <section className="avatar-requirement-block">
        <strong>渠道策略</strong>
        <div className="avatar-creator-field-grid compact-top">
          <label>
            <span>主平台</span>
            <input className="input" value={value.primary_platform} onChange={(event) => updateField("primary_platform", event.target.value)} placeholder="例如：B站" />
          </label>
          <label>
            <span>活跃平台</span>
            <input className="input" value={value.active_platforms} onChange={(event) => updateField("active_platforms", event.target.value)} placeholder="例如：B站、小红书、抖音" />
          </label>
          <label>
            <span>个性签名</span>
            <input className="input" value={value.signature} onChange={(event) => updateField("signature", event.target.value)} />
          </label>
          <label>
            <span>默认 CTA</span>
            <input className="input" value={value.default_call_to_action} onChange={(event) => updateField("default_call_to_action", event.target.value)} placeholder="例如：评论区聊聊你更站哪边" />
          </label>
          <label className="avatar-creator-field-span">
            <span>简介生成策略</span>
            <textarea className="input avatar-textarea" value={value.description_strategy} onChange={(event) => updateField("description_strategy", event.target.value)} placeholder="例如：B站偏专业判断，小红书偏生活化分享，抖音只留短身份锚点" />
          </label>
        </div>
      </section>

      <section className="avatar-requirement-block">
        <strong>商务与归档</strong>
        <div className="avatar-creator-field-grid compact-top">
          <label>
            <span>联系方式</span>
            <input className="input" value={value.contact} onChange={(event) => updateField("contact", event.target.value)} />
          </label>
          <label>
            <span>合作状态 / 可约情况</span>
            <input className="input" value={value.availability} onChange={(event) => updateField("availability", event.target.value)} placeholder="例如：可接商单 / 暂不合作" />
          </label>
          <label className="avatar-creator-field-span">
            <span>合作备注</span>
            <textarea className="input avatar-textarea" value={value.collaboration_notes} onChange={(event) => updateField("collaboration_notes", event.target.value)} />
          </label>
          <label className="avatar-creator-field-span">
            <span>档案附注</span>
            <textarea className="input avatar-textarea" value={value.archive_notes} onChange={(event) => updateField("archive_notes", event.target.value)} />
          </label>
        </div>
      </section>
    </div>
  );
}

function AvatarFileField({
  label,
  hint,
  accept,
  files,
  onChange,
}: {
  label: string;
  hint: string;
  accept: string;
  files: File[];
  onChange: (files: File[]) => void;
}) {
  return (
    <label className="avatar-role-column">
      <span className="stat-label">{label}</span>
      <input className="input" type="file" multiple accept={accept} onChange={(event) => onChange(Array.from(event.target.files ?? []))} />
      <span className="muted">{hint}</span>
      <span className="muted">{files.length ? files.map((file) => file.name).join("、") : "未选择文件"}</span>
    </label>
  );
}

function CreatorArchiveCard({
  profile,
  removing,
  previewing,
  onRemove,
  onPreview,
  onPreviewUnavailable,
  onReplace,
  replacingFileId,
  previewError,
  onUpdateProfile,
  updating,
}: {
  profile: AvatarMaterialProfile;
  removing: boolean;
  previewing: boolean;
  onRemove: () => void;
  onPreview: (script: string) => void;
  onPreviewUnavailable: (message: string) => void;
  onReplace: (fileId: string, file: File) => void;
  replacingFileId: string | null;
  previewError: string | null;
  onUpdateProfile: (displayName: string, presenterAlias: string, notes: string, creatorProfile: AvatarCreatorProfile) => void;
  updating: boolean;
}) {
  const previewSpeakerName = profile.creator_profile?.identity?.public_name || profile.presenter_alias || profile.display_name;
  const [previewScript, setPreviewScript] = useState(
    `大家好，我是${previewSpeakerName}。现在这是一条 RoughCut 自动生成的创作者数字人预览样片，主要用于检查音色一致性、口型同步和讲话镜头稳定性。`,
  );
  const [openPreviewId, setOpenPreviewId] = useState<string | null>(null);
  const lastLatestPreviewRunId = useRef<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editDisplayName, setEditDisplayName] = useState(profile.display_name);
  const [editPresenterAlias, setEditPresenterAlias] = useState(profile.presenter_alias || "");
  const [editNotes, setEditNotes] = useState(profile.notes || "");
  const [editCreatorProfile, setEditCreatorProfile] = useState<CreatorProfileFormState>(() => creatorProfileFormStateFromValue(profile.creator_profile));
  const groupedFiles = useMemo(() => {
    const groups: Record<string, AvatarMaterialFile[]> = {
      speaking_video: [],
      portrait_photo: [],
      voice_sample: [],
      generic: [],
    };
    profile.files.forEach((file) => {
      const role = file.role in groups ? file.role : "generic";
      groups[role].push(file);
    });
    return groups;
  }, [profile.files]);

  useEffect(() => {
    setEditDisplayName(profile.display_name);
    setEditPresenterAlias(profile.presenter_alias || "");
    setEditNotes(profile.notes || "");
    setEditCreatorProfile(creatorProfileFormStateFromValue(profile.creator_profile));
    setEditing(false);
  }, [profile.id, profile.display_name, profile.presenter_alias, profile.notes, profile.creator_profile]);

  useEffect(() => {
    const latestRunId = profile.preview_runs?.[0]?.id || null;
    if (!latestRunId || latestRunId === lastLatestPreviewRunId.current) {
      return;
    }
    lastLatestPreviewRunId.current = latestRunId;
    setOpenPreviewId(latestRunId);
  }, [profile.preview_runs]);

  const saveProfile = () => {
    if (!editDisplayName.trim()) return;
    onUpdateProfile(editDisplayName.trim(), editPresenterAlias.trim(), editNotes.trim(), buildCreatorProfilePayload(editCreatorProfile));
    setEditing(false);
  };

  const dashboard = profile.profile_dashboard;
  const publicName = profile.creator_profile?.identity?.public_name || profile.presenter_alias || profile.display_name;

  return (
    <article className="avatar-profile-card">
      <div className="avatar-profile-head">
        <div>
          {editing ? <input className="input" value={editDisplayName} onChange={(event) => setEditDisplayName(event.target.value)} /> : <strong>{profile.display_name}</strong>}
          <div className="muted compact-top">
            {editing ? <input className="input" value={editPresenterAlias} onChange={(event) => setEditPresenterAlias(event.target.value)} placeholder="出镜 / 口播名" /> : `${publicName} · ${new Date(profile.created_at).toLocaleString()}`}
          </div>
        </div>
        <div className="toolbar">
          <span className={`status-pill ${profile.training_status === "ready_for_manual_training" ? "done" : "running"}`}>
            {profile.training_status === "ready_for_manual_training" ? "数字人链路可导入" : "待补素材"}
          </span>
          <span className="status-pill">{dashboard?.completeness_score ?? 0}% 完整度</span>
          <button className="button ghost" type="button" disabled={updating || removing} onClick={() => setEditing((current) => !current)}>
            {editing ? "取消编辑" : "编辑档案"}
          </button>
          <button className="button ghost" type="button" onClick={onRemove} disabled={removing}>
            删除
          </button>
        </div>
      </div>

      {editing ? (
        <div className="form-stack compact-top">
          <label>
            <span>内部备注</span>
            <textarea className="input avatar-textarea" value={editNotes} onChange={(event) => setEditNotes(event.target.value)} />
          </label>
          <CreatorProfileFields value={editCreatorProfile} onChange={setEditCreatorProfile} />
          <div className="toolbar">
            <button className="button primary" type="button" disabled={updating || !editDisplayName.trim()} onClick={saveProfile}>
              {updating ? "保存中..." : "保存档案"}
            </button>
            <button className="button ghost" type="button" disabled={updating} onClick={() => setEditing(false)}>
              取消
            </button>
          </div>
        </div>
      ) : (
        <>
          {profile.notes ? <div className="muted compact-top">{profile.notes}</div> : null}
          <div className="avatar-stat-grid top-gap">
            <div className="activity-card">
              <strong>{dashboard?.material_counts?.speaking_videos ?? 0}</strong>
              <div className="muted compact-top">讲话视频</div>
            </div>
            <div className="activity-card">
              <strong>{dashboard?.material_counts?.voice_samples ?? 0}</strong>
              <div className="muted compact-top">声音采样</div>
            </div>
            <div className="activity-card">
              <strong>{dashboard?.material_counts?.portrait_photos ?? 0}</strong>
              <div className="muted compact-top">肖像照</div>
            </div>
            <div className="activity-card">
              <strong>{(dashboard?.strengths ?? []).length}</strong>
              <div className="muted compact-top">已成型优势</div>
            </div>
          </div>
          <div className="mode-chip-list top-gap">
            <CapabilityChip label="身份信息" ready={Boolean(dashboard?.section_status?.identity)} />
            <CapabilityChip label="内容定位" ready={Boolean(dashboard?.section_status?.positioning)} />
            <CapabilityChip label="渠道策略" ready={Boolean(dashboard?.section_status?.publishing)} />
            <CapabilityChip label="商务信息" ready={Boolean(dashboard?.section_status?.business)} />
            <CapabilityChip label="数字人素材" ready={Boolean(dashboard?.section_status?.materials)} />
          </div>
          <CreatorProfileSummary profile={profile} />
          {(dashboard?.strengths?.length || dashboard?.next_steps?.length) ? (
            <div className="avatar-creator-section-grid top-gap">
              {(dashboard?.strengths?.length ?? 0) > 0 ? (
                <section className="avatar-requirement-block">
                  <div className="stat-label">当前优势</div>
                  <div className="list-stack compact-top">
                    {(dashboard?.strengths ?? []).map((item) => (
                      <div key={item} className="activity-card">
                        {item}
                      </div>
                    ))}
                  </div>
                </section>
              ) : null}
              {(dashboard?.next_steps?.length ?? 0) > 0 ? (
                <section className="avatar-requirement-block">
                  <div className="stat-label">下一步补齐</div>
                  <div className="list-stack compact-top">
                    {(dashboard?.next_steps ?? []).map((item) => (
                      <div key={item} className="notice">
                        {item}
                      </div>
                    ))}
                  </div>
                </section>
              ) : null}
            </div>
          ) : null}
        </>
      )}

      {profile.blocking_issues.length ? (
        <div className="avatar-issue-block top-gap">
          <div className="stat-label">阻塞项</div>
          <div className="list-stack compact-top">
            {profile.blocking_issues.map((item) => (
              <div key={item} className="notice">
                {item}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {profile.warnings.length ? (
        <div className="avatar-issue-block top-gap">
          <div className="stat-label">建议补充</div>
          <div className="list-stack compact-top">
            {profile.warnings.map((item) => (
              <div key={item} className="activity-card">
                {item}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="avatar-file-grid top-gap">
        <AvatarRoleColumn
          title="讲话视频片段"
          files={groupedFiles.speaking_video}
          profileId={profile.id}
          roleKey="speaking_video"
          onReplace={onReplace}
          replacingFileId={replacingFileId}
        />
        <AvatarRoleColumn
          title="肖像照"
          files={groupedFiles.portrait_photo}
          profileId={profile.id}
          roleKey="portrait_photo"
          onReplace={onReplace}
          replacingFileId={replacingFileId}
        />
        <AvatarRoleColumn
          title="声音采样"
          files={groupedFiles.voice_sample}
          profileId={profile.id}
          roleKey="voice_sample"
          onReplace={onReplace}
          replacingFileId={replacingFileId}
        />
      </div>

      <section className="avatar-issue-block top-gap">
        <div className="stat-label">数字人预览</div>
        <div className="form-stack compact-top">
          {previewError ? <div className="notice">{previewError}</div> : null}
          <textarea className="input avatar-textarea" value={previewScript} onChange={(event) => setPreviewScript(event.target.value)} placeholder="输入一段预览台词" />
          <div className="toolbar">
            <button
              className="button primary"
              type="button"
              disabled={previewing}
              onClick={() => {
                const script =
                  previewScript.trim() ||
                  `大家好，我是${previewSpeakerName}。现在这是一条 RoughCut 自动生成的创作者数字人预览样片，主要用于检查音色一致性、口型同步和讲话镜头稳定性。`;
                const hasPrerequisite = profile.capability_status?.heygem_avatar === "ready" && profile.capability_status?.voice_clone === "ready";
                if (!hasPrerequisite) {
                  onPreviewUnavailable(profile.next_action || "需要讲话视频片段和声音采样。");
                  return;
                }
                setPreviewScript(script);
                onPreview(script);
              }}
            >
              {previewing ? "生成中..." : "生成数字人预览"}
            </button>
          </div>
          {profile.capability_status.preview !== "ready" ? <span className="muted">{profile.next_action || "需要讲话视频片段和声音采样。"}</span> : null}
          <div className="list-stack">
            {(profile.preview_runs ?? []).map((run) => (
              <div key={run.id} className="avatar-file-card">
                <div className="toolbar">
                  <strong>{run.status === "running" ? "生成中" : run.status === "completed" ? "预览已生成" : "预览失败"}</strong>
                  <div className="toolbar">
                    {run.output_path ? (
                      <button className="button ghost" type="button" onClick={() => setOpenPreviewId((current) => (current === run.id ? null : run.id))}>
                        {openPreviewId === run.id ? "收起播放" : "直接播放"}
                      </button>
                    ) : null}
                    {run.output_path ? (
                      <a className="button ghost" href={api.avatarMaterialPreviewUrl(profile.id, run.id)} target="_blank" rel="noreferrer">
                        下载样片
                      </a>
                    ) : null}
                  </div>
                </div>
                <div className="muted compact-top">{new Date(run.created_at).toLocaleString()}</div>
                <div className="muted compact-top">{run.script}</div>
                {run.preview_mode ? (
                  <div className="muted compact-top">
                    {run.preview_mode === "scripted_tts" ? "脚本 TTS 预览" : run.preview_mode === "source_audio_direct" ? "HeyGem 直连预览" : "原始声音样本回退预览"}
                  </div>
                ) : null}
                {run.fallback_reason ? <div className="muted compact-top">已回退到原始声音样本</div> : null}
                {run.output_path && openPreviewId === run.id ? (
                  <video className="avatar-preview-player compact-top" controls playsInline preload="metadata" src={api.avatarMaterialPreviewUrl(profile.id, run.id)} />
                ) : null}
                {run.duration_sec ? <div className="muted compact-top">{run.duration_sec.toFixed(1)}s · {run.width}x{run.height}</div> : null}
                {run.error_message ? <div className="notice compact-top">{run.error_message}</div> : null}
              </div>
            ))}
            {!profile.preview_runs?.length ? <div className="empty-state">还没有预览样片。</div> : null}
          </div>
        </div>
      </section>

      <div className="muted compact-top">{profile.next_action}</div>
    </article>
  );
}

function CreatorProfileSummary({ profile }: { profile: AvatarMaterialProfile }) {
  const creator = profile.creator_profile;
  const identity = creator?.identity;
  const positioning = creator?.positioning;
  const publishing = creator?.publishing;
  const business = creator?.business;

  const sections = [
    { title: "身份", values: [identity?.public_name, identity?.title, identity?.organization, identity?.location, identity?.bio].filter(Boolean) },
    { title: "定位", values: [positioning?.creator_focus, positioning?.expertise?.join("、"), positioning?.audience, positioning?.style, positioning?.tone_keywords?.join("、")].filter(Boolean) },
    { title: "渠道", values: [publishing?.primary_platform ? `主平台：${publishing.primary_platform}` : null, (publishing?.active_platforms?.length ?? 0) > 0 ? `活跃平台：${publishing?.active_platforms?.join("、")}` : null, publishing?.signature, publishing?.default_call_to_action, publishing?.description_strategy].filter(Boolean) },
    { title: "商务", values: [business?.contact, business?.availability, business?.collaboration_notes, creator?.archive_notes].filter(Boolean) },
  ].filter((section) => section.values.length);

  if (!sections.length) return null;

  return (
    <div className="avatar-creator-section-grid top-gap">
      {sections.map((section) => (
        <section key={section.title} className="avatar-requirement-block">
          <div className="stat-label">{section.title}</div>
          <div className="list-stack compact-top">
            {section.values.map((item) => (
              <div key={item} className="activity-card">
                {item}
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function AvatarRoleColumn({
  title,
  files,
  profileId,
  roleKey,
  onReplace,
  replacingFileId,
}: {
  title: string;
  files: AvatarMaterialFile[];
  profileId: string;
  roleKey: "speaking_video" | "portrait_photo" | "voice_sample" | "generic";
  onReplace: (fileId: string, file: File) => void;
  replacingFileId: string | null;
}) {
  const accept = roleAcceptByRole[roleKey];

  return (
    <section className="avatar-role-column">
      <div className="stat-label">{title}</div>
      <div className="list-stack compact-top">
        {files.map((file) => {
          const isReplacing = replacingFileId === file.id;
          const fileUrl = buildAvatarMaterialFileUrl(profileId, file.id, file.created_at);
          return (
            <div key={file.id} className="avatar-file-card">
              <div className="avatar-role-file-head">
                <strong>{file.original_name}</strong>
                <div className="toolbar">
                  <label className={`button ghost ${isReplacing ? "button-disabled" : ""}`}>
                    {isReplacing ? "替换中..." : "替换素材"}
                    <input
                      className="avatar-hidden-file-input"
                      type="file"
                      accept={accept}
                      disabled={isReplacing}
                      onChange={(event) => {
                        const nextFile = event.target.files?.[0] || null;
                        if (!nextFile) return;
                        event.target.value = "";
                        onReplace(file.id, nextFile);
                      }}
                    />
                  </label>
                  <a className="text-link" href={fileUrl} target="_blank" rel="noreferrer">
                    下载
                  </a>
                </div>
              </div>
              {isPreviewableMedia(file) ? (
                <div className="avatar-media-preview compact-top">
                  {renderAvatarFilePreview(file, buildAvatarMaterialFileUrl(profileId, file.id, file.created_at))}
                </div>
              ) : null}
              <div className="muted compact-top">
                {file.role_label} · {(file.size_bytes / 1024 / 1024).toFixed(2)} MB
              </div>
              {file.probe ? (
                <div className="muted compact-top">
                  时长 {Number(file.probe.duration ?? 0).toFixed(1)}s · {Number(file.probe.width ?? 0)}x{Number(file.probe.height ?? 0)} · {Number(file.probe.fps ?? 0).toFixed(1)}fps
                </div>
              ) : null}
              <div className="mode-chip-list compact-top">
                <span className="mode-chip subtle">{pipelineLabel(file.pipeline_target)}</span>
                {file.artifacts?.training_preprocess ? <span className="mode-chip subtle">已预处理</span> : null}
              </div>
              <div className="list-stack compact-top">
                {file.checks.map((check, index) => (
                  <div key={`${file.id}-${index}`} className={`status-pill ${check.level === "error" ? "failed" : check.level === "warning" ? "running" : "done"}`}>
                    {check.message}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
        {!files.length ? <div className="empty-state">暂未上传</div> : null}
      </div>
    </section>
  );
}

const roleAcceptByRole: Record<"speaking_video" | "portrait_photo" | "voice_sample" | "generic", string> = {
  speaking_video: ".mp4,.mov,.mkv,.avi",
  portrait_photo: ".jpg,.jpeg,.png",
  voice_sample: ".wav,.mp3,.m4a",
  generic: "",
};

function CapabilityChip({ label, ready }: { label: string; ready: boolean }) {
  return <span className={`mode-chip ${ready ? "" : "planned"}`}>{label} · {ready ? "已完善" : "待完善"}</span>;
}

function pipelineLabel(target: string) {
  if (target === "heygem_avatar") return "HeyGem 数字人";
  if (target === "voice_clone") return "声音克隆";
  if (target === "avatar_identity") return "形象管理";
  return "人工复核";
}

function isPreviewableImage(file: AvatarMaterialFile): boolean {
  return /^image\//.test(file.content_type);
}

function isPreviewableVideo(file: AvatarMaterialFile): boolean {
  return /^video\//.test(file.content_type);
}

function isPreviewableAudio(file: AvatarMaterialFile): boolean {
  return /^audio\//.test(file.content_type);
}

function isPreviewableMedia(file: AvatarMaterialFile): boolean {
  return isPreviewableVideo(file) || isPreviewableAudio(file) || isPreviewableImage(file);
}

function renderAvatarFilePreview(file: AvatarMaterialFile, src: string) {
  if (isPreviewableVideo(file)) {
    return <video key={src} className="avatar-preview-player compact-top" controls playsInline preload="metadata" src={src} />;
  }
  if (isPreviewableAudio(file)) {
    return <audio key={src} className="avatar-audio-player compact-top" controls src={src} />;
  }
  if (isPreviewableImage(file)) {
    return <img key={src} className="avatar-image-preview compact-top" src={src} alt={file.original_name} />;
  }
  return null;
}

function buildAvatarMaterialFileUrl(profileId: string, fileId: string, createdAt: string) {
  const base = api.avatarMaterialFileUrl(profileId, fileId);
  return `${base}?v=${encodeURIComponent(createdAt || "")}`;
}
