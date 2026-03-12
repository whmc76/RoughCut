import type { ServiceStatus } from "../types";
import { request } from "./core";

export const controlApi = {
  getControlStatus: () => request<ServiceStatus>("/control/status"),
  stopServices: (stopDocker: boolean) =>
    request<{ status: string; message: string }>("/control/stop", { method: "POST", body: JSON.stringify({ stop_docker: stopDocker }) }),
};
