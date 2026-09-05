import type { CaseInboxItem } from "@/lib/api";

export type CaseSortKey = "updated_at" | "occurred_at" | "state" | "incident_type";
export type SortDirection = "ascending" | "descending";

export function sortCaseInboxItems(
  items: readonly CaseInboxItem[],
  key: CaseSortKey,
  direction: SortDirection,
): CaseInboxItem[] {
  const multiplier = direction === "ascending" ? 1 : -1;
  return [...items].sort((left, right) => {
    const comparison = compareSortValues(left[key], right[key]);
    return comparison === 0
      ? left.case_id.localeCompare(right.case_id) * multiplier
      : comparison * multiplier;
  });
}

export function toggleCaseSelection(selectedIds: ReadonlySet<string>, caseId: string): Set<string> {
  const next = new Set(selectedIds);
  if (next.has(caseId)) next.delete(caseId);
  else next.add(caseId);
  return next;
}

function compareSortValues(left: string, right: string): number {
  const leftTime = Date.parse(left);
  const rightTime = Date.parse(right);
  if (Number.isFinite(leftTime) && Number.isFinite(rightTime)) return leftTime - rightTime;
  return left.localeCompare(right);
}
