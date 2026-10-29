import type { Contest } from "../../lib/api";
import { needsExpire } from "../../lib/contest";
import { stateLabel, stateTone } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
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
  const { t } = useI18n();
  if (needsExpire(contest, now)) {
    return (
      <Badge
        tone="warning"
        dot={dot}
        title={t(
          "Time has expired; any address can settle it with expire().",
          "时间已到，等待任何地址调用 expire 结算",
        )}
      >
        {t("Needs settlement", "待结算")}
      </Badge>
    );
  }
  return (
    <Badge tone={stateTone(contest.state)} dot={dot}>
      {stateLabel(contest.state)}
    </Badge>
  );
}
