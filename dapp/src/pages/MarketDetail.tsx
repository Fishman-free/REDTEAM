import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  CheckCircle2,
  Database,
  Download,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  ShoppingBag,
  TriangleAlert,
  Wallet,
} from "lucide-react";
import type { Address } from "viem";
import { useAccount } from "wagmi";
import {
  api,
  ApiClientError,
  type AttackerInfo,
  type DeliveryGrant,
} from "../lib/api";
import { dataMarketAbi, rtmAbi } from "../lib/contracts";
import {
  errorText,
  formatDateTime,
  formatRtm,
  formatRtmUnit,
  isZeroHash,
  shortAddr,
  stateLabel,
  timeAgo,
} from "../lib/format";
import { useLocalStorage } from "../lib/hooks";
import { useI18n } from "../lib/i18n";
import {
  useAllowance,
  useBoughtAttacker,
  useBoughtOwn,
  useContestQuery,
  useDataMarketPrices,
  useDatasetRoot,
  requireAddresses,
  usePlatform,
  useRtmBalance,
} from "../lib/platform";
import { CHAIN_ID, isSupportedChain } from "../lib/chain";
import { useWalletChainId } from "../lib/useWalletChainId";
import { useArenaWriteContract } from "../lib/useArenaWriteContract";
import { useActivity } from "../context/ActivityContext";
import { useToast } from "../context/ToastContext";
import { AddressChip } from "../components/ui/Address";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Dialog } from "../components/ui/Dialog";
import { EmptyState } from "../components/ui/EmptyState";
import { Panel } from "../components/ui/Panel";
import { Skeleton, SkeletonText } from "../components/ui/Skeleton";
import { Stat } from "../components/ui/Stat";
import { ConnectPrompt } from "../components/wallet/ConnectPrompt";

interface PurchaseRecord {
  kind: "own" | "attacker";
  attacker?: string;
  txHash: string;
  boughtAt: number;
  status: "pending" | "delivered" | "failed";
  grant?: DeliveryGrant;
  error?: string;
}

interface PendingPurchase {
  kind: "own" | "attacker";
  attacker?: string;
}

const sleep = (milliseconds: number) =>
  new Promise((resolve) => window.setTimeout(resolve, milliseconds));

function keyFor(kind: "own" | "attacker", attacker?: string): string {
  return kind === "own" ? "own" : `attacker:${attacker?.toLowerCase() ?? ""}`;
}

export default function MarketDetail() {
  const { contestId } = useParams();
  const query = useContestQuery(contestId);
  const contest = query.data?.contest;
  const detail = query.data;
  const { address, isConnected } = useAccount();
  const walletChainId = useWalletChainId();
  const { addresses } = usePlatform();
  const { writeContractAsync } = useArenaWriteContract();
  const { trackTransaction } = useActivity();
  const { toast } = useToast();
  const { t } = useI18n();
  const root = useDatasetRoot(contestId);
  const prices = useDataMarketPrices();
  const boughtOwn = useBoughtOwn(contestId, address);
  const allowance = useAllowance(address, addresses?.dataMarket);
  const balance = useRtmBalance(address);
  const [records, setRecords] = useLocalStorage<PurchaseRecord[]>(
    `rtm.market.purchases.v1:${CHAIN_ID}:${contestId?.toLowerCase() ?? "none"}:${address?.toLowerCase() ?? "guest"}`,
    [],
  );
  const [pending, setPending] = useState<PendingPurchase | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  const published = !isZeroHash(root.data);
  const isDefender =
    Boolean(address) && Boolean(contest) &&
    contest!.defender.toLowerCase() === address!.toLowerCase();
  const ended = Boolean(contest) && contest!.state !== "live";
  const correctChain = isSupportedChain(walletChainId);
  const ownPrice =
    contest && prices.priceBps !== undefined
      ? (BigInt(contest.stake) * prices.priceBps) / 10_000n
      : null;
  const attackerPrice = prices.attackerPrice;
  const purchaseReady = published && ended && isDefender && isConnected && correctChain;

  if (query.isLoading) {
    return (
      <div className="market-detail-loading">
        <Skeleton width={100} height={12} />
        <Skeleton width="48%" height={40} />
        <SkeletonText lines={2} />
        <div className="stat-strip">
          <Skeleton height={78} />
          <Skeleton height={78} />
          <Skeleton height={78} />
          <Skeleton height={78} />
        </div>
      </div>
    );
  }

  if (query.isError || !contest || !detail) {
    return (
      <EmptyState
        title={t("Dataset not found", "找不到这份数据集")}
        description={t(
          "The contest may not be indexed yet, or the link is invalid.",
          "比赛可能尚未被索引，或链接有误。",
        )}
        action={
          <div className="row-actions">
            <Link className="btn btn--ghost btn--sm" to="/market">
              <ArrowLeft size={13} />
              {t("Back to market", "返回市场")}
            </Link>
            <Button size="sm" onClick={() => void query.refetch()}>
              {t("Retry", "重试")}
            </Button>
          </div>
        }
      />
    );
  }

  const ownRecord = records.find((record) => record.kind === "own");
  const attackers = Object.entries(detail.attackers);

  function upsertRecord(record: PurchaseRecord) {
    setRecords((current) => {
      const key = keyFor(record.kind, record.attacker);
      const rest = current.filter((item) => keyFor(item.kind, item.attacker) !== key);
      return [record, ...rest];
    });
  }

  async function pollDelivery(txHash: string): Promise<DeliveryGrant> {
    let lastError: unknown = null;
    for (let attempt = 0; attempt < 15; attempt += 1) {
      try {
        return await api.deliver(contest!.id, txHash);
      } catch (reason) {
        lastError = reason;
        if (reason instanceof ApiClientError && [408, 409, 502].includes(reason.status)) {
          await sleep(2_000);
          continue;
        }
        throw reason;
      }
    }
    throw lastError ?? new Error(t("Delivery is not ready yet.", "交付尚未就绪"));
  }

  async function downloadGrant(grant: DeliveryGrant) {
    await api.download(
      grant.token,
      `${contest!.id.slice(0, 10)}-${grant.kind}.zip`,
    );
  }

  async function deliver(
    txHash: `0x${string}`,
    kind: "own" | "attacker",
    attacker?: string,
  ) {
    setStatus(
      t(
        "Waiting for the indexer to confirm DataSold and prepare the slices…",
        "等待索引器确认 DataSold 并准备切片…",
      ),
    );
    try {
      const grant = await pollDelivery(txHash);
      upsertRecord({
        kind,
        attacker,
        txHash,
        boughtAt: Math.floor(Date.now() / 1_000),
        status: "delivered",
        grant,
      });
      setStatus(t("Download started.", "下载已开始。"));
      await downloadGrant(grant);
      toast({
        title: t("Delivery complete", "数据交付完成"),
        description: t("The ZIP slice has started downloading.", "ZIP 切片已开始下载。"),
        tone: "success",
      });
    } catch (reason) {
      const message = errorText(reason);
      upsertRecord({
        kind,
        attacker,
        txHash,
        boughtAt: Math.floor(Date.now() / 1_000),
        status: "failed",
        error: message,
      });
      setStatus("");
      setError(message);
      toast({ title: t("Delivery failed", "交付未完成"), description: message, tone: "error" });
    }
  }

  async function buy(kind: "own" | "attacker", attacker?: string) {
    if (!contest || !address) return;
    const key = keyFor(kind, attacker);
    setError("");
    setStatus("");
    if (!purchaseReady) {
      setError(
        t(
          "Not eligible yet: the contest must have ended, the dataset must be published, and you must be this contest's defender.",
          "当前条件不满足：需要比赛结束、数据集已发布，且你是该场守方。",
        ),
      );
      return;
    }
    const price = kind === "own" ? ownPrice : attackerPrice;
    if (price === null || price === undefined) {
      setError(t("The price is still loading. Try again shortly.", "价格还在读取，请稍后重试。"));
      return;
    }
    setBusy(key);
    try {
      // The cached allowance may be from before an earlier purchase consumed
      // it; read it fresh or this buy reverts on-chain.
      const refreshed = await allowance.refetch();
      const available = refreshed.error ? 0n : refreshed.data ?? 0n;
      if (available < price) {
        const approvalHash = await writeContractAsync({
          address: requireAddresses(addresses).rtm,
          abi: rtmAbi,
          functionName: "approve",
          args: [requireAddresses(addresses).dataMarket, price],
        });
        await trackTransaction(approvalHash, t("Approve data payment", "授权数据费用"), "approve");
      }
      const hash = await writeContractAsync({
        address: requireAddresses(addresses).dataMarket,
        abi: dataMarketAbi,
        functionName: kind === "own" ? "buyOwn" : "buyFromAttacker",
        args:
          kind === "own"
            ? [contest.id as `0x${string}`]
            : [contest.id as `0x${string}`, attacker as Address],
      });
      await trackTransaction(
        hash,
        kind === "own" ? t("Buy defender data", "购买守方数据") : t("Buy attacker data", "购买攻方数据"),
        "data-buy",
      );
      upsertRecord({
        kind,
        attacker,
        txHash: hash,
        boughtAt: Math.floor(Date.now() / 1_000),
        status: "pending",
      });
      setPending(null);
      await Promise.all([boughtOwn.refetch(), allowance.refetch(), balance.refetch()]);
      await deliver(hash, kind, attacker);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(null);
    }
  }

  async function retry(record: PurchaseRecord) {
    setError("");
    setStatus("");
    setBusy(keyFor(record.kind, record.attacker));
    try {
      await deliver(record.txHash as `0x${string}`, record.kind, record.attacker);
    } finally {
      setBusy(null);
    }
  }

  async function downloadExisting(record: PurchaseRecord) {
    if (!record.grant) {
      await retry(record);
      return;
    }
    if (record.grant.expires_at * 1_000 <= Date.now()) {
      await retry(record);
      return;
    }
    try {
      await downloadGrant(record.grant);
      toast({ title: t("Download started", "下载已开始"), tone: "success" });
    } catch (reason) {
      setError(errorText(reason));
    }
  }

  const pendingPrice =
    pending?.kind === "own" ? ownPrice : pending?.kind === "attacker" ? attackerPrice : null;

  return (
    <div className="market-detail">
      <div className="detail-back">
        <Link to="/market" className="detail-back__link">
          <ArrowLeft size={13} />
          {t("Data market", "数据市场")}
        </Link>
        <span className="mono">DATASET / {contest.id.slice(0, 12)}…</span>
      </div>

      <header className="detail-head">
        <div className="detail-head__main">
          <div className="detail-head__badges">
            <Badge tone={published ? "success" : "warning"} dot>
              {published
                ? t("DATASET PUBLISHED", "数据集已发布")
                : t("NOT PUBLISHED", "未发布")}
            </Badge>
            <Badge tone={contest.state === "breached" ? "danger" : "neutral"}>
              {stateLabel(contest.state)}
            </Badge>
            <Badge tone="neutral">
              <LockKeyhole size={11} /> {t("DEFENDER ONLY", "仅限守方")}
            </Badge>
          </div>
          <h1 className="detail-head__title">
            {t("Dataset", "数据集")}{" "}
            <span className="mono muted">{contest.id.slice(0, 10)}…</span>
          </h1>
          <div className="detail-head__meta">
            <span>
              <ShieldCheck size={13} /> {t("Defender", "守方")}{" "}
              <AddressChip value={contest.defender} />
            </span>
            <span>
              <Database size={13} /> root{" "}
              <span className="mono">
                {published ? `${root.data!.slice(0, 12)}…` : t("Not published", "未发布")}
              </span>
            </span>
            <span>
              <ShoppingBag size={13} /> {contest.paid_count}{" "}
              {t("paid messages", "条付费消息")}
            </span>
          </div>
        </div>
        <div className="detail-head__aside">
          <span className="detail-head__aside-label mono">
            {t("DATASET STATE", "数据集状态")}
          </span>
          <div className="dataset-state">
            {published ? <CheckCircle2 size={16} /> : <TriangleAlert size={16} />}
            <strong>
              {published ? t("Available", "可用") : t("Waiting for operator to publish", "等待运营发布")}
            </strong>
          </div>
          <span className="detail-head__aside-foot mono">
            {t(
              "Purchase window: after the contest ends · once per address",
              "购买窗口：比赛结束后 · 每地址一次",
            )}
          </span>
        </div>
      </header>

      <div className="stat-strip">
        <Stat
          label={t("Defender-owned data", "守方自有数据")}
          value={ownPrice !== null ? formatRtm(ownPrice) : "—"}
          unit="tRTM"
          icon={<ShoppingBag size={14} />}
        />
        <Stat
          label={t("Attacker slices", "攻方切片")}
          value={attackerPrice !== undefined ? formatRtm(attackerPrice) : "—"}
          unit="tRTM"
          icon={<Database size={14} />}
        />
        <Stat
          label={t("Platform split", "平台分账")}
          value="70%"
          hint={t(
            "The remaining 30% goes to the data provider",
            "其余 30% 归数据提供方",
          )}
          icon={<ShieldCheck size={14} />}
        />
        <Stat
          label={<>{t("Your", "你的")} <span className="preserve-case">tRTM</span></>}
          value={formatRtm(balance.data)}
          unit="tRTM"
          icon={<Wallet size={14} />}
        />
      </div>

      {!published && (
        <Alert tone="warning" title={t("Dataset not published", "数据集尚未发布")}>
          {t(
            "The contest has ended, but the operator has not published the consent-aware dataset to DataMarket yet. Buy buttons appear here once it is published.",
            "比赛已经结束，但运营还没有把 consent-aware 数据集发布到 DataMarket。发布后这里会出现购买按钮。",
          )}
        </Alert>
      )}
      {!ended && (
        <Alert tone="info" title={t("Contest still live", "比赛还在进行")}>
          {t(
            "Data can only be published and purchased after a standard contest ends. Mining contest data feeds RSI only and never appears on the market.",
            "只有普通赛结束后才能发布和购买数据。挖矿赛数据只进入 RSI，不会出现在市场。",
          )}
        </Alert>
      )}
      {!isConnected && (
        <ConnectPrompt title={t("Connect the defender wallet to purchase", "连接守方钱包以购买")} compact />
      )}
      {isConnected && !correctChain && (
        <ConnectPrompt title={t("Switch to RTM Testnet", "切换到 RTM Testnet")} compact />
      )}
      {isConnected && correctChain && !isDefender && (
        <Alert tone="info" title={t("Only this contest's defender can purchase", "只有该场守方可以购买")}>
          {t(
            "This wallet is not the data buyer for this contest. You can browse dataset info but cannot purchase.",
            "当前钱包不是这场比赛的数据买家。你可以浏览数据集信息，但不能发起购买。",
          )}
        </Alert>
      )}

      <div className="market-detail-grid">
        <div className="market-detail-main">
          <Panel
            eyebrow={t("Bundle / Data slices", "Bundle / 数据切片")}
            title={t("Defender-owned data", "守方自有数据")}
            bracket
            actions={
              <Badge tone={ownRecord?.status === "delivered" ? "success" : "neutral"}>
                {ownRecord?.status === "delivered"
                  ? t("Delivered", "已交付")
                  : ownRecord
                    ? t("Pending delivery", "待交付")
                    : t("Not purchased", "未购买")}
              </Badge>
            }
          >
            <div className="buy-card">
              <div className="buy-card__icon">
                <Database size={20} />
              </div>
              <div className="buy-card__body">
                <strong>{t("Full contest dataset", "整套比赛数据")}</strong>
                <p>
                  {t(
                    "Includes the defender's own records and attacker slices approved for sale, packed as a ZIP per the manifest.",
                    "包含守方自有记录与已同意出售的攻方切片，按 manifest 打包为 ZIP。",
                  )}
                </p>
                <div className="buy-card__meta">
                  <span>{t("Price", "价格")}</span>
                  <strong>
                    {ownPrice !== null ? formatRtmUnit(ownPrice) : t("Loading…", "读取中…")}
                  </strong>
                  <span>{t("Net cost", "净付出")}</span>
                  <strong>{ownPrice !== null ? formatRtmUnit((ownPrice * 70n) / 100n) : "—"}</strong>
                </div>
              </div>
              <div className="buy-card__action">
                {ownRecord?.status === "delivered" ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    iconLeft={<Download size={13} />}
                    onClick={() => void downloadExisting(ownRecord)}
                  >
                    {t("Download", "下载")}
                  </Button>
                ) : ownRecord ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={busy === "own"}
                    iconLeft={<RefreshCw size={13} />}
                    onClick={() => void retry(ownRecord)}
                  >
                    {t("Retry delivery", "重试交付")}
                  </Button>
                ) : boughtOwn.data ? (
                  <Badge tone="success">{t("Purchased", "已购买")}</Badge>
                ) : (
                  <Button
                    size="sm"
                    loading={busy === "own"}
                    disabled={!purchaseReady || ownPrice === null}
                    iconLeft={<ShoppingBag size={13} />}
                    onClick={() => setPending({ kind: "own" })}
                  >
                    {t("Purchase", "购买")}
                  </Button>
                )}
              </div>
            </div>
          </Panel>

          <Panel
            eyebrow={t("Attacker slices", "攻方切片")}
            title={t("Attacker data consented for sale", "已同意出售的攻方数据")}
            actions={
              <Badge tone="neutral">
                {t(`${attackers.length} addresses`, `${attackers.length} 个地址`)}
              </Badge>
            }
          >
            {attackers.length === 0 ? (
              <EmptyState
                icon={<Database size={20} />}
                title={t("No attacker data in this contest", "这场比赛没有攻方数据")}
                description={t(
                  "Only attackers who joined and sent paid messages can have data slices.",
                  "只有加入并产生付费消息的攻方才可能有数据切片。",
                )}
              />
            ) : (
              <div className="attacker-table">
                <div className="attacker-table__head">
                  <span>{t("Attacker", "攻方")}</span>
                  <span>{t("Consent", "同意")}</span>
                  <span>{t("Paid / delivered", "付费 / 送达")}</span>
                  <span>{t("Outcome", "结果")}</span>
                  <span>{t("Price", "价格")}</span>
                  <span />
                </div>
                {attackers.map(([attacker, info]) => (
                  <AttackerRow
                    key={attacker}
                    contestId={contest.id}
                    attacker={attacker}
                    info={info}
                    buyer={address}
                    isDefender={isDefender}
                    published={published}
                    ended={ended}
                    price={attackerPrice}
                    record={records.find(
                      (item) =>
                        item.kind === "attacker" &&
                        item.attacker?.toLowerCase() === attacker.toLowerCase(),
                    )}
                    busy={busy}
                    onBuy={() => setPending({ kind: "attacker", attacker })}
                    onRetry={retry}
                    onDownload={downloadExisting}
                  />
                ))}
              </div>
            )}
            <p className="muted small market-detail__note">
              {t(
                "Mining contest data is not shown here and cannot be purchased. Opt-out attackers have no slices.",
                "挖矿赛数据不在此展示，也不可购买。opt-out 攻方没有切片。",
              )}
            </p>
          </Panel>

          {records.length > 0 && (
            <Panel
              eyebrow={t("Purchases", "购买记录")}
              title={t("Your data orders", "你的数据订单")}
            >
              <div className="purchase-list">
                {records.map((record) => (
                  <div className="purchase-row" key={keyFor(record.kind, record.attacker)}>
                    <span className={`purchase-row__icon ${record.status === "delivered" ? "is-ok" : ""}`.trim()}>
                      {record.status === "delivered" ? <CheckCircle2 size={15} /> : <RefreshCw size={15} />}
                    </span>
                    <div className="purchase-row__main">
                      <strong>
                        {record.kind === "own"
                          ? t("Defender-owned data", "守方自有数据")
                          : t(
                              `Attacker ${shortAddr(record.attacker)}`,
                              `攻方 ${shortAddr(record.attacker)}`,
                            )}
                      </strong>
                      <span className="mono">{shortAddr(record.txHash)}</span>
                      <span className="muted small">
                        {record.status === "delivered"
                          ? t(
                              `Delivered · ${timeAgo(record.boughtAt)}`,
                              `已交付 · ${timeAgo(record.boughtAt)}`,
                            )
                          : record.status === "failed"
                            ? t(
                                `Delivery failed · ${record.error ?? "unknown error"}`,
                                `交付失败 · ${record.error ?? "未知错误"}`,
                              )
                            : t("Waiting for indexing and delivery", "等待索引与交付")}
                      </span>
                    </div>
                    <div className="purchase-row__actions">
                      {record.status === "delivered" ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          iconLeft={<Download size={12} />}
                          onClick={() => void downloadExisting(record)}
                        >
                          {t("Download", "下载")}
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          variant="ghost"
                          loading={busy === keyFor(record.kind, record.attacker)}
                          iconLeft={<RefreshCw size={12} />}
                          onClick={() => void retry(record)}
                        >
                          {t("Retry delivery", "重试交付")}
                        </Button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          )}
        </div>

        <aside className="market-detail-side">
          <Panel
            eyebrow={t("Dataset info", "数据集信息")}
            title={t("Data boundaries", "数据边界")}
            tone="flat"
          >
            <dl className="dataset-info">
              <div>
                <dt>{t("Contest status", "比赛状态")}</dt>
                <dd>{stateLabel(contest.state)}</dd>
              </div>
              <div>
                <dt>{t("End time", "结束时间")}</dt>
                <dd>{formatDateTime(contest.ended_ts ?? Number(contest.end))}</dd>
              </div>
              <div>
                <dt>datasetRoot</dt>
                <dd className="mono">
                  {published ? shortAddr(root.data) : t("Not published", "未发布")}
                </dd>
              </div>
              <div>
                <dt>{t("Price basis", "价格基准")}</dt>
                <dd>{prices.priceBps !== undefined ? `${prices.priceBps} bps` : "—"}</dd>
              </div>
              <div>
                <dt>{t("Defender", "守方")}</dt>
                <dd>
                  <AddressChip value={contest.defender} />
                </dd>
              </div>
            </dl>
          </Panel>

          <Panel
            eyebrow={t("How delivery works", "交付流程")}
            title={t("Purchase and delivery", "购买与交付")}
            tone="flat"
          >
            <ol className="mini-loop">
              <li>
                <span className="mono">01</span>
                <div>
                  <strong>approve + buy</strong>
                  <p>
                    {t(
                      "DataMarket splits payment directly from your wallet and never custodies funds.",
                      "DataMarket 直接从你的钱包分账，不托管资金。",
                    )}
                  </p>
                </div>
              </li>
              <li>
                <span className="mono">02</span>
                <div>
                  <strong>{t("Index DataSold", "索引 DataSold")}</strong>
                  <p>
                    {t(
                      "The platform generates the ZIP slice only after the trade is indexed.",
                      "交易被索引后，平台才生成 ZIP 切片。",
                    )}
                  </p>
                </div>
              </li>
              <li>
                <span className="mono">03</span>
                <div>
                  <strong>{t("Download", "下载")}</strong>
                  <p>
                    {t(
                      "Delivery tokens expire; request delivery again after expiry.",
                      "交付令牌有有效期；过期可重新发起交付。",
                    )}
                  </p>
                </div>
              </li>
            </ol>
          </Panel>

          <div className="market-detail-side__note">
            <ShieldCheck size={14} />
            <span>
              {t(
                "Purchases are irreversible; each dataset can be bought once per address.",
                "购买不可撤销；每份数据每地址仅可购买一次。",
              )}
            </span>
          </div>
        </aside>
      </div>

      {status && <Alert tone="info" className="market-detail__status">{status}</Alert>}
      {error && <Alert tone="error" className="market-detail__status">{error}</Alert>}

      <Dialog
        open={Boolean(pending)}
        onClose={() => !busy && setPending(null)}
        eyebrow={t("Confirm purchase", "确认购买")}
        title={
          pending?.kind === "own"
            ? t("Buy defender-owned data", "购买守方自有数据")
            : t("Buy an attacker data slice", "购买攻方数据切片")
        }
        description={t(
          "DataMarket splits payment directly from your wallet; purchases are irreversible.",
          "DataMarket 会从你的钱包直接分账；购买后不可撤销。",
        )}
        size="sm"
        footer={
          <div className="dialog__footer-row">
            <Button variant="ghost" onClick={() => setPending(null)} disabled={Boolean(busy)}>
              {t("Cancel", "取消")}
            </Button>
            <Button
              loading={Boolean(busy)}
              onClick={() =>
                pending && void buy(pending.kind, pending.attacker)
              }
            >
              {t("Confirm payment", "确认支付")}{" "}
              {pendingPrice !== null && pendingPrice !== undefined
                ? formatRtmUnit(pendingPrice)
                : ""}
            </Button>
          </div>
        }
      >
        <div className="purchase-confirm">
          <div>
            <span>{t("Buyer", "买家")}</span>
            <strong>
              <AddressChip value={address} />
            </strong>
          </div>
          <div>
            <span>{t("Seller", "卖家")}</span>
            <strong>
              <AddressChip
                value={pending?.kind === "own" ? contest.defender : pending?.attacker}
              />
            </strong>
          </div>
          <div>
            <span>{t("Price", "价格")}</span>
            <strong>
              {pendingPrice !== null && pendingPrice !== undefined
                ? formatRtmUnit(pendingPrice)
                : "—"}
            </strong>
          </div>
          <div>
            <span>{t("Split", "分账")}</span>
            <strong>{t("70% Treasury / 30% data provider", "平台 70% / 数据提供方 30%")}</strong>
          </div>
        </div>
        <p className="muted small">
          {pending?.kind === "own"
            ? t(
                "When the defender buys their own data, 30% returns to your own address, so the net cost is about 70%.",
                "守方购买自有数据时，30% 会退回你自己的地址，净付出约 70%。",
              )
            : t(
                "30% of an attacker slice goes to that attacker; the platform keeps 70%.",
                "攻方切片的 30% 会支付给该攻方，平台保留 70%。",
              )}
        </p>
      </Dialog>
    </div>
  );
}

function AttackerRow({
  contestId,
  attacker,
  info,
  buyer,
  isDefender,
  published,
  ended,
  price,
  record,
  busy,
  onBuy,
  onRetry,
  onDownload,
}: {
  contestId: string;
  attacker: string;
  info: AttackerInfo;
  buyer: string | undefined;
  isDefender: boolean;
  published: boolean;
  ended: boolean;
  price: bigint | undefined;
  record: PurchaseRecord | undefined;
  busy: string | null;
  onBuy: () => void;
  onRetry: (record: PurchaseRecord) => Promise<void>;
  onDownload: (record: PurchaseRecord) => Promise<void>;
}) {
  const { t } = useI18n();
  const bought = useBoughtAttacker(contestId, attacker, buyer);
  const key = `attacker:${attacker.toLowerCase()}`;
  const consented = info.data_consent === true;
  const alreadyBought = Boolean(bought.data) || Boolean(record);
  const disabled = !isDefender || !published || !ended || !consented || alreadyBought;

  return (
    <div className="attacker-row">
      <div>
        <AddressChip value={attacker} />
      </div>
      <div>
        <Badge tone={consented ? "success" : "neutral"}>
          {info.data_consent === null
            ? t("Not recorded", "未记录")
            : consented
              ? t("Consented", "同意")
              : t("Declined", "拒绝")}
        </Badge>
      </div>
      <div className="tabular attacker-row__counts">
        {info.paid} / {info.delivered}
      </div>
      <div>
        {info.won ? (
          <Badge tone="danger">{t("Breached", "攻破")}</Badge>
        ) : (
          <span className="muted">—</span>
        )}
      </div>
      <div className="tabular">{price !== undefined ? formatRtm(price) : "—"} tRTM</div>
      <div className="attacker-row__action">
        {record?.status === "delivered" ? (
          <Button
            size="sm"
            variant="ghost"
            iconLeft={<Download size={12} />}
            onClick={() => void onDownload(record)}
          >
            {t("Download", "下载")}
          </Button>
        ) : record ? (
          <Button
            size="sm"
            variant="ghost"
            loading={busy === key}
            iconLeft={<RefreshCw size={12} />}
            onClick={() => void onRetry(record)}
          >
            {t("Retry", "重试")}
          </Button>
        ) : (
          <Button
            size="sm"
            variant={disabled ? "quiet" : "secondary"}
            disabled={disabled}
            loading={busy === key}
            onClick={onBuy}
          >
            {!consented
              ? t("Not consented", "未同意")
              : alreadyBought
                ? t("Purchased", "已购买")
                : t("Purchase", "购买")}
          </Button>
        )}
      </div>
    </div>
  );
}
