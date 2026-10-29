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
import { useAccount, useSignMessage } from "wagmi";
import { api } from "../lib/api";
import { errorText, formatCountdown, formatRtm } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { useLocalStorage, useNow } from "../lib/hooks";
import { useFaucetDrip, usePlatform, useRtmBalance } from "../lib/platform";
import { useToast } from "../context/ToastContext";
import { AddressChip } from "../components/ui/Address";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { InfoTip } from "../components/ui/InfoTip";
import { Panel } from "../components/ui/Panel";
import { SectionHeader } from "../components/ui/SectionHeader";
import { Stat } from "../components/ui/Stat";
import { ConnectPrompt } from "../components/wallet/ConnectPrompt";

type ClaimStep = "idle" | "sign" | "relay" | "done";

const COOLDOWN_SECONDS = 24 * 60 * 60;

function randomNonce(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return `0x${Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

function claimMessage(to: string, issuedAt: number, nonce: string): string {
  return [
    "RTM Arena testnet faucet claim",
    `address: ${to.toLowerCase()}`,
    `issued-at: ${issuedAt}`,
    `nonce: ${nonce.toLowerCase()}`,
  ].join("\n");
}

export default function Faucet() {
  const { address, isConnected } = useAccount();
  const { signMessageAsync } = useSignMessage();
  const { meta } = usePlatform();
  const { toast } = useToast();
  const { t } = useI18n();
  const balance = useRtmBalance(address);
  const drip = useFaucetDrip();
  const now = useNow(1_000);
  const [claiming, setClaiming] = useState(false);
  const [step, setStep] = useState<ClaimStep>("idle");
  const [error, setError] = useState("");
  const [justClaimed, setJustClaimed] = useState(false);
  const [lastClaim, setLastClaim] = useLocalStorage<number | null>(
    `rtm.faucet.lastClaim.v2:${meta.chainId}:${address?.toLowerCase() ?? "guest"}`,
    null,
  );

  const dripWei = drip.data ?? BigInt(meta.faucet.dripAmountWei || "0");
  const cooldownLeft = useMemo(() => {
    if (!lastClaim) return 0;
    return Math.max(0, lastClaim + COOLDOWN_SECONDS - Math.floor(now / 1_000));
  }, [lastClaim, now]);
  const cooldownActive = cooldownLeft > 0;

  const signatureHelp = t(
    "You sign one human-readable message bound to this wallet and a one-time nonce. It is accepted for 5 minutes and authorizes one testnet claim. It is not a transaction: no gas and no network switch are required.",
    "你签一条绑定当前钱包和一次性 nonce 的明文消息。签名在 5 分钟内有效，只授权一次测试网领取。它不是交易：不需要 gas，也不需要切换钱包网络。",
  );
  const relayHelp = t(
    "After your signature, the platform submits the mint on the chain used by this application. Your wallet RPC is not used for the credit, so a stale local network cannot misroute it.",
    "签名后，平台会在本站使用的正确链上代为提交增发。到账过程不使用钱包 RPC，因此旧的本地网络配置不会把交易发错链。",
  );

  async function claim() {
    setError("");
    if (!address) {
      setError(t("Connect a wallet first.", "请先连接钱包。"));
      return;
    }
    if (cooldownActive) {
      setError(t("This address is still in its 24-hour cooldown.", "这个地址还在 24 小时冷却期内。"));
      return;
    }
    setClaiming(true);
    try {
      setStep("sign");
      const issuedAt = Math.floor(Date.now() / 1_000);
      const nonce = randomNonce();
      const signature = await signMessageAsync({
        message: claimMessage(address, issuedAt, nonce),
      });
      setStep("relay");
      const result = await api.faucetClaim({
        to: address,
        issued_at: issuedAt,
        nonce,
        signature,
      });
      setStep("done");
      setLastClaim(result.claimed_at || Math.floor(Date.now() / 1_000));
      setJustClaimed(true);
      window.setTimeout(() => setJustClaimed(false), 4_000);
      toast({
        title: t("Claim confirmed", "领取成功"),
        description: t(
          `${formatRtm(result.amount_wei)} tRTM credited. The platform submitted it on the correct chain.`,
          `${formatRtm(result.amount_wei)} tRTM 已到账。交易已由平台在正确的链上提交。`,
        ),
        tone: "success",
        duration: 6_000,
      });
      await balance.refetch();
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
          "Sign once and the platform credits you on the correct chain. No gas, no wallet transaction and no network switching.",
          "签一次名，平台在正确的链上代发到账。不需要 gas、不需要钱包交易，也不需要切换网络。",
        )}
        actions={
          <Badge tone="accent" dot>
            SIGN & CREDIT
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
                {t("Cooldown", "冷却")}
                <InfoTip label={t("cooldown", "冷却")}>
                  {t(
                    "One successful claim per wallet every 24 hours. The timer starts after the platform confirms the credit.",
                    "每个钱包每 24 小时只能成功领取一次。计时从平台确认到账后开始。",
                  )}
                </InfoTip>
              </span>
              <strong className={cooldownActive ? "is-warning" : ""}>
                {cooldownActive
                  ? formatCountdown(cooldownLeft * 1_000)
                  : t("Available", "可领取")}
              </strong>
            </div>
            <div>
              <span>
                {t("Delivery", "发放方式")}
                <InfoTip label={t("delivery", "发放方式")}>{relayHelp}</InfoTip>
              </span>
              <strong>{t("Platform relays", "平台代发")}</strong>
            </div>
          </div>

          {!isConnected ? (
            <ConnectPrompt
              compact
              title={t("Connect a wallet to claim", "连接钱包领取")}
              description={t(
                "You will sign one message; the platform submits the credit on the correct chain.",
                "你只需要签一条消息；到账交易由平台在正确的链上提交。",
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
                  ? step === "relay"
                    ? t("Crediting on-chain…", "平台正在上链…")
                    : t("Waiting for signature…", "等待签名…")
                  : t(`Sign & claim ${formatRtm(dripWei)} tRTM`, `签名领取 ${formatRtm(dripWei)} tRTM`)}
            </Button>
          )}

          {step !== "idle" && (
            <div className="faucet-steps" aria-label={t("Claim steps", "领取步骤")}>
              <FaucetStep
                label={t("Sign request", "签名授权")}
                active={step === "sign"}
                done={step === "relay" || step === "done"}
              />
              <span className="faucet-steps__line" />
              <FaucetStep
                label={t("Platform submits", "平台上链")}
                active={step === "relay"}
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

          <p className="faucet-ticket mono">
            {t(
              "Signed message · valid 5 min · no wallet transaction",
              "签名消息 · 5 分钟内有效 · 不需要钱包交易",
            )}
            <InfoTip label={t("signature validity", "签名有效期")}>{signatureHelp}</InfoTip>
          </p>

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
                    "No gas and no wallet transaction: the platform submits the credit on this application's chain.",
                    "不需要 gas，也不需要钱包交易：平台会在本站使用的链上代发到账。",
                  )}
                  <InfoTip label={t("platform relay", "平台代发")}>{relayHelp}</InfoTip>
                </span>
              </div>
              <div>
                <Clock3 size={15} />
                <span>
                  {t(
                    "One signed message per address every 24 hours; each signature is valid for 5 minutes.",
                    "同一地址每 24 小时只需签一次消息；每次签名 5 分钟内有效。",
                  )}
                  <InfoTip label={t("signature validity", "签名有效期")}>{signatureHelp}</InfoTip>
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
                  "Starts after a confirmed credit; one claim per wallet per 24 hours.",
                  "平台确认到账后开始计时；每个钱包每 24 小时可领取一次。",
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
              {t("Signature validity", "签名有效期")}
              <InfoTip label={t("signature validity", "签名有效期")}>{signatureHelp}</InfoTip>
            </>
          }
          value={t("5 minutes", "5 分钟")}
          icon={<Clock3 size={14} />}
        />
        <Stat label={t("Gas paid", "支付 gas")} value="0 G" icon={<Fuel size={14} />} />
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
