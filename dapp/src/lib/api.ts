const API_BASE = (import.meta.env.VITE_API_URL || "/api").replace(/\/+$/, "");
const API_TOKEN = import.meta.env.VITE_API_TOKEN || "";

export class ApiClientError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (API_TOKEN) headers.set("Authorization", `Bearer ${API_TOKEN}`);
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
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

export interface Contest {
  id: string;
  defender: string;
  wallet: string;
  stake: string;
  end: string;
  is_mining: boolean;
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

export interface DeliveryGrant {
  token: string;
  expires_at: number;
  root: string;
  files: string[];
  kind: string;
  attacker: string | null;
}

export const api = {
  registerDefender(payload: {
    defender: string;
    provider: string;
    api_key: string;
    defense_prompt: string;
    mandate: string;
  }) {
    return request<{ qualification: string; defender: string; wallet: string }>(
      "/defenders/register",
      { method: "POST", body: JSON.stringify(payload) },
    );
  },

  createContest(
    defender: string,
    payload: { stake: string; duration_h: number; stake_bps: number },
  ) {
    return request<{
      contest_id: string;
      tx_hash: string;
      wallet: string;
      approve: { token: string; spender: string; amount: string };
    }>(`/contests?defender=${encodeURIComponent(defender)}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
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
    return request<MessageResponse>(`/contests/${contestId}/messages`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  leaderboards() {
    return request<Leaderboards>("/leaderboards");
  },

  contests(limit = 200) {
    return request<Contest[]>(`/contests?limit=${limit}`);
  },

  contest(contestId: string) {
    return request<ContestDetail>(`/contests/${contestId}`);
  },

  faucetTicket(to: string, captchaToken?: string) {
    return request<FaucetTicket>("/faucet/ticket", {
      method: "POST",
      body: JSON.stringify({ to, captcha_token: captchaToken || null }),
    });
  },

  publishDataSet(contestId: string) {
    return request<{ contest_id: string; root: string; tx_hash: string }>(
      `/data/${contestId}/publish`,
      { method: "POST" },
    );
  },

  deliver(contestId: string, txHash: string) {
    return request<DeliveryGrant>(`/data/${contestId}/deliver`, {
      method: "POST",
      body: JSON.stringify({ tx_hash: txHash }),
    });
  },

  async download(token: string, filename: string): Promise<void> {
    const headers = new Headers();
    if (API_TOKEN) headers.set("Authorization", `Bearer ${API_TOKEN}`);
    const response = await fetch(`${API_BASE}/downloads/${token}`, { headers });
    if (!response.ok) throw new ApiClientError(response.status, "download failed");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  },
};
