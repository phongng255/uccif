import { describe, expect, it } from "vitest";
import { sharePerMember } from "../src/domain/split";

describe("sharePerMember", () => {
  it("splits spending evenly", () => {
    expect(sharePerMember([{ id: "1", kind: "Chi", amount: 900, payer: "An", note: "", day: 1 }], ["An", "Bình", "Chi"])).toBe(300);
  });
});
