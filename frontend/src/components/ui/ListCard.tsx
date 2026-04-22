import type { ReactNode } from "react";

import { classNames } from "../../utils";

type ListCardProps = {
  children: ReactNode;
  className?: string;
  column?: boolean;
  selectable?: boolean;
  selected?: boolean;
  as?: "article" | "button";
  onClick?: () => void;
};

export function ListCard({ children, className, column = false, selectable = false, selected = false, as = "article", onClick }: ListCardProps) {
  const classes = classNames("list-card", column && "column", selectable && "selectable", selected && "selected", className);

  if (as === "button") {
    return (
      <button className={classes} type="button" onClick={onClick}>
        {children}
      </button>
    );
  }

  return (
    <article className={classes} onClick={onClick}>
      {children}
    </article>
  );
}
