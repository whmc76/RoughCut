import type { ReactNode } from "react";

type FieldProps = {
  label: ReactNode;
  children: ReactNode;
  className?: string;
};

export function Field({ label, children, className }: FieldProps) {
  return (
    <label className={className}>
      <span>{label}</span>
      {children}
    </label>
  );
}
