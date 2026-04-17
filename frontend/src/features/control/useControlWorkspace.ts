import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";

export function useControlWorkspace() {
  const queryClient = useQueryClient();
  const [stopDocker, setStopDocker] = useState(false);
  const [reviewNotificationJobIdFilter, setReviewNotificationJobIdFilter] = useState("");
  const status = useQuery({ queryKey: ["control-status"], queryFn: api.getControlStatus, refetchInterval: 10_000 });
  const healthDetail = useQuery({ queryKey: ["health-detail"], queryFn: api.getHealthDetail, refetchInterval: 10_000 });
  const reviewNotifications = useQuery({
    queryKey: ["control-review-notifications", reviewNotificationJobIdFilter],
    queryFn: () => api.getReviewNotifications({ jobId: reviewNotificationJobIdFilter.trim() || undefined, limit: 50 }),
    refetchInterval: 10_000,
  });
  const requeueReviewNotification = useMutation({
    mutationFn: (notificationId: string) => api.requeueReviewNotification(notificationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["control-status"] });
      queryClient.invalidateQueries({ queryKey: ["control-review-notifications"] });
    },
  });
  const requeueReviewNotifications = useMutation({
    mutationFn: (notificationIds: string[]) => api.requeueReviewNotifications(notificationIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["control-status"] });
      queryClient.invalidateQueries({ queryKey: ["control-review-notifications"] });
    },
  });
  const dropReviewNotification = useMutation({
    mutationFn: (notificationId: string) => api.dropReviewNotification(notificationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["control-status"] });
      queryClient.invalidateQueries({ queryKey: ["control-review-notifications"] });
    },
  });
  const dropReviewNotifications = useMutation({
    mutationFn: (notificationIds: string[]) => api.dropReviewNotifications(notificationIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["control-status"] });
      queryClient.invalidateQueries({ queryKey: ["control-review-notifications"] });
    },
  });
  const stop = useMutation({
    mutationFn: () => api.stopServices(stopDocker),
  });

  return {
    stopDocker,
    setStopDocker,
    reviewNotificationJobIdFilter,
    setReviewNotificationJobIdFilter,
    status,
    healthDetail,
    reviewNotifications,
    requeueReviewNotification,
    requeueReviewNotifications,
    dropReviewNotification,
    dropReviewNotifications,
    stop,
  };
}
