import { useEffect } from "react";
import type { ReactNode } from "react";

import { useI18n } from "../../i18n";

type JobCreateModalProps = {
  open: boolean;
  title?: string;
  onClose: () => void;
  children: ReactNode;
};

export function JobCreateModal({
  open,
  title = "创建任务",
  onClose,
  children,
}: JobCreateModalProps) {
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
        className="floating-modal-shell jobs-create-modal-shell"
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
        {children}
      </div>
    </div>
  );
}
