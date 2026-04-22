import { useEffect } from "react";
import type { ReactNode } from "react";

import { useI18n } from "../../i18n";

type WatchRootEditorModalProps = {
  open: boolean;
  title: string;
  subtitle: string;
  onClose: () => void;
  children: ReactNode;
};

export function WatchRootEditorModal({
  open,
  title,
  subtitle,
  onClose,
  children,
}: WatchRootEditorModalProps) {
  const { t } = useI18n();

  useEffect(() => {
    if (!open) return undefined;

    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };

    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="floating-modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="floating-modal-shell watch-root-editor-modal-shell"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <button
          className="button ghost floating-modal-close"
          type="button"
          onClick={onClose}
          aria-label={t("jobs.modal.closeAria")}
        >
          {t("jobs.modal.close")}
        </button>
        <section className="watch-root-editor-modal-content">
          <header className="watch-root-editor-modal-header">
            <div className="watch-root-editor-modal-kicker">目录编辑器</div>
            <h2>{title}</h2>
            <p>{subtitle}</p>
          </header>
          {children}
        </section>
      </div>
    </div>
  );
}
