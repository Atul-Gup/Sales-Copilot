import type { SourceRef } from "@/lib/api";

// docs/PRD.md / GUARDRAILS.md: sources visible on every row, not hidden
// behind a tooltip (T7.2). This renders inline, always visible — a tooltip
// only reveals its content on hover/focus, which is exactly what's ruled
// out. `document_title` is shown when present since it's the more specific
// citation a consultant would actually want to point to; the publisher
// name is the fallback every source has.
export function SourceLink({ source }: { source: SourceRef }) {
  const label = source.document_title ?? source.publisher;
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noreferrer"
      className="inline-block text-xs text-blue-600 underline decoration-dotted underline-offset-2 dark:text-blue-400"
    >
      Source: {label}
    </a>
  );
}
