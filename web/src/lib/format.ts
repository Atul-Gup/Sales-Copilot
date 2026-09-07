export function formatPaise(paise: number | null): string {
  if (paise === null) return "Not sourced";
  return `₹${(paise / 100).toLocaleString("en-IN")}`;
}
