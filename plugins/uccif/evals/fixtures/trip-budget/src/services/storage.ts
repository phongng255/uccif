import type { Entry } from "../domain/entry";

const KEY = "trip-budget:entries";

export function loadEntries(): Entry[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]") as Entry[];
  } catch {
    return [];
  }
}

export function saveEntries(entries: Entry[]): void {
  localStorage.setItem(KEY, JSON.stringify(entries));
}
