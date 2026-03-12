import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { api } from "../../api";

export function useControlWorkspace() {
  const [stopDocker, setStopDocker] = useState(false);
  const status = useQuery({ queryKey: ["control-status"], queryFn: api.getControlStatus, refetchInterval: 10_000 });
  const stop = useMutation({
    mutationFn: () => api.stopServices(stopDocker),
  });

  return {
    stopDocker,
    setStopDocker,
    status,
    stop,
  };
}
