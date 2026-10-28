import { formatEther } from "viem";

export function formatRtm(value: string | bigint | null | undefined): string {
  if (value === null || value === undefined) return "—";
  try {
    return `${formatEther(BigInt(value))} RTM`;
  } catch {
    return String(value);
  }
}

export function shortAddr(address?: string | null): string {
  if (!address) return "—";
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

export function stateLabel(state: string): string {
  switch (state) {
    case "live":
      return "进行中";
    case "breached":
      return "已攻破";
    case "expired":
      return "守到到期";
    case "faulted":
      return "守方弃权";
    case "settled":
      return "已结算";
    case "retired":
      return "已退役";
    default:
      return state;
  }
}

export function errorText(error: unknown): string {
  if (!error) return "";
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}
