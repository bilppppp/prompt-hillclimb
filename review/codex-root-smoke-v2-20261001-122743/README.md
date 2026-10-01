# Codex Root AGENTS Smoke Test v2 审查报告 (20261001-122743)

本目录为针对 Codex 根 `~/.codex/AGENTS.md` 进行的第二轮受控 Smoke 运行（v2）的完整中间产物、日志快照与评测结果，用于远程协同审查。
本次测试由独立测试执行者 `agy3` 运行并冻结，`pi` 验收通过，由 `agy1` 进行资料整理与归档提交。

---

## 1. 运行背景与代码版本声明

- **Git Base Commit**：`2d3ce17e01833677351226d99eacb189e2bdc746` (`docs: add codex root agents smoke test review artifacts (20260930-174424)`)
- **测试时的 5 个未提交 (dirty) 产品文件**：
  - `README.md`
  - `SKILL.md`
  - `hillclimb.py`
  - `install.md`
  - `tests/test_core.py`
  （以及测试支持文件 `tests/__init__.py`）
- **核心被测依据声明（重要）**：
  - **本次 Smoke v2 测试是以 `tested-source/` 目录中的代码快照作为唯一被测依据**。
  - 切勿误把仓库根目录历史提交或未提交的工作区旧状态误当作被测版本。
  - `tested-source/` 已与当时测试现场代码做逐字节哈希核对，完全一致。后续远程复现与审计必须严格基于 `tested-source/` 快照。
  - **产品版本一致性说明**：本次后续产品提交的根目录 5 个文件与 `tested-source/` 快照内容完全一致；同时保留测试执行当时这 5 个文件处于未提交 dirty 状态的历史事实。

---

## 2. 精确执行命令与退出码

所有命令均在测试当时以退出码 0 完成，具体日志见 `logs/` 目录：

1. **单元测试 (Unittest)**：
   ```bash
   python3 -m unittest -q > .hillclimb/codex-root-smoke-v2-20261001-122717/unittest.log 2>&1
   ```
   - **退出码**：`0`（57 个测试全部通过）
   - **完整日志**：[unittest.log](logs/unittest.log)

2. **Dry-Run 预检 (Dry-Run Preflight)**：
   ```bash
   python3 hillclimb.py \
     --target .hillclimb/codex-root-smoke-v2-20261001-122717/inputs/target-prompt.md \
     --eval .hillclimb/codex-root-smoke-v2-20261001-122717/inputs/evals.jsonl \
     --runner pi \
     --rounds 1 \
     --limit 1 \
     --repeats 1 \
     --dry-run > .hillclimb/codex-root-smoke-v2-20261001-122717/dryrun.log 2>&1
   ```
   - **退出码**：`0`
   - **调用预算上限预估**：至多 16 次
   - **完整日志**：[dryrun.log](logs/dryrun.log)

3. **真实 Smoke 运行 (Real Smoke Execution)**：
   ```bash
   python3 -u hillclimb.py \
     --target .hillclimb/codex-root-smoke-v2-20261001-122717/inputs/target-prompt.md \
     --eval .hillclimb/codex-root-smoke-v2-20261001-122717/inputs/evals.jsonl \
     --runner pi \
     --rounds 1 \
     --limit 1 \
     --repeats 1 > .hillclimb/codex-root-smoke-v2-20261001-122717/smoke.log 2>&1
   ```
   - **退出码**：`0`
   - **运行目录**：`.hillclimb/20261001-122743`
   - **完整日志**：[smoke.log](logs/smoke.log)

---

## 3. 评测结果与执行路径推算

- **Baseline 阶段**：
  - Train: **100.0%**
  - Val: **100.0%**
- **Preflight 检验（3 项事实）**：
  1. **Noise**: Observed val variation: `0.0`（delta: 0.0，Warning: False）
  2. **Headroom Warning**: `True`（Baseline train 100.0 与 val 100.0 均 >= 95%，提示评测裕度较低）
  3. **Grader Stability**: Grader disagreement: `0/3 (0.0%)`（Warning: False）
  - **Preflight 综合状态**：`PASSED`
- **Rounds 阶段**：
  - 配置轮数：1
  - 实际执行轮数：**0**
  - 停止原因：**`NO_TRAIN_FAILURE_SIGNAL`**（Baseline train 得分达 100%，无训练失败样本信号驱动优化器，算法安全早停）
- **Final Blind Comparison**：
  - 关系：**`Original == Best`**（共享同一 Prompt）
  - Original 得分：**66.7%**
  - Best 得分：**66.7%**
  - Delta：**0.0**（无接受的 Prompt 变更）
- **模型调用统计（按实际执行路径推算）**：
  - 理论预算上限：16 次
  - **实际调用总数：9 次**（按已记录执行路径推算，非后端逐调用计量）：
    - Baseline: **4 次**（Train target 1 + Train grader 1 + Val target 1 + Val grader 1）
    - Preflight: **3 次**（Repeat-val target 1 + Repeat-val grader 1 + Train grader stability check 1）
    - Rounds: **0 次**（因触发 `NO_TRAIN_FAILURE_SIGNAL` 提前停止，未调用优化器）
    - Final: **2 次**（共享 Prompt：Final target 1 + Final grader 1）
    - **小计**：4 + 3 + 0 + 2 = **9 次**。

---

## 4. 产物真实性与无伪造声明

- **无 Candidate 文件**：由于在 Round 1 优化器介入前已触发早停，本次运行未生成任何候选 Prompt 文件（如 `candidate.md`），真实反映执行路径，不伪造任何不存在的文件。
- **无 Stall 分析文件**：本次运行未出现停滞 (stall)，故无 stall 分析产物。
- **无新增产品中间件**：本次测试完全基于纯 Python 标准库的既有 `hillclimb.py` 执行，未引入任何外部产品中间件或额外包装层。

---

## 5. 数据集限制与指标警示

- **数据集规格**：评测集 `inputs/evals.jsonl` 共包含 8 条由开发阶段拟制的合成用例（4 条 `train`、2 条 `val`、2 条 `final`）。
- **`--limit 1` 实际生效范围**：由于指定了 `--limit 1`，每个 split 实际仅各运行了第 1 条用例。
- **核心指标局限性警示**：
  - 评测用例为合成测试集，非生产环境真实黄金集。
  - 上一次测试（20260930-174424）Final 得分为 33.3%（在 3 项判定点中 PASS 1 项），本次 Final 得分为 66.7%（PASS 2 项）。**这绝不能归因于 Prompt 本身的质量提升**。本次 Prompt 根本未做变更（`Original == Best`，Delta = 0.0），得分差异可能受模型生成波动、裁判评判差异等因素影响，并非已证明的确定原因，不可作为模型通用泛化改善的证明。
  - 小样本单次 Smoke 运行绝非正式统计学证据，亦不能作为模型通用泛化改善的证明。

---

## 6. 复现指南

若需使用冻结源码复现本次测试，可直接使用本目录中的 `tested-source/` 快照与 `inputs/`（明确提示：执行后端仍可能加载全局上下文或配置，且受模型生成波动影响，输出不保证绝对一致）：

```bash
# 导航至本 review 目录所在仓库根目录

# 1. 运行快照源码单元测试（进入 tested-source 目录以确保加载快照代码与测试，避免受到仓库根目录同名文件影响）
( cd review/codex-root-smoke-v2-20261001-122743/tested-source && python3 -m unittest -q )

# 2. 复现 Dry-Run 预检
PYTHONPATH=review/codex-root-smoke-v2-20261001-122743/tested-source python3 \
  review/codex-root-smoke-v2-20261001-122743/tested-source/hillclimb.py \
  --target review/codex-root-smoke-v2-20261001-122743/inputs/target-prompt.md \
  --eval review/codex-root-smoke-v2-20261001-122743/inputs/evals.jsonl \
  --runner pi \
  --rounds 1 \
  --limit 1 \
  --repeats 1 \
  --dry-run

# 3. 复现真实 Smoke 运行
PYTHONPATH=review/codex-root-smoke-v2-20261001-122743/tested-source python3 -u \
  review/codex-root-smoke-v2-20261001-122743/tested-source/hillclimb.py \
  --target review/codex-root-smoke-v2-20261001-122743/inputs/target-prompt.md \
  --eval review/codex-root-smoke-v2-20261001-122743/inputs/evals.jsonl \
  --runner pi \
  --rounds 1 \
  --limit 1 \
  --repeats 1
```

---

## 7. 文件导航与目录结构

```text
review/codex-root-smoke-v2-20261001-122743/
├── README.md                      # 本审查说明文档
├── REPORT.md                      # agy3 独立测试总结报告
├── manifest.json                  # 结构化运行元数据与指标
├── manifest.md                    # 详细清单与逐字节校验记录
├── inputs/                        # 输入资产
│   ├── target-prompt.md           # 被评测的目标 Prompt 快照（~/.codex/AGENTS.md）
│   └── evals.jsonl                # 评测用例集（4/2/2，共 8 条）
├── logs/                          # 测试执行终端日志
│   ├── dryrun.log                 # Dry-Run 预检输出日志
│   ├── smoke.log                  # Real Smoke 运行输出日志
│   └── unittest.log               # 57 项单元测试输出日志
├── tested-source/                 # 被测源码快照（真实被测版本）
│   ├── README.md                  # 被测 README
│   ├── SKILL.md                   # 被测 SKILL
│   ├── install.md                 # 被测 install 文档
│   ├── hillclimb.py               # 被测核心代码
│   └── tests/                     # 被测测试套件
│       ├── __init__.py
│       └── test_core.py
└── results/                       # Hillclimb 运行产物
    ├── config.json                # 运行配置参数
    ├── preflight.json             # Preflight 检验结果与 3 项事实
    ├── summary.md                 # 运行总结
    ├── original-prompt.md         # 初始 Prompt 副本
    ├── best-prompt.md             # 最优 Prompt（保持 Baseline）
    ├── baseline/
    │   ├── train.jsonl            # Baseline train 评分结果
    │   └── val.jsonl              # Baseline val 评分结果
    └── final/
        └── original.jsonl         # Final 评估评分结果与回答
```

---

## 8. 生命周期与 Git 历史声明

- 本目录仅作为临时远程协同审查载体，待审查完成后将按指示移除。
- **Git 历史提示**：未来即使在仓库中执行 `git rm` 移除本目录及其文件，**这些文件的完整内容与提交记录仍将保留在 Git 历史中**。
