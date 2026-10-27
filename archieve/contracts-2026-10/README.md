# 已归档：旧 RTM 减半发币与 Bounty 体系（2026-10 归档）

本目录保存被 2026-10-27 新机制取代的合约、脚本与测试：
- `RTMToken.sol`：按年减半发币（YEAR0_BUDGET/`mintedByYear`），被靶钱包版 RTMToken 取代
- `BountyVault.sol`：评估者门控铸币结算，被 Arena 质押/罚款/结算取代
- `BountyRound.sol`：ETH 托管提交优先层，被 Arena 托管取代
- `rtm-reward-bridge.js`：claim-requests.jsonl → configureClaim/settleClaim 桥
- 四个 rtm*/bounty-round 测试与 audit-poc 中依赖减半的用例

设计沿革见 `docs/references/research/RTM_BOUNTY_DESIGN.md`（标注已取代）与
`docs/superpowers/specs/2026-10-27-rtm-redteam-game-design.md`（现行机制）。
本目录代码不再编译、不再维护，仅供历史审查。
