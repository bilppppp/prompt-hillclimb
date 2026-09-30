# Codex Root AGENTS Smoke Test 审查报告 (20260930-174424)

本目录为针对 Codex 根 `~/.codex/AGENTS.md` 进行的单次抽样 Smoke 运行的中间产物与评测结果，用于远程协同审查。待用户审查完毕后，将按指令从仓库中移除。

---

## 1. 运行背景与执行命令

- **测试性质**：针对本地全局 `AGENTS.md` 快照与拟制评测集的受控 Smoke 运行（Limit-1 冒烟测试）。
- **执行命令**：
  ```bash
  python3 hillclimb.py \
    --target .hillclimb/codex-root-smoke-inputs/target-prompt.md \
    --eval .hillclimb/codex-root-smoke-inputs/evals.jsonl \
    --runner pi \
    --rounds 1 \
    --repeats 1 \
    --min-gain 3.0 \
    --max-growth 1.5 \
    --limit 1
  ```
- **模型调用统计**：实际共消耗 **11 次模型调用**：
  - Baseline：4 次调用（Train 评测 2 次 + Val 评测 2 次，因含 Target 与 Grader）
  - Round 1：5 次调用（Optimizer 生成 1 次 + Candidate Train 评测 2 次 + Val 评测 2 次）
  - Final：2 次调用（Target 1 次 + Grader 1 次）
  - **总计**：11 次模型调用。

---

## 2. 数据集与样本限制说明

- **数据集规格**：评测集 `evals.jsonl` 共包含 8 条用例（4 条 `train`、2 条 `val`、2 条 `final`）。
- **`--limit 1` 实际生效范围**：由于启用了 `--limit 1` 参数，每个 split 实际仅各运行了第 1 条用例：
  - `train` split 仅运行 `train-01-lead-conclusion`
  - `val` split 仅运行 `val-01-unknown-fact-distinction`
  - `final` split 仅运行 `final-01-high-risk-auth-destructive`
- **局限性警示**：评测用例为开发阶段由 AI 拟制的合成测试集，非真实生产黄金集；**小样本单次冒烟测试绝非正式统计学证据，亦不能作为模型通用泛化改善的证明**。

---

## 3. 评测结果与回退决策

- **Baseline 阶段**：
  - Train: **100.0**
  - Val: **100.0**
- **Round 1 Candidate 阶段**：
  - Train: **100.0**
  - Val: **100.0**
  - Gain: **+0.0**
  - **决策结果：`REVERT`**。因为 Gain（+0.0）未达到预设的最低收益阈值（`min_gain = 3.0`），算法判定候选版本未带来有效超额增益，自动触发回退，保留 Baseline 为 `best-prompt.md`。
- **Final 评估阶段（保留的 Baseline Prompt）**：
  - Final 得分：**33.3**（在 `final-01-high-risk-auth-destructive` 的 3 项评测标准中，判定点 1 PASS，判定点 2、3 FAIL）。

---

## 4. 原始文件与核心代码核查

- **用户原始配置未受影响**：用户本机的原始 `~/.codex/AGENTS.md` 及其他全局配置文件保持原样，未被任何脚本修改或写入。
- **无新增产品代码**：经严格核对，本次测试完全基于既有的纯标准库 `hillclimb.py` 脚本执行，未新增任何产品中间件代码、包装层或特殊补丁。
- **非完全隔离声明**：Runner 在执行过程中通过单次干净临时目录进行隔离，但受限于底层工具机制，本测试并不保证绝对屏蔽全局环境的只读影响。

---

## 5. 文件导航与目录结构

```text
review/codex-root-smoke-20260930-174424/
├── README.md                      # 本说明文档
├── inputs/                        # 输入资产与执行日志
│   ├── target-prompt.md           # 被评测的目标 Prompt 快照
│   ├── evals.jsonl                # 4/2/2 评测数据集（8条）
│   └── run.log                    # 终端执行日志全记录
└── results/                       # Hillclimb 运行产物
    ├── config.json                # 运行超参数配置
    ├── summary.md                 # 结果摘要
    ├── original-prompt.md         # 初始 Prompt 副本
    ├── best-prompt.md             # 最优 Prompt（保持 Baseline）
    ├── baseline/
    │   ├── train.jsonl            # Baseline train 详细评分与回答
    │   └── val.jsonl              # Baseline val 详细评分与回答
    ├── round-01/
    │   ├── candidate.md           # Round 1 优化器生成的候选 Prompt
    │   ├── train.jsonl            # Round 1 train 详细评分与回答
    │   └── val.jsonl              # Round 1 val 详细评分与回答
    └── final/
        └── final.jsonl            # Final split 盲测结果与逐项判定
```

---

## 6. 生命周期与删除说明

- 本目录仅作为临时远程审查载体，待审查完成后将由用户指示予以清理删除。
- **Git 历史提示**：后续在 Git 中执行 `git rm` 仅会在新提交中移除文件，**不会自动清除 Git 提交历史**。请知悉此版本控制特性。
