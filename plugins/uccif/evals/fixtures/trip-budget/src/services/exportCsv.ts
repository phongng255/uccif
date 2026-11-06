import type { Entry } from "../domain/entry";

export function toCsv(entries: Entry[]): string {
  const rows = entries.map((e) => {
    const sign = e.kind === "Thu" ? "+" : "-";
    return [e.day, e.kind, sign + e.amount, e.payer, e.note].join(",");
  });
  return ["day,kind,amount,payer,note", ...rows].join("\n");
}
