import { formatEther, parseEther } from "viem";
import { ApiClientError } from "./api";
import { getLang, locale as activeLocale } from "./i18n";

function msg(en: string, zh: string): string {
  return getLang() === "en" ? en : zh;
}

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
  return text === "—" ? text : `${text} tRTM`;
}

export function formatInt(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return Math.round(value).toLocaleString(activeLocale());
}

export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(activeLocale(), {
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
      return msg("Live", "进行中");
    case "breached":
      return msg("Breached", "已攻破");
    case "expired":
      return msg("Expired", "到期结束");
    case "faulted":
      return msg("Defender fault", "守方弃权");
    case "settled":
      return msg("Settled", "已结算");
    case "retired":
      return msg("Retired", "已退役");
    case "none":
      return msg("Not started", "未开始");
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
      return msg("Breached", "攻破");
    case "retired":
      return msg("Retired unbroken", "未攻破退役");
    case "breached":
      return msg("Breached", "已攻破");
    case "expired":
      return msg("Expired", "到期结束");
    case "faulted":
      return msg("Defender fault", "守方弃权");
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
  if (!Number.isFinite(milliseconds) || milliseconds <= 0) return msg("Ended", "已结束");
  const total = Math.floor(milliseconds / 1000);
  const days = Math.floor(total / 86_400);
  const hours = Math.floor((total % 86_400) / 3_600);
  const minutes = Math.floor((total % 3_600) / 60);
  const seconds = total % 60;
  if (days > 0) {
    const clock = `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
    return getLang() === "en" ? `${days}d ${clock}` : `${days}天 ${clock}`;
  }
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  if (seconds < 60) {
    const value = Math.max(0, Math.round(seconds));
    return getLang() === "en" ? `${value}s` : `${value} 秒`;
  }
  if (seconds < 3_600) {
    const value = Math.round(seconds / 60);
    return getLang() === "en" ? `${value} min` : `${value} 分钟`;
  }
  if (seconds < 86_400) {
    const hours = Math.floor(seconds / 3_600);
    const minutes = Math.round((seconds % 3_600) / 60);
    if (getLang() === "en") return minutes ? `${hours} h ${minutes} min` : `${hours} h`;
    return minutes ? `${hours} 小时 ${minutes} 分` : `${hours} 小时`;
  }
  const days = Math.floor(seconds / 86_400);
  const hours = Math.round((seconds % 86_400) / 3_600);
  if (getLang() === "en") return hours ? `${days} d ${hours} h` : `${days} d`;
  return hours ? `${days} 天 ${hours} 小时` : `${days} 天`;
}

export function formatDateTime(timestamp: number | null | undefined): string {
  if (!timestamp) return "—";
  return new Date(timestamp * 1000).toLocaleString(activeLocale(), {
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
  const english = getLang() === "en";
  if (delta < 5) return english ? "just now" : "刚刚";
  if (delta < 60) return english ? `${Math.floor(delta)}s ago` : `${Math.floor(delta)} 秒前`;
  if (delta < 3_600) return english ? `${Math.floor(delta / 60)}m ago` : `${Math.floor(delta / 60)} 分钟前`;
  if (delta < 86_400) return english ? `${Math.floor(delta / 3_600)}h ago` : `${Math.floor(delta / 3_600)} 小时前`;
  return english ? `${Math.floor(delta / 86_400)}d ago` : `${Math.floor(delta / 86_400)} 天前`;
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

const API_MESSAGES: Array<[string, string, string]> = [
  ["invalid API token", "Platform API authentication failed. Check the server proxy configuration.", "平台 API 鉴权失败，请检查服务端代理配置。"],
  ["defender is already registered", "This wallet is already registered as a defender.", "该钱包已完成守方注册。"],
  ["defender is not registered", "This wallet has not completed defender registration.", "该钱包尚未完成守方注册。"],
  ["defender must approve Arena first", "Approve the Arena contract to use your staked tRTM first.", "需要先授权 Arena 使用质押 tRTM。"],
  ["this BYOK registration already created a contest", "This registration has already created a contest.", "这次注册已经创建过一场比赛。"],
  ["this is a mining contest", "This is a mining contest. Use the Mine page.", "这是一场挖矿赛，请到挖矿中心操作。"],
  ["this is not a mining contest", "This is not a mining contest. Use the Arena page.", "这不是挖矿赛，请到竞技场操作。"],
  ["contest is not live", "This contest is no longer live.", "比赛已不在进行中。"],
  ["contest has ended", "This contest has ended.", "比赛已经结束。"],
  ["contest is not indexed", "The on-chain event is not indexed yet. Wait a few seconds and retry.", "链上事件尚未同步，请等几秒后重试。"],
  ["contest not found or chain unavailable", "Contest not found, or the chain RPC is temporarily unavailable.", "找不到比赛，或链 RPC 暂时不可用。"],
  ["sender is not a joined attacker", "This wallet has not joined the contest as an attacker.", "当前钱包还没有加入这场比赛的攻方。"],
  ["mining join requires data consent", "Mining contests require consent to data retention.", "挖矿赛必须同意数据留存条款。"],
  ["this attack payment was already processed", "This attack payment was already processed. Do not send it again.", "这笔攻击付款已经处理过，请不要重复发送。"],
  ["payment is not indexed yet", "The payment is not indexed yet. Retry shortly.", "付款尚未被索引，请稍后重试。"],
  ["dataset is already published", "The dataset is already published.", "数据集已经发布。"],
  ["dataset is not published", "The dataset has not been published yet.", "数据集尚未发布，请等待运营发布。"],
  ["only the defender may buy this dataset", "Only the defender of this contest may buy the dataset.", "只有该场守方可以购买这份数据。"],
  ["attacker did not consent to data sales", "This attacker did not consent to data sales.", "该攻方没有同意出售数据。"],
  ["already bought", "This dataset has already been purchased.", "这份数据已经购买过。"],
  ["download not found or expired", "The download link was not found or has expired. Request delivery again.", "下载链接已过期，请重新发起交付。"],
  ["defense hash is retired", "This defense version is retired and cannot be reused.", "该防守版本已经退役，不能再次开赛。"],
  ["defense hash already has an active contest", "This defense version already has an active contest.", "该防守版本已有进行中的挖矿赛。"],
  ["active mining contest cap reached", "The active mining contest limit (3) has been reached.", "活跃挖矿赛已达到平台上限（3 场）。"],
  ["platform model key is not configured", "The platform mining model key is not configured.", "平台未配置挖矿模型 Key。"],
  ["PLATFORM_MODEL_PROVIDER", "The platform mining model provider is not configured.", "平台未配置挖矿模型 provider。"],
  ["custody unavailable", "The platform custody service is unavailable. Contact the operator.", "平台托管服务不可用，请联系运营。"],
  ["faucet signer is not configured", "The faucet signing service is not configured.", "水龙头签名服务未配置。"],
  ["captcha", "Captcha verification failed. Refresh and retry.", "验证码校验失败，请刷新后重试。"],
  ["faucet cooldown active", "This address is still in its 24-hour faucet cooldown.", "该地址仍在 24 小时水龙头冷却期内。"],
  ["claim signature expired", "The signed faucet message expired. Sign a new message and retry.", "水龙头签名消息已过期，请重新签名后再试。"],
  ["claim signature was already used", "This signed faucet message was already used. Sign a new message and retry.", "这条水龙头签名已经使用过，请重新签名后再试。"],
  ["claim signature does not match address", "The faucet signature does not match the connected wallet.", "水龙头签名与当前钱包地址不匹配。"],
  ["claim signature cannot be recovered", "The faucet signature is invalid. Sign the claim again.", "水龙头签名无效，请重新签名领取。"],
  ["claim signature is invalid", "The faucet signature is invalid. Sign the claim again.", "水龙头签名无效，请重新签名领取。"],
  ["faucet relay failed", "The platform could not submit the faucet credit. Try again shortly.", "平台代发水龙头交易失败，请稍后重试。"],
  ["faucet relay is not configured", "The faucet relay is not configured on this deployment.", "本次部署未配置水龙头代发服务。"],
  ["faucet amount is not configured", "The faucet amount is not configured on this deployment.", "本次部署未配置水龙头额度。"],
];

function translateApiMessage(message: string): string {
  const lower = message.toLowerCase();
  for (const [needle, english, chinese] of API_MESSAGES) {
    if (lower.includes(needle.toLowerCase())) return msg(english, chinese);
  }
  return message;
}

function statusMessage(status: number): string {
  if (status === 401) return msg("Platform authentication failed. Check the proxy configuration.", "平台鉴权失败，请检查代理配置。");
  if (status === 403) return msg("You do not have permission to perform this action.", "没有权限执行这个操作。");
  if (status === 404) return msg("The record was not found; it may not be indexed yet.", "没有找到对应记录，可能尚未同步。");
  if (status === 409) return msg("The current state does not allow this action. Refresh and retry.", "当前状态不允许这个操作，请刷新后重试。");
  if (status === 422) return msg("The submitted data is invalid. Check it and retry.", "提交的内容不符合要求，请检查后重试。");
  if (status === 429) return msg("Too many requests. Try again later.", "请求过于频繁，请稍后再试。");
  if (status >= 500) return msg("The platform service is temporarily unavailable. Try again later.", "平台服务暂时不可用，请稍后重试。");
  return msg(`Request failed (HTTP ${status})`, `请求失败（HTTP ${status}）`);
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
    if (record.qualification === "failed") {
      return msg(
        "Qualification failed. Check the model and API key.",
        "资格测试未通过，请检查模型与 API Key。",
      );
    }
    if (typeof record.recovery === "string") {
      return msg(
        `Operation failed (recovery state: ${record.recovery}).`,
        `操作失败（恢复状态：${record.recovery}）。`,
      );
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
    if (anyError.code === 4001) {
      return msg("You cancelled the request in your wallet.", "你在钱包中取消了这次操作。");
    }
    const raw = anyError.shortMessage || anyError.message || "";
    if (/user rejected|denied transaction|rejected the request/i.test(raw)) {
      return msg("You cancelled the request in your wallet.", "你在钱包中取消了这次操作。");
    }
    if (/insufficient funds/i.test(raw)) {
      return msg("The wallet balance cannot cover this transaction.", "钱包余额不足以支付这笔交易。");
    }
    if (/chain mismatch|wrong network|does not match the target chain/i.test(raw)) {
      return msg(
        "The wallet network is incorrect. Switch to RTM Testnet (48850).",
        "钱包网络不正确，请切换到 RTM Testnet（48850）。",
      );
    }
    if (/nonce/i.test(raw)) {
      return msg("Transaction nonce conflict. Refresh and retry.", "交易 nonce 冲突，请刷新后重试。");
    }
    if (/Wallet RPC did not respond/i.test(raw)) {
      return msg("The wallet RPC did not respond. Check its URL and retry.", "钱包 RPC 无响应，请检查 RPC 地址后重试。");
    }
    return raw || msg("Operation failed.", "操作失败。");
  }
  if (typeof error === "object") {
    const detail = detailText(error);
    if (detail) return translateApiMessage(detail);
  }
  return String(error);
}
