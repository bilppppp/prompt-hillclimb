# Prompt Hillclimb MVP

`prompt-hillclimb` 是一个面向通用 AI Agent 与 Coding Harness 的轻量级 Prompt 自动优化工具与便携式 Skill。核心方法与评测框架不绑定特定 Agent 体系。

通过划分 `train`（Learning Signal）、`val`（Selection Signal）和 `final`（Blind Confirmation）三重经验评测集，借助本机配置好的 execution backend（当前 Python MVP 参考实现支持 `codex` 与 `pi` CLI），通过带有拒绝与早期停止机制的 Hillclimb 循环持续寻找具备实际泛化能力的 Prompt 改进版本。

> **核心声明**：当前版本专注于优化纯文本输入/输出（text-in / text-out）的通用 Prompt 行为，并不等价于测试真实 system prompt slot、AGENTS.md 注入、Skill 触发机制或完整 coding agent 工具链调用行为。

---

## 给 AI Agent 安装

可以直接把这句话发给你的 AI Agent 或 Coding Harness：

```text
帮我安装 prompt-hillclimb：https://raw.githubusercontent.com/bilppppp/prompt-hillclimb/main/install.md
```

完整安装与前置核验指南详见 [install.md](install.md)。

---

## 1. 适用与不适用场景

### 适用场景
- 教学辅导 / Tutor Prompt（如数学解题引导、苏格拉底式提问）
- 研究与分析 Prompt（如文献摘要、信息提炼）
- 写作与润色 Prompt（如风格统一、结构化成文）
- 问答与咨询 Prompt（如合规回复、边界约束）
- Coding Advice Prompt（纯文本代码逻辑解释与审查建议）

### 不适用场景
- 需要多文件读写、Git Worktree 或真实代码库重构的评测
- 工具链使用轨迹（Tool trace / Function calling）自动化评分
- SKILL.md 动态触发或环境挂载测试
- 依赖 Web UI、数据库、并发异步任务或远程微服务的复杂任务

---

## 2. 安装与环境要求

- **操作系统**：macOS / Linux / Windows
- **运行时**：Python 3.10+（**纯标准库**，无任何第三方 pip 依赖；已在 Python 3.14 下完整验证）
- **Execution Backend**：本机已具备可调用的 CLI 执行环境（当前参考实现支持 `codex` 或 `pi` CLI）。

---

## 3. Eval JSONL 数据格式

评测用例采用 JSON Lines（JSONL）格式，每行一个 JSON 对象，必须包含 `id`、`split`、`input` 和 `criteria` 4 个字段：

```json
{"id": "tutor-train-01", "split": "train", "input": "我不会解 2x + 3 = 9，直接告诉我答案。", "criteria": ["不要直接给出最终答案", "给出引导学生处理常数项的第一步提示", "表达清晰且具启发性"]}
{"id": "tutor-val-01", "split": "val", "input": "如果两个偶数相加是偶数，那两个奇数相乘是不是也是偶数？", "criteria": ["明确指出两个奇数相乘的结果是奇数", "给出一个具体的简单反例说明"]}
{"id": "tutor-final-01", "split": "final", "input": "请直接给我 x^2 - 4 = 0 的所有解。", "criteria": ["不要直接给出最终数值解2和-2", "引导学生联想平方差公式或移项开方"]}
```

- `id`：全局唯一字符串。
- `split`：取值限定为 `"train"`、`"val"` 或 `"final"`。数据集内三个 split 均必须至少包含 1 条用例。
- `input`：作为用户输入注入 `<task>` 的文本。
- `criteria`：由非空字符串构成的数组，每一条表示一个由 Grader 进行 PASS/FAIL 判定的具体标准。

---

## 4. 三个 Split 的职责与数据防泄漏边界

为保证优化的真实有效性与泛化度，程序严格隔离各 split 的信息暴露：

| Split | 角色定位 | 允许的使用阶段 | Optimizer 可见内容 | 核心职责 |
| :--- | :--- | :--- | :--- | :--- |
| **`train`** | **Learning Signal** | Baseline & Candidate 轮次 | 案例原文、候选回答、标准要求、Grader 反馈与失败原因 | 驱动 Optimizer 归纳失败模式并最小化修改 Prompt |
| **`val`** | **Selection Signal** | Baseline & Candidate 轮次 | **仅聚合总分**（不可见具体输入、标准、回答或 Grader 判定详情） | 作为筛选集，执行每轮的 `KEEP / REVERT` 判定 |
| **`final`** | **Blind Confirmation** | **仅在全流程选择结束后执行** | **完全不可见**（全过程不得运行、不得用于任何保留判定） | 作为最终盲测集，对 Original 与 Best 进行独立盲测对比 |

---

## 5. 快速上手

### 5.1 Dry Run 预检
在不发起真实执行调用的情况下验证数据格式、Runner 可用性、配置参数并打印执行调用次数预估：
```bash
python3 hillclimb.py \
  --target examples/tutor-prompt.md \
  --eval examples/tutor-evals.jsonl \
  --runner codex \
  --rounds 1 \
  --dry-run
```

### 5.2 测量基线噪声（可选独立模式）
Prompt 评估容易受到 natural variance 干扰。使用 `--measure-noise` 会独立执行 2 次 Baseline 评测并计算验证集的分数波动：
```bash
python3 hillclimb.py \
  --target examples/tutor-prompt.md \
  --eval examples/tutor-evals.jsonl \
  --runner codex \
  --measure-noise
```
输出示例：
```text
Agent invocation estimate (Noise Measurement):
  Run 1: 12
  Run 2: 12
  Total: ~24

Baseline run 1
train: 75.0
val:   66.7

Baseline run 2
train: 75.0
val:   83.3

Observed val delta:
16.6

Observed baseline variation is 16.6 points.
Consider using --min-gain >= 17 or increasing --repeats.
```

### 5.3 启动 Hillclimb 优化
使用 Codex Runner 运行 3 轮优化：
```bash
python3 hillclimb.py \
  --target examples/tutor-prompt.md \
  --eval examples/tutor-evals.jsonl \
  --runner codex \
  --rounds 3 \
  --min-gain 3.0
```

使用 Pi Runner 运行优化：
```bash
python3 hillclimb.py \
  --target examples/tutor-prompt.md \
  --eval examples/tutor-evals.jsonl \
  --runner pi \
  --rounds 3 \
  --min-gain 3.0
```

---

## 6. 参数详解

| 参数 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--target` | 路径 | 必须 | 待优化的初始 Prompt 文件路径（如 markdown 或 txt） |
| `--eval` | 路径 | 必须 | 评测数据集 JSONL 路径 |
| `--runner` | `codex` \| `pi` | `codex` | 指定调用的本机 CLI execution backend |
| `--rounds` | 整数 | `3` | Hillclimb 尝试优化的轮次上限（配置轮次） |
| `--repeats` | 整数 | `1` | 每个 case 的重复评测次数，综合平摊单次采样方差 |
| `--min-gain` | 浮点数 | `3.0` | 接受 candidate 的最小验证集得分提升（百分点） |
| `--max-growth` | 浮点数 | `1.5` | Candidate 长度相对当前 Best Prompt 允许的最大膨胀倍数 |
| `--limit` | 整数 | `None` | 每个 split 仅截取前 N 条用例用于快速 Smoke Run |
| `--dry-run` | 标志 | `False` | 仅做静态校验与调用估算，不发起任何真实执行调用 |
| `--measure-noise` | 标志 | `False` | 独立运行两次 Baseline 评估验证集天然方差后退出 |

---

## 7. 判定规则、Preflight 与停止机制

### 7.1 轻量 Preflight 预检
在 Baseline 成功评估后、正式进入优化轮次前，程序会自动执行 3 项轻量 Preflight 检查并生成 `preflight.json`：
1. **Noise Check**：Original Prompt 保持不变，独立重测一次完整 val 集。若得分绝对差 $\Delta \ge \text{min\_gain}$，输出 WARNING（不中止流程，min_gain 保持用户设定）。若重测出错，立即 `ABORT` 并退出非零。
2. **Headroom Check**：若 Baseline train $\ge 95\%$ 且 val $\ge 95\%$，发出余量狭窄警告（$95\%$ 仅为工程经验阈值，不额外调用，不自动中止）。
3. **Grader Stability Check**：从 Baseline train 结果中最多抽取 3 份输出记录，以完全相同的 task、criteria 和已获得 response 重新调用 Grader（**绝不重新调用 Target 生成**），比对每个 criterion 的 PASS/FAIL 判定，统计不一致数量与比例。若出现不一致则输出警告；若 Grader 进程或格式异常则立即 `PREFLIGHT FAILED ABORT`。

### 7.2 Candidate 静态过滤
Optimizer 生成候选 Prompt 后，在发起真实评估前必须通过 3 重静态检查：
1. **Case ID 泄漏检测**：Candidate 中严禁直接包含任一 train case 的 id（如 `tutor-train-01`）。
2. **输入片段抄袭启发式检测**：提取 train 用例输入中长度 $\ge 30$ 字符的滑动片段，检查是否被直接拼入 Prompt。
3. **长度膨胀限制**：`len(candidate) <= len(best_prompt) * max_growth`，防止模型无休止堆砌特例规则。

若任一检查失败，该轮标记为 `INVALID` 并立即 `REVERT`，不进入评估阶段。

### 7.3 接受规则（KEEP vs. REVERT）
只有当 Candidate 同时满足以下两个条件时才被采纳：
$$\text{candidate\_train} \ge \text{best\_train} \quad \text{AND} \quad \text{candidate\_val} \ge \text{best\_val} + \text{min\_gain}$$
若采纳，当前 candidate 成为新的 best_prompt，重置连续 revert 计数器为 0；否则一律执行 `REVERT`。

### 7.4 早期停止与停滞诊断（Early Stopping & Stall Analysis）
1. **无失败立即停止（Stop reason: `NO_TRAIN_FAILURE_SIGNAL`）**：
   每轮开始前检查 train failures，若集合为空（无论源自满分 Baseline 还是某轮 KEEP 后达到满分），程序立即正常停止，不调用 Optimizer，不创建该轮目录与候选。
2. **连续 2 次有效 REVERT 停滞（Stop reason: `STALLED_AFTER_2_REVERTS`）**：
   - `consecutive_reverts` 计数器初始为 0；
   - 每次完整 train+val 评估后的有效 `REVERT` 使计数器 $+1$；
   - 任何 `KEEP` 或 `INVALID`（optimizer 异常、静态校验失败、评测进程错误等）均将其重置为 0；
   - 当计数器达到 2 时，立即停止后续 Prompt 修改，调用诊断分析器生成 `stall-analysis.md`；
   - **诊断定位说明**：诊断分析器仅用于向开发者提供只读归因建议（分类包括 `PROMPT_GAP`、`GRADER_ISSUE`、`AMBIGUOUS_EVAL`、`LIKELY_VARIANCE`、`OTHER`），**严禁输出新候选 Prompt，绝不自动篡改评测标准、用例、划分或重启优化**。

### 7.5 Final 盲测对比（Final Blind Comparison）
全流程选择全部结束后，执行一次最终盲测对比：
- **Best != Original**：分别使用相同 backend 和 repeats 评测 Original 与 Best，生成 `final/original.jsonl` 与 `final/best.jsonl`，报告 `Delta: Best - Original`（负值照实报告）。
- **Best == Original**：只执行 1 次评测，逻辑共用结果，生成 `final/original.jsonl`，明确报告 `Delta: 0.0 (no accepted prompt change)`。
- **错误语义**：若任何一方评测发生异常，保留错误并报告 `Final comparison: FAILED`，不生成虚假 Delta，程序以非零状态码退出。

---

## 8. 执行调用次数估算（Agent Invocation Estimate）

每次运行的 Agent 执行调用次数（Agent invocation estimate，上限）计算公式如下：
- **Baseline**：$(\text{train} + \text{val}) \times \text{repeats} \times 2$
- **Preflight**：$2 \times \text{val} \times \text{repeats} \text{ (Noise)} + \min(3, \text{train} \times \text{repeats}) \text{ (Grader stability)}$
- **每轮 Candidate**：$1 \text{ (Optimizer)} + (\text{train} + \text{val}) \times \text{repeats} \times 2$
- **Stall 诊断**：当 $\text{rounds} \ge 2$ 时最多包含 $1$ 次条件性诊断调用
- **Final 盲测对比**：最坏情况下（Best != Original）为 $4 \times \text{final} \times \text{repeats}$（若未发生改动仅运行 $2 \times \text{final} \times \text{repeats}$）

以 4 train、2 val、2 final、3 轮、repeats=1 为例：
- Baseline: $(4 + 2) \times 1 \times 2 = 12$
- Preflight: $2 \times 2 \times 1 + \min(3, 4 \times 1) = 4 + 3 = 7$
- Rounds (3 轮): $3 \times [1 + (4 + 2) \times 1 \times 2] = 3 \times 13 = 39$
- Stall categorizer: 至多 $1$
- Final blind comparison: 上限 $4 \times 2 \times 1 = 8$
$$\text{Total (upper bound)} = 12 + 7 + 39 + 1 + 8 = 67 \text{ calls}$$

> [!NOTE]
> Hillclimb会重复调用当前execution backend，正式运行前用--dry-run查看预计执行次数。

---

## 9. 子进程隔离与当前 CLI 能力限制

### 9.1 临时目录隔离
每次调用 execution backend（Target、Grader、Optimizer、Categorizer）时，主程序都会：
1. 创建全新的独立临时目录 `tempfile.TemporaryDirectory()`。
2. 将子进程的 `cwd` 强制设定为该空临时目录。
3. 严禁在临时目录内拷贝原 prompt、eval JSONL、`.hillclimb/` 历史记录或项目文件。
4. 所需文本均通过标准输入（stdin）或参数传入，并在 Prompt 首部注入无外部工具与目录读取的强指令。

### 9.2 Codex CLI 隔离与局限
- **已使用的隔离参数**：
  - `-C <temp_dir>`：强制工作根目录为新空临时目录
  - `--skip-git-repo-check`：脱离 git 仓库限制
  - `--ephemeral`：不持久化会话记录
  - `--ignore-user-config`：忽略用户级 config.toml
  - `--ignore-rules`：忽略本地 execpolicy 规则
  - `-s read-only`：启用 read-only 沙箱，禁止外部工作区写操作
  - `--color never`：关闭 ANSI 颜色标记
  - `-o <output_file>`：直接输出模型最后一次回答至目标文件，规避终端格式混淆
- **当前限制与明确说明**：
  - **Read-only 不等于禁用读文件或工具**：`-s read-only` 仅禁止破坏性写操作，底层执行环境仍然具备读取系统文件或触发工具的能力，不能声称 Codex 实现了完全隔离。
  - **全局指令与技能污染**：若 `$CODEX_HOME/AGENTS.md` 或全局 `$CODEX_HOME/skills` 存在，相关指令与技能上下文仍可能被底层载入。程序在运行时会输出明确 WARNING，但绝不自动篡改或删除用户全局配置。

### 9.3 Pi CLI 隔离与局限
- **已使用的隔离参数与输入方式**：
  - `-p`（`--print`）：非交互单次打印模式
  - **标准输入传参（stdin）**：Prompt 完整通过 stdin 管道传入，彻底规避 CLI 参数长度限制以及 `@filename` 语法误触发文件载入的边界问题。
  - `--no-tools`：彻底禁用所有内建与扩展工具
  - `--no-skills`：禁用所有技能发现
  - `--no-context-files`：彻底禁用 `AGENTS.md` 与 `CLAUDE.md` 发现与加载
  - `--no-extensions`：禁用外部插件
  - `--no-session`：无状态瞬态运行，不落盘
  - `--no-prompt-templates`：禁用模板载入
  - `--no-themes`：禁用交互主题
  - `--no-approve`：忽略项目本地信任配置
- **当前限制与明确说明**：
  - **全局 SYSTEM.md / APPEND_SYSTEM.md 绕过风险**：经源码确认，Pi CLI 的 `--no-context-files` 仅负责清空 `AGENTS.md` 与 `CLAUDE.md`，若用户目录（如 `~/.pi/agent/SYSTEM.md` 或 `APPEND_SYSTEM.md`）存在系统提示词文件，Pi 底层仍会将其作为 system prompt 载入。主程序在启动时会检测该路径并打印 WARNING，但绝不擅自篡改用户文件。
  - **底层 Persona 模板**：底层各 execution backend 的默认系统提示词模板由 CLI 内部控制，无法完全抹除 runner 自身的默认 coding assistant persona。

---

## 10. 输出目录结构与报告示例

### 10.1 目录结构
每次运行在当前目录下生成 `.hillclimb/YYYYMMDD-HHMMSS/`（若同秒多次调用自动追加 `_1`、`_2` 等后缀）：

```text
.hillclimb/
└── 20261001-120000/
    ├── original-prompt.md        # 原始输入的 Prompt
    ├── best-prompt.md            # 最终优胜的 Best Prompt
    ├── preflight.json            # Preflight 诊断数据（noise、headroom、grader_stability）
    ├── stall-analysis.md         # 触发连续 2 次 REVERT 停滞时的只读诊断报告（仅在触发时生成）
    ├── summary.md                # 完整的 Markdown 评测报告
    ├── config.json               # 本次运行的完整超参和配置
    ├── baseline/
    │   ├── train.jsonl           # Baseline train 逐条回答与 Grader 结果
    │   └── val.jsonl             # Baseline val 逐条回答与 Grader 结果
    ├── round-01/
    │   ├── candidate.md          # 第 1 轮生成的 Candidate Prompt
    │   ├── train.jsonl           # 候选 Prompt 在 train 上的详细评测
    │   └── val.jsonl             # 候选 Prompt 在 val 上的详细评测
    ├── round-02/
    │   └── ...
    └── final/
        ├── original.jsonl        # Original Prompt 在 final 盲测集上的评测明细
        └── best.jsonl            # Best Prompt 在 final 盲测集上的评测明细（若 Best!=Original）
```

### 10.2 Summary 报告示例
```markdown
# Prompt Hillclimb

Execution backend: codex
Rounds configured: 3
Rounds executed: 2
Stop reason: STALLED_AFTER_2_REVERTS
Repeats: 1
Min gain: 3.0

## Baseline

Train: 75.0
Val: 66.7

## Preflight

Observed val variation: 0.0
Headroom warning: False
Grader disagreement: 0/3 (0.0%)

## Round 1

Train: 75.0
Val: 66.7
Gain: +0.0
Decision: REVERT

## Round 2

Train: 75.0
Val: 66.7
Gain: +0.0
Decision: REVERT

## Best

Train: 75.0
Val: 66.7

## Final Blind Comparison

Original == Best
Original: 75.0
Best: 75.0 (shared with Original)
Delta: 0.0 (no accepted prompt change)

Best prompt:
best-prompt.md

Stall analysis:
stall-analysis.md
```

---

## 11. 已知限制与使用建议

1. **Eval 质量决定优化上限**：Prompt 得分提高不代表现实效果一定变好。有偏或低质的标准会导致模型优化到错误或投机的方向。
2. **Val 仍会被间接过拟合**：虽然 Optimizer 不可见 Val 内容，但由于每一轮的 KEEP/REVERT 由 Val 分数决定，Val 充当了选择集角色。多轮迭代后 Val 分数仍可能虚高，因此必须依靠最终一次性的 Final 盲测作校核。
3. **示例与小样本局限**：示例中的少量 case 仅供快速验证流程通道，小样本无法证明 Prompt 真正得到改进。正式使用需要构建规模更大、覆盖更多样真实场景的 case 集合，并结合 `--measure-noise` 与 `--repeats` 观察结果稳定性，而不是盲目将小样本波动宣称为统计结论。
4. **默认 min-gain 仅为工程经验值**：默认 `--min-gain 3.0` 是一个保守的工程经验阈值，并无通用统计显著性意义。强烈建议先使用 `--measure-noise` 观测 baseline 在当前任务上的天然波动，再针对性选择合理阈值。
5. **LLM Grader 波动**：细粒度 Criterion PASS/FAIL 旨在拆解多维度要求、减少单一大分的主观性，但仍可能受判定抖动影响。Preflight 的 Grader stability 提供了轻量观测通道。
6. **同 Execution Backend 偏好风险（Self-preference）**：当前 MVP 的 Target、Grader 和 Optimizer 复用同一 CLI runner，可能存在自洽偏好或关联错误。代码内部保留了 `run_target`、`run_grader`、`run_optimizer` 独立函数，为后续扩展多 backend 架构预留了扩展点。
7. **防泄漏启发式并不绝对**：当前的文本滑动窗口检查无法拦截同义改写（paraphrase）或语义层面的基准记忆（benchmark memorization）。
