import { defineStore } from "pinia";
import { makeEntry, type Entry } from "../domain/entry";
import { computeLedger, totalsByDay } from "../domain/ledger";
import { loadEntries, saveEntries } from "../services/storage";

export const useLedgerStore = defineStore("ledger", {
  state: () => ({ entries: loadEntries() as Entry[] }),
  getters: {
    totals: (s) => computeLedger(s.entries),
    byDay: (s) => totalsByDay(s.entries),
    expenses: (s) => s.entries.filter((e) => e.kind !== "Thu"),
  },
  actions: {
    add(partial: Omit<Entry, "id">) {
      this.entries.push(makeEntry(partial));
      saveEntries(this.entries);
    },
    remove(id: string) {
      this.entries = this.entries.filter((e) => e.id !== id);
      saveEntries(this.entries);
    },
  },
});
