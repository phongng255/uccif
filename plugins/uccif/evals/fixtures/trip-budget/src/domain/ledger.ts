import type { Entry } from "./entry";

export interface LedgerTotals {
  income: number;
  expense: number;
  balance: number;
}

export function computeLedger(entries: Entry[]): LedgerTotals {
  let income = 0;
  let expense = 0;
  for (const e of entries) {
    if (e.kind === "Thu") income += e.amount;
    else expense += e.amount;
  }
  return { income, expense, balance: income - expense };
}

export function totalsByDay(entries: Entry[]): Record<number, LedgerTotals> {
  const out: Record<number, LedgerTotals> = {};
  for (const day of [1, 2, 3]) {
    out[day] = computeLedger(entries.filter((e) => e.day === day));
  }
  return out;
}
