import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Clock3,
  Droplets,
  Fuel,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type { Address } from "viem";
import { useAccount, useChainId } from "wagmi";
import { api, type FaucetTicket } from "../lib/api";
import { faucetAbi } from "../lib/contracts";
import { errorText, formatCountdown, formatRtm } from "../lib/format";
import { isSupportedChain } from "../lib/chain";
import { useI18n } from "../lib/i18n";
import { useLocalStorage, useNow } from "../lib/hooks";
import {
  useFaucetDrip,
  useFaucetNonce,
  usePlatform,
  useRtmBalance,
} from "../lib/platform";
import { useArenaWriteContract } from "../lib/useArenaWriteContract";
import { useActivity } from "../context/ActivityContext";
import { useToast } from "../context/ToastContext";
import { AddressChip } from "../components/ui/Address";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { InfoTip } from "../components/ui/InfoTip";
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
  const { writeContractAsync } = useArenaWriteContract();
  const { trackTransaction } = useActivity();
  const { toast } = useToast();
  const { t } = useI18n();
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

  const ticketHelp = t(
    "A ticket is a signed EIP-712 authorization, not a token. It is bound to this wallet, one nonce and an expiry time. It can be used for one on-chain claim before the 10-minute deadline. An expired ticket costs nothing; clicking claim again issues a new one.",
    "票据是一张 EIP-712 签名授权，不是代币。它绑定当前钱包、一个 nonce 和到期时间；必须在 10 分钟内完成一次链上 claim。票据过期不会产生费用，重新点击领取会自动换发新票。",
  );

  async function claim() {
    setError("");
    if (!address) {
      setError(t("Connect a wallet first.", "请先连接钱包。"));
      return;
    }
    if (!isSupportedChain(chainId)) {
      setError(t("Switch to RTM Testnet (48850) first.", "请先切换到 RTM Testnet（48850）。"));
      return;
    }
    if (cooldownActive) {
      setError(t("This address is still in its 24-hour cooldown.", "这个地址还在 24 小时冷却期内。"));
      return;
    }
    if (meta.faucet.captchaRequired && !captcha.trim()) {
      setError(t("This deployment requires a captcha token.", "平台要求验证码；请填写验证码 token。"));
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
      await trackTransaction(hash, t("Claim test tRTM", "领取测试 tRTM"), "faucet");
      setStep("done");
      setTicket(null);
      setLastClaim(Math.floor(Date.now() / 1_000));
      setJustClaimed(true);
      window.setTimeout(() => setJustClaimed(false), 4_000);
      toast({
        title: t("Claim confirmed", "领取成功"),
        description: t(
          `${formatRtm(dripWei)} tRTM credited to your wallet.`,
          `${formatRtm(dripWei)} tRTM 已到账。`,
        ),
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
        eyebrow={t("Testnet faucet", "测试网水龙头")}
        title={
          <>
            {t("Claim test", "领取测试")} <em>tRTM</em>
          </>
        }
        description={t(
          "Each address can claim a fixed amount every 24 hours. tRTM is a test token with no real value, and this testnet charges zero gas.",
          "每个地址每 24 小时可领取固定额度。tRTM 是无真实价值的测试币，测试网 gas 为 0。",
        )}
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
              <p className="mono">FAUCET // tRTM</p>
              <h2>{t("Test token claim", "测试币领取")}</h2>
            </div>
            <span className="faucet-card__icon" aria-hidden="true">
              <Droplets size={22} />
            </span>
          </div>

          <div className="faucet-amount">
            <span className="faucet-amount__value tabular">{formatRtm(dripWei)}</span>
            <span className="faucet-amount__unit">tRTM</span>
            <span className="faucet-amount__cadence">/ 24h</span>
          </div>

          <div className="faucet-stats">
            <div>
              <span>{t("Wallet", "当前钱包")}</span>
              <strong>
                {address ? <AddressChip value={address} /> : t("Not connected", "未连接")}
              </strong>
            </div>
            <div>
              <span><span className="preserve-case">tRTM</span> {t("balance", "余额")}</span>
              <strong className="tabular">{formatRtm(balance.data)}</strong>
            </div>
            <div>
              <span>
                {t("On-chain nonce", "链上 nonce")}
                <InfoTip label={t("on-chain nonce", "链上 nonce")}>
                  {t(
                    "The faucet keeps a strictly increasing counter per wallet. A ticket must use a number greater than the last one, which prevents the same authorization from being claimed twice.",
                    "水龙头会为每个钱包维护一个严格递增的计数器。新票据必须使用比上次更大的数字，从而防止同一张授权被重复领取。",
                  )}
                </InfoTip>
              </span>
              <strong className="tabular">{nonce.data !== undefined ? String(nonce.data) : "—"}</strong>
            </div>
            <div>
              <span>
                {t("Cooldown", "冷却")}
                <InfoTip label={t("cooldown", "冷却")}>
                  {t(
                    "Measured from the last successful on-chain claim, not from the button click. A wallet can claim once every 24 hours.",
                    "从上一次链上成功 claim 的时间开始计算，不是从点击按钮开始。每个钱包每 24 小时只能领取一次。",
                  )}
                </InfoTip>
              </span>
              <strong className={cooldownActive ? "is-warning" : ""}>
                {cooldownActive
                  ? formatCountdown(cooldownLeft * 1_000)
                  : t("Available", "可领取")}
              </strong>
            </div>
          </div>

          {meta.faucet.captchaRequired && (
            <TextField
              label={t("Captcha token", "验证码 token")}
              value={captcha}
              onChange={(event) => setCaptcha(event.target.value)}
              placeholder={t("Paste the token from your captcha provider", "粘贴验证码服务返回的 token")}
              hint={t(
                "Production captcha widgets should fill this automatically.",
                "生产环境应由验证码组件自动填充",
              )}
            />
          )}

          {!ready ? (
            <ConnectPrompt
              compact
              title={t("Connect a wallet to claim", "连接钱包领取")}
              description={t(
                "The ticket is bound to the claiming address; only you can submit it.",
                "票据与领取地址绑定，只能由本人 claim。",
              )}
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
                ? `${t("Cooldown", "冷却中")} · ${formatCountdown(cooldownLeft * 1_000)}`
                : claiming
                  ? t("Claiming…", "领取中…")
                  : t(`Claim ${formatRtm(dripWei)} tRTM`, `领取 ${formatRtm(dripWei)} tRTM`)}
            </Button>
          )}

          {step !== "idle" && (
            <div className="faucet-steps" aria-label={t("Claim steps", "领取步骤")}>
              <FaucetStep
                label={t("Issue ticket", "签发票据")}
                active={step === "ticket"}
                done={step === "claim" || step === "done"}
              />
              <span className="faucet-steps__line" />
              <FaucetStep
                label={t("On-chain claim", "链上 claim")}
                active={step === "claim"}
                done={step === "done"}
              />
              <span className="faucet-steps__line" />
              <FaucetStep
                label={t("Credited", "到账")}
                active={step === "done"}
                done={step === "done"}
              />
            </div>
          )}

          {error && (
            <Alert tone="error">
              {error}{" "}
              <Link to="/docs#troubleshooting" className="docs-inline-link">
                {t("Troubleshooting", "故障排查")}
              </Link>
            </Alert>
          )}

          {ticket && ticketExpiry > 0 && (
            <p className="faucet-ticket mono">
              TICKET {ticket.to.slice(0, 6)}…{ticket.to.slice(-4)} · NONCE {ticket.nonce} ·{" "}
              {t("valid for", "有效")} {formatCountdown(ticketExpiry)}
              <InfoTip label={t("ticket validity", "票据有效期")}>{ticketHelp}</InfoTip>
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
          <Panel eyebrow={<>{t("What is", "了解")} <span className="preserve-case">tRTM</span></>} title={t("This is a test token", "这是测试币")} tone="flat">
            <div className="faucet-info-list">
              <div>
                <ShieldCheck size={15} />
                <span>
                  {t(
                    "tRTM is only used for testnet stakes, message fees and dataset purchases. It has no real value.",
                    "tRTM 只用于测试网质押、消息费与数据购买，没有真实价值。",
                  )}
                </span>
              </div>
              <div>
                <Fuel size={15} />
                <span>
                  {t(
                    "Network gas is zero. After claiming tRTM you do not need a separate native gas token.",
                    "网络 gas 为 0；领取 tRTM 后不需要再准备原生 gas 币。",
                  )}
                </span>
              </div>
              <div>
                <Clock3 size={15} />
                <span>
                  {t(
                    "One claim per address every 24 hours; each signed ticket is valid for 10 minutes.",
                    "同一地址每 24 小时只能领取一次；每张签名票据本身 10 分钟内有效。",
                  )}
                  <InfoTip label={t("ticket validity", "票据有效期")}>{ticketHelp}</InfoTip>
                </span>
              </div>
            </div>
          </Panel>

          <Panel eyebrow="Next step" title={t("After you claim", "领完以后")} tone="flat">
            <ol className="faucet-next">
              <li>
                <span className="mono">01</span>
                <div>
                  <strong>{t("Enter the arena", "进入竞技场")}</strong>
                  <p>
                    {t(
                      "Stake tRTM to join a standard contest, or challenge a mining contest.",
                      "用 tRTM 质押加入普通赛，或直接挑战挖矿赛。",
                    )}
                  </p>
                </div>
                <Link to="/arena" className="faucet-next__link" aria-label={t("Open arena", "进入竞技场")}>
                  <ArrowRight size={13} />
                </Link>
              </li>
              <li>
                <span className="mono">02</span>
                <div>
                  <strong>{t("Register a defender", "注册守方")}</strong>
                  <p>
                    {t(
                      "Bring your own model key and stake a contest of your own.",
                      "自带模型 Key，质押开一场自己的比赛。",
                    )}
                  </p>
                </div>
                <Link to="/defend" className="faucet-next__link" aria-label={t("Open defender workspace", "打开守方工作区")}>
                  <ArrowRight size={13} />
                </Link>
              </li>
              <li>
                <span className="mono">03</span>
                <div>
                  <strong>{t("Read the field manual", "阅读使用文档")}</strong>
                  <p>
                    {t(
                      "Understand the rules, roles, data boundaries and recovery steps.",
                      "了解规则、角色、数据边界和故障恢复步骤。",
                    )}
                  </p>
                </div>
                <Link to="/docs" className="faucet-next__link" aria-label={t("Read the guide", "阅读使用文档")}>
                  <BookOpen size={13} />
                </Link>
              </li>
            </ol>
          </Panel>

          <div className="faucet-spark">
            <Sparkles size={14} />
            <span>
              {t(
                "Testnet assets have no value. Never buy tRTM from anyone.",
                "测试网资产无价值。不要向任何人购买 tRTM。",
              )}
            </span>
          </div>
        </aside>
      </div>

      <div className="stat-strip faucet-strip">
        <Stat
          label={t("Per claim", "单次额度")}
          value={`${formatRtm(dripWei)} tRTM`}
          icon={<Droplets size={14} />}
        />
        <Stat
          label={
            <>
              {t("Cooldown", "冷却")}
              <InfoTip label={t("cooldown", "冷却")}>
                {t(
                  "Starts after a successful on-chain claim; one claim per wallet per 24 hours.",
                  "成功完成链上 claim 后开始计时；每个钱包每 24 小时可领取一次。",
                )}
              </InfoTip>
            </>
          }
          value={t("24 hours", "24 小时")}
          icon={<Clock3 size={14} />}
        />
        <Stat
          label={
            <>
              {t("Ticket validity", "票据有效期")}
              <InfoTip label={t("ticket validity", "票据有效期")}>{ticketHelp}</InfoTip>
            </>
          }
          value={t("10 minutes", "10 分钟")}
          icon={<Clock3 size={14} />}
        />
        <Stat label={t("Network gas", "网络 gas")} value="0 G" icon={<Fuel size={14} />} />
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
