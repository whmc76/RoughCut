import type { InputHTMLAttributes } from "react";

import { classNames } from "../../utils";

type CheckboxFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  label: string;
  className?: string;
};

export function CheckboxField({ label, className, ...inputProps }: CheckboxFieldProps) {
  return (
    <label className={classNames("checkbox-row", className)}>
      <input {...inputProps} type="checkbox" />
      <span>{label}</span>
    </label>
  );
}
