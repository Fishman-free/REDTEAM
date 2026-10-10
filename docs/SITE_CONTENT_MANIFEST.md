# REDTEAM 单 HTML 内容整合与发布清单

用户明确纠正后的要求：**把各方面的实质内容去重、合并进同一个 HTML；菜单只定位本页章节，不使用 iframe、子页面加载或链接目录代替正文。**

## 交付形式

- 编辑源：`docs/site/index.html`。
- 发布入口：仓库根 `index.html`，由 `scripts/build_site.py` 对源文件作字节一致的复制。
- 网站：[https://fishman-free.github.io/REDTEAM/](https://fishman-free.github.io/REDTEAM/)。
- 最终静态构建产物只有 `index.html` 一个文件。CSS、交互脚本、SVG 插画、Flower 快照 JSON 和图片均内联。
- 正文无需加载其他 HTML、CSS、JavaScript、字体、图片或 JSON；资料外链只供核对出处，不能替代内容说明。
- 现有 Pages 使用 `main` 根目录发布，Jekyll 配置排除整个 `docs/` 和研究目录，仅公开根单页。旧页面仍留在 GitHub 作为来源，不是新站运行依赖。

## 同一正文内的章节与覆盖来源

| 本页锚点 | 必须具备的实质内容 | 原始内容来源 |
|---|---|---|
| `#overview` | 项目定位、智能体交易安全价值、授权模拟研究与当前边界 | 旧 overview、项目介绍、商业 Markdown |
| `#arena` | 虚拟社区三角色、验收后付款例子、权限与四输入面、L0/L1、七工具、贡献与研究闭环 | overview、历史座谈简报、当前研究方案、PayAssist 指南 |
| `#evidence` | 真实实验的协议/模型/日期、L0/L1 对照、12 个开放发现、修复容量限制、历史结果与统计校正、六字段样本 | 2026-10-05 live.v3 报告、研究方案、旧资料页 |
| `#flower` | 可信审核、接收同意、不可转让、撤销/隐私/无经济权益、同一本地 token 的两个快照 | Flower HTML、技术 Markdown、合成导出 JSON |
| `#services` | 客户假设、六项 MVP、交付物、收入和成本假设、人民币合同与资金边界 | 当前商业计划、历史座谈简报 |
| `#roadmap` | 90 天建议路径、合作参与者、场景/算力/孵化/评价与治理需求 | 商业计划、overview、两份历史介绍 |
| `#governance` | 五类治理风险、授权/披露/数据/备案/资金边界、停线条件、历史 RTM 的准确定位 | 商业计划、技术说明、历史简报和研究构想 |
| `#faq` | 合并去重的研究、支付、数据、模型改善、区块链、NFT、商业、法律与合作问答 | 五份原 HTML 的 FAQ 和当前指南 |
| `#resources` | 当前/历史资料身份、协议出处、PDF 替代关系、核对链接 | 原 resources、文档索引及证据报告 |

这些章节必须有实际正文，不以链接数量、菜单数量或文件清单代替内容验收。重复说明合并一次；历史材料的商业、合作与治理独有内容进入相关主章节，不整体藏入历史页面。

## 视觉参考与独立性

参考用户指定的支付宝 PAYATHON 页面：

https://aipay.alipay.com/community/events/payathon-2026?product=AI_WEB_APP_PAY&accessMode=agent

实际浏览观察到的设计语言：深炭黑 `#10141b`、明亮文字 `#f3f4f6`、灰蓝辅助文字、暖橙/珊瑚点缀、技术感大标题、宽留白、横向章节节奏、同页交互选择及时间线。新页面使用原创 REDTEAM 图形与文本，不复制支付宝品牌图形、赛事报名、奖金、合作伙伴或背书。

## 事实与数据边界

- 2026-10-05 `arena.payassist.live.v3` / `2026-10-05-required-reading-v5` 的两场冻结验收通过仍有 12 个开放发现，不能称生产安全认证。
- 当前模拟执行、模型越权提案、宿主拦截与正常任务效用分别计量；历史试验不同协议/分母不能混用。
- 20%→100% 的历史曲线受未见族分母缩小影响，不证明跨族泛化；工程包修复不等于基础模型训练提升。
- Flower 是独立本地 NFT 原型，免费发行价格但不保证未来 gas 免费；钱包控制不是真实身份、证据摘要不证明贡献真伪。
- 内嵌 `flower-demo.json` 必须与已核对的合成导出完全相同：Hardhat 31337、无 fork、同 token #1 的 issued/revoked 两个历史时点，不是两枚 NFT 或实时公网链资产。
- 企业业务、客户与收入仍为待验证方案；不新增客户、机构背书、现金奖金或金融权益承诺。
- 法律引文未独立核验，不将名称、免费或不可转让表述为监管豁免。

## 来源保留与排除

两份历史源文件未修改，完整归档仍在 GitHub：

| 原始来源 | GitHub 中保留的原稿 | 原始 SHA-256 |
|---|---|---|
| `REDTEAM-座谈材料/REDTEAM-项目介绍.html` | `docs/site/archive-introduction.html` | `8cf53fc61249f7a43902e0e1b291bdcb1c8244b0ddab6db1d80f79bf9552daae` |
| `REDTEAM-座谈材料/_backups/REDTEAM-座谈简报-20260923-220135.html` | `docs/site/archive-brief.html` | `2482dc5c53a2d376ed1305528a3b8d7df0400548815a3fe1bfb56909946ddcc0` |

旧 `overview.html`、`flower.html`、`resources.html`、两归档 HTML 与 `portal.css`/`portal.js` 只是前版来源；新站不加载它们。

排除：部署 body 片段、本地故意脆弱靶场、AgentTrust 独立项目及重复架构页面、视觉 QA 产物、原始漏洞证据、真实业务数据、依赖/缓存/日志、密钥/环境/运维配置。公开站点不启动后端、模型、付款、领取或交易功能。

## 验收方法

```bash
python scripts/build_site.py
python scripts/build_site.py --check
python -m unittest discover -s tests -p test_site_build.py -v
```

程序检查单 HTML 结构、零 iframe/外部运行依赖、内联内容章节、内部锚点、七工具、证据与风险、企业/合作正文、合成快照一致性和单文件构建产物；再在真实浏览器检查导航、局部交互、手机布局和上线结果。代码测试不能代替内容审阅或 UI 检查。法律审查与公开 NFT 发行不属于本次网页重做。
