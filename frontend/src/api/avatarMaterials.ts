import type { AvatarCreatorProfile, AvatarMaterialLibrary, AvatarPublicationProfileList } from "../types";
import { apiPath, request, requestForm } from "./core";

export const avatarMaterialsApi = {
  getAvatarMaterials: () => request<AvatarMaterialLibrary>("/avatar-materials"),
  getAvatarPublicationProfiles: () => request<AvatarPublicationProfileList>("/avatar-materials/publication-profiles"),
  matchPublicationBrowserLogin: (profileId: string, browser: string, platforms: string[]) =>
    request<AvatarPublicationProfileList>(`/avatar-materials/publication-profiles/${encodeURIComponent(profileId)}/match-browser-login`, {
      method: "POST",
      body: JSON.stringify({ browser, platforms }),
    }),
  uploadAvatarMaterialProfile: (
    displayName: string,
    presenterAlias: string,
    notes: string,
    creatorProfile: AvatarCreatorProfile,
    speakingVideos: File[],
    portraitPhotos: File[],
    voiceSamples: File[],
  ) => {
    const formData = new FormData();
    formData.append("display_name", displayName);
    if (presenterAlias.trim()) formData.append("presenter_alias", presenterAlias.trim());
    if (notes.trim()) formData.append("notes", notes.trim());
    formData.append("creator_profile_json", JSON.stringify(creatorProfile));
    speakingVideos.forEach((file) => formData.append("speaking_videos", file));
    portraitPhotos.forEach((file) => formData.append("portrait_photos", file));
    voiceSamples.forEach((file) => formData.append("voice_samples", file));
    return requestForm<AvatarMaterialLibrary>("/avatar-materials/profiles", formData);
  },
  deleteAvatarMaterialProfile: (profileId: string) =>
    request<AvatarMaterialLibrary>(`/avatar-materials/profiles/${profileId}`, { method: "DELETE" }),
  deleteAvatarMaterialFile: (profileId: string, fileId: string) =>
    request<AvatarMaterialLibrary>(`/avatar-materials/profiles/${profileId}/files/${fileId}`, { method: "DELETE" }),
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
  updateAvatarMaterialProfile: (
    profileId: string,
    displayName: string,
    presenterAlias: string,
    notes: string,
    creatorProfile: AvatarCreatorProfile,
  ) =>
    request<AvatarMaterialLibrary>(`/avatar-materials/profiles/${profileId}`, {
      method: "PATCH",
      body: JSON.stringify({
        display_name: displayName,
        presenter_alias: presenterAlias,
        notes,
        creator_profile: creatorProfile,
      }),
    }),
  avatarMaterialFileUrl: (profileId: string, fileId: string) =>
    apiPath(`/avatar-materials/profiles/${profileId}/files/${fileId}`),
  avatarMaterialPreviewUrl: (profileId: string, previewId: string) =>
    apiPath(`/avatar-materials/profiles/${profileId}/preview-runs/${previewId}/file`),
};
