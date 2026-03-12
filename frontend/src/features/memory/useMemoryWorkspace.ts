import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../../api";

export function useMemoryWorkspace() {
  const [channelProfile, setChannelProfile] = useState("");
  const stats = useQuery({
    queryKey: ["memory-stats", channelProfile],
    queryFn: () => api.getMemoryStats(channelProfile || undefined),
  });

  return {
    channelProfile,
    setChannelProfile,
    stats,
  };
}
