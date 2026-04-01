import { useEffect } from "react";
import type { ReactNode } from "react";
import { useI18n } from "../../i18n";

type JobDetailModalProps = {
  open: boolean;
  title?: string;
  onClose: () => void;
  children: ReactNode;
};

export function JobDetailModal({ open, title, onClose, children }: JobDetailModalProps) {
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
    <div className="detail-modal-backdrop" onClick={onClose} role="presentation" style={{ left: "var(--sidebar-width)" }}>
      <div className="detail-modal-shell" role="dialog" aria-modal="true" aria-label={title || t("jobs.modal.title")} onClick={(event) => event.stopPropagation()}>
        <button className="button ghost detail-modal-close" type="button" onClick={onClose} aria-label={t("jobs.modal.closeAria")}>
          {t("jobs.modal.close")}
        </button>
        {children}
      </div>
    </div>
  );
}
