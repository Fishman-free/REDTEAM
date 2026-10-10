# REDTEAM

**统一项目网站：[fishman-free.github.io/REDTEAM](https://fishman-free.github.io/REDTEAM/)**。一个入口、五个菜单：项目概览、Flower 本地原型、研究与商业资料、历史项目简述、历史完整介绍。完整 HTML 内容保留在对应菜单中；历史材料明确标注，不把本地靶场或原始研究数据当作公开交互服务。页面来源与范围见[站点清单](docs/SITE_CONTENT_MANIFEST.md)。

站点维护：`python scripts/build_site.py` 更新根入口和 Pages 排除配置；`python scripts/build_site.py --check` 与 `python -m unittest discover -s tests -p test_site_build.py -v` 校验五个菜单及发布文件。现有 Pages 使用 `main` 根目录发布，根 `index.html` 是统一入口。

当前主线是 **PayAssist L0/L1 支付智能体的攻击、修复与独立验证**。从[运行指南](rsi4safety/payment_agents/README.md)开始；三环设计、信任边界和真实实验判断统一在[研究方案](docs/RESEARCH_PLAN.md)。

当前live.v3协议分别确认模型越权提案与系统突破，记录真实模型触达和验收覆盖；v5套件加入必须读取外部文档/记忆的任务。旧实验中的“0系统发现”不代表模型未被诱导。新机制已有离线闭环验证，真实模型结果仍以对应冻结实验为准。

```text
rsi4safety/payment_agents/   当前 PayAssist 运行、四暴露面、防御包和评判
rsi4safety/execution/        共享宿主组件与保留的独立研究原型
contracts/                  独立支付合约、历史 RTM 与 Flower 本地 NFT 原型
scripts/                    历史宿主证据审计
archieve/                   原始结果与已被当前指南替代的历史说明
```

## 开始

从仓库根目录执行。已有环境可以复用：

```bash
python3 -m venv rsi4safety/.venv
source rsi4safety/.venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

线上模型实验按[PayAssist 指南](rsi4safety/payment_agents/README.md)另行启动。离线测试通过和模型实验通过是不同结论；当前资金均为宿主模拟资金。

## 证据与其他研究

本轮4B真实模型[工程筛查证据](rsi4safety/payment_agents/evidence/v3-smoke-2026-10-03/README.md)：同提示裸对照DEV2/8，工程包DEV8/8、transfer8/8、acceptance7/8；截断反例复测3/3、角色包有限换例筛查10/10分别保留。它们不构成规范攻击发现、独立晋级或未见族推广；原失败、费用缺口及可复算原始包均在链接中。

2026-10-03 的旧版 L0/L1 原始运行共 4158 次。当前[宿主证据复核](rsi4safety/payment_agents/evidence/HOST_EVIDENCE_REVIEW_2026-10-03.md)校正了版本、分母和报告解释；原报告原字节见[实验归档](archieve/experiments/payassist-v2/README.md)。这些旧版 prompt-only、两暴露面实验与当前防御包/四暴露面协议不可直接比较。

[合约模块](contracts/README.md)、[总构想与独立规格](docs/INDEX.md)继续保留。旧Arena已有本地RTM证据奖励桥和公开提交原型；当前PayAssist campaign尚未接入这条桥，见[证据与奖励协议](docs/EVIDENCE_REWARD_PROTOCOL.md)。

当前真实模型结果见 [2026-10-05 live.v3 / required-reading-v5 对照报告](rsi4safety/payment_agents/evidence/VALIDATION10H_COMPARATIVE_2026-10-05.md)：L0/L1 冻结验收通过但仍有 **12 个开放发现**（1+11），不是生产安全证书。历史论文的20%→100%修复率曲线受未见族分母缩小影响，逐点成功项仍为2，不能证明跨族泛化。

## 独立产品研究：REDTEAM Flower

商业主线为[安全评测、整改复核与持续回归服务（当前 Markdown）](docs/business/redteam-business-plan.md)。[REDTEAM Flower 协议](docs/FLOWER_RECOGNITION.md)与[静态演示页](docs/site/flower.html)介绍一个独立、可选的 **ERC-721 + ERC-5192 不可转让 NFT 本地原型**，不是历史 RTM ERC-20，不接入当前 PayAssist。发行者可信链下审核、接收 EOA 的 EIP-712 同意后免费发行；无销售、转让、授权、赎回、收益、算力效用或所有权特权，撤销保留原 token/owner。普通钱包控制不是真实身份认证；digest 只验证字节，不证明贡献真实。仅无分叉 Hardhat 31337、合成数据演示，公开发行尚待法律/隐私/安全与人工流程审查，NFT 名称或免费/锁定不保证合法。

```bash
# 在 contracts/ 中；仅本地演示，不连接公共网络
npm test
npm run flower:demo
```

[研究论文 Markdown](docs/paper/payment-agent-security-rsi.md)与[历史论文 PDF](docs/paper/payment-agent-security-rsi.pdf)保留为历史讨论稿。[商业 PDF](docs/business/redteam-business-plan.pdf)是本次 Flower 更新前的旧快照，**未重新生成，产品说明已由当前商业 Markdown 替代**。论文统计和收入假设不替代当前验证；归档去向与 SHA-256 见[归档清单](archieve/manifest.json)。
