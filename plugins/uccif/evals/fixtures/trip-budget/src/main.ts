import { createApp } from "vue";
import { createPinia } from "pinia";
import { useLedgerStore } from "./stores/ledgerStore";
import { renderTable } from "./components/ledger/LedgerTable";
import { renderSummary } from "./components/ledger/LedgerSummary";

const app = createApp({});
app.use(createPinia());
app.mount("#app");

const ledger = useLedgerStore();
document.querySelector("#table")!.innerHTML = renderTable(ledger.entries);
document.querySelector("#summary")!.innerHTML = renderSummary(ledger.entries);
