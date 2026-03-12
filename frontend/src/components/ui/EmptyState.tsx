type EmptyStateProps = {
  message: string;
  tone?: "default" | "error";
};

export function EmptyState({ message, tone = "default" }: EmptyStateProps) {
  return <div className={tone === "error" ? "empty-state error" : "empty-state"}>{message}</div>;
}
