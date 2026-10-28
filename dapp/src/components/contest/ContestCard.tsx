import { Link } from "react-router-dom";
import { ArrowUpRight, Banknote, MessageSquare, Pickaxe, Shield, Timer } from "lucide-react";
import type { Contest } from "../../lib/api";
import { attackFeeWei, contestEndMs, contestProgress, requiredStakeWei } from "../../lib/contest";
import { formatRtm, stateLabel } from "../../lib/format";
import { useNow } from "../../lib/hooks";
import { usePlatform } from "../../lib/platform";
import { AddressChip } from "../ui/Address";
import { Countdown } from "../ui/Countdown";
import { Progress } from "../ui/Progress";
import { ContestStatusBadge } from "./ContestStatusBadge";

export function ContestCard({
  contest,
  index,
  href,
}: {
  contest: Contest;
  index: number;
  href?: string;
}) {
  const { meta } = usePlatform();
  const now = useNow(1_000);
  const fee = attackFeeWei(contest, meta);
  const stake = requiredStakeWei(contest);
  const progress = contestProgress(contest, now);
  const target = href ?? (contest.is_mining ? `/mine/${contest.id}` : `/arena/${contest.id}`);

  return (
    <article className={`contest-card ${contest.is_mining ? "contest-card--mining" : ""}`.trim()}>
      <div className="contest-card__top">
        <span className="contest-card__index mono">OP-{String(index + 1).padStart(2, "0")}</span>
        <ContestStatusBadge contest={contest} now={now} />
        <Countdown endMs={contestEndMs(contest)} showIcon label="" />
      </div>

      <div className="contest-card__title-row">
        <div>
          <p className="contest-card__kicker mono">
            {contest.is_mining ? "MINING TARGET" : "NORMAL CONTEST"}
          </p>
          <h3 className="contest-card__title">
            {contest.is_mining ? "挖矿靶" : "攻防靶"}{" "}
            <span className="mono muted">{contest.id.slice(0, 10)}</span>
          </h3>
        </div>
        <span className={`contest-card__glyph ${contest.is_mining ? "is-mining" : ""}`.trim()} aria-hidden="true">
          {contest.is_mining ? <Pickaxe size={18} /> : <Shield size={18} />}
        </span>
      </div>

      <div className="contest-card__actors">
        <AddressChip
          value={contest.is_mining ? contest.defense_hash : contest.defender}
          kind="hash"
          label={contest.is_mining ? "DEFENSE" : "DEFENDER"}
          copy
        />
      </div>

      <div className="contest-card__stats">
        <div>
          <span className="contest-card__stat-label">
            <Banknote size={11} /> 奖池
          </span>
          <strong className="tabular">{contest.is_mining ? "1 RTM" : formatRtm(contest.stake)}</strong>
        </div>
        <div>
          <span className="contest-card__stat-label">
            <Shield size={11} /> {contest.is_mining ? "固定奖励" : "攻方质押"}
          </span>
          <strong className="tabular">
            {contest.is_mining ? "1 RTM" : formatRtm(stake)}
          </strong>
        </div>
        <div>
          <span className="contest-card__stat-label">
            <MessageSquare size={11} /> 单条费用
          </span>
          <strong className="tabular">{formatRtm(fee, { maxFraction: 4 })}</strong>
        </div>
        <div>
          <span className="contest-card__stat-label">
            <Timer size={11} /> 已付费消息
          </span>
          <strong className="tabular">{contest.paid_count}</strong>
        </div>
      </div>

      {contest.is_mining ? (
        <div className="contest-card__open mono">OPEN-ENDED · 由攻破或平台退役结束</div>
      ) : (
        <Progress
          value={progress}
          size="sm"
          tone={contest.state === "live" ? "accent" : "neutral"}
          label={contest.state === "live" ? "时间进度" : stateLabel(contest.state)}
          right={`${Math.round(progress * 100)}%`}
          className="contest-card__progress"
        />
      )}

      <Link to={target} className="contest-card__cta">
        进入战场
        <ArrowUpRight size={14} />
      </Link>
    </article>
  );
}
