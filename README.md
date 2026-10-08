# Prompt Hillclimb

用评测用例反复改进可复用的 Prompt。可作为 Skill 使用，通过统一 Runtime Contract 接入不同 AI Agent / Coding Harness。

---

## 给 AI Agent 安装

可以直接把这句话发给你的 AI Agent：

```text
帮我安装 prompt-hillclimb：https://raw.githubusercontent.com/bilppppp/prompt-hillclimb/main/install.md
```

完整安装指南详见 [install.md](install.md)，Skill 规范详见 [SKILL.md](SKILL.md)。

---

## 准备工作

运行优化前需要准备：

1. **Python 运行时**：Python 3.10+（纯标准库，无第三方依赖）。
2. **待优化 Prompt**：初始 Markdown 或文本文件（如 [examples/tutor-prompt.md](examples/tutor-prompt.md)）。
3. **评测数据集**：JSONL 格式文件（如 [examples/tutor-evals.jsonl](examples/tutor-evals.jsonl)），每行包含 `id`、`split`（`train`、`val`、`final` 各至少 1 条）、`input`、`criteria` 4 个字段。

---

## Runtime 确认

`--runtime` 参数指向符合 [Runtime Contract](references/runtime-contract.md) 的可执行程序。**Runtime 必须经由用户显式选定与确认**；若用户未指定，Agent 必须先进行环境探测、呈现候选方案与已知风险并等待用户选择，严禁擅自默认 Codex、Pi 或当前宿主环境（详见 [Runtime 选择引导](references/runtime-selection.md)）。仓库在 [examples/runtimes/codex-runtime.sh](examples/runtimes/codex-runtime.sh) 与 [examples/runtimes/pi-runtime.sh](examples/runtimes/pi-runtime.sh) 提供了参考包装脚本。

---

## 快速上手

```bash
# 1. 设定经用户确认的 Runtime 路径（通用占位，严禁静默默认某 Harness）
RUNTIME_PATH="/absolute/path/to/your-confirmed-runtime"

# 2. Dry-Run 预检（零成本验证参数、用例格式与调用预算）
python3 hillclimb.py \
  --target examples/tutor-prompt.md \
  --eval examples/tutor-evals.jsonl \
  --runtime "$RUNTIME_PATH" \
  --rounds 1 \
  --dry-run

# 3. 启动优化运行（更多参数参见 python3 hillclimb.py --help）
python3 hillclimb.py \
  --target examples/tutor-prompt.md \
  --eval examples/tutor-evals.jsonl \
  --runtime "$RUNTIME_PATH" \
  --rounds 3 \
  --min-gain 3.0
```

---

## 运行结果

运行输出保存于 `.hillclimb/YYYYMMDD-HHMMSS/` 目录，核心产物包括完整评测报告 `summary.md` 与优选提示词 `best-prompt.md`。全流程结束会对 Original 与 Best 进行独立 Final 盲测比对并输出真实 Delta 分差，优化过程默认绝不覆盖原始 Prompt 文件。算法流程、早停规则与停滞诊断详见 [SKILL.md](SKILL.md)。

---

## 边界声明

本项目专注于纯文本输入/输出的 Prompt 评测，并非测试原生 AGENTS.md 注入或复杂工具链行为；执行隔离程度与优化质量根本上取决于所选 Runtime 的实际隔离能力与评测集设计质量。

---

## 实验扩展（Astra 行为评测冒烟）

基于执行隔离契约，[experiment/](experiment/README.md) 包含针对 `gpt-6-astra` 的单次 T02/P0 行为冒烟流水线与执行评估中间件（尚未接入 Hillclimb 优化循环，非统计结论）。详细设计与单次归档记录参见 [experiment/README.md](experiment/README.md)。
