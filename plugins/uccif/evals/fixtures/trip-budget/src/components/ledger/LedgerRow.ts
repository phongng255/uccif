import type { Entry } from "../../domain/entry";
import { formatMoney } from "./formatMoney";

export function renderRow(e: Entry): string {
  const cls = e.kind === "Thu" ? "in" : "out";
  return `<tr class="${cls}"><td>${e.day}</td><td>${e.kind}</td><td>${formatMoney(e.amount)}</td><td>${e.note}</td></tr>`;
}
