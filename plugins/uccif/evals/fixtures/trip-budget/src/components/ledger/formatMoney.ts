export function formatMoney(amount: number, currency: "VND" | "THB" = "VND"): string {
  return new Intl.NumberFormat("vi-VN", { style: "currency", currency }).format(amount);
}
