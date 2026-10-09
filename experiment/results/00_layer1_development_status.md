# 第一层开发交付汇总与调度者复核

## 当前结论

三路开发交付已收到，但**不能直接启动 81 次正式矩阵**。
正式新运行数为 **0**；实验目录内唯一完成的目标运行仍是原来的 T02/P0 冒烟。
本轮没有新增 Codex/Judge 实验调用、没有接 Hillclimb、没有 commit/push。

## 已交付

| Pane | 交付 |
|---|---|
| w8:p2 | 补齐 T01、T03–T09：每任务普通项目、task、外置 hidden tests、manifest、私有仓库摘要；原始失败与最小参考修复自检 |
| w8:p4 | P1/P2、泛化 Runner、固定种子乱序的 81 格矩阵调度器、并发/状态文件/恢复接口和 mock 测试 |
| w8:p3 | 泛化 Evaluator、JUnit XML 结果解析、多运行指标汇总、方法审查文档 |

调度者独立执行：

```sh
PYTHONDONTWRITEBYTECODE=1 experiment/.venv/bin/python -B \
  -m pytest experiment/tests -q -p no:cacheprovider
```

结果：**58 passed, 24 subtests passed in 7.20s**。
24 个子测试覆盖 8 个新 fixture 的完整性、原始基线和最小修复。
这些是工程自动测试，不是模型实验结果。

## 复核发现：实际阻塞

### 1. 真实预检命令直接报错（已复现）

`python -m experiment.matrix --preflight` 因 `tempfile` 未导入而抛出 NameError。
因此 mock 单测通过不等于全部 fixture 已通过真实 sandbox 预检。

### 2. Judge 会拿到错误的原始仓库摘要（代码确认）

`experiment/matrix.py` 对所有任务固定传入
`experiment/evaluator/repository_summary.md`，这是 T02 的 parser 摘要。
其他任务的正确摘要已经生成在 `evaluator/manifests/repository_summary_T*.md`，
但没有接入调度链路。

### 3. 历史冒烟误纳入正式统计（已复现）

对 `experiment/runs/layer1/P0/T02/run1` 调用新的 `summarize_run()` 得到：

```text
stage = formal
eligible_for_behavioral_aggregation = True
agent_collection_errors = 4
exclusion_reason = None
```

这与原先明确排除冒烟的要求冲突。应要求显式正式批次身份，不能将缺少 stage
的历史运行默认视为 formal。缺失/损坏的目标 trace 和缺失 Judge 原始流也需要
fail closed；目前部分路径会吞掉错误或使用默认模型名后判合格。

### 4. 异常止损、中断和恢复接口还不完整（代码确认）

- 一次性提交全部 81 个 future，故障后没有实际停止后续排队任务的机制。
- 批次结束总是记为 completed，且返回 0，即使发生失败。
- matrix 管理 wrapper 进程组，但 Runner/Judge 内部模型进程另建进程组；
  外层 kill 不能保证终止实际模型调用。
- target 已完成、Judge 尚未成功的 run，resume 没有真正从后置评估阶段恢复。
- 汇总步骤返回非零时仍可能记 run_completed；最终没有自动执行整批聚合。

这些问题关系到费用、完成计数和证据完整性，必须在正式调用前修复。

### 5. 汇总错误分支自身报错（已复现）

`python -m experiment.summarize --batch-dir <不存在的批次>` 因 `sys` 未导入
而抛出 NameError，不能按预期报告“没有运行记录”。

## 实验设计偏差

### 所有任务都被加了显式停止原则

复核显示 **T01–T09 全部**含有 `Stop once ...`。
原方案只有 T02 明确要求目标测试通过后停止；将相同原则加到全部 task，会使 P0
也接受类似 P2 的停止干预，压低 P0/P1/P2 的可测差异。

### 部分任务改成了纯函数，偏离原定工程场景

- T05：`fmt="json"` 函数任务，而非原计划的 CLI `--format json`。
- T08：内存列表去重，而非读取小本地 JSON 的重复导入脚本。
- T09：`transform_record()`，而非 `convert input.json output.json` 一次性命令。

特别是 T08/T09，去掉文件与重复执行场景，可能削弱对 hash/state/checkpoint
等不必要永久机制的测量。应恢复原定场景，而不是为了得到正结果增加陷阱。

### 新 fixture 体量比计划偏小

8 个新项目均为 3 个源文件、3–4 个可见测试、6 个隐藏测试，但包含测试在内的
有效行数约 **36–63**，低于原建议的 100–500；T02 约 102。
应补齐必要的 CLI/文件 I/O 场景保持可比性，不建议用无关代码凑行数。

### 报告模板存在结论越界

当前无 PE 案例时模板直接宣称所有实现满足 intent；这不能从 PE=0 推出，
尤其在 HC/ISS 失败或 eligible 数量为 0 时。分类标题也应恢复原始 A/B/C 含义：
过度验证、Proxy optimization、不必要机制。

## 建议下一步

1. 先修复调度/汇总阻塞与证据资格门禁。
2. 对照原方案修正 task 指令与 CLI/导入/转换场景。
3. 增加真实接口连接测试，实际运行全部 9 个 fixture 的零模型 sandbox 预检。
4. 全部通过后再启动 81 次正式运行；最多 81 次 Codex + 81 次 Gemini Judge。
5. 第一层结果报告后再考虑第二层；本轮不启动 Hillclimb。

各 agent 的“无 blocker”是交付自评，不代表调度者已验收。以上以实际命令复现
和当前代码连接关系为依据；未对原有文件或已发布的历史结果做覆盖修改。
