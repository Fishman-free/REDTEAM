import type { Contest, PlatformMeta } from "./api";
import { getLang } from "./i18n";

export function contestEndMs(contest: Contest): number {
  if (contest.is_mining) return Number.POSITIVE_INFINITY;
  const seconds = Number(contest.end);
  if (!Number.isFinite(seconds) || seconds > Number.MAX_SAFE_INTEGER) {
    return Number.POSITIVE_INFINITY;
  }
  return seconds * 1_000;
}

export function contestStartMs(contest: Contest): number {
  return Number(contest.start_ts) * 1_000;
}

export function attackFeeWei(contest: Contest, meta: Pick<PlatformMeta, "fees">): bigint {
  if (contest.is_mining) {
    try {
      return BigInt(meta.fees.miningFeeWei);
    } catch {
      return 5_000_000_000_000_000n;
    }
  }
  try {
    return (BigInt(contest.stake) * BigInt(meta.fees.attackFeeBps)) / 10_000n;
  } catch {
    return 0n;
  }
}

export function requiredStakeWei(contest: Contest): bigint {
  try {
    return (BigInt(contest.stake) * BigInt(contest.stake_bps)) / 10_000n;
  } catch {
    return 0n;
  }
}

export function contestProgress(contest: Contest, now: number): number {
  const start = contestStartMs(contest);
  const end = contestEndMs(contest);
  if (!start || end <= start) return 0;
  return Math.max(0, Math.min(1, (now - start) / (end - start)));
}

export function isExpiredByTime(contest: Contest, now: number): boolean {
  const end = contestEndMs(contest);
  return Number.isFinite(end) && now >= end;
}

export function isContestLive(contest: Contest, now: number): boolean {
  return contest.state === "live" && !isExpiredByTime(contest, now);
}

export function needsExpire(contest: Contest, now: number): boolean {
  return !contest.is_mining && contest.state === "live" && isExpiredByTime(contest, now);
}

export function contestStateForDisplay(
  contest: Contest,
  now: number,
): { state: string; label: string } {
  if (needsExpire(contest, now)) {
    return {
      state: "pending",
      label: getLang() === "en" ? "Needs settlement" : "待结算",
    };
  }
  return { state: contest.state, label: contest.state };
}
