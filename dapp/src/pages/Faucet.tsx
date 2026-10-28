import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  CheckCircle2,
  Clock3,
  Droplets,
  Fuel,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type { Address } from "viem";
import { useAccount, useChainId, useWriteContract } from "wagmi";
import { api, type FaucetTicket } from "../lib/api";
import { faucetAbi } from "../lib/contracts";
import {
  errorText,
  formatCountdown,
  formatRtm,
  formatRtmUnit,
  shortAddr,
} from "../lib/format";
import { isSupportedChain } from "../lib/chain";
import { useLocalStorage, useNow } from "../lib/hooks";
import {
  useFaucetDrip,
  useFaucetNonce,
  usePlatform,
  useRtmBalance,
} from "../lib/platform";
import { useActivity } from "../context/ActivityContext";
import { useToast } from "../context/ToastContext";
import { AddressChip } from "../components/ui/Address";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Panel } from "../components/ui/Panel";
import { SectionHeader } from "../components/ui/SectionHeader";
import { Stat } from "../components/ui/Stat";
import { TextField } from "../components/ui/Field";
import { ConnectPrompt } from "../components/wallet/ConnectPrompt";

type ClaimStep = "idle" | "ticket" | "claim" | "done";

const COOLDOWN_SECONDS = 24 * 60 * 60;

export default function Faucet() {
  const { address, isConnected } = useAccount();
  const chainId = useChainId();
  const { meta } = usePlatform();
  const { writeContractAsync } = useWriteContract();
  const { trackTransaction } = useActivity();
  const { toast } = useToast();
  const balance = useRtmBalance(address);
  const nonce = useFaucetNonce(address);
  const drip = useFaucetDrip();
  const now = useNow(1_000);
  const [captcha, setCaptcha] = useState("");
  const [ticket, setTicket] = useState<FaucetTicket | null>(null);
  const [claiming, setClaiming] = useState(false);
  const [step, setStep] = useState<ClaimStep>("idle");
  const [error, setError] = useState("");
  const [justClaimed, setJustClaimed] = useState(false);
  const [lastClaim, setLastClaim] = useLocalStorage<number | null>(
    `rtm.faucet.lastClaim.v1:${chainId}:${address?.toLowerCase() ?? "guest"}`,
    null,
  );

  const dripWei = drip.data ?? BigInt(meta.faucet.dripAmountWei || "0");
  const cooldownLeft = useMemo(() => {
    if (!lastClaim) return 0;
    return Math.max(0, lastClaim + COOLDOWN_SECONDS - Math.floor(now / 1_000));
  }, [lastClaim, now]);
  const cooldownActive = cooldownLeft > 0;
  const ready = isConnected && isSupportedChain(chainId);
  const ticketExpiry = ticket ? ticket.deadline * 1_000 - now : 0;

  async function claim() {
    setError("");
    if (!address) {
      setError("请先连接钱包。");
      return;
    }
    if (!isSupportedChain(chainId)) {
      setError("请先切换到 RTM Testnet（48850）。");
      return;
    }
    if (cooldownActive) {
      setError("这个地址还在 24 小时冷却期内。");
      return;
    }
    if (meta.faucet.captchaRequired && !captcha.trim()) {
      setError("平台要求验证码；请填写验证码 token。");
      return;
    }
    setClaiming(true);
    try {
      let activeTicket = ticket;
      if (
        !activeTicket ||
        activeTicket.to.toLowerCase() !== address.toLowerCase() ||
        activeTicket.deadline * 1_000 <= Date.now()
      ) {
        setStep("ticket");
        activeTicket = await api.faucetTicket(address, captcha.trim() || undefined);
        setTicket(activeTicket);
      }
      setStep("claim");
      const hash = await writeContractAsync({
        address: meta.addresses.faucet as Address,
        abi: faucetAbi,
        functionName: "claim",
        args: [
          {
            to: activeTicket.to as Address,
            nonce: BigInt(activeTicket.nonce),
            deadline: BigInt(activeTicket.deadline),
          },
          activeTicket.signature as `0x${string}`,
        ],
      });
      await trackTransaction(hash, "领取测试 RTM", "faucet");
      setStep("done");
      setTicket(null);
      setLastClaim(Math.floor(Date.now() / 1_000));
      setJustClaimed(true);
      window.setTimeout(() => setJustClaimed(false), 4_000);
      toast({
        title: "领取成功",
        description: `${formatRtm(dripWei)} RTM 已到账。`,
        tone: "success",
      });
      await Promise.all([balance.refetch(), nonce.refetch()]);
    } catch (reason) {
      setError(errorText(reason));
      setStep("idle");
    } finally {
      setClaiming(false);
    }
  }

  return (
    <div className="faucet-page">
      <SectionHeader
        eyebrow="Testnet faucet / 水龙头"
        title={
          <>
            领取测试 <em>RTM</em>
          </>
        }
        description="每个地址每 24 小时可领取固定额度。RTM 是测试网游戏代币，没有真实价值；测试网 gas 为 0。"
        actions={
          <Badge tone="accent" dot>
            ZERO GAS NETWORK
          </Badge>
        }
      />

      <div className="faucet-layout">
        <section className={`faucet-card ${justClaimed ? "is-claimed" : ""}`.trim()}>
          <div className="faucet-card__glow" aria-hidden="true" />
          <div className="faucet-card__head">
            <div>
              <p className="mono">FAUCET // RTM</p>
              <h2>测试币领取</h2>
            </div>
            <span className="faucet-card__icon" aria-hidden="true">
              <Droplets size={22} />
            </span>
          </div>

          <div className="faucet-amount">
            <span className="faucet-amount__value tabular">{formatRtm(dripWei)}</span>
            <span className="faucet-amount__unit">RTM</span>
            <span className="faucet-amount__cadence">/ 24h</span>
          </div>

          <div className="faucet-stats">
            <div>
              <span>当前钱包</span>
              <strong>
                {address ? <AddressChip value={address} /> : "未连接"}
              </strong>
            </div>
            <div>
              <span>RTM 余额</span>
              <strong className="tabular">{formatRtm(balance.data)}</strong>
            </div>
            <div>
              <span>链上 nonce</span>
              <strong className="tabular">{nonce.data !== undefined ? String(nonce.data) : "—"}</strong>
            </div>
            <div>
              <span>冷却</span>
              <strong className={cooldownActive ? "is-warning" : ""}>
                {cooldownActive ? formatCountdown(cooldownLeft * 1_000) : "可领取"}
              </strong>
            </div>
          </div>

          {meta.faucet.captchaRequired && (
            <TextField
              label="验证码 token"
              value={captcha}
              onChange={(event) => setCaptcha(event.target.value)}
              placeholder="粘贴验证码服务返回的 token"
              hint="生产环境应由验证码组件自动填充"
            />
          )}

          {!ready ? (
            <ConnectPrompt
              compact
              title="连接钱包领取"
              description="票据与领取地址绑定，只能由本人 claim。"
            />
          ) : (
            <Button
              block
              size="lg"
              loading={claiming}
              disabled={cooldownActive}
              iconLeft={<Droplets size={16} />}
              onClick={() => void claim()}
            >
              {cooldownActive
                ? `冷却中 · ${formatCountdown(cooldownLeft * 1_000)}`
                : claiming
                  ? "领取中…"
                  : `领取 ${formatRtm(dripWei)} RTM`}
            </Button>
          )}

          {step !== "idle" && (
            <div className="faucet-steps" aria-label="领取步骤">
              <FaucetStep label="签发票据" active={step === "ticket"} done={step === "claim" || step === "done"} />
              <span className="faucet-steps__line" />
              <FaucetStep label="链上 claim" active={step === "claim"} done={step === "done"} />
              <span className="faucet-steps__line" />
              <FaucetStep label="到账" active={step === "done"} done={step === "done"} />
            </div>
          )}

          {error && <Alert tone="error">{error}</Alert>}

          {ticket && ticketExpiry > 0 && (
            <p className="faucet-ticket mono">
              TICKET {shortAddr(ticket.to)} · NONCE {ticket.nonce} · 有效{" "}
              {formatCountdown(ticketExpiry)}
            </p>
          )}

          {justClaimed && (
            <div className="claim-stamp" aria-live="polite">
              <CheckCircle2 size={18} />
              CLAIMED
            </div>
          )}
        </section>

        <aside className="faucet-side">
          <Panel eyebrow="What is RTM" title="这是测试币" tone="flat">
            <div className="faucet-info-list">
              <div>
                <ShieldCheck size={15} />
                <span>RTM 只用于测试网游戏质押、消息费与数据购买，没有真实价值。</span>
              </div>
              <div>
                <Fuel size={15} />
                <span>网络 gas 为 0；领取 RTM 后不需要再准备原生 gas 币。</span>
              </div>
              <div>
                <Clock3 size={15} />
                <span>同一地址每 24 小时只能领取一次；票据本身 10 分钟内有效。</span>
              </div>
            </div>
          </Panel>

          <Panel eyebrow="Next step" title="领完以后" tone="flat">
            <ol className="faucet-next">
              <li>
                <span className="mono">01</span>
                <div>
                  <strong>进入竞技场</strong>
                  <p>用 RTM 质押加入普通赛，或直接挑战挖矿赛。</p>
                </div>
                <Link to="/arena" className="faucet-next__link">
                  <ArrowRight size={13} />
                </Link>
              </li>
              <li>
                <span className="mono">02</span>
                <div>
                  <strong>注册守方</strong>
                  <p>自带模型 Key，质押开一场自己的比赛。</p>
                </div>
                <Link to="/defend" className="faucet-next__link">
                  <ArrowRight size={13} />
                </Link>
              </li>
              <li>
                <span className="mono">03</span>
                <div>
                  <strong>查看排行</strong>
                  <p>看看谁在赢，以及攻破率如何变化。</p>
                </div>
                <Link to="/leaderboard" className="faucet-next__link">
                  <ArrowRight size={13} />
                </Link>
              </li>
            </ol>
          </Panel>

          <div className="faucet-spark">
            <Sparkles size={14} />
            <span>测试网资产无价值。不要向任何人购买 RTM。</span>
          </div>
        </aside>
      </div>

      <div className="stat-strip faucet-strip">
        <Stat label="单次额度" value={formatRtmUnit(dripWei)} icon={<Droplets size={14} />} />
        <Stat label="冷却" value="24 小时" icon={<Clock3 size={14} />} />
        <Stat label="票据有效期" value="10 分钟" icon={<Clock3 size={14} />} />
        <Stat label="网络 gas" value="0 G" icon={<Fuel size={14} />} />
      </div>
    </div>
  );
}

function FaucetStep({ label, active, done }: { label: string; active: boolean; done: boolean }) {
  return (
    <span className={`faucet-step ${active ? "is-active" : ""} ${done ? "is-done" : ""}`.trim()}>
      <span className="faucet-step__dot">{done ? <CheckCircle2 size={10} /> : null}</span>
      {label}
    </span>
  );
}
