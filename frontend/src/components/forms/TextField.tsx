import type { InputHTMLAttributes } from "react";

import { classNames } from "../../utils";
import { Field } from "./Field";

type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "className"> & {
  label: string;
  fieldClassName?: string;
  inputClassName?: string;
};

export function TextField({ label, fieldClassName, inputClassName, ...inputProps }: TextFieldProps) {
  return (
    <Field label={label} className={fieldClassName}>
      <input {...inputProps} className={classNames("input", inputClassName)} />
    </Field>
  );
}
