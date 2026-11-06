import { describe, expect, it } from "vitest";
import { computeLedger } from "../src/domain/ledger";
import type { Entry } from "../src/domain/entry";

const e = (kind: Entry["kind"], amount: number): Entry => ({ id: kind + amount, kind, amount, payer: "An", note: "", day: 1 });

describe("computeLedger", () => {
  it("adds income and expense", () => {
    expect(computeLedger([e("Thu", 1000), e("Chi", 300)])).toEqual({ income: 1000, expense: 300, balance: 700 });
  });
});
