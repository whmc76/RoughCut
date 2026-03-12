import { configApi } from "./config";
import { controlApi } from "./control";
import { glossaryApi } from "./glossary";
import { jobsApi } from "./jobs";
import { memoryApi } from "./memory";
import { packagingApi } from "./packaging";
import { watchRootsApi } from "./watchRoots";

export const api = {
  ...jobsApi,
  ...watchRootsApi,
  ...glossaryApi,
  ...packagingApi,
  ...configApi,
  ...controlApi,
  ...memoryApi,
};
