# REDTEAM Flower 本地实现与验证记录

日期：2026-10-10。基于 `main@c276ee0` 的未提交本地改动。没有提交、推送、公开发行、公网链部署或线上站点更新。

## 已交付

- `contracts/src/ContributionFlower.sol`：ERC-721 / ERC-5192，接收者 EIP-712 同意，发行权限与管理权限分开，nonce、防跨链与跨合约重放、全局贡献去重、底层不可转让、禁止授权及销毁、撤销状态与静态链上小花元数据。
- `contracts/scripts/flower-protocol.js`：严格的合成证据、链下审核、SHA-256、路径、领取同意及本地网络校验。
- `contracts/scripts/flower-demo.js`：限定进程内、非 fork 的 Hardhat 31337，完成审核示例、签名、铸造、拒绝转让/授权和撤销。
- `contracts/scenarios/flower-v1/`：合成贡献与审核夹具；不包含真实身份、真实漏洞或私钥。
- `docs/site/flower.html`、`docs/site/flower-demo.json`：同一 NFT 的发行后和撤销后快照；不是两枚 NFT，不查询实时链，不连接钱包。
- README、研究索引、合约指南、主页和商业计划同步；历史 RTM / BountyVault / BountyRound 不接入 Flower，PayAssist 主线未修改。
- 本地 Solidity 0.8.24 编译目标改为 Cancun，满足已锁定 OpenZeppelin 组件的 MCOPY 要求；没有更换编译器或安装新依赖。
- CI 增加本地 Flower 演示步骤；Pages 文件打包采用明确白名单。工作流没有被运行，服务没有发布。

协议与限制详见 [FLOWER_RECOGNITION.md](FLOWER_RECOGNITION.md)。

## 可重复命令

在 `contracts/` 执行：

```bash
npm run flower:demo
npm run flower:test
npm test
```

展示 JSON 已随本地改动生成；演示可以重新生成。测试和演示使用临时本地链，不保存可用的公网资产或链状态。

用仅绑定 loopback 的静态 HTTP 服务查看 `docs/site/flower.html`，不要依赖 `file://` 的 JSON fetch。静态演示无需钱包和真实资金。

## 测试结果

| 范围 | 结果 |
|---|---|
| Flower 专项合约 | 43 项通过 |
| Flower 审核协议与网络边界 | 130 项通过 |
| 安全展示导出 | 4 项通过 |
| `flower:test` 合计 | 177 项通过，包含上述三类 |
| 完整 Hardhat `npm test` | 267 项通过，包含 Flower 专项及原有合约回归 |
| PayAssist 当前 Python 测试、Python 付款实验和旧 claim 协议 | 475 项通过，另 31 个子测试通过 |
| 旧 Arena claim binding 三项测试 | 3 项通过 |
| 上述独立 Python 范围合计 | 478 项通过；不是仓库全部 Python 测试的通过声明 |
| `git diff --check` | 通过 |

Python 命令范围：

```bash
python -m pytest rsi4safety/payment_agents/tests rsi4safety/execution/tests/test_claim_protocol.py contracts/tests -q --durations=10 --basetemp <new-isolated-directory>
python -m pytest rsi4safety/execution/tests/arena/test_claim_binding.py -q -x --basetemp <new-isolated-directory> -o faulthandler_timeout=60
```

原始根目录 Python 全量尝试在 Windows 的旧 Arena HTTP 启动/子进程清理环节长时间等待，已中止，不能据此声称全量通过。随后缩小到相关范围；本机默认 pytest 临时目录还出现 `PermissionError: [WinError 5]`，改用全新、独立的项目测试缓存目录后相关范围全部通过，没有修改系统权限。单独的旧 Arena claim binding 三项最终通过，耗时约 236 秒，期间有诊断线程堆栈输出。

Python 有两项已有依赖弃用警告（Starlette/httpx 与 anyio BlockingPortal），未修改无关依赖。测试没有调用付费模型或真实资金系统。

## 浏览器验证

使用就绪的 Kimi WebBridge 与仅绑定 `127.0.0.1` 的测试服务进行验证：

- 桌面宽度 1080px：状态为 ready、两张快照均加载实际 400px SVG、没有横向溢出。
- 390px 手机等效 iframe 视口：状态为 ready，两张图片加载，快照单列，文档 scrollWidth 375px，检查到的正文与导航元素无视口外溢出。
- 更新后的主页包含 Flower 入口及 2026 年 10 月研究状态，入口可以跳到小花页面。
- 缺少 JSON：error，内容隐藏，快照数为零。
- chainId 改成公网链：error，内容隐藏，快照数为零。
- 两张快照 tokenId 不同：error，内容隐藏，快照数为零。
- SVG 含 script：error，内容隐藏，快照数为零。
- 撤销快照换成不同图片：error，内容隐藏，快照数为零。

曾发现 SVG 校验错误地拒绝标准 `xmlns` 命名空间，已修复并重跑实际图片加载。仅接受精确 SVG namespace，其他脚本、链接或远程资源仍拒绝。

上述为真实浏览器加载、状态和响应式几何检查。截图逐像素的美术评阅未完成：当前会话的图像输入不可用，不能把程序化几何检查表述为全面视觉验收。页面留待用户在本地实际观看；此限制不影响已经通过的链上逻辑和页面拒绝非法数据测试。

## 未实现或未授权的范围

- 不支持公网发行、市场、交易、付费铸造、兑换、收益或经济权益。
- 没有生产用户身份系统、审核人密码学认证、多签治理、合约钱包接收或遗失钱包迁移。
- 证据摘要与审核声明只由可信链下协议核对；合约没有验证贡献真实性或证据摘要。钱包签名只证明密钥控制。
- 贡献标识基于稳定贡献键；去重只防止同一标识重发，不自动识别换键重复提交。审核者必须做语义去重。
- 链上地址、贡献标识与事件仍公开；元数据去敏不等于匿名，撤销不删除历史。
- 不可转让 NFT 不能阻止私钥/钱包账号被转卖。
- 法律引文未独立核验，没有完成法律审查，NFT 名称与技术锁定不构成合法性保证。
- 商业 PDF 未重建，明确作为更新前旧快照；当前产品口径以本地 Markdown 为准。
- GitHub 与线上页面仍可能为旧版本。所有新代码和新口径仅在本地工作区，未发布。
