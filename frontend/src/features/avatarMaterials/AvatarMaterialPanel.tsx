import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../../api";
import { PanelHeader } from "../../components/ui/PanelHeader";
import type { AvatarMaterialFile, AvatarMaterialProfile } from "../../types";

export function AvatarMaterialPanel() {
  const queryClient = useQueryClient();
  const [displayName, setDisplayName] = useState("");
  const [presenterAlias, setPresenterAlias] = useState("");
  const [notes, setNotes] = useState("");
  const [speakingVideos, setSpeakingVideos] = useState<File[]>([]);
  const [portraitPhotos, setPortraitPhotos] = useState<File[]>([]);
  const [voiceSamples, setVoiceSamples] = useState<File[]>([]);
  const [replaceFileId, setReplaceFileId] = useState<string | null>(null);
  const [replaceError, setReplaceError] = useState<string | null>(null);
  const [previewErrors, setPreviewErrors] = useState<Record<string, string | null>>({});
  const library = useQuery({ queryKey: ["avatar-materials"], queryFn: api.getAvatarMaterials });

  const selectedFileCount = speakingVideos.length + portraitPhotos.length + voiceSamples.length;
  const upload = useMutation({
    mutationFn: () => api.uploadAvatarMaterialProfile(displayName, presenterAlias, notes, speakingVideos, portraitPhotos, voiceSamples),
    onSuccess: (data) => {
      queryClient.setQueryData(["avatar-materials"], data);
      setDisplayName("");
      setPresenterAlias("");
      setNotes("");
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
    }: {
      profileId: string;
      displayName: string;
      presenterAlias: string;
      notes: string;
    }) => api.updateAvatarMaterialProfile(profileId, displayName, presenterAlias, notes),
    onSuccess: (data) => {
      queryClient.setQueryData(["avatar-materials"], data);
    },
  });

  const payload = library.data;

  return (
    <section className="panel top-gap">
      <PanelHeader
        title="数字人素材上传"
        description="数字人部分现在按声音采样、肖像照、讲话视频片段分开上传，分别对应声音克隆、形象管理和 HeyGem 数字人链路。"
      />

      {library.error ? <div className="notice">{String(library.error)}</div> : null}

      <div className="avatar-material-grid">
        <article className="avatar-material-card">
          <div className="stat-label">素材要求</div>
          <p className="muted compact-top">{payload?.summary ?? "加载中..."}</p>
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
          <div className="stat-label">上传入口</div>
          <div className="form-stack compact-top">
            <label>
              <span>形象名称</span>
              <input className="input" value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="例如：半佛男声解说" />
            </label>
            <label>
              <span>展示别名</span>
              <input className="input" value={presenterAlias} onChange={(event) => setPresenterAlias(event.target.value)} placeholder="可选，用于前台展示" />
            </label>
            <label>
              <span>补充说明</span>
              <textarea className="input avatar-textarea" value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="例如：人物来源、录制环境、希望保留的语气" />
            </label>
            <AvatarFileField
              label="讲话视频片段"
              hint="给 HeyGem 数字人用，至少 1 段。建议单人出镜、口型清楚、20 到 120 秒。"
              accept=".mp4,.mov,.mkv,.avi"
              files={speakingVideos}
              onChange={setSpeakingVideos}
            />
            <AvatarFileField
              label="肖像照"
              hint="给形象核验和模板管理用。建议 3 到 10 张正脸图片。"
              accept=".jpg,.jpeg,.png"
              files={portraitPhotos}
              onChange={setPortraitPhotos}
            />
            <AvatarFileField
              label="声音采样"
              hint="给声音克隆和 AI 导演重配音用。建议单说话人、干净人声 10 秒以上。"
              accept=".wav,.mp3,.m4a"
              files={voiceSamples}
              onChange={setVoiceSamples}
            />
            <div className="muted">本次共选 {selectedFileCount} 个文件。</div>
            <button
              className="button primary"
              type="button"
              disabled={upload.isPending || !displayName.trim() || selectedFileCount === 0}
              onClick={() => upload.mutate()}
            >
              {upload.isPending ? "上传中..." : "上传并建立数字人档案"}
            </button>
            {upload.error ? <div className="notice">{String(upload.error)}</div> : null}
            <div className="notice">
              声音采样现在会优先转成标准 WAV，并在本地训练预处理接口可用时自动准备参考文本。即使训练接口暂时不可用，也可以先用原始声音样本做数字人验证预览。
            </div>
          </div>
        </article>
      </div>

      <div className="list-stack top-gap">
        {(payload?.profiles ?? []).map((profile) => (
          <AvatarProfileCard
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
            onUpdateProfile={(displayName, presenterAlias, notes) =>
              updateProfile.mutate({ profileId: profile.id, displayName, presenterAlias, notes })
            }
            updating={updateProfile.isPending}
          />
        ))}
        {replaceError ? <div className="notice top-gap">{replaceError}</div> : null}
        {!payload?.profiles?.length ? <div className="empty-state">还没有数字人素材档案，先上传讲话视频片段，再补肖像照和声音采样。</div> : null}
      </div>
    </section>
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
    <label>
      <span>{label}</span>
      <input
        className="input"
        type="file"
        multiple
        accept={accept}
        onChange={(event) => onChange(Array.from(event.target.files ?? []))}
      />
      <span className="muted">{hint}</span>
      <span className="muted">{files.length ? files.map((file) => file.name).join("、") : "未选择文件"}</span>
    </label>
  );
}

function AvatarProfileCard({
  profile,
  removing,
  previewing,
  onRemove,
  onPreview,
  onPreviewUnavailable,
  onReplace,
  replacingFileId,
  onUpdateProfile,
  updating,
  previewError,
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
  onUpdateProfile: (displayName: string, presenterAlias: string, notes: string) => void;
  updating: boolean;
}) {
  const [previewScript, setPreviewScript] = useState(
    `大家好，我是${profile.display_name}。现在这是一条 RoughCut 自动生成的数字人预览样片，主要用于检查音色一致性、口型同步和讲话镜头的整体稳定性。`,
  );
  const [openPreviewId, setOpenPreviewId] = useState<string | null>(null);
  const lastLatestPreviewRunId = useRef<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editDisplayName, setEditDisplayName] = useState(profile.display_name);
  const [editPresenterAlias, setEditPresenterAlias] = useState(profile.presenter_alias || "");
  const [editNotes, setEditNotes] = useState(profile.notes || "");
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
    setEditing(false);
  }, [profile.id, profile.display_name, profile.presenter_alias, profile.notes]);

  useEffect(() => {
    const latestRunId = profile.preview_runs?.[0]?.id || null;
    if (!latestRunId || latestRunId === lastLatestPreviewRunId.current) {
      return;
    }
    lastLatestPreviewRunId.current = latestRunId;
    setOpenPreviewId(latestRunId);
  }, [profile.preview_runs]);
  const saveProfile = () => {
    if (!editDisplayName.trim()) {
      return;
    }
    onUpdateProfile(editDisplayName.trim(), editPresenterAlias.trim(), editNotes.trim());
    setEditing(false);
  };

  return (
    <article className="avatar-profile-card">
      <div className="avatar-profile-head">
        <div>
          {editing ? <input className="input" value={editDisplayName} onChange={(event) => setEditDisplayName(event.target.value)} /> : <strong>{profile.display_name}</strong>}
          <div className="muted compact-top">
            {editing ? (
              <input
                className="input"
                value={editPresenterAlias}
                onChange={(event) => setEditPresenterAlias(event.target.value)}
                placeholder="展示别名"
              />
            ) : (
              `${profile.presenter_alias ?? "未设置展示别名"} · ${new Date(profile.created_at).toLocaleString()}`
            )}
          </div>
        </div>
        <div className="toolbar">
          <span className={`status-pill ${profile.training_status === "ready_for_manual_training" ? "done" : "running"}`}>
            {profile.training_status === "ready_for_manual_training" ? "HeyGem 可导入" : "待补素材"}
          </span>
          <button
            className="button ghost"
            type="button"
            disabled={updating || removing}
            onClick={() => setEditing((current) => !current)}
          >
            {editing ? "取消编辑" : "编辑"}
          </button>
          <button className="button ghost" type="button" onClick={onRemove} disabled={removing}>
            删除
          </button>
        </div>
      </div>
      {editing ? (
        <div className="form-stack compact-top">
          <textarea className="input avatar-textarea" value={editNotes} onChange={(event) => setEditNotes(event.target.value)} placeholder="补充说明" />
          <div className="toolbar">
            <button className="button primary" type="button" disabled={updating || !editDisplayName.trim()} onClick={saveProfile}>
              {updating ? "保存中..." : "保存"}
            </button>
            <button className="button ghost" type="button" disabled={updating} onClick={() => setEditing(false)}>
              取消
            </button>
          </div>
        </div>
      ) : (
        <>{profile.notes ? <div className="muted compact-top">{profile.notes}</div> : null}</>
      )}

      <div className="mode-chip-list top-gap">
        <CapabilityChip label="HeyGem 数字人" status={profile.capability_status.heygem_avatar} />
        <CapabilityChip label="声音克隆" status={profile.capability_status.voice_clone} />
        <CapabilityChip label="肖像管理" status={profile.capability_status.portrait_reference} />
        <CapabilityChip label="预览样片" status={profile.capability_status.preview} />
      </div>

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
          previewError={previewError}
        />
        <AvatarRoleColumn
          title="肖像照"
          files={groupedFiles.portrait_photo}
          profileId={profile.id}
          roleKey="portrait_photo"
          onReplace={onReplace}
          replacingFileId={replacingFileId}
          previewError={previewError}
        />
        <AvatarRoleColumn
          title="声音采样"
          files={groupedFiles.voice_sample}
          profileId={profile.id}
          roleKey="voice_sample"
          onReplace={onReplace}
          replacingFileId={replacingFileId}
          previewError={previewError}
        />
      </div>
      <section className="avatar-issue-block top-gap">
        <div className="stat-label">预览样片</div>
        <div className="form-stack compact-top">
          {previewError ? <div className="notice">{previewError}</div> : null}
          <textarea
            className="input avatar-textarea"
            value={previewScript}
            onChange={(event) => setPreviewScript(event.target.value)}
            placeholder="输入一段预览台词"
          />
            <div className="toolbar">
            <button
              className="button primary"
              type="button"
              disabled={previewing}
              onClick={() => {
                const script = previewScript.trim() || `大家好，我是${profile.display_name}。现在这是一条 RoughCut 自动生成的数字人预览样片，主要用于检查音色一致性、口型同步和讲话镜头的整体稳定性。`;
                const hasPrerequisite =
                  profile.capability_status?.heygem_avatar === "ready" && profile.capability_status?.voice_clone === "ready";
                if (!hasPrerequisite) {
                  onPreviewUnavailable(
                    profile.next_action || "需要讲话视频片段和声音采样。"
                  );
                  return;
                }
                setPreviewScript(script);
                onPreview(script);
              }}
            >
              {previewing ? "生成中..." : "生成数字人预览"}
            </button>
          </div>
          {profile.capability_status.preview !== "ready" ? (
            <span className="muted">{profile.next_action || "需要讲话视频片段和声音采样。"}</span>
          ) : null}
          <div className="list-stack">
            {(profile.preview_runs ?? []).map((run) => (
              <div key={run.id} className="avatar-file-card">
                <div className="toolbar">
                  <strong>
                    {run.status === "running" ? "生成中" : run.status === "completed" ? "预览已生成" : "预览失败"}
                  </strong>
                  <div className="toolbar">
                    {run.output_path ? (
                      <button
                        className="button ghost"
                        type="button"
                        onClick={() => setOpenPreviewId((current) => (current === run.id ? null : run.id))}
                      >
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
                    {run.preview_mode === "scripted_tts"
                      ? "脚本 TTS 预览"
                      : run.preview_mode === "source_audio_direct"
                        ? "HeyGem 直连预览"
                        : "原始声音样本回退预览"}
                  </div>
                ) : null}
                {run.fallback_reason ? <div className="muted compact-top">已回退到原始声音样本</div> : null}
                {run.output_path && openPreviewId === run.id ? (
                  <video
                    className="avatar-preview-player compact-top"
                    controls
                    playsInline
                    preload="metadata"
                    src={api.avatarMaterialPreviewUrl(profile.id, run.id)}
                  />
                ) : null}
                {run.duration_sec ? (
                  <div className="muted compact-top">
                    {run.duration_sec.toFixed(1)}s · {run.width}x{run.height}
                  </div>
                ) : null}
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
  previewError: string | null;
}) {
  const accept = roleAcceptByRole[roleKey];

  return (
    <section className="avatar-role-column">
      <div className="stat-label">{title}</div>
      <div className="list-stack compact-top">
        {files.map((file) => (
          <div key={file.id} className="avatar-file-card">
            {(() => {
              const isReplacing = replacingFileId === file.id;
              const fileUrl = buildAvatarMaterialFileUrl(profileId, file.id, file.created_at);
              return (
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
              );
            })()}
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
                时长 {Number(file.probe.duration ?? 0).toFixed(1)}s
                {" · "}
                {Number(file.probe.width ?? 0)}x{Number(file.probe.height ?? 0)}
                {" · "}
                {Number(file.probe.fps ?? 0).toFixed(1)}fps
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
        ))}
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

function CapabilityChip({ label, status }: { label: string; status?: string }) {
  const ready = status === "ready";
  return <span className={`mode-chip ${ready ? "" : "planned"}`}>{label} · {ready ? "已具备" : "未具备"}</span>;
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
    return (
      <video
        key={src}
        className="avatar-preview-player compact-top"
        controls
        playsInline
        preload="metadata"
        src={src}
      />
    );
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
