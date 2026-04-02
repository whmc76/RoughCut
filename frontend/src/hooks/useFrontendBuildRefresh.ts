import { useEffect, useRef } from "react";

type UseFrontendBuildRefreshOptions = {
  intervalMs?: number;
  onUpdate?: () => void;
};

function normalizeAssetPath(src: string) {
  const url = new URL(src, window.location.origin);
  return `${url.pathname}${url.search}`;
}

function getCurrentEntryAsset() {
  const script = document.querySelector<HTMLScriptElement>('script[type="module"][src*="/assets/index-"]');
  const src = script?.getAttribute("src");
  return src ? normalizeAssetPath(src) : null;
}

function getRemoteEntryAsset(html: string) {
  const parsed = new DOMParser().parseFromString(html, "text/html");
  const script = parsed.querySelector<HTMLScriptElement>('script[type="module"][src*="/assets/index-"]');
  const src = script?.getAttribute("src");
  return src ? normalizeAssetPath(src) : null;
}

export function useFrontendBuildRefresh({
  intervalMs = 15_000,
  onUpdate = () => window.location.reload(),
}: UseFrontendBuildRefreshOptions = {}) {
  const currentEntryRef = useRef<string | null>(null);
  const isCheckingRef = useRef(false);
  const hasUpdatedRef = useRef(false);

  useEffect(() => {
    currentEntryRef.current = getCurrentEntryAsset();

    const checkForNewBuild = async () => {
      if (isCheckingRef.current || hasUpdatedRef.current) {
        return;
      }
      const currentEntry = currentEntryRef.current ?? getCurrentEntryAsset();
      if (!currentEntry) {
        return;
      }

      isCheckingRef.current = true;
      try {
        const response = await fetch(window.location.pathname || "/", {
          cache: "no-store",
          headers: {
            "Cache-Control": "no-cache",
            Pragma: "no-cache",
          },
        });
        if (!response.ok) {
          return;
        }

        const nextEntry = getRemoteEntryAsset(await response.text());
        if (nextEntry && nextEntry !== currentEntry) {
          hasUpdatedRef.current = true;
          onUpdate();
        }
      } catch {
        // Ignore transient fetch failures; the next check will retry.
      } finally {
        isCheckingRef.current = false;
      }
    };

    const intervalId = window.setInterval(() => {
      void checkForNewBuild();
    }, intervalMs);

    const handleFocus = () => {
      void checkForNewBuild();
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        void checkForNewBuild();
      }
    };

    void checkForNewBuild();
    window.addEventListener("focus", handleFocus);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("focus", handleFocus);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [intervalMs, onUpdate]);
}
