const API_BASE = (import.meta.env.VITE_API_URL || "/api").replace(/\/+$/, "");

export class ApiClientError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `HTTP ${status}`);
    this.name = "ApiClientError";
    this.status = status;
    this.detail = detail;
  }
}

interface RequestOptions {
  timeoutMs?: number;
  adminKey?: string;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  options: RequestOptions = {},
): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    options.timeoutMs ?? 25_000,
  );
  const headers = new Headers(init.headers);
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  headers.set("Accept", "application/json");
  if (options.adminKey) headers.set("X-Admin-Key", options.adminKey);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      signal: controller.signal,
    });
  } catch (error) {
    if (controller.signal.aborted) {
      throw new ApiClientError(408, "request timed out");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }
  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : payload;
    throw new ApiClientError(response.status, detail);
  }
  return payload as T;
}

export interface PlatformMeta {
  network: string;
  chainId: number;
  rpc: string;
  addresses: {
    treasury: string;
    arena: string;
    rtm: string;
    faucet: string;
    dataMarket: string;
    taskSink?: string;
  };
  fees: {
    attackFeeBps: number;
    miningFeeBps: number;
    miningRewardWei: string;
    miningFeeWei: string;
  };
  limits: {
    minDurationH: number;
    maxDurationH: number;
    minStakeBps: number;
    maxStakeBps: number;
    maxActiveMining: number;
  };
  providers: string[];
  faucet: {
    dripAmountWei: string;
    captchaRequired: boolean;
  };
  features: {
    mining: boolean;
    dataMarket: boolean;
    defenderRegistration: boolean;
    byoa?: boolean;
  };
  byoa?: {
    attestationTiers: string[];
    transports: string[];
    walletMcpUrl: string;
  };
  indexer: {
    startBlock: number;
  };
}

export interface IndexerStatus {
  status: string;
  network?: string;
  chainId?: number;
  indexer?: {
    running?: boolean;
    lastBlock?: number | null;
    latestBlock?: number | null;
    lag?: number | null;
    lastError?: string | null;
    updatedAt?: number | null;
    events?: number | null;
  };
  time?: number;
}

export interface Contest {
  id: string;
  defender: string;
  wallet: string;
  stake: string;
  end: string;
  is_mining: boolean;
  is_byoa?: boolean;
  stake_bps: number;
  defense_hash: string;
  start_ts: number;
  ended_ts: number | null;
  state: string;
  paid_count: number;
  winner: string | null;
  breach_amount: string;
  reward: string;
  settled: boolean;
}

export interface AttackerInfo {
  is_mining: boolean;
  stake: string;
  data_consent: boolean | null;
  paid: number;
  delivered: number;
  won: boolean;
}

export interface ContestDetail {
  contest: Contest;
  attackers: Record<string, AttackerInfo>;
}

export interface LeaderboardEntry {
  wins: number;
  rtm_won: string;
  difficulty: number;
  current_streak: number;
  longest_streak: number;
}

export interface ByoaBundleResult {
  bundle_id: string;
  defender: string;
  commitment: string;
  attestation_tier: "simulated" | "hardware";
  runtime_measurement: string;
  tee_pubkey: string;
  tee_signer: string;
  wallet: string;
  byoa_nonce: number;
  defender_data_consent: boolean;
  policy_fingerprint: string;
  manifest: Record<string, unknown>;
  egress: { models: string[]; oracles: Record<string, unknown>[] };
}

export interface ByoaContestResult {
  contest_id: string;
  tx_hash: string;
  wallet: string;
  defender: string;
  tee_signer: string;
  config_commitment: string;
  runtime_measurement: string;
  attestation_tier: string;
  end: number;
  task_sink: string;
  pull_token?: string | null;
}

export interface ByoaTurnResult {
  contest_id: string;
  seq: number;
  sealed: boolean;
  reply_envelope?: Record<string, unknown>;
  reply_hash?: string;
  reply_signature?: string;
  tee_signer?: string;
  reply?: string;
  completed_tasks: string[];
  transfers: { to: string | null; amount: string; tx: string | null }[];
}

export interface ByoaState {
  contest_id: string;
  defender: string;
  wallet: string;
  tee_signer: string;
  tee_pubkey: string;
  config_commitment: string;
  runtime_measurement: string;
  attestation_tier: string;
  policy_fingerprint: string;
  defender_data_consent: boolean;
  manifest: Record<string, unknown>;
  egress: { models: string[]; oracles: Record<string, unknown>[] };
  transcript: {
    seq: number;
    at: number;
    channel: string;
    kind: string;
    contentHash: string;
    replyHash: string;
    content: string | null;
    reply: string | null;
    toolCalls: unknown[];
  }[];
  utility: {
    issued: number;
    completed: number;
    expired: number;
    open: number;
    miss_threshold: number;
    breached: boolean;
    completion_ratio: number;
  };
  wallet_audit: Record<string, unknown>[];
  encryption: string;
  end: number;
}

export interface DefenderEntry {
  contests_survived: number;
  msgs_withstood: number;
  penalties: string;
  breach_loss: string;
  net_income: string;
  faults: number;
  longest_survival: number;
}

export interface MinerEntry {
  joined: number;
  decided_joined: number;
  wins: number;
  rtm_won_fixed: string;
  difficulty: number;
  breach_rate: number;
}

export interface MiningStats {
  created: number;
  settled: number;
  retired: number;
  decided: number;
  breach_rate: number;
  total_fixed_reward: string;
  active_contests: number;
  active_versions: Array<{
    contest_id: string;
    defense_hash: string;
    start_ts: number;
    paid_messages: number;
  }>;
  history: Array<{
    contest_id: string;
    outcome: string;
    defense_hash: string;
    ended_ts: number;
    paid_messages: number;
    winner: string | null;
  }>;
}

export interface Leaderboards {
  network: string;
  attackers: Record<string, LeaderboardEntry>;
  defenders: Record<string, DefenderEntry>;
  miners: Record<string, MinerEntry>;
  mining: MiningStats;
}

export interface JoinIntent {
  contest_id: string;
  function: string;
  args: [string, string, boolean];
  max_stake: string;
  data_consent: boolean;
  approve: { token: string; spender: string; amount: string };
}

export interface MiningJoinIntent {
  contest_id: string;
  function: string;
  args: [string, boolean];
  accept_data: boolean;
  terms: string;
}

export interface MessageResponse {
  status: string;
  reply: string | null;
  error: { kind?: string; message?: string } | null;
  defender_fault: boolean;
  fault_path: string | null;
  persisted: boolean;
  turn: number;
}

export interface FaucetTicket {
  to: string;
  nonce: number;
  deadline: number;
  signature: string;
}

export interface FaucetRelayClaim {
  to: string;
  amount_wei: string;
  tx_hash: string;
  claimed_at: number;
}

export interface DeliveryGrant {
  token: string;
  expires_at: number;
  root: string;
  files: string[];
  kind: string;
  attacker: string | null;
}

export interface RegisterResult {
  qualification: string;
  defender: string;
  wallet: string;
  version?: string;
  digest?: string;
}

export interface CreateContestResult {
  contest_id: string;
  tx_hash: string;
  wallet: string;
  defender: string;
  approve: { token: string; spender: string; amount: string };
}

export interface MiningContestResult {
  contest_id: string;
  wallet: string;
  defense_hash: string;
  tx_hash: string;
  version: string;
}

export interface PublishResult {
  contest_id: string;
  root: string;
  tx_hash: string;
}

export interface RsiCase {
  case_id: string;
  contest_id: string;
  attacker: string;
  breach_classes: string[];
  turns: number;
  path: string;
  sha256: string;
}

export interface RsiCandidate {
  candidate_id: string;
  name: string;
  parent: string;
  digest: string;
  case_ids: string[];
  created_at: number;
  verified: boolean;
}

export interface RsiCheck {
  name: string;
  status: "pass" | "fail" | "unsupported";
  detail: string;
}

export interface RsiVerification {
  candidate_id: string;
  digest: string;
  passed: boolean;
  checks: RsiCheck[];
  replays: Array<{
    case_id: string;
    status: string;
    breached: boolean;
    detail: string;
  }>;
  verified_at: number;
}

export interface RsiPromotion {
  name: string;
  digest: string;
  created: boolean;
}

export const api = {
  meta() {
    return request<PlatformMeta>("/meta", {}, { timeoutMs: 10_000 });
  },

  status() {
    return request<IndexerStatus>("/status", {}, { timeoutMs: 10_000 });
  },

  health() {
    return request<{ status: string }>("/health", {}, { timeoutMs: 6_000 });
  },

  registerDefender(payload: {
    defender: string;
    provider: string;
    api_key: string;
    defense_prompt: string;
    mandate: string;
    nonce: number;
    deadline: number;
    signature: string;
  }) {
    return request<RegisterResult>(
      "/defenders/register",
      { method: "POST", body: JSON.stringify(payload) },
      { timeoutMs: 180_000 },
    );
  },

  registerByoaBundle(payload: Record<string, unknown>) {
    return request<ByoaBundleResult>(
      "/byoa/bundles",
      { method: "POST", body: JSON.stringify(payload) },
      { timeoutMs: 120_000 },
    );
  },

  createByoaContest(payload: Record<string, unknown>) {
    return request<ByoaContestResult>(
      "/byoa/contests",
      { method: "POST", body: JSON.stringify(payload) },
      { timeoutMs: 120_000 },
    );
  },

  byoaState(contestId: string) {
    return request<ByoaState>(`/byoa/contests/${contestId}`, {}, { timeoutMs: 20_000 });
  },

  generateByoaTasks(contestId: string, payload: { count: number; seed?: string }) {
    return request<Record<string, unknown>[]>(
      `/byoa/contests/${contestId}/tasks/generate`,
      { method: "POST", body: JSON.stringify(payload) },
      { timeoutMs: 120_000 },
    );
  },

  byoaTurn(contestId: string, payload: Record<string, unknown>) {
    return request<ByoaTurnResult>(
      `/byoa/contests/${contestId}/turns`,
      { method: "POST", body: JSON.stringify(payload) },
      { timeoutMs: 180_000 },
    );
  },

  byoaFinalize(contestId: string) {
    return request<{
      issued: number;
      completed: number;
      expired: number;
      open: number;
      miss_threshold: number;
      breached: boolean;
      completion_ratio: number;
      penalty_tx: string | null;
      errors: string[];
    }>(`/byoa/contests/${contestId}/finalize`, { method: "POST", body: "{}" }, { timeoutMs: 120_000 });
  },

  createContest(
    defender: string,
    payload: { stake: string; duration_h: number; stake_bps: number },
  ) {
    return request<CreateContestResult>(
      `/contests?defender=${encodeURIComponent(defender)}`,
      { method: "POST", body: JSON.stringify(payload) },
      { timeoutMs: 90_000 },
    );
  },

  joinIntent(contestId: string, payload: { max_stake: string; data_consent: boolean }) {
    return request<JoinIntent>(`/contests/${contestId}/join-intent`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  miningJoinIntent(contestId: string) {
    return request<MiningJoinIntent>("/mining/join-intent", {
      method: "POST",
      body: JSON.stringify({ contest_id: contestId, accept_data: true }),
    });
  },

  sendMessage(contestId: string, payload: { tx_hash: string; content: string }) {
    return request<MessageResponse>(
      `/contests/${contestId}/messages`,
      { method: "POST", body: JSON.stringify(payload) },
      { timeoutMs: 180_000 },
    );
  },

  leaderboards() {
    return request<Leaderboards>("/leaderboards", {}, { timeoutMs: 35_000 });
  },

  contests(limit = 500) {
    return request<Contest[]>(`/contests?limit=${limit}`, {}, { timeoutMs: 25_000 });
  },

  contest(contestId: string) {
    return request<ContestDetail>(`/contests/${contestId}`, {}, { timeoutMs: 20_000 });
  },

  faucetTicket(to: string, captchaToken?: string) {
    return request<FaucetTicket>("/faucet/ticket", {
      method: "POST",
      body: JSON.stringify({ to, captcha_token: captchaToken || null }),
    });
  },

  faucetClaim(payload: {
    to: string;
    issued_at: number;
    nonce: string;
    signature: string;
  }) {
    return request<FaucetRelayClaim>(
      "/faucet/claim",
      { method: "POST", body: JSON.stringify(payload) },
      { timeoutMs: 40_000 },
    );
  },

  publishDataSet(contestId: string, adminKey?: string) {
    return request<PublishResult>(
      `/data/${contestId}/publish`,
      { method: "POST" },
      { timeoutMs: 90_000, adminKey },
    );
  },

  deliver(contestId: string, txHash: string) {
    return request<DeliveryGrant>(
      `/data/${contestId}/deliver`,
      { method: "POST", body: JSON.stringify({ tx_hash: txHash }) },
      { timeoutMs: 35_000 },
    );
  },

  createMiningContest(version: string, adminKey?: string) {
    return request<MiningContestResult>(
      "/mining/contests",
      { method: "POST", body: JSON.stringify({ version }) },
      { timeoutMs: 120_000, adminKey },
    );
  },

  rsiCases() {
    return request<{ cases: RsiCase[] }>("/rsi/cases", {}, { timeoutMs: 15_000 });
  },

  rsiCandidates() {
    return request<{ candidates: RsiCandidate[] }>("/rsi/candidates", {}, { timeoutMs: 15_000 });
  },

  rsiExport(contestId: string, adminKey?: string) {
    return request<{ case_id: string; path: string; sha256: string }>(
      "/rsi/export",
      { method: "POST", body: JSON.stringify({ contest_id: contestId }) },
      { timeoutMs: 45_000, adminKey },
    );
  },

  rsiPropose(parentVersion: string, adminKey?: string, caseIds?: string[]) {
    return request<RsiCandidate & { defense: unknown; evidence: unknown }>(
      "/rsi/candidates",
      {
        method: "POST",
        body: JSON.stringify(
          caseIds && caseIds.length
            ? { parent_version: parentVersion, case_ids: caseIds }
            : { parent_version: parentVersion },
        ),
      },
      { timeoutMs: 30_000, adminKey },
    );
  },

  rsiVerify(candidateId: string, adminKey?: string) {
    return request<RsiVerification>(
      `/rsi/candidates/${encodeURIComponent(candidateId)}/verify`,
      { method: "POST" },
      { timeoutMs: 300_000, adminKey },
    );
  },

  rsiPromote(candidateId: string, adminKey?: string) {
    return request<RsiPromotion>(
      `/rsi/candidates/${encodeURIComponent(candidateId)}/promote`,
      { method: "POST" },
      { timeoutMs: 30_000, adminKey },
    );
  },

  async download(token: string, filename: string): Promise<void> {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 90_000);
    let response: Response;
    try {
      response = await fetch(`${API_BASE}/downloads/${encodeURIComponent(token)}`, {
        signal: controller.signal,
      });
    } finally {
      window.clearTimeout(timeout);
    }
    if (!response.ok) throw new ApiClientError(response.status, "download failed");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 2_000);
  },
};
