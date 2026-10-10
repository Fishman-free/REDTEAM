# REDTEAM 统一网站内容清单

本清单记录当前说明页、完整历史演示材料及公开静态站的排除边界。归档整理日期：2026-10-10。只整理公开内容；不把研究服务、脆弱靶场或私有部署配置发布为网站。

## 入口与菜单映射

统一入口由仓库根 `index.html` 包装路由，保留 `docs/site/` 下的独立页面。菜单键与源页面按下表对应；包装入口及发布配置由网站集成负责，不由归档页面实现。

| 菜单键 | `docs/site/` 页面 / 数据 | 角色 |
| --- | --- | --- |
| `#overview` | `overview.html` | 当前项目概览；承接原 `docs/site/index.html` 内容 |
| `#flower` | `flower.html` + `flower-demo.json` | Flower 当前说明与静态演示数据 |
| `#resources` | `resources.html` | 当前资料导航与历史材料目录 |
| `#brief` | `archive-brief.html` | 2026-09 完整历史座谈简报 |
| `#introduction` | `archive-introduction.html` | 2026-09 完整历史项目介绍 |

归档页中的“当前项目概览”“资料导航与历史材料”链接分别为同目录的 `overview.html`、`resources.html`。父级站点包装器可拦截这些同站导航并切换菜单；独立访问时保持普通链接。当前 overview / Flower 文案与资源清单由各自页面维护，不能用历史材料替代。

## 当前说明页面盘点

归档工作开始时，仓库内独立说明 HTML 为 `docs/site/index.html`、`docs/site/flower.html` 两页；Flower 静态演示另依赖 `docs/site/flower-demo.json`。原 `index.html` 内容将在统一入口整理时承接到 `overview.html`，资源导航使用 `resources.html`。两份以下历史材料完整加入归档，不拆成节选、不丢弃原 FAQ 或打印脚本。

## 历史来源与目标

来源相对于本地工作区父目录，仅用于溯源，不是额外公开发布目录。外部源文件保持原样。

| 原始来源 | 仓库内归档目标 | 源文件 SHA-256 |
| --- | --- | --- |
| `REDTEAM-座谈材料/REDTEAM-项目介绍.html` | `docs/site/archive-introduction.html` | `8cf53fc61249f7a43902e0e1b291bdcb1c8244b0ddab6db1d80f79bf9552daae` |
| `REDTEAM-座谈材料/_backups/REDTEAM-座谈简报-20260923-220135.html` | `docs/site/archive-brief.html` | `2482dc5c53a2d376ed1305528a3b8d7df0400548815a3fe1bfb56909946ddcc0` |

归档页使用各自准确的公开地址作为 canonical 与 OG URL：

- `https://fishman-free.github.io/REDTEAM/docs/site/archive-introduction.html`
- `https://fishman-free.github.io/REDTEAM/docs/site/archive-brief.html`

保留原文正文、内联 CSS、内联 JavaScript、章节锚点、问答展开与打印状态恢复。只增加历史上下文提示、当前站点链接及归档元数据，不替历史构想补写“已经上线”的事实。新增顶部说明在正文正常文档流内，非 sticky；打印时保留历史声明。

### 阅读边界

- 两页是 **2026-09 历史演示材料**，不是当前运行状态、实时服务入口、生产安全证明或正式法律意见。
- 原文中的“目前已有”“当前”“尚未打通”等描述按当时语境阅读；历史商业收费、人民币现金奖励、RTM 与试点建议不是 Flower 当前规则，也不预设 NFT。
- 法规、外部引用、固定提交的事实判断未在本次归档中重新核验；不保证时效性、真实性或链接可用。固定提交 `792c5b4137b32c7e624a2b910b61ed3747367708` 是历史引用，不代表当前源码状态。
- 公共项目代码、公开法规链接可以保留；未执行外部请求、浏览器验证或服务测试。

## 隐私与发布审查

完整阅读两份源 HTML，并进行联系方式、IP、凭据、私有路径与主动网络调用的静态扫描。未发现真实个人电话、邮箱、住址、身份号码、密码、API key、token、私有 IP 或实际运维主机配置。URL 仅涉及公开 GitHub 项目与固定提交、公共法规站点、旧公开项目域名。旧 `redteam.agenttrust.site` canonical / OG 已改为准确 Pages 归档地址，未复制任何真实服务配置。

两页全部样式与问答/打印行为内联，无外部 CSS、字体、图片或脚本依赖，无后端调用、支付操作或凭据。外部链接仅供主动点击查阅，不以此证明服务正在运行。隐私审查不等同安全审计或法规核验；实际发布仍需由集成方审查站点全部构建产物。

## 排除内容与原因

| 内容 | 排除理由 |
| --- | --- |
| `REDTEAM-座谈材料/_deploy/project-introduction-body.html` | 部署用 body 片段，不是独立完整页面；由完整项目介绍覆盖，不单独导出 |
| `contracts/redteam/server.py` 的内联 HTML | 绑定 localhost 的故意脆弱本地研究靶场，不是公开前端，不启动、不部署、不导出 |
| 工作区根 `agenttrust-architecture.html` | AgentTrust 独立项目架构，不是 REDTEAM 自有架构图，不混入本网站 |
| `agenttrust-architecture-worktree/`、`agenttrust-latest/`、`multiagent/` 中 12 份 AgentTrust 架构 HTML 副本 | 各目录的 `docs/agenttrust-architecture.html`、`docs/agenttrust-architecture-legacy.html`、`frontend/public/architecture/index.html`、`frontend/public/architecture-legacy/index.html` 属于另一个项目；非 REDTEAM 内容 |
| AgentTrust `frontend/out/`、`.next/` 等构建输出 | 另一个项目的生成副本/路由页面；不作为新增 REDTEAM 材料 |
| `agenttrust-architecture.visual-check.html` 及 visual-check 图像/JSON | 生成的视觉检查 QA 产物，不是对外项目页面，不导出 |
| `cache/`、`node_modules/`、`.pytest_cache/`、`.venv/`、运行日志及中间产物 | 缓存、依赖或测试/运行资料，不在静态站内容范围内 |
| SSH 密钥、凭据、环境文件、运维或真实业务部署配置 | 无公开内容授权且不需要用于纯静态说明；不复制、不发布 |

## 集成依赖与职责边界

归档变更仅涉及 `docs/site/archive-introduction.html`、`docs/site/archive-brief.html` 和本清单。`overview.html`、`resources.html`、统一根入口、Flower 页面/数据和 Pages 工作流由其负责人提供。归档页独立可读并保留原交互；同站导航需要目标页面存在。未修改 root / workflow / build 文件、未运行服务或测试套件、未提交或推送。
