import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  useAccount,
  usePublicClient,
  useReadContract,
  useSignMessage,
  useSignTypedData,
} from "wagmi";
import {
  getAddress,
  parseEther,
  verifyMessage,
  type Address,
  type Hex,
} from "viem";
import { KeyRound, Send, ShieldCheck, Sparkles, Wallet } from "lucide-react";
import {
  api,
  ApiClientError,
  type ByoaBundleResult,
  type ByoaContestResult,
  type ByoaState,
} from "../lib/api";
import { arenaAbi, rtmAbi } from "../lib/contracts";
import {
  attackContext,
  ciphertextHash,
  deriveIdentity,
  IDENTITY_MESSAGE,
  isEnvelope,
  openFrom,
  replyContext,
  sealTo,
  type Identity,
} from "../lib/byoaCrypto";
import { errorText, shortAddr, shortHash } from "../lib/format";
import { CHAIN_ID, isSupportedChain } from "../lib/chain";
import { useWalletChainId } from "../lib/useWalletChainId";
import { useI18n } from "../lib/i18n";
import { useLocalStorage } from "../lib/hooks";
import { usePlatform } from "../lib/platform";
import { useArenaWriteContract } from "../lib/useArenaWriteContract";
import { useToast } from "../context/ToastContext";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { CheckboxField, SelectField, TextAreaField, TextField } from "../components/ui/Field";
import { Panel } from "../components/ui/Panel";
import { SectionHeader } from "../components/ui/SectionHeader";
import { Stat } from "../components/ui/Stat";
import { AddressChip } from "../components/ui/Address";
import { ConnectPrompt } from "../components/wallet/ConnectPrompt";

const ATTESTATION_SIMULATED = 0;
const BYOA_TYPES = {
  ByoaMandate: [
    { name: "defender", type: "address" },
    { name: "wallet", type: "address" },
    { name: "teeSigner", type: "address" },
    { name: "stake", type: "uint256" },
    { name: "duration", type: "uint64" },
    { name: "stakeBps", type: "uint32" },
    { name: "configCommitment", type: "bytes32" },
    { name: "runtimeMeasurement", type: "bytes32" },
    { name: "teePubKey", type: "bytes32" },
    { name: "attestationTier", type: "uint8" },
    { name: "defenderDataConsent", type: "bool" },
    { name: "utilityMissThreshold", type: "uint16" },
    { name: "utilityPenaltyBps", type: "uint16" },
    { name: "nonce", type: "uint64" },
    { name: "deadline", type: "uint64" },
  ],
} as const;
const ATTACK_KEY_TYPES = {
  AttackKey: [
    { name: "attacker", type: "address" },
    { name: "contestId", type: "bytes32" },
    { name: "msgHash", type: "bytes32" },
    { name: "pubkey", type: "bytes32" },
    { name: "deadline", type: "uint64" },
  ],
} as const;

interface ChatMessage {
  role: "attacker" | "agent" | "system";
  text: string;
  hash?: string;
  verified?: boolean;
}

function ownershipChallenge(address: string, nonce: number, deadline: number) {
  return [
    "RTM Arena key ownership",
    `address: ${getAddress(address)}`,
    "purpose: byoa-bundle",
    `nonce: ${nonce}`,
    `deadline: ${deadline}`,
  ].join("\n");
}

export default function Byoa() {
  const { address, isConnected } = useAccount();
  const walletChainId = useWalletChainId();
  const { meta, addresses } = usePlatform();
  const { signMessageAsync } = useSignMessage();
  const { signTypedDataAsync } = useSignTypedData();
  const { writeContractAsync } = useArenaWriteContract();
  const publicClient = usePublicClient({ chainId: CHAIN_ID });
  const { t } = useI18n();
  const { toast } = useToast();

  const [bundle, setBundle] = useLocalStorage<ByoaBundleResult | null>(
    `byoa:bundle:${address?.toLowerCase() ?? "anon"}`,
    null,
  );
  const [defenderContest, setDefenderContest] = useLocalStorage<ByoaContestResult | null>(
    `byoa:contest:${address?.toLowerCase() ?? "anon"}`,
    null,
  );
  const [transportKind, setTransportKind] = useState("hosted-mcp");
  const [endpoint, setEndpoint] = useState("http://127.0.0.1:8200");
  const [transportSecret, setTransportSecret] = useState("");
  const [imageDigest, setImageDigest] = useState(`sha256:${"ab".repeat(32)}`);
  const [egressModels, setEgressModels] = useState("models.example");
  const [perTxLimit, setPerTxLimit] = useState("5");
  const [totalLimit, setTotalLimit] = useState("20");
  const [maxTaskAmount, setMaxTaskAmount] = useState("5");
  const [defenderConsent, setDefenderConsent] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [registerError, setRegisterError] = useState("");
  const [stake, setStake] = useState("50");
  const [durationHours, setDurationHours] = useState(24);
  const [stakeBps, setStakeBps] = useState(1000);
  const [missThreshold, setMissThreshold] = useState(0);
  const [penaltyBps, setPenaltyBps] = useState(1000);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const [taskBusy, setTaskBusy] = useState(false);
  const [finalizing, setFinalizing] = useState(false);
  const [attackContestId, setAttackContestId] = useState(defenderContest?.contest_id ?? "");
  const [joinConsent, setJoinConsent] = useState(false);
  const [joining, setJoining] = useState(false);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [message, setMessage] = useState("");
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [attackError, setAttackError] = useState("");

  const arena = addresses?.arena as Address | undefined;
  const rtm = addresses?.rtm as Address | undefined;
  const byoaContest = attackContestId.trim().toLowerCase();
  const validContest = /^0x[0-9a-f]{64}$/.test(byoaContest);

  const chainContest = useReadContract({
    address: arena,
    abi: arenaAbi,
    functionName: "contestInfo",
    args: validContest ? [byoaContest as Hex] : undefined,
    query: { enabled: Boolean(arena && validContest) },
  });
  const byoaInfo = useReadContract({
    address: arena,
    abi: arenaAbi,
    functionName: "byoaContestInfo",
    args: validContest ? [byoaContest as Hex] : undefined,
    query: { enabled: Boolean(arena && validContest) },
  });
  const joined = useReadContract({
    address: arena,
    abi: arenaAbi,
    functionName: "isRegisteredAttacker",
    args: validContest && address ? [byoaContest as Hex, address] : undefined,
    query: { enabled: Boolean(arena && validContest && address) },
  });
  const consent = useReadContract({
    address: arena,
    abi: arenaAbi,
    functionName: "dataConsent",
    args: validContest && address ? [byoaContest as Hex, address] : undefined,
    query: { enabled: Boolean(arena && validContest && address) },
  });

  const stateQuery = useQuery<ByoaState>({
    queryKey: ["byoa-state", defenderContest?.contest_id],
    queryFn: () => api.byoaState(defenderContest!.contest_id),
    enabled: Boolean(defenderContest?.contest_id),
    refetchInterval: 10_000,
  });

  const info = byoaInfo.data as
    | readonly [boolean, Address, Hex, Hex, Hex, number, boolean, bigint, bigint]
    | undefined;
  const contestTuple = chainContest.data as
    | readonly [
        Address,
        Address,
        bigint,
        number,
        Hex,
        bigint,
        bigint,
        bigint,
        number,
        boolean,
        number,
        boolean,
        boolean,
      ]
    | undefined;
  const isByoa = Boolean(info?.[0]);
  const teePubKey = info?.[2];
  const teeSigner = info?.[1];
  const attestationTier = Number(info?.[5] ?? 0);
  const isJoined = Boolean(joined.data);
  const joinConsentValue = Boolean(consent.data);

  const stakeWei = useMemo(() => {
    try {
      return parseEther(stake);
    } catch {
      return 0n;
    }
  }, [stake]);
  const maxTaskWei = useMemo(() => {
    try {
      return parseEther(maxTaskAmount);
    } catch {
      return 0n;
    }
  }, [maxTaskAmount]);

  async function registerBundle() {
    setRegisterError("");
    if (!address || !isSupportedChain(walletChainId)) {
      setRegisterError(t("Connect the RTM Testnet wallet first.", "请先连接 RTM Testnet 钱包。"));
      return;
    }
    let perTx = 0n;
    let total = 0n;
    try {
      perTx = parseEther(perTxLimit);
      total = parseEther(totalLimit);
    } catch {
      setRegisterError(t("Policy limits must be decimal RTM.", "策略额度必须是十进制 RTM。"));
      return;
    }
    if (maxTaskWei <= 0n || perTx < maxTaskWei || total < maxTaskWei) {
      setRegisterError(
        t(
          "Per-transaction and total limits must cover the largest task.",
          "单笔与累计额度必须覆盖最大任务金额。",
        ),
      );
      return;
    }
    setRegistering(true);
    try {
      const nonce = Date.now();
      const deadline = Math.floor(Date.now() / 1000) + 900;
      const signature = await signMessageAsync({
        message: ownershipChallenge(address, nonce, deadline),
      });
      const models = egressModels
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      const result = await api.registerByoaBundle({
        defender: address,
        image_digest: imageDigest.trim(),
        transport_kind: transportKind,
        transport_endpoint: endpoint.trim(),
        transport_secret: transportKind === "webhook" ? transportSecret : null,
        egress: { models },
        policy: {
          per_tx_limit: perTxLimit.trim(),
          total_limit: totalLimit.trim(),
          not_after: Math.floor(Date.now() / 1000) + 14 * 86_400,
          confirm_threshold: null,
          payee_allowlist: null,
        },
        max_task_amount: maxTaskAmount.trim(),
        defender_data_consent: defenderConsent,
        compose_files: { "compose.yaml": imageDigest.trim() },
        attestation_tier: "simulated",
        nonce,
        deadline,
        signature,
      });
      setBundle(result);
      toast({
        title: t("Bundle registered", "Bundle 已注册"),
        description: t(
          `Simulated TEE signer ${shortAddr(result.tee_signer)}`,
          `模拟 TEE 签名者 ${shortAddr(result.tee_signer)}`,
        ),
        tone: "success",
      });
    } catch (reason) {
      setRegisterError(errorText(reason));
    } finally {
      setRegistering(false);
    }
  }

  async function createContest() {
    setCreateError("");
    if (!bundle || !address || !arena || !rtm) return;
    if (!isSupportedChain(walletChainId)) {
      setCreateError(t("Switch to RTM Testnet (48850).", "请切换到 RTM Testnet（48850）。"));
      return;
    }
    if (stakeWei <= 0n) {
      setCreateError(t("Stake must be positive.", "质押必须大于 0。"));
      return;
    }
    setCreating(true);
    try {
      const approvalHash = await writeContractAsync({
        address: rtm,
        abi: rtmAbi,
        functionName: "approve",
        args: [arena, stakeWei],
      });
      if (publicClient) {
        await publicClient.waitForTransactionReceipt({ hash: approvalHash });
      }
      const nonce = BigInt(bundle.byoa_nonce);
      const deadline = BigInt(Math.floor(Date.now() / 1000) + 1800);
      const message = {
        defender: address as Address,
        wallet: bundle.wallet as Address,
        teeSigner: bundle.tee_signer as Address,
        stake: stakeWei,
        duration: BigInt(durationHours * 3600),
        stakeBps,
        configCommitment: bundle.commitment as Hex,
        runtimeMeasurement: bundle.runtime_measurement as Hex,
        teePubKey: bundle.tee_pubkey as Hex,
        attestationTier: ATTESTATION_SIMULATED,
        defenderDataConsent: bundle.defender_data_consent,
        utilityMissThreshold: missThreshold,
        utilityPenaltyBps: penaltyBps,
        nonce,
        deadline,
      } as const;
      const defenderSignature = await signTypedDataAsync({
        domain: {
          name: "RTM Arena",
          version: "1",
          chainId: CHAIN_ID,
          verifyingContract: arena,
        },
        types: BYOA_TYPES,
        primaryType: "ByoaMandate",
        message,
      });
      const result = await api.createByoaContest({
        bundle_id: bundle.bundle_id,
        stake: stake.trim(),
        duration_h: durationHours,
        stake_bps: stakeBps,
        defender_signature: defenderSignature,
        miss_threshold: missThreshold,
        penalty_bps: penaltyBps,
        nonce: Number(nonce),
        deadline: Number(deadline),
      });
      setDefenderContest(result);
      setAttackContestId(result.contest_id);
      toast({
        title: t("BYOA contest created", "BYOA 赛已创建"),
        description: shortHash(result.contest_id),
        tone: "success",
      });
    } catch (reason) {
      setCreateError(errorText(reason));
    } finally {
      setCreating(false);
    }
  }

  async function generateTasks() {
    if (!defenderContest) return;
    setTaskBusy(true);
    try {
      const tasks = await api.generateByoaTasks(defenderContest.contest_id, { count: 3 });
      toast({
        title: t("Owner tasks issued", "主人任务已下发"),
        description: t(`${tasks.length} tasks`, `${tasks.length} 个任务`),
        tone: "success",
      });
      await stateQuery.refetch();
    } catch (reason) {
      toast({ title: t("Task generation failed", "任务生成失败"), description: errorText(reason), tone: "error" });
    } finally {
      setTaskBusy(false);
    }
  }

  async function finalizeContest() {
    if (!defenderContest) return;
    setFinalizing(true);
    try {
      const report = await api.byoaFinalize(defenderContest.contest_id);
      toast({
        title: report.penalty_tx
          ? t("Utility breach penalized", "效用违约已罚没")
          : t("Contest finalized", "比赛已结算"),
        description: t(
          `${String(report.completed)} completed / ${String(report.expired)} expired`,
          `${String(report.completed)} 完成 / ${String(report.expired)} 过期`,
        ),
        tone: report.penalty_tx ? "warning" : "success",
      });
      await stateQuery.refetch();
    } catch (reason) {
      toast({ title: t("Finalize failed", "结算失败"), description: errorText(reason), tone: "error" });
    } finally {
      setFinalizing(false);
    }
  }

  async function joinContest() {
    if (!address || !arena || !rtm || !contestTuple) return;
    setJoining(true);
    setAttackError("");
    try {
      const maxStake = (contestTuple[2] * BigInt(contestTuple[3])) / 10_000n;
      const approvalHash = await writeContractAsync({
        address: rtm,
        abi: rtmAbi,
        functionName: "approve",
        args: [arena, maxStake],
      });
      if (publicClient) {
        await publicClient.waitForTransactionReceipt({ hash: approvalHash });
      }
      await writeContractAsync({
        address: arena,
        abi: arenaAbi,
        functionName: "join",
        args: [byoaContest as Hex, maxStake, joinConsent],
      });
      toast({
        title: t("Joined contest", "已加入比赛"),
        description: t(
          joinConsent ? "Attack data may be sold under your consent." : "Attack data stays private.",
          joinConsent ? "攻击数据可按你的同意出售。" : "攻击数据保持私密。",
        ),
        tone: "success",
      });
      await joined.refetch();
      await consent.refetch();
    } catch (reason) {
      setAttackError(errorText(reason));
    } finally {
      setJoining(false);
    }
  }

  async function sendAttack() {
    setAttackError("");
    if (!address || !arena || !teePubKey || !validContest) return;
    if (!message.trim()) return;
    if (!isJoined) {
      setAttackError(t("Join the contest first.", "请先加入比赛。"));
      return;
    }
    setSending(true);
    try {
      let identityValue = identity;
      if (!identityValue) {
        const signature = await signMessageAsync({ message: IDENTITY_MESSAGE });
        identityValue = deriveIdentity(signature);
        setIdentity(identityValue);
      }
      const envelope = sealTo(
        teePubKey,
        message.trim(),
        attackContext(byoaContest, address),
      );
      const msgHash = ciphertextHash(envelope);
      const txHash = await writeContractAsync({
        address: arena,
        abi: arenaAbi,
        functionName: "attack",
        args: [byoaContest as Hex, msgHash],
      });
      const keyDeadline = BigInt(Math.floor(Date.now() / 1000) + 900);
      const keySignature = await signTypedDataAsync({
        domain: {
          name: "RTM Arena",
          version: "1",
          chainId: CHAIN_ID,
          verifyingContract: arena,
        },
        types: ATTACK_KEY_TYPES,
        primaryType: "AttackKey",
        message: {
          attacker: address as Address,
          contestId: byoaContest as Hex,
          msgHash,
          pubkey: identityValue.publicKey,
          deadline: keyDeadline,
        },
      });
      const response = await submitWithIndexerRetry({
        tx_hash: txHash,
        attacker: address,
        ciphertext: envelope,
        attacker_pubkey: identityValue.publicKey,
        key_signature: keySignature,
        key_deadline: Number(keyDeadline),
        kind: "dialogue",
        metadata: {},
      });
      if (!response.reply_envelope || !response.reply_hash || !response.reply_signature) {
        throw new Error(t("Reply is not sealed", "回复未加密"));
      }
      const envelopeValue = response.reply_envelope;
      if (!isEnvelope(envelopeValue)) throw new Error(t("Invalid reply envelope", "回复信封无效"));
      const plaintext = openFrom(
        identityValue.privateKey,
        envelopeValue,
        replyContext(byoaContest, address, msgHash, response.seq),
      );
      const signedPayload = [
        "RTM BYOA reply v1",
        `contest: ${byoaContest}`,
        `attacker: ${getAddress(address)}`,
        `msgHash: ${msgHash.toLowerCase()}`,
        `replyHash: ${response.reply_hash.toLowerCase()}`,
        `seq: ${response.seq}`,
      ].join("\n");
      // The TEE signer comes from the chain, not from the relay response.
      const verified = teeSigner
        ? await verifyMessage({
            address: getAddress(teeSigner),
            message: signedPayload,
            signature: response.reply_signature as Hex,
          }).catch(() => false)
        : false;
      setChat((items) => [
        ...items,
        { role: "attacker", text: message.trim(), hash: msgHash },
        { role: "agent", text: plaintext, hash: response.reply_hash, verified },
      ]);
      setMessage("");
    } catch (reason) {
      setAttackError(errorText(reason));
    } finally {
      setSending(false);
    }
  }

  async function submitWithIndexerRetry(payload: Record<string, unknown>) {
    let last: unknown = null;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      try {
        return await api.byoaTurn(byoaContest, payload);
      } catch (reason) {
        last = reason;
        const indexedWait =
          reason instanceof ApiClientError &&
          reason.status === 409 &&
          String(reason.detail).includes("indexed");
        if (!indexedWait) throw reason;
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
      }
    }
    throw last instanceof Error ? last : new Error(t("Indexer timeout", "索引器超时"));
  }

  if (!isConnected || !address) {
    return (
      <div className="page page--defend">
        <SectionHeader
          eyebrow="BYOA / SEALED ARENA"
          title={t("Bring your own payment agent", "守方自带支付 agent")}
          description={t(
            "Register a sealed bundle, issue delegated payment tasks and attack through an end-to-end encrypted channel.",
            "注册密封 bundle、下发委托付款任务，并通过端到端加密信道发起攻击。",
          )}
        />
        <ConnectPrompt />
      </div>
    );
  }

  const tierBadge =
    attestationTier === 1 ? (
      <Badge tone="success" dot>
        {t("Hardware attestation", "硬件证明")}
      </Badge>
    ) : (
      <Badge tone="warning" dot>
        {t("Simulated proof", "模拟证明")}
      </Badge>
    );

  return (
    <div className="page page--byoa">
      <SectionHeader
        eyebrow="BYOA / SEALED ARENA"
        title={t("Bring your own payment agent", "守方自带支付 agent")}
        description={t(
          "In the simulator, W and the TEE signer live in the sealed runtime object. The platform sees only public commitments, ciphertext hashes and policy fingerprints.",
          "模拟器中 W 与 TEE 签名者都只在密封运行时对象内。平台只看到公开承诺、密文 hash 与策略指纹。",
        )}
        actions={
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Badge tone="warning">{t("Simulator tier", "模拟器档位")}</Badge>
            {addresses?.taskSink ? (
              <Badge tone="success" dot>
                TaskSink {shortAddr(addresses.taskSink)}
              </Badge>
            ) : (
              <Badge tone="danger">{t("TaskSink missing", "缺少 TaskSink")}</Badge>
            )}
          </div>
        }
      />

      <Alert tone="warning" title={t("Read this before using BYOA", "使用 BYOA 前请阅读")}>
        {t(
          "The local simulator validates the flow only; it provides no hardware confidentiality. Attack plaintext is decrypted inside the TEE process, and the relay view never receives it. All funds are testnet tRTM.",
          "本地模拟器只验证流程，不提供硬件保密。攻击明文只在 TEE 进程内解密，中继视图不会收到明文。全部资金为测试网 tRTM。",
        )}
      </Alert>
      {meta.features.byoa === false && (
        <Alert tone="error" title={t("TaskSink is not deployed", "TaskSink 尚未部署")}>
          {t(
            "The running registry has no TaskSink, so BYOA contests cannot be created until the stack is redeployed. Bundle registration is still available for dry runs.",
            "运行中的 registry 没有 TaskSink，重新部署前无法创建 BYOA 赛。Bundle 注册仍可用于演练。",
          )}
        </Alert>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 14 }}>
        <Panel
          eyebrow="STEP 1 / BUNDLE"
          title={t("Sealed defender bundle", "密封守方 Bundle")}
          description={t(
            "The platform records a commitment; the image, policy and transport secret stay off-chain.",
            "平台只记录承诺；镜像、策略与传输密钥不进入公开存储。",
          )}
        >
          <div className="field-row" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
            <SelectField
              label={t("Transport", "接入方式")}
              value={transportKind}
              onChange={(event) => setTransportKind(event.target.value)}
              options={[
                { value: "hosted-mcp", label: "hosted-mcp" },
                { value: "a2a", label: "a2a" },
                { value: "webhook", label: "webhook" },
                { value: "mcp-pull", label: "mcp-pull" },
              ]}
            />
            <TextField
              label={t("Defender endpoint", "守方端点")}
              value={endpoint}
              onChange={(event) => setEndpoint(event.target.value)}
              hint={t("CVM-internal URL; the relay never calls it.", "CVM 内部地址；中继不会直接调用。")}
            />
            {transportKind === "webhook" && (
              <TextField
                label={t("Webhook secret", "Webhook 密钥")}
                value={transportSecret}
                onChange={(event) => setTransportSecret(event.target.value)}
                type="password"
              />
            )}
            <TextField
              label={t("Image digest", "镜像 digest")}
              value={imageDigest}
              onChange={(event) => setImageDigest(event.target.value)}
            />
            <TextField
              label={t("Model hosts (comma separated)", "模型主机（逗号分隔）")}
              value={egressModels}
              onChange={(event) => setEgressModels(event.target.value)}
            />
            <TextField
              label={t("Per-transaction limit (tRTM)", "单笔额度（tRTM）")}
              value={perTxLimit}
              onChange={(event) => setPerTxLimit(event.target.value)}
            />
            <TextField
              label={t("Total limit (tRTM)", "累计额度（tRTM）")}
              value={totalLimit}
              onChange={(event) => setTotalLimit(event.target.value)}
            />
            <TextField
              label={t("Largest owner task (tRTM)", "最大主人任务（tRTM）")}
              value={maxTaskAmount}
              onChange={(event) => setMaxTaskAmount(event.target.value)}
            />
            <CheckboxField
              checked={defenderConsent}
              onChange={setDefenderConsent}
            >
              {t(
                "Authorize the platform to keep replies and tool traces after the contest",
                "允许平台在赛后保留回复和工具轨迹",
              )}
            </CheckboxField>
          </div>
          {registerError && <Alert tone="error">{registerError}</Alert>}
          <Button loading={registering} onClick={() => void registerBundle()} iconLeft={<KeyRound size={14} />}>
            {t("Sign ownership proof and register", "签署所有权证明并注册")}
          </Button>

          {bundle && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <Badge tone="success" dot>
                  {bundle.attestation_tier}
                </Badge>
                <Badge tone="neutral">W {shortAddr(bundle.wallet)}</Badge>
                <Badge tone="neutral">TEE {shortAddr(bundle.tee_signer)}</Badge>
              </div>
              <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 12px", margin: 0 }}>
                <dt>Commitment</dt>
                <dd className="mono">{shortHash(bundle.commitment)}</dd>
                <dt>{t("Measurement", "运行时度量")}</dt>
                <dd className="mono">{shortHash(bundle.runtime_measurement)}</dd>
                <dt>{t("Policy fingerprint", "策略指纹")}</dt>
                <dd className="mono">{shortHash(bundle.policy_fingerprint)}</dd>
              </dl>
            </div>
          )}
        </Panel>

        <Panel
          eyebrow="STEP 2 / CONTEST"
          title={t("Create a stake-backed BYOA contest", "创建带质押的 BYOA 赛")}
          description={t(
            "The defender mandate binds W, the TEE signer, the runtime measurement and the utility penalty.",
            "守方委托签名绑定 W、TEE 签名者、运行时度量与效用罚没条款。",
          )}
        >
          <div className="field-row" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
            <TextField label={t("Stake (tRTM)", "质押（tRTM）")} value={stake} onChange={(event) => setStake(event.target.value)} />
            <TextField
              label={t("Duration (hours)", "时长（小时）")}
              type="number"
              value={durationHours}
              onChange={(event) => setDurationHours(Number(event.target.value))}
            />
            <TextField
              label={t("Attacker stake (bps)", "攻方质押（bps）")}
              type="number"
              value={stakeBps}
              onChange={(event) => setStakeBps(Number(event.target.value))}
            />
            <TextField
              label={t("Missed-task threshold", "漏做任务阈值")}
              type="number"
              value={missThreshold}
              onChange={(event) => setMissThreshold(Number(event.target.value))}
            />
            <TextField
              label={t("Utility penalty (bps)", "效用罚没（bps）")}
              type="number"
              value={penaltyBps}
              onChange={(event) => setPenaltyBps(Number(event.target.value))}
            />
          </div>
          {createError && <Alert tone="error">{createError}</Alert>}
          <Button
            loading={creating}
            disabled={!bundle || meta.features.byoa === false}
            onClick={() => void createContest()}
            iconLeft={<ShieldCheck size={14} />}
          >
            {t("Approve stake and sign mandate", "授权质押并签署委托")}
          </Button>
          {defenderContest && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
              <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 12px", margin: 0 }}>
                <dt>{t("Contest", "比赛")}</dt>
                <dd className="mono">{shortHash(defenderContest.contest_id)}</dd>
                <dt>TaskSink</dt>
                <dd>
                  <AddressChip value={defenderContest.task_sink} />
                </dd>
                <dt>{t("Ends", "结束")}</dt>
                <dd>{new Date(defenderContest.end * 1000).toLocaleString()}</dd>
              </dl>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <Button size="sm" variant="secondary" loading={taskBusy} onClick={() => void generateTasks()}>
                  <Sparkles size={13} /> {t("Issue 3 owner tasks", "下发 3 个主人任务")}
                </Button>
                <Button size="sm" variant="ghost" loading={finalizing} onClick={() => void finalizeContest()}>
                  {t("Finalize and adjudicate", "结算与裁判")}
                </Button>
              </div>
            </div>
          )}
        </Panel>
      </div>

      {defenderContest && (
        <Panel
          eyebrow="DEFENDER VIEW"
          title={t("Sealed runtime state", "密封运行时状态")}
          description={t(
            "Only commitments, hashes and aggregate utility are visible here.",
            "这里只展示承诺、hash 与聚合效用。",
          )}
        >
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 10 }}>
            <Stat label={t("Attestation", "证明档位")} value={attestationTier === 1 ? "hardware" : "simulated"} />
            <Stat label={t("Tasks issued", "已下发任务")} value={String(stateQuery.data?.utility.issued ?? "—")} />
            <Stat label={t("Completed", "已完成")} value={String(stateQuery.data?.utility.completed ?? "—")} />
            <Stat
              label={t("Expired", "已过期")}
              value={String(stateQuery.data?.utility.expired ?? "—")}
              tone={stateQuery.data?.utility.breached ? "danger" : "neutral"}
            />
            <Stat label={t("Encryption", "加密")} value={stateQuery.data?.encryption ?? "—"} />
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
            <Badge tone="neutral">
              {t("Manifest", "清单")} {shortHash(String(stateQuery.data?.config_commitment ?? ""))}
            </Badge>
            <Badge tone="neutral">
              {t("Policy", "策略")} {shortHash(String(stateQuery.data?.policy_fingerprint ?? ""))}
            </Badge>
            <Badge tone="warning">{t("Simulated TEE", "模拟 TEE")}</Badge>
          </div>
          {stateQuery.data && (
            <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 12px", margin: "8px 0 0" }}>
              <dt>{t("Egress models", "出网模型")}</dt>
              <dd className="mono">{stateQuery.data.egress.models.join(", ") || "—"}</dd>
              <dt>{t("Transcript entries", "对话条目")}</dt>
              <dd>{stateQuery.data.transcript.length}</dd>
              <dt>{t("Wallet audit entries", "钱包审计条目")}</dt>
              <dd>{stateQuery.data.wallet_audit.length}</dd>
            </dl>
          )}
        </Panel>
      )}

      <Panel
        eyebrow="ATTACKER VIEW"
        title={t("End-to-end encrypted attack", "端到端加密攻击")}
        description={t(
          "Your message is encrypted to the on-chain TEE public key. The relay verifies keccak(ciphertext) and never sees plaintext.",
          "消息加密到链上 TEE 公钥。中继只核验 keccak(密文)，看不到明文。",
        )}
      >
        <div className="field-row" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
          <TextField
            label={t("BYOA contest id", "BYOA 比赛 id")}
            value={attackContestId}
            onChange={(event) => setAttackContestId(event.target.value)}
            placeholder="0x..."
          />
        </div>
        {validContest && info && !isByoa && (
          <Alert tone="error">{t("This contest is not BYOA.", "这不是 BYOA 比赛。")}</Alert>
        )}
        {validContest && info && isByoa && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              {tierBadge}
              <Badge tone="neutral">TEE {shortAddr(String(teeSigner))}</Badge>
              <Badge tone={joinConsentValue ? "success" : "neutral"}>
                {joinConsentValue ? t("Attack data shareable", "攻击数据可共享") : t("Attack data private", "攻击数据私密")}
              </Badge>
            </div>
            {!isJoined && (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <CheckboxField checked={joinConsent} onChange={setJoinConsent}>
                  {t(
                    "I consent to my attack data entering the data market (optional)",
                    "我同意攻击数据进入数据市场（可选）",
                  )}
                </CheckboxField>
                <Button loading={joining} onClick={() => void joinContest()} iconLeft={<Wallet size={14} />}>
                  {t("Approve and join", "授权并加入")}
                </Button>
              </div>
            )}
            {isJoined && (
              <>
                <div className="chat__log">
                  {chat.length === 0 && (
                    <p className="muted">
                      {t("No messages yet. The ciphertext is sent only after the on-chain payment is indexed.", "还没有消息。链上付费被索引后才会发送密文。")}
                    </p>
                  )}
                  {chat.map((item, index) => (
                    <div key={`${item.role}-${index}`} className={`bubble bubble--${item.role}`}>
                      <div className="bubble__meta">
                        <span className="bubble__role">{item.role === "attacker" ? t("You", "你") : t("Defender", "守方")}</span>
                        {item.verified !== undefined && (
                          <Badge tone={item.verified ? "success" : "danger"}>
                            {item.verified ? t("TEE signature verified", "TEE 签名已验证") : t("Signature invalid", "签名无效")}
                          </Badge>
                        )}
                      </div>
                      <p>{item.text}</p>
                      {item.hash && <span className="mono muted">{shortHash(item.hash)}</span>}
                    </div>
                  ))}
                </div>
                <TextAreaField
                  label={t("Attack message", "攻击消息")}
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  maxLength={1000}
                  hint={t("Encrypted in the browser before the on-chain payment.", "在浏览器内加密后再发起链上付费。")}
                />
                {attackError && <Alert tone="error">{attackError}</Alert>}
                <Button loading={sending} onClick={() => void sendAttack()} iconLeft={<Send size={14} />}>
                  {t("Encrypt, pay and send", "加密、付费并发送")}
                </Button>
              </>
            )}
          </div>
        )}
      </Panel>
    </div>
  );
}
