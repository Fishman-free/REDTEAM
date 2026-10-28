import type { Contest } from "../../lib/api";
import { needsExpire } from "../../lib/contest";
import { stateLabel, stateTone } from "../../lib/format";
import { Badge } from "../ui/Badge";

export function ContestStatusBadge({
  contest,
  now,
  dot = true,
}: {
  contest: Contest;
  now: number;
  dot?: boolean;
}) {
  if (needsExpire(contest, now)) {
    return (
      <Badge tone="warning" dot={dot} title="时间已到，等待任何地址调用 expire 结算">
        待结算
      </Badge>
    );
  }
  return (
    <Badge tone={stateTone(contest.state)} dot={dot}>
      {stateLabel(contest.state)}
    </Badge>
  );
}
