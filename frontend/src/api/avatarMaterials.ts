import type { AvatarMaterialLibrary } from "../types";
import { apiPath, request, requestForm } from "./core";

export const avatarMaterialsApi = {
  getAvatarMaterials: () => request<AvatarMaterialLibrary>("/avatar-materials"),
  uploadAvatarMaterialProfile: (
    displayName: string,
    presenterAlias: string,
    notes: string,
    speakingVideos: File[],
    portraitPhotos: File[],
    voiceSamples: File[],
  ) => {
    const formData = new FormData();
    formData.append("display_name", displayName);
    if (presenterAlias.trim()) formData.append("presenter_alias", presenterAlias.trim());
    if (notes.trim()) formData.append("notes", notes.trim());
    speakingVideos.forEach((file) => formData.append("speaking_videos", file));
    portraitPhotos.forEach((file) => formData.append("portrait_photos", file));
    voiceSamples.forEach((file) => formData.append("voice_samples", file));
    return requestForm<AvatarMaterialLibrary>("/avatar-materials/profiles", formData);
  },
  deleteAvatarMaterialProfile: (profileId: string) =>
    request<AvatarMaterialLibrary>(`/avatar-materials/profiles/${profileId}`, { method: "DELETE" }),
  generateAvatarMaterialPreview: (profileId: string, script: string) =>
    request<AvatarMaterialLibrary>(`/avatar-materials/profiles/${profileId}/preview`, {
      method: "POST",
      body: JSON.stringify({ script }),
      headers: { "Content-Type": "application/json" },
    }),
  replaceAvatarMaterialFile: (profileId: string, fileId: string, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return requestForm<AvatarMaterialLibrary>(`/avatar-materials/profiles/${profileId}/files/${fileId}`, formData, {
      method: "PUT",
    });
  },
  updateAvatarMaterialProfile: (profileId: string, displayName: string, presenterAlias: string, notes: string) =>
    request<AvatarMaterialLibrary>(`/avatar-materials/profiles/${profileId}`, {
      method: "PATCH",
      body: JSON.stringify({
        display_name: displayName,
        presenter_alias: presenterAlias,
        notes,
      }),
    }),
  avatarMaterialFileUrl: (profileId: string, fileId: string) =>
    apiPath(`/avatar-materials/profiles/${profileId}/files/${fileId}`),
  avatarMaterialPreviewUrl: (profileId: string, previewId: string) =>
    apiPath(`/avatar-materials/profiles/${profileId}/preview-runs/${previewId}/file`),
};
