---
name: prompt-hillclimb
description: Evaluate and iteratively improve a reusable text prompt using train, validation, and final evaluation cases.
---

# Prompt Hillclimb Skill

面向通用 AI Agent 与 Coding Harness 的轻量级 Prompt 优化 Skill。通过经验评测集（Empirical Evaluation Data）系统化优化通用文本输入/输出 Prompt，而非人工盲目猜测。

本方法与优化思想不绑定任何特定 Agent 体系。在当前 Python MVP 参考实现中，底层 execution backend 支持 `codex` 与 `pi` CLI。

## When to Use
- 优化长生命周期的指导性 Prompt（教学辅导、分析调研、助手交互、文本写作等）。
- 借助经验评估验证 Prompt 候选版本是否能在多样用例上带来真实泛化收益。
- 自动化进行 Baseline 与轻量 Preflight（检测自然抖动、空间余量与 Grader 稳定性）。
- 在选择阶段完全结束后，对 Original 与 Best 进行独立盲测对比（Final Blind Comparison）。

## When NOT to Use
- 涉及多文件代码库修改、代码执行或真实工具调用（Tool trace）评测的任务。
- 评测系统槽位注入、全局 Agent 提示词注入或宿主特定运行时插件机制。
- 缺少或未经核实评估用例的场景（严禁凭空捏造未验证评测用例谎称优化）。

## Step-by-Step Workflow

> **路径定位说明**：宿主 AI Agent / Harness 在调用本 Skill 时，应先定位本项目的安装目录 `<prompt-hillclimb-skill-dir>`。运行时调用 `python3 <prompt-hillclimb-skill-dir>/hillclimb.py`，生成的 `.hillclimb/` 运行记录目录将保存在当前执行工作区（`cwd`）中。

1. **核验输入数据**：
   - 确认待优化的目标 Prompt 文件存在（如 `prompt.md`）。
   - 确认包含三阶段数据集的 JSONL 文件存在：
     - `train`（Learning Signal）：用于捕获失败模式并驱动优化；
     - `val`（Selection Signal）：用于计算验证得分并执行 KEEP / REVERT 候选保留决策；
     - `final`（Blind Confirmation）：仅在全流程选择结束后执行一次盲测对比，结果绝不反馈给优化。
   - 若尚无评估数据集，需先与用户共同构建真实评测集，切勿凭空编造虚假用例。

2. **执行 Dry-Run 预检**：
   核验配置、execution backend 可用性、用例分布与执行调用次数估算：
   ```bash
   python3 <prompt-hillclimb-skill-dir>/hillclimb.py \
     --target path/to/prompt.md \
     --eval path/to/evals.jsonl \
     --runner codex \
     --rounds 1 \
     --dry-run
   ```

3. **测量基线噪声（可选独立模式）**：
   若需在优化前单独观测当前任务在当前 execution backend 下的天然波动：
   ```bash
   python3 <prompt-hillclimb-skill-dir>/hillclimb.py \
     --target path/to/prompt.md \
     --eval path/to/evals.jsonl \
     --runner codex \
     --measure-noise
   ```

4. **启动优化循环**：
   ```bash
   python3 <prompt-hillclimb-skill-dir>/hillclimb.py \
     --target path/to/prompt.md \
     --eval path/to/evals.jsonl \
     --runner codex \
     --rounds 3 \
     --min-gain 3.0
   ```
   - 程序在 Baseline 成功后会自动执行轻量 Preflight（包含验证集方差观测、满分余量告警与最多 3 份输出的 Grader 稳定性重测）。
   - 若 Baseline 或优化后某轮 train 评测无任何失败标准，程序将立即停止（Stop reason: `NO_TRAIN_FAILURE_SIGNAL`）。
   - 若连续 2 轮有效评估均触发 REVERT，程序将判定停滞（Stop reason: `STALLED_AFTER_2_REVERTS`），生成只读诊断报告 `stall-analysis.md`（仅给出分析与建议，绝不擅自篡改评测集或重启优化）。
   - 选出 Best Prompt 后，自动进入 Final 盲测对比：若 Best 与 Original 相同则共享 1 次评测（Delta 为 0.0）；若不同则分别评测并报告实际 Delta（含负值）。

5. **审查并向用户报告结果**：
   - 检查 `.hillclimb/<timestamp>/summary.md`。
   - 向用户汇报 Baseline（train/val）、Preflight 事实、每轮 candidate 变更及 KEEP / REVERT 决策、最终盲测对比（Original / Best / Delta）。
   - 查看 `.hillclimb/<timestamp>/best-prompt.md`。
   - **注意**：程序默认绝不覆盖用户的原始 Prompt 文件，始终将结果呈现给用户审核确认。

## Cost Notice
> [!NOTE]
> Hillclimb会重复调用当前execution backend，正式运行前用--dry-run查看预计执行次数。
