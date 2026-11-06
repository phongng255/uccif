import type { Entry } from "../../domain/entry";
import { renderRow } from "./LedgerRow";

export function renderTable(entries: Entry[]): string {
  return `<table>${entries.map(renderRow).join("")}</table>`;
}
