import type { Entry } from "../../domain/entry";
import { computeLedger } from "../../domain/ledger";
import { formatMoney } from "./formatMoney";

export function renderSummary(entries: Entry[]): string {
  const t = computeLedger(entries);
  const spentCount = entries.filter((e) => e.kind !== "Thu").length;
  return `<div>Thu ${formatMoney(t.income)} · Chi ${formatMoney(t.expense)} (${spentCount} khoản) · Còn ${formatMoney(t.balance)}</div>`;
}
