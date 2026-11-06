import { defineStore } from "pinia";
import { useLedgerStore } from "./ledgerStore";
import { sharePerMember, balances } from "../domain/split";

export const useTripStore = defineStore("trip", {
  state: () => ({ name: "Thailand 3N2D", members: ["An", "Bình", "Chi"] as string[] }),
  getters: {
    share(): number {
      return sharePerMember(useLedgerStore().entries, this.members);
    },
    memberBalances(): Record<string, number> {
      return balances(useLedgerStore().entries, this.members);
    },
  },
});
