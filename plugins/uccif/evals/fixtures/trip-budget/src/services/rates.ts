const BASE = import.meta.env?.RATES_API_URL ?? "https://api.example-rates.test/v1";

export async function thbToVnd(amountThb: number): Promise<number> {
  const res = await fetch(`${BASE}/latest?from=THB&to=VND`);
  if (!res.ok) throw new Error(`rates: HTTP ${res.status}`);
  const { rate } = (await res.json()) as { rate: number };
  return Math.round(amountThb * rate);
}
