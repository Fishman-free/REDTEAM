/**
 * Registration state is authoritative on the platform, but the UI only learns
 * about it from the POST response. If that response is lost (proxy timeout, a
 * closed tab) the platform still holds the registration, the next attempt gets
 * 409 "defender is already registered", and the page dead-ends on step 1.
 * These helpers rebuild the local record from GET /defenders/{address}.
 */

export interface DefenderRegistration {
  wallet: string;
  version?: string;
  digest?: string;
  contestId?: string;
  registeredAt: number;
}

export interface DefenderStatus {
  registered: boolean;
  defender: string;
  wallet: string;
  version: string;
  digest: string;
  contests: string[];
  registered_at: number | null;
}

export function registrationFromStatus(
  status: DefenderStatus,
  current: DefenderRegistration | null,
  nowSeconds: number,
): DefenderRegistration {
  const sameWallet =
    current !== null && current.wallet.toLowerCase() === status.wallet.toLowerCase();
  // The server appends contests in creation order; one BYOK registration can
  // create at most one standard contest.
  const contestId = status.contests[0] ?? current?.contestId;
  return {
    wallet: status.wallet,
    version: status.version,
    digest: status.digest,
    ...(contestId ? { contestId } : {}),
    registeredAt:
      sameWallet && current
        ? current.registeredAt
        : status.registered_at && status.registered_at > 0
          ? status.registered_at
          : nowSeconds,
  };
}

/**
 * An incomplete record used when the user asserts a registration exists but
 * the status endpoint cannot confirm it. createContest needs no detail from
 * the record, so the page can advance instead of dead-ending; the next
 * reconciliation fills in the real values.
 */
export function placeholderRegistration(nowSeconds: number): DefenderRegistration {
  return { wallet: "", registeredAt: nowSeconds };
}

export function isUnknownDefenderDetail(detail: unknown): boolean {
  return typeof detail === "string" && detail === "defender is not registered";
}

export function isRegistrationInProgressDetail(detail: unknown): boolean {
  return (
    typeof detail === "string" && detail === "defender registration is already in progress"
  );
}

export function isContestAlreadyCreatedDetail(detail: unknown): boolean {
  return typeof detail === "string" && detail.includes("already created a contest");
}

export function isProxyUnavailableDetail(detail: unknown): boolean {
  return typeof detail === "string" && detail === "platform API unavailable";
}
