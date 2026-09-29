# Prompt Hillclimb 安装与接入指引（面向 AI Agent）

本文档专为受用户委托安装本项目的 **AI Agent**（及协助人类的调度 Agent）编写。请严格按本指引理解项目本质、核验环境并安全引入。

---

## 1. 项目本质与定位

- **纯标准库实现**：`prompt-hillclimb` 是由单文件 Python 脚本（`hillclimb.py`）与便携式 Skill 规范（`SKILL.md`）构成的工具。
- **无依赖安装**：**无需** `pip install`、`npm install`、`pipx` 或任何虚拟环境包安装，不引入任何第三方 Python 库。
- **复用本机 Runner**：通过子进程调度本机已登录的 `codex` 或 `pi` 命令行工具完成 Prompt 评测与优化。

---

## 2. 环境前置核验（Agent Checklist）

在执行任何操作前，Agent 必须依次检查并确认以下条件：

1. **Python 运行环境**：
   ```bash
   python3 --version
   ```
   要求 **Python 3.10+**（推荐 3.10 ~ 3.14）。
2. **Git 工具**：
   ```bash
   git --version
   ```
3. **Runner CLI（二选一或兼备）**：
   - 检查 `codex`：`which codex && codex --help`
   - 检查 `pi`：`which pi && pi --help`

> [!CAUTION]
> **严格配置守则**：若当前环境缺失可用 Runner 或 Runner 尚未登录，**严禁**擅自通过脚本下载未知程序、发起自动登录或修改用户凭据/配置。Agent 必须直接向用户汇报缺失项并请求指导。

---

## 3. Clone、目录管理与前置阅读

在用户明确指定的工作目录（或由用户认可的工具存放目录）下克隆本仓库：

```bash
git clone https://github.com/bilppppp/prompt-hillclimb.git
cd prompt-hillclimb
```

> [!WARNING]
> **保护已有目录**：如果目标目录已存在，**严禁**执行 `rm -rf`、`git reset --hard` 或覆盖其中的未知文件。请先检查目录内容并向用户确认。

克隆完成后，Agent 应**首先阅读**项目根目录下的 `README.md` 与 `SKILL.md`，充分理解评测机制、数据防泄漏边界与安全选项。

---

## 4. 零成本验证流程（不发起评测模型调用）

完成克隆与文档阅读后，Agent **仅可**执行以下不发起评测模型调用的验证步骤：

### 4.1 运行单元测试
```bash
python3 -m unittest -q
```
*预期结果*：38 项内置测试全部通过（耗时一般 < 0.1s）。

### 4.2 验证命令行选项
```bash
python3 hillclimb.py --help
```

### 4.3 运行安全 Dry-Run（仅验证参数、环境与预算，不发起评测模型调用）
使用本机实际存在的 Runner 运行示例：

```bash
# 若本机配置了 codex:
python3 hillclimb.py --target examples/tutor-prompt.md --eval examples/tutor-evals.jsonl --runner codex --rounds 1 --dry-run

# 若本机配置了 pi:
python3 hillclimb.py --target examples/tutor-prompt.md --eval examples/tutor-evals.jsonl --runner pi --rounds 1 --dry-run
```

---

## 5. 隔离机制与全局环境注意事项

- **执行隔离**：每次模型调用均在独立的干净临时目录（`tempfile.TemporaryDirectory`）中执行，并通过沙箱/无工具参数最小化上下文。
- **不可完全消除的全局污染**：
  - **Codex**：`~/.codex/AGENTS.md` 和全局 skills 仍可能被读取。`-s read-only` 仅限制文件写操作，不等于禁用文件读取或模型已知能力。
  - **Pi**：若存在 `~/.pi/agent/SYSTEM.md` 或 `APPEND_SYSTEM.md`，Pi 可能会将其自动拼入系统上下文。
- **额度授权**：`--dry-run` 不会发起真实模型调用。真正运行 hillclimb 或 `--measure-noise` 会消耗大量模型 Token / API 额度，**必须获得用户明确许可后方可启动**。
- **文件保护**：优化生成的 Prompt 保存于 `.hillclimb/YYYYMMDD-HHMMSS/best-prompt.md`，**默认绝不会覆盖用户的原始 Prompt 文件**。

---

## 6. Skill 接入与调用方式

- **禁止擅自修改全局配置**：**不要**擅自将本项目文件复制到目标 Agent 的全局技能目录，也不要擅自修改用户的 Agent 配置文件。
- **推荐调用方式（Portable Skill）**：
  1. Agent 读取本项目根目录下的 `SKILL.md` 理解能力与规范；
  2. 从任意工作目录下运行时，使用 `python3` 调用 `hillclimb.py` 的绝对路径，例如：
     ```bash
     python3 /path/to/prompt-hillclimb/hillclimb.py --target /path/to/prompt.md --eval /path/to/evals.jsonl --runner codex
     ```
     *注：若使用 Pi Runner，将 `--runner codex` 替换为 `--runner pi` 即可，避免使用 `<codex|pi>` 导致 shell 管道符号歧义。*
  3. 若用户明确要求将本工具注册为全局 Skill，Agent 应向用户确认目标 Agent 体系（Codex、Pi、Claude Desktop 等），并提供对应配置指引由用户确认。
