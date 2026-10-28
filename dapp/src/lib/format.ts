import { formatEther, parseEther } from "viem";
import { ApiClientError } from "./api";

export function toBigInt(value: string | bigint | number | null | undefined): bigint | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "bigint") return value;
  try {
    return BigInt(value);
  } catch {
    return null;
  }
}

export function formatRtm(
  value: string | bigint | number | null | undefined,
  options: { exact?: boolean; maxFraction?: number } = {},
): string {
  const amount = toBigInt(value);
  if (amount === null) return "—";
  const negative = amount < 0n;
  const raw = formatEther(negative ? -amount : amount);
  const [whole, fraction = ""] = raw.split(".");
  const limit = options.exact ? fraction.length : (options.maxFraction ?? 3);
  const trimmed = fraction.slice(0, limit).replace(/0+$/, "");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const body = trimmed ? `${grouped}.${trimmed}` : grouped;
  return negative ? `-${body}` : body;
}

export function formatRtmUnit(
  value: string | bigint | number | null | undefined,
  options?: { exact?: boolean; maxFraction?: number },
): string {
  const text = formatRtm(value, options);
  return text === "—" ? text : `${text} RTM`;
}

export function formatInt(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return Math.round(value).toLocaleString("zh-CN");
}

export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("zh-CN", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

export function shortAddr(address?: string | null, head = 6, tail = 4): string {
  if (!address) return "—";
  if (address.length <= head + tail + 1) return address;
  return `${address.slice(0, head)}…${address.slice(-tail)}`;
}

export const shortHash = shortAddr;

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function stateLabel(state: string): string {
  switch (state) {
    case "live":
      return "进行中";
    case "breached":
      return "已攻破";
    case "expired":
      return "到期结束";
    case "faulted":
      return "守方弃权";
    case "settled":
      return "已结算";
    case "retired":
      return "已退役";
    case "none":
      return "未开始";
    default:
      return state;
  }
}

export type Tone = "live" | "success" | "danger" | "warning" | "neutral" | "accent";

export function stateTone(state: string): Tone {
  switch (state) {
    case "live":
      return "live";
    case "settled":
    case "expired":
      return "success";
    case "breached":
      return "danger";
    case "faulted":
      return "warning";
    default:
      return "neutral";
  }
}

export function outcomeLabel(outcome: string): string {
  switch (outcome) {
    case "settled":
      return "攻破";
    case "retired":
      return "未攻破退役";
    case "breached":
      return "已攻破";
    case "expired":
      return "到期结束";
    case "faulted":
      return "守方弃权";
    default:
      return outcome;
  }
}

export function parseRtmInput(value: string): bigint | null {
  const trimmed = value.trim();
  if (!/^\d+(?:\.\d{0,18})?$/.test(trimmed)) return null;
  try {
    return parseEther(trimmed);
  } catch {
    return null;
  }
}

export function formatCountdown(milliseconds: number): string {
  if (!Number.isFinite(milliseconds) || milliseconds <= 0) return "已结束";
  const total = Math.floor(milliseconds / 1000);
  const days = Math.floor(total / 86_400);
  const hours = Math.floor((total % 86_400) / 3_600);
  const minutes = Math.floor((total % 3_600) / 60);
  const seconds = total % 60;
  if (days > 0) return `${days}天 ${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))} 秒`;
  if (seconds < 3_600) return `${Math.round(seconds / 60)} 分钟`;
  if (seconds < 86_400) {
    const hours = Math.floor(seconds / 3_600);
    const minutes = Math.round((seconds % 3_600) / 60);
    return minutes ? `${hours} 小时 ${minutes} 分` : `${hours} 小时`;
  }
  const days = Math.floor(seconds / 86_400);
  const hours = Math.round((seconds % 86_400) / 3_600);
  return hours ? `${days} 天 ${hours} 小时` : `${days} 天`;
}

export function formatDateTime(timestamp: number | null | undefined): string {
  if (!timestamp) return "—";
  return new Date(timestamp * 1000).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function timeAgo(timestamp: number | null | undefined): string {
  if (!timestamp) return "—";
  const delta = Date.now() / 1000 - timestamp;
  if (delta < 5) return "刚刚";
  if (delta < 60) return `${Math.floor(delta)} 秒前`;
  if (delta < 3_600) return `${Math.floor(delta / 60)} 分钟前`;
  if (delta < 86_400) return `${Math.floor(delta / 3_600)} 小时前`;
  return `${Math.floor(delta / 86_400)} 天前`;
}

export function explorerTxUrl(hash: string | null | undefined): string | null {
  const base = import.meta.env.VITE_EXPLORER_URL as string | undefined;
  if (!base || !hash) return null;
  return `${base.replace(/\/+$/, "")}/tx/${hash}`;
}

export function explorerAddressUrl(address: string | null | undefined): string | null {
  const base = import.meta.env.VITE_EXPLORER_URL as string | undefined;
  if (!base || !address) return null;
  return `${base.replace(/\/+$/, "")}/address/${address}`;
}

export function isZeroAddress(address?: string | null): boolean {
  return !address || /^0x0{40}$/i.test(address);
}

export function isZeroHash(hash?: string | null): boolean {
  return !hash || /^0x0{64}$/i.test(hash);
}

const API_MESSAGES: Array<[string, string]> = [
  ["invalid API token", "平台 API 鉴权失败，请检查服务端代理配置。"],
  ["defender is already registered", "该钱包已完成守方注册。"],
  ["defender is not registered", "该钱包尚未完成守方注册。"],
  ["defender must approve Arena first", "需要先授权 Arena 使用质押 RTM。"],
  ["this BYOK registration already created a contest", "这次注册已经创建过一场比赛。"],
  ["this is a mining contest", "这是一场挖矿赛，请到挖矿中心操作。"],
  ["this is not a mining contest", "这不是挖矿赛，请到竞技场操作。"],
  ["contest is not live", "比赛已不在进行中。"],
  ["contest has ended", "比赛已经结束。"],
  ["contest is not indexed", "链上事件尚未同步，请等几秒后重试。"],
  ["contest not found or chain unavailable", "找不到比赛，或链 RPC 暂时不可用。"],
  ["sender is not a joined attacker", "当前钱包还没有加入这场比赛的攻方。"],
  ["mining join requires data consent", "挖矿赛必须同意数据留存条款。"],
  ["this attack payment was already processed", "这笔攻击付款已经处理过，请不要重复发送。"],
  ["payment is not indexed yet", "付款尚未被索引，请稍后重试。"],
  ["dataset is already published", "数据集已经发布。"],
  ["dataset is not published", "数据集尚未发布，请等待运营发布。"],
  ["only the defender may buy this dataset", "只有该场守方可以购买这份数据。"],
  ["attacker did not consent to data sales", "该攻方没有同意出售数据。"],
  ["already bought", "这份数据已经购买过。"],
  ["download not found or expired", "下载链接已过期，请重新发起交付。"],
  ["defense hash is retired", "该防守版本已经退役，不能再次开赛。"],
  ["defense hash already has an active contest", "该防守版本已有进行中的挖矿赛。"],
  ["active mining contest cap reached", "活跃挖矿赛已达到平台上限（3 场）。"],
  ["platform model key is not configured", "平台未配置挖矿模型 Key。"],
  ["PLATFORM_MODEL_PROVIDER", "平台未配置挖矿模型 provider。"],
  ["custody unavailable", "平台托管服务不可用，请联系运营。"],
  ["faucet signer is not configured", "水龙头签名服务未配置。"],
  ["captcha", "验证码校验失败，请刷新后重试。"],
];

function translateApiMessage(message: string): string {
  const lower = message.toLowerCase();
  for (const [needle, chinese] of API_MESSAGES) {
    if (lower.includes(needle.toLowerCase())) return chinese;
  }
  return message;
}

function statusMessage(status: number): string {
  if (status === 401) return "平台鉴权失败，请检查代理配置。";
  if (status === 403) return "没有权限执行这个操作。";
  if (status === 404) return "没有找到对应记录，可能尚未同步。";
  if (status === 409) return "当前状态不允许这个操作，请刷新后重试。";
  if (status === 422) return "提交的内容不符合要求，请检查后重试。";
  if (status === 429) return "请求过于频繁，请稍后再试。";
  if (status >= 500) return "平台服务暂时不可用，请稍后重试。";
  return `请求失败（HTTP ${status}）`;
}

function detailText(detail: unknown, depth = 0): string | null {
  if (depth > 3) return null;
  if (!detail) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          const msg = (item as { msg?: unknown }).msg;
          return typeof msg === "string" ? msg : null;
        }
        return detailText(item, depth + 1);
      })
      .filter((value): value is string => Boolean(value));
    return parts.length ? parts.join("；") : null;
  }
  if (typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    if (record.detail !== undefined) return detailText(record.detail, depth + 1);
    if (typeof record.message === "string") return record.message;
    if (typeof record.error === "string") return record.error;
    if (record.qualification === "failed") return "资格测试未通过，请检查模型与 API Key。";
    if (typeof record.recovery === "string") {
      return `操作失败（恢复状态：${record.recovery}）。`;
    }
  }
  return null;
}

export function errorText(error: unknown): string {
  if (!error) return "";
  if (error instanceof ApiClientError) {
    const detail = detailText(error.detail);
    return detail ? translateApiMessage(detail) : statusMessage(error.status);
  }
  if (error instanceof Error) {
    const anyError = error as Error & { shortMessage?: string; details?: string; code?: number };
    if (anyError.code === 4001) return "你在钱包中取消了这次操作。";
    const raw = anyError.shortMessage || anyError.message || "";
    if (/user rejected|denied transaction|rejected the request/i.test(raw)) {
      return "你在钱包中取消了这次操作。";
    }
    if (/insufficient funds/i.test(raw)) return "钱包余额不足以支付这笔交易。";
    if (/chain mismatch|wrong network|does not match the target chain/i.test(raw)) {
      return "钱包网络不正确，请切换到 RTM Testnet（48850）。";
    }
    if (/nonce/i.test(raw)) return "交易 nonce 冲突，请刷新后重试。";
    return raw || "操作失败。";
  }
  if (typeof error === "object") {
    const detail = detailText(error);
    if (detail) return translateApiMessage(detail);
  }
  return String(error);
}
