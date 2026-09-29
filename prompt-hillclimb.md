# Prompt Hillclimb MVP

请直接在当前目录实现一个可运行的小项目 `prompt-hillclimb`。

不要只给方案。创建实际文件、实现代码、运行必要测试，并在最后汇报结果。

---

# 1. 项目目标

实现一个最小的 Prompt 自动优化工具。

给定：

- 一个待优化 Prompt
- 一组 eval cases
- 一个 runner：`codex` 或 `pi`

程序自动执行：

```text
baseline
→ 在 train cases 上发现失败
→ 让模型对 Prompt 做一个最小修改
→ 重新跑 train + val
→ 判断是否真正改善
→ keep / revert
→ 下一轮
→ 选择最佳 Prompt
→ 最后只运行一次 final
```

核心目标不是“润色 Prompt”，而是：

> 根据可重复 eval，寻找能够泛化到未参与优化的数据上的 Prompt 改进。

第一版只优化 **text-in / text-out Prompt**。

适用于：

- 学习 / tutor prompt
- 研究 / 分析 prompt
- 写作 prompt
- 创意 prompt
- 问答 prompt
- coding advice prompt
- 普通 system-like instruction

第一版不实现：

- Git worktree
- 对真实代码仓库修改结果的评分
- AGENTS.md 的真实 harness 注入
- SKILL.md trigger eval
- tool trace grading
- Web UI
- 数据库
- API server
- 并行执行
- 多 agent orchestration
- 自动生成 eval
- model / effort 自动搜索
- provider API abstraction

---

# 2. 技术原则

优先最小实现。

要求：

```text
Python 3
只使用标准库
不新增第三方 Python 依赖
不直接调用 OpenAI / Anthropic / Gemini API
不要求额外 API key
```

模型调用全部复用用户已经安装并登录的 CLI。

Codex 和 Pi 的具体 CLI 参数不要凭记忆写死。

实现前先实际运行：

```bash
codex exec --help
pi --help
```

确认：

- 如何在非 Git / 临时空目录运行
- 如何只取得最终回答
- 如何关闭 Skill、context file、project instructions 等自动加载
- 如何关闭工具使用
- 是否存在 ephemeral / no-session 等隔离参数

只使用实际存在的参数。

如果某个隔离能力当前 CLI 不支持，明确记录为限制，不要伪造参数。

---

# 3. 项目结构

最终至少实现：

```text
prompt-hillclimb/
├── README.md
├── SKILL.md
├── hillclimb.py
├── examples/
│   ├── tutor-prompt.md
│   └── tutor-evals.jsonl
└── tests/
    └── test_core.py
```

如果确实能明显简化代码，可以拆出一个小模块，但不要为了架构漂亮增加无必要文件。

---

# 4. Eval 格式

使用 JSONL。

每个 case：

```json
{
  "id": "tutor-01",
  "split": "train",
  "input": "我不会解 2x + 3 = 9，直接告诉我答案。",
  "criteria": [
    "不要直接给出最终答案",
    "先给一个能够推动学生继续思考的提示",
    "数学内容必须正确"
  ]
}
```

允许：

```text
split = train | val | final
```

只要求字段：

```text
id
split
input
criteria
```

其中：

```text
id 必须唯一
criteria 必须为非空字符串数组
```

程序启动时检查：

- id 唯一
- split 合法
- train / val / final 都至少存在一个 case
- criteria 非空
- JSONL 可正常解析

不要设计复杂 schema。

---

# 5. 三个 split 的职责

必须严格区分：

## train

用于：

- optimizer 查看具体 case
- optimizer 查看 target response
- optimizer 查看 criterion PASS / FAIL
- optimizer 分析失败模式

## val

用于：

- 每一轮 candidate 的 KEEP / REVERT
- optimizer 不得看到 case 内容
- optimizer 不得看到 criteria
- optimizer 不得看到 response 或 grader feedback

hillclimb 只能获得 val 的 aggregate score。

## final

只用于最终报告。

在 hillclimb 选择结束前：

```text
不得运行 final
```

最佳 candidate 确定后，只运行一次 final。

不得使用 final 做任何 KEEP / REVERT 判断。

---

# 6. 子进程隔离

这是核心正确性要求。

target、grader、optimizer 每次模型调用必须：

```python
subprocess.run(..., cwd=<全新的空临时目录>)
```

使用 `tempfile.TemporaryDirectory()`。

临时目录中不得复制：

```text
eval JSONL
prompt 文件
.hillclimb/
历史输出
项目文件
AGENTS.md
SKILL.md
```

模型需要的全部输入通过 command argument、stdin 或明确生成的单个输入文本传入。

每次 wrapper prompt 中加：

```text
直接根据下面提供的文本回答。
不要读取本地文件。
不要搜索目录。
不要使用工具。
不要尝试寻找额外上下文。
```

但这只是第二道防线，不能替代 CLI 层面的实际隔离。

---

# 7. Codex / Pi 隔离

实现前通过：

```bash
codex exec --help
pi --help
```

确认当前版本能力。

尽可能关闭：

```text
tools
skills
context files
project instructions
session history
extensions
web search
prompt templates
```

如果 Pi 当前支持类似：

```text
--no-tools
--no-skills
--no-context-files
--no-extensions
--no-session
```

则使用实际存在的参数。

如果 Codex 当前支持类似：

```text
--skip-git-repo-check
--ephemeral
--ignore-user-config
--ignore-rules
-C <temp_dir>
```

则使用实际存在的参数。

不要假设这些参数一定存在，必须以本机 `--help` 为准。

如果无法彻底关闭用户级全局 instructions，例如：

```text
$CODEX_HOME/AGENTS.md
```

则：

- 检测其是否存在
- 打印明确 WARNING
- README 中记录此限制
- 不自动删除、移动或修改用户全局配置
- 不复制或修改 auth/token 文件

---

# 8. Runner

实现：

```python
run_agent(runner: str, prompt: str) -> str
```

支持：

```text
codex
pi
```

使用：

```python
subprocess.run()
```

禁止：

```text
shell=True
```

设置合理 timeout，例如：

```text
300 秒
```

CLI 不存在时给明确错误：

```text
codex executable not found
pi executable not found
```

不要尝试自动安装。

不要修改用户 Codex / Pi 配置。

---

# 9. 最终回答读取

不要简单把整个 stdout 当模型最终回答。

Codex：

优先使用本机 `codex exec --help` 中实际存在的“只输出最终回答”能力。

如果存在类似：

```text
--output-last-message <path>
```

则：

- 提前创建父目录
- 执行后检查 return code
- 检查输出文件实际存在
- 再读取文件

即使 exit code 为 0，但输出文件不存在，也视为 error。

Pi：

如果当前版本 `--print` 明确只输出最终回答，则使用。

如果 stdout 中混入进度日志，则按当前 CLI 提供的机器可读 / final-only 方式处理。

不要靠脆弱的字符串猜测日志边界。

---

# 10. Target execution

对于每个 eval case，将 candidate Prompt 和 case input 组合成：

```text
直接根据下面提供的文本回答。
不要读取本地文件。
不要搜索目录。
不要使用任何工具。

<instruction>
{candidate_prompt}
</instruction>

<task>
{case_input}
</task>
```

调用指定 runner。

保存模型原始输出。

target 不得获得：

- criteria
- split
- case id
- grader instruction
- 其他 case

---

# 11. Grader

MVP 使用 criterion-level LLM grader。

grader 输入包含：

```text
task
criteria
response
```

不包含：

```text
split
case id
其他 case
历史结果
```

要求 grader 对每条 criterion 输出：

```text
1: PASS | 简短原因
2: FAIL | 简短原因
3: PASS | 简短原因
```

编号必须与 criteria 顺序一致。

禁止 grader 自己输出最终 0-100 总分。

Python 负责计算。

---

# 12. Grader 解析

对于 N 条 criteria，必须成功解析出：

```text
1..N
```

每条只能是：

```text
PASS
FAIL
```

允许后面有原因。

任何情况：

```text
缺编号
重复编号
未知状态
条数不匹配
无法解析
```

均视为 grader error。

case score：

```python
passed / total * 100
```

split score 使用：

```text
所有 criterion 的总体通过率
```

即：

```python
total_passed_criteria / total_criteria * 100
```

不要简单平均 case score。

---

# 13. Error 规则

不得悄悄忽略失败 case。

以下都算 error：

```text
target timeout
target non-zero exit
target final output 缺失
grader timeout
grader non-zero exit
grader parse failure
optimizer timeout
optimizer non-zero exit
optimizer marker parse failure
candidate validation failure
```

规则：

## baseline

任何 case 出现 error：

```text
ABORT
```

不得继续 hillclimb。

## candidate round

任何 case 出现 error：

```text
round = INVALID
REVERT
```

不得只对成功 case 求平均。

不得把 error 自动记成 0 分继续比较。

---

# 14. Baseline

首先使用原始 Prompt 跑：

```text
train
val
```

不运行 final。

分别计算：

```text
train score
val score
```

例如：

```text
Baseline

train: 71.3
val:   68.8
```

保存 train 每条：

```text
input
response
criterion results
grader feedback
```

保存 val 结果到磁盘用于报告，但：

```text
不得传给 optimizer
```

optimizer 只能知道：

```text
val aggregate score
```

甚至默认 optimizer 不需要知道当前 val score，只负责根据 train 改 prompt。

---

# 15. Noise measurement

增加：

```bash
--measure-noise
```

行为：

- 不执行 hillclimb
- baseline 连续独立执行 2 次
- 输出 train / val 两次结果
- 输出 absolute delta

例如：

```text
Baseline run 1
train: 74.2
val:   70.5

Baseline run 2
train: 73.1
val:   74.0

Observed val delta:
3.5
```

简单提示：

```text
Observed baseline variation is 3.5 points.
Consider using --min-gain >= 4 or increasing --repeats.
```

不要实现复杂统计模型。

---

# 16. Repeats

增加：

```bash
--repeats N
```

默认：

```text
1
```

对于每个 case：

```text
target → grader
```

重复 N 次。

该 case 的各 criterion 通过率取所有重复结果综合后的通过率。

split score仍使用全部 criterion × repeats 的总体通过率。

baseline 和 candidate 必须使用同样 repeats。

---

# 17. Optimizer

每轮 optimizer 只能看到：

```text
当前 best Prompt
train cases
train target responses
train criterion PASS / FAIL
train grader feedback
```

不得看到：

```text
val case
val criteria
val response
val grader feedback
final 的任何内容
```

optimizer instruction：

```text
目标是改善重复出现的失败模式，而不是针对具体案例打补丁。

每轮只做一个主要的概念性修改。

优先：
- 删除无效或冲突规则
- 澄清模糊约束
- 增加缺失的通用原则
- 简化不必要 wording

避免：
- 把具体 eval case 写进 Prompt
- 针对 case id 添加规则
- 加大量例外
- 无理由重写整个 Prompt
- 单纯让 Prompt 越来越长
```

要求输出：

```text
<<<PROMPT>>>
完整的新 Prompt
<<<END_PROMPT>>>
```

---

# 18. Marker 提取

解析规则：

1. 找最后一个：

```text
<<<PROMPT>>>
```

2. 从该位置向后找第一个：

```text
<<<END_PROMPT>>>
```

3. 中间内容作为 candidate

如果没有完整闭合：

```text
optimizer error
round INVALID
停止本轮
```

增加测试：

```text
解释文本中出现旧 marker
真正答案中又出现 marker
```

确保取最后一个完整 prompt block。

---

# 19. Candidate validation

candidate 在执行 eval 前先做静态检查。

## 19.1 Case ID 泄漏

如果 candidate 包含任意 train case id：

```text
INVALID
REVERT
```

## 19.2 Input 明显复制

检查 train input 中较长片段是否直接出现在 candidate 中。

实现保持简单。

例如对 train input 做：

- normalize whitespace
- 取长度 >= 30 字符的连续片段
- 检查是否直接出现在 candidate

如果命中：

```text
INVALID
REVERT
```

这是 heuristic。

README 明确说明：

> 该检查不能检测 paraphrase 或语义级 benchmark memorization。

## 19.3 Prompt 长度增长

增加：

```bash
--max-growth
```

默认：

```text
1.5
```

candidate 长度不得超过当前 best Prompt：

```text
current_length * max_growth
```

超过：

```text
INVALID
REVERT
```

用户可修改该阈值。

---

# 20. Hillclimb 规则

默认：

```text
3 rounds
```

CLI：

```bash
--rounds 3
```

每轮：

```text
best prompt
↓
optimizer 看 train failures
↓
candidate
↓
candidate validation
↓
完整重新跑 train
↓
完整重新跑 val
↓
KEEP / REVERT
```

---

# 21. 接受规则

增加：

```bash
--min-gain
```

默认：

```text
3
```

接受 candidate：

```text
candidate_train >= best_train
AND
candidate_val >= best_val + min_gain
```

满足：

```text
KEEP
```

否则：

```text
REVERT
```

默认 `3` 只是保守值，不代表统计意义上的通用阈值。

README 要说明：

> 建议先使用 `--measure-noise` 测 baseline 自身波动，再选择合理的 `--min-gain`。

---

# 22. Final evaluation

hillclimb 全部完成后：

```text
确定 best Prompt
```

然后第一次运行：

```text
final
```

final：

- 使用与前面相同 runner
- 使用相同 repeats
- 不用于任何选择
- 只写进最终报告

输出：

```text
Best train
Best val
Final
```

不得用 final score 再修改 Prompt。

---

# 23. Smoke limit

增加：

```bash
--limit N
```

只用于快速 smoke run。

行为：

- 每个 split 最多取前 N 条
- 保留 train / val / final 三类
- 明确在输出中标记：

```text
LIMITED SMOKE RUN
```

README 明确：

> 使用 `--limit` 的结果不能视为正式 Prompt 改进证据。

---

# 24. 成本 / 调用次数预估

在正式运行前打印预计模型调用次数。

基本公式：

```text
每个 case 每个 repeat：
1 target
1 grader
```

baseline：

```text
(train + val) × repeats × 2
```

每轮：

```text
1 optimizer
+
(train + val) × repeats × 2
```

最终：

```text
final × repeats × 2
```

打印例如：

```text
Estimated model calls

Baseline: 32
Round 1: 33
Round 2: 33
Round 3: 33
Final: 12

Total: ~143
```

这里只统计模型 invocation 数，不需要估算 token 或价格。

README 说明：

> 如果在 Codex Skill 内运行本项目，又由脚本启动 `codex exec`，这些嵌套调用仍会消耗同一账户 / 订阅额度。

---

# 25. 输出目录

每次运行创建：

```text
.hillclimb/
└── YYYYMMDD-HHMMSS/
    ├── original-prompt.md
    ├── best-prompt.md
    ├── summary.md
    ├── config.json
    ├── baseline/
    │   ├── train.jsonl
    │   └── val.jsonl
    ├── round-01/
    │   ├── candidate.md
    │   ├── train.jsonl
    │   └── val.jsonl
    ├── round-02/
    │   └── ...
    └── final/
        └── final.jsonl
```

`.hillclimb/` 位于主程序工作目录。

但任何 agent subprocess：

```text
都不能以这个目录作为 cwd
```

---

# 26. JSONL result

每条至少记录：

```json
{
  "id": "tutor-01",
  "repeat": 1,
  "response": "...",
  "criteria": [
    {
      "index": 1,
      "status": "PASS",
      "reason": "..."
    },
    {
      "index": 2,
      "status": "FAIL",
      "reason": "..."
    }
  ]
}
```

error 时记录：

```json
{
  "id": "tutor-01",
  "repeat": 1,
  "error": {
    "stage": "grader",
    "type": "parse_error",
    "message": "..."
  }
}
```

不要静默丢弃。

---

# 27. summary.md

最终报告：

```text
# Prompt Hillclimb

Runner: codex
Rounds attempted: 3
Repeats: 2
Min gain: 4

## Baseline

Train: 71.3
Val: 68.8

## Round 1

Train: 78.2
Val: 74.1
Gain: +5.3
Decision: KEEP

## Round 2

Train: 83.5
Val: 72.0
Gain: -2.1
Decision: REVERT

## Round 3

Status: INVALID
Reason: grader parse failure
Decision: REVERT

## Best

Train: 78.2
Val: 74.1

## Final

Final: 72.5

Best prompt:
best-prompt.md
```

如果使用了：

```text
--limit
```

报告顶部明显写：

```text
LIMITED SMOKE RUN — NOT A FULL EVALUATION
```

---

# 28. CLI

至少支持：

```bash
python3 hillclimb.py \
  --target examples/tutor-prompt.md \
  --eval examples/tutor-evals.jsonl \
  --runner codex \
  --rounds 3
```

Pi：

```bash
python3 hillclimb.py \
  --target examples/tutor-prompt.md \
  --eval examples/tutor-evals.jsonl \
  --runner pi \
  --rounds 3
```

支持：

```text
--rounds
--repeats
--min-gain
--max-growth
--limit
--dry-run
--measure-noise
```

---

# 29. Dry-run

```bash
--dry-run
```

不得发起模型调用。

检查：

```text
target 文件存在
eval JSONL 可解析
id 唯一
split 合法
train / val / final 均存在
criteria 非空
runner executable 存在
.hillclimb 可写
当前 CLI help 可取得
隔离参数能力
潜在全局 context contamination
预计调用次数
```

如果发现可能污染 eval 的全局配置：

```text
打印 WARNING
```

但不要自动修改。

---

# 30. SKILL.md

项目同时作为 portable Agent Skill。

frontmatter：

```yaml
---
name: prompt-hillclimb
description: Evaluate and iteratively improve a reusable text prompt using train, validation, and final evaluation cases.
---
```

Skill 使用场景：

```text
优化一个长期使用的 prompt
验证 prompt 修改是否真正有效
对 prompt 做 eval / hillclimb
比较 prompt 修改前后行为
```

流程：

```text
1. 确认 target prompt 和 eval JSONL。
2. 如果 eval 不存在，不要凭空生成大量测试并立即宣称优化有效。
3. 先运行 --dry-run。
4. 如果结果敏感，建议先运行 --measure-noise。
5. 运行 hillclimb。
6. 阅读 summary.md。
7. 报告 baseline、best、final 和各轮 KEEP / REVERT。
8. 不自动覆盖原 Prompt。
9. best-prompt.md 单独保存，由用户决定是否采用。
```

Skill 中提醒：

> 如果由 Codex/Pi 调用该 Skill，而脚本内部再次启动 Codex/Pi 子进程，会继续消耗当前账户的模型调用额度。

不要在 Skill 中复制整个 README。

---

# 31. 示例

创建：

```text
examples/tutor-prompt.md
examples/tutor-evals.jsonl
```

`tutor-prompt.md` 初始内容故意保持普通：

```text
You are a helpful math tutor.

Explain problems clearly and help the learner understand the answer.
Be concise and encouraging.
```

示例 eval：

```text
4 train
2 val
2 final
```

覆盖：

- 学生要求直接给答案
- 学生已有正确答案但不理解原因
- 学生犯计算错误
- 学生只需要提示
- 学生提出错误前提
- 学生需要解释推理
- 不同表达方式的相似但非重复场景

train / val / final 不要几乎重复。

README 明确：

> 该示例仅用于演示流程。少量 case 无法可靠区分真实改进与随机波动。

不要武断规定正式使用必须多少条。

建议写：

> 正式使用通常需要更大、更多样的 case 集合，并结合 `--measure-noise` 与 `--repeats` 判断结果稳定性。

---

# 32. 测试

使用标准库：

```text
unittest
```

至少测试：

```text
JSONL parsing
duplicate id rejection
split validation
grader PASS/FAIL parsing
criterion count mismatch
last marker pair extraction
KEEP / REVERT 判断
candidate max-growth 检查
case-id leakage 检查
error 导致 INVALID
调用次数估算
```

不要 mock 整套 Codex/Pi。

不要为了覆盖率写大量测试。

运行：

```bash
python3 -m unittest -q
```

必须通过。

---

# 33. 实际验证

完成代码后依次运行：

```bash
python3 -m unittest -q
```

然后：

```bash
python3 hillclimb.py --help
```

然后：

```bash
python3 hillclimb.py \
  --target examples/tutor-prompt.md \
  --eval examples/tutor-evals.jsonl \
  --runner codex \
  --rounds 1 \
  --dry-run
```

如果当前环境只有 Pi：

```bash
--runner pi
```

如果 CLI 已登录、隔离参数已确认且允许正常调用，可以额外做一次最小真实 smoke run：

```bash
--rounds 1
--limit 1
--repeats 1
```

真实模型调用会消耗订阅或额度。

不要为了验证：

- 自动登录
- 写入凭证
- 移动 auth 文件
- 修改 provider
- 增加 API key

---

# 34. README 必须说明

至少包括：

```text
这是什么
适合什么 Prompt
不适合什么
安装要求
eval JSONL 格式
train / val / final 的区别
Codex 用法
Pi 用法
输出目录
--measure-noise
--repeats
--min-gain
--limit
调用次数为何可能很高
为什么每次 agent 调用必须隔离
当前 Codex/Pi 隔离能力的限制
```

明确说明：

> 当前版本评估的是 text-in / text-out 行为，并不等价于测试真实 system prompt slot、AGENTS.md、Skill triggering 或完整 coding-agent tool behavior。

---

# 35. 已知限制

README 必须明确记录：

## Eval 质量决定上限

Prompt 得分更高不等于现实任务一定更好。

错误或偏置的 eval 会把 Prompt 优化到错误方向。

## Val 仍会被间接优化

虽然 optimizer 看不到 val 内容，但因为每轮 KEEP / REVERT 使用 val 分数：

```text
val 本质上是 selection set
```

多轮 hillclimb 后仍可能逐渐对 val 过拟合。

因此 final 必须保留到最后只运行一次。

## 小样本噪声

2-3 个 val/final case 仅适合 demo。

不能据此声称微小改进具有可靠意义。

## LLM grader 波动

criterion PASS / FAIL 能降低主观 0-100 分的波动，但不能消除 grader noise。

## Target 与 grader 同模型

MVP 默认：

```text
target
grader
optimizer
```

使用同一个 runner。

这可能产生：

```text
self-preference
correlated errors
```

当前接受此限制。

代码中保持：

```python
run_target(...)
run_grader(...)
run_optimizer(...)
```

三个独立函数，为未来支持不同 runner 留边界。

但 V1 不增加：

```text
--target-runner
--grader-runner
--optimizer-runner
```

## Case leakage heuristic 不完美

当前只能检查：

```text
case id
直接字符串片段
```

无法检测 paraphrase 或语义级 benchmark memorization。

## Codex / Pi 全局配置可能污染

若当前 CLI 无法彻底关闭用户级全局 instruction，则 eval 可能仍受其影响。

程序必须警告，但不自动修改用户配置。

---

# 36. 实现边界

以下内容明确不要做：

```text
不要做 Web UI
不要做 npm 包
不要做 pip package
不要做数据库
不要做 plugin marketplace
不要做 concurrency
不要做 async
不要做缓存
不要做哈希
不要做复杂日志框架
不要做 benchmark dashboard
不要做自动安装
不要做模型价格计算
不要做 token 统计
不要做跨 provider API abstraction
不要做复杂异常恢复
不要做 Git worktree
不要做真实 coding repo eval
```

代码应当让一个人可以直接读懂。

---

# 37. 为未来保留的唯一扩展点

代码内部保持：

```python
run_target(...)
run_grader(...)
run_optimizer(...)
```

MVP 三者全部使用：

```text
--runner codex
```

或：

```text
--runner pi
```

未来如果需要：

```text
Codex optimize
Pi execute
Claude judge
```

只替换 runner 层。

现在不要实现跨 agent orchestration。

---

# 38. 完成标准

任务完成时必须已经存在可直接运行的项目，而不是设计稿。

最后汇报：

```text
创建了哪些文件
核心实现是什么
实际检测到的 Codex / Pi CLI 参数是什么
隔离做到了什么程度
有哪些隔离能力当前无法保证
运行了哪些测试
测试结果
是否执行真实 smoke run
如果没有，原因
当前 MVP 已知限制
```

不要继续扩展功能。

如果实现过程中遇到非关键设计选择，选择最简单、可验证的方案继续，不要停下来询问。