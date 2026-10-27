# v0_demo

基准库的第一个版本，只用于演示统一接口：

- 底座提示词、两个工具（`get_balance` / `transfer_rtm`）与消息信封由 `benchmark/base_prompt.py`
  和 `benchmark/harness.py` 固定，本目录只提供 `DefensePackage`。
- 目标是"可用但不弱智"的起点，不是安全上限。迭代提示词时复制本目录为
  `v1_xxx/`，改 `name` 与 `defense`，再跑 `python -m benchmark.demo` 与
  `python -m pytest benchmark/tests -q` 对比行为。
- 新版本不得引入额外工具或改写底座提示词；需要新工具属于机制变更，应走规格修订。
