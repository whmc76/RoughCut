import { avatarMaterialsApi } from "./avatarMaterials";
import { configApi } from "./config";
import { controlApi } from "./control";
import { creatorAssetsApi } from "./creatorAssets";
import { glossaryApi } from "./glossary";
import { intelligentCopyApi } from "./intelligentCopy";
import { jobsApi } from "./jobs";
import { memoryApi } from "./memory";
import { packagingApi } from "./packaging";
import { toolsApi } from "./tools";
import { watchRootsApi } from "./watchRoots";

export const api = {
  ...avatarMaterialsApi,
  ...creatorAssetsApi,
  ...jobsApi,
  ...watchRootsApi,
  ...glossaryApi,
  ...intelligentCopyApi,
  ...packagingApi,
  ...configApi,
  ...controlApi,
  ...memoryApi,
  ...toolsApi,
};
