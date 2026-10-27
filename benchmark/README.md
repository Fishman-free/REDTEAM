# benchmark/ — 智能体版本基准库

存放守方智能体的各个版本（提示词 / runtime 开关 / memory），对外暴露**同一个接口**，
供平台 runner、离线 demo 与回归测试无差别加载。提示词迭代和"我们自己打自己"
的评测都在这里进行，比赛合约与后端不感知版本差异。

## 版本契约

每个版本是一个目录 `versions/<name>/`：

```
versions/<name>/
  agent.json   # 必需：{name, description?, defense}
  README.md    # 可选：该版本的设计意图、已知弱点、迭代记录
```

`defense` 直接使用 `payassist_agent.defense.DefensePackage`（system_prompt
100–16000 字符 + runtime 布尔开关 + ≤8 条 memory）。版本之间**只允许**这部分不同：

| 固定项 | 由谁定义 |
|---|---|
| 底座提示词（角色、渠道语义、mandate 注入、泄题禁令） | `base_prompt.py` |
| 工具面（`get_balance` / `transfer_rtm`） | `harness.py` |
| 消息信封（`external_dialogue` / `verified_owner`） | `harness.py` |
| 预算（10 步 / 120s / 200k 上下文 / 消息 ≤1000 字符） | `harness.py` |

新增工具或修改底座提示词属于机制变更，应先改规格，不在版本目录里偷偷加。

## 使用

```bash
python -m benchmark.demo                      # 离线回放：资格测试 + 外部诱导转账
python -m pytest benchmark/tests -q           # 接口一致性测试（所有版本）
```

在平台 runner 中加载版本：

```python
from benchmark.interface import load_version
version = load_version("v0_demo")
prompt = version.system_prompt(mandate=mandate, wallet_address=wallet)
```

平台部署时以仓库根为工作目录（或将仓库根加入 `PYTHONPATH`），
`pytest.ini` 已包含 `benchmark/tests` 与仓库根路径。

## 迭代流程

1. 复制 `versions/v0_demo/` 为 `versions/v1_<主题>/`，改 `agent.json` 的 `name`；
2. 只改 `defense`，跑 demo + 测试；
3. 版本目录的 `README.md` 记录"想防住什么攻击、引入了什么规则"；
4. 平台挖矿赛通过 `load_version()` 指定版本名，攻破数据回流后再开新版本。

版本目录不可变：已被比赛引用过的版本保留原样，新改动一律另开目录，保证链上
比赛与 `defense_package_sha256` 可对账。
