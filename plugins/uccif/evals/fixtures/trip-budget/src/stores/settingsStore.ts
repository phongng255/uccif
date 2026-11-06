import { defineStore } from "pinia";

export const useSettingsStore = defineStore("settings", {
  state: () => ({ currency: "VND" as "VND" | "THB", showCents: false }),
  actions: {
    toggleCurrency() {
      this.currency = this.currency === "VND" ? "THB" : "VND";
    },
  },
});
