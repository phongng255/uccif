import type { Entry } from "./entry";

export function sharePerMember(entries: Entry[], members: string[]): number {
  const spent = entries.filter((e) => e.kind !== "Thu").reduce((s, e) => s + e.amount, 0);
  return members.length ? Math.round(spent / members.length) : 0;
}

export function balances(entries: Entry[], members: string[]): Record<string, number> {
  const out: Record<string, number> = Object.fromEntries(members.map((m) => [m, 0]));
  for (const e of entries) {
    if (e.kind === "Thu") out[e.payer] += e.amount;
    else if (e.kind === "Chuyển" && e.receiver) {
      out[e.payer] += e.amount;
      out[e.receiver] -= e.amount;
    }
  }
  return out;
}
