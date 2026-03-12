import type { PackagingLibrary } from "../types";
import { apiPath, request, requestForm } from "./core";

export const packagingApi = {
  getPackaging: () => request<PackagingLibrary>("/packaging"),
  patchPackagingConfig: (body: Record<string, unknown>) =>
    request<PackagingLibrary>("/packaging/config", { method: "PATCH", body: JSON.stringify(body) }),
  uploadPackagingAsset: async (assetType: string, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return requestForm<PackagingLibrary>(`/packaging/assets/${assetType}`, formData);
  },
  deletePackagingAsset: (assetId: string) => request<PackagingLibrary>(`/packaging/assets/${assetId}`, { method: "DELETE" }),
  packagingAssetUrl: (assetId: string) => apiPath(`/packaging/assets/${assetId}/file`),
};
