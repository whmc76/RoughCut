import type { ReactNode } from "react";

import { classNames } from "../../utils";

type ListActionsProps = {
  children: ReactNode;
  className?: string;
};

export function ListActions({ children, className }: ListActionsProps) {
  return <div className={classNames("toolbar", className)}>{children}</div>;
}
