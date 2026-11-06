export type EntryKind = "Thu" | "Chi" | "Chuyển";

export interface Entry {
  id: string;
  kind: EntryKind;
  amount: number; // VND, integer
  payer: string;
  receiver?: string; // only for "Chuyển"
  note: string;
  day: 1 | 2 | 3;
}

export function makeEntry(partial: Omit<Entry, "id">): Entry {
  return { id: Math.random().toString(36).slice(2), ...partial };
}
