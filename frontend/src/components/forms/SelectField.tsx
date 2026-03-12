import type { SelectHTMLAttributes } from "react";

import { classNames } from "../../utils";
import { Field } from "./Field";

type SelectOption = {
  value: string;
  label: string;
};

type SelectFieldProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, "className" | "children"> & {
  label: string;
  options: ReadonlyArray<SelectOption>;
  fieldClassName?: string;
  selectClassName?: string;
};

export function SelectField({ label, options, fieldClassName, selectClassName, ...selectProps }: SelectFieldProps) {
  return (
    <Field label={label} className={fieldClassName}>
      <select {...selectProps} className={classNames("input", selectClassName)}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </Field>
  );
}
