import type { ReactNode } from "react";

import { classNames } from "../../utils";

type FormActionsProps = {
  children: ReactNode;
  className?: string;
};

export function FormActions({ children, className }: FormActionsProps) {
  return <div className={classNames("toolbar", className)}>{children}</div>;
}
