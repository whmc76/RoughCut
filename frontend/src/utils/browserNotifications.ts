type BrowserNotificationPayload = {
  title: string;
  body: string;
  tag: string;
};

const DEFAULT_ICON = "/roughcut-mark.svg";
const permissionState = { value: "" as NotificationPermission | "" };
let permissionRequest: Promise<boolean> | null = null;

function supportsBrowserNotification(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

function normalizePermissionState(): NotificationPermission | null {
  if (!supportsBrowserNotification()) {
    return null;
  }
  return (permissionState.value || Notification.permission) as NotificationPermission;
}

function requestPermissionOnce(): Promise<boolean> {
  if (!supportsBrowserNotification() || permissionRequest) {
    return permissionRequest ?? Promise.resolve(false);
  }

  permissionRequest = Notification.requestPermission().then((nextPermission) => {
    permissionState.value = nextPermission;
    return nextPermission === "granted";
  }).finally(() => {
    permissionRequest = null;
  });
  return permissionRequest;
}

export async function maybeNotify({
  title,
  body,
  tag,
}: BrowserNotificationPayload): Promise<void> {
  if (!supportsBrowserNotification()) return;

  const currentPermission = normalizePermissionState();
  if (currentPermission === "denied") return;

  const hasPermission = currentPermission === "granted" || await requestPermissionOnce();
  if (!hasPermission) return;

  try {
    new Notification(title, {
      body,
      tag,
      icon: DEFAULT_ICON,
    });
  } catch {
    // Ignore notification failures to avoid crashing the interface.
  }
}
