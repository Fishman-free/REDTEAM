export type Page =
  | "home"
  | "defender"
  | "attacker"
  | "mining"
  | "leaderboard"
  | "faucet"
  | "market";

export const NAV: Array<{ id: Page; label: string }> = [
  { id: "home", label: "概览" },
  { id: "defender", label: "守方中心" },
  { id: "attacker", label: "攻方中心" },
  { id: "mining", label: "挖矿中心" },
  { id: "leaderboard", label: "排行榜" },
  { id: "faucet", label: "水龙头" },
  { id: "market", label: "数据市场" },
];
