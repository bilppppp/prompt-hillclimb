# Prompt Hillclimb 安装与接入指引（面向 AI Agent 与 Coding Harness）

本文档专为受用户委托安装本项目的 **AI Agent**（及协作宿主 Coding Harness）编写。请严格按本指引理解项目本质、核验环境并安全引入。

---

## 1. 项目本质与定位

- **面向通用 AI Agent / Coding Harness**：`prompt-hillclimb` 是用于经验性自动优化通用文本输入/输出 Prompt 的便携式 Skill。方法与评测框架不绑定特定 Agent 平台。
- **纯标准库单文件实现**：核心逻辑由单文件 Python 脚本（`hillclimb.py`）与便携式 Skill 规范（`SKILL.md`）构成。
- **无第三方依赖**：**无需** `pip install`、`npm install`、`pipx` 或创建虚拟环境，不引入任何第三方 Python 库。
- **Runtime Contract 与解耦架构**：Core 完全解耦，仅依赖通用 `--runtime <executable_path>`（规范定义见 [runtime-contract.md](references/runtime-contract.md)）。仓库在 [examples/runtimes/](examples/runtimes/) 目录下提供 `codex-runtime.sh` 与 `pi-runtime.sh` 作为参考 wrapper。

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
3. **Runtime 可执行文件确认**：
   - 若使用参考 wrapper，核验文件存在且具备执行权限：
     ```bash
     ls -l examples/runtimes/codex-runtime.sh
     ls -l examples/runtimes/pi-runtime.sh
     ```
   - 若用户指定其他 Runtime 或本机环境未选定，遵循 [runtime-selection.md](references/runtime-selection.md) 进行安全探测、候选陈述并由用户最终确认。

> [!CAUTION]
> **严格配置守则**：若当前环境缺失可用 Runtime，**严禁**擅自通过脚本下载未知程序、发起自动登录或修改用户全局凭据/配置。Agent 必须直接向用户汇报候选状态与风险，由用户决策。

---

## 3. Clone、目录管理与前置阅读

在用户明确指定的工作目录（或由用户认可的工具存放目录）下克隆本仓库：

```bash
git clone https://github.com/bilppppp/prompt-hillclimb.git
cd prompt-hillclimb
```

> [!WARNING]
> **保护已有目录**：如果目标目录已存在，**严禁**执行 `rm -rf`、`git reset --hard` 或覆盖其中的未知文件。请先检查目录内容并向用户确认。

克隆完成后，Agent 应**首先阅读**项目根目录下的 `README.md`、`SKILL.md` 以及 `references/` 文档，充分理解评测机制、数据防泄漏边界与安全选项。

---

## 4. 零成本验证流程（不发起真实执行调用）

完成克隆与文档阅读后，Agent **仅可**执行以下不调用 Runtime 进行模型推理的静态验证步骤：

### 4.1 运行单元测试
```bash
python3 -m unittest -q
```
*预期结果*：全部内置测试通过。

### 4.2 验证命令行选项
```bash
python3 hillclimb.py --help
```
*预期结果*：输出帮助信息，确认支持 `--runtime PATH` 等选项。

### 4.3 运行安全 Dry-Run（仅验证参数、环境与预算，不发起真实调用）
在用户明确确认 Runtime（详见 [runtime-selection.md](references/runtime-selection.md)）后，使用其路径运行示例：

```bash
# 将 $RUNTIME_PATH 替换为经用户选定确认的 Runtime 可执行程序绝对或相对路径
python3 hillclimb.py --target examples/tutor-prompt.md --eval examples/tutor-evals.jsonl --runtime "$RUNTIME_PATH" --rounds 1 --dry-run
```
*(若用户确认使用参考 wrapper，可传入 `examples/runtimes/codex-runtime.sh` 或 `examples/runtimes/pi-runtime.sh` 作为具体示例，严禁静默默认。)*

---

## 5. 隔离机制与全局环境注意事项

- **执行隔离**：Core 在每次调用 Runtime 时均切换到全新的独立临时目录（`tempfile.TemporaryDirectory`），并通过标准输入输出流交互。
- **不可完全消除的全局污染**：
  - **Codex**：`~/.codex/AGENTS.md` 和全局 skills 仍可能被底层读取。`-s read-only` 仅限制文件写操作，不等于禁用文件读取或模型已知能力。
  - **Pi**：若存在 `~/.pi/agent/SYSTEM.md` 或 `APPEND_SYSTEM.md`，Pi 可能会将其自动拼入系统上下文。
  - 完整隔离边界说明请参阅 [runtime-contract.md](references/runtime-contract.md)。
- **调用预算提示**：Hillclimb 会在多轮评估中多次调用 Runtime，正式运行前请务必使用 `--dry-run` 查看预计的 `runtime invocations` 上限。
- **文件保护**：优化生成的 Prompt 保存于 `.hillclimb/YYYYMMDD-HHMMSS/best-prompt.md`，**默认绝不会覆盖用户的原始 Prompt 文件**。

---

## 6. Skill 接入与调用方式

- **禁止擅自修改全局配置**：**不要**擅自将本项目文件复制到目标 Agent 的全局技能目录，也不要擅自修改用户的 Agent 配置文件。
- **推荐调用方式（Portable Skill）**：
  1. Agent 读取本项目根目录下的 `SKILL.md` 理解能力与规范；
  2. 遵循 [runtime-selection.md](references/runtime-selection.md) 引导用户选定本次使用的 Runtime 可执行文件路径（严禁静默默认某种 Harness）；
  3. 从任意工作目录下运行时，使用 `python3` 调用 `hillclimb.py` 的绝对路径并传入用户确认的 `--runtime "$RUNTIME_PATH"`，例如：
     ```bash
     python3 /path/to/prompt-hillclimb/hillclimb.py --target /path/to/prompt.md --eval /path/to/evals.jsonl --runtime "$RUNTIME_PATH"
     ```
  4. 若用户明确要求将本工具注册为全局 Skill，Agent 应向用户确认目标宿主体系并提供配置指引供用户确认。
