# midrop CLI

把本机文件通过小米互传（MiDrop / 小米电脑管家）发到小米手机或平板。

面向 Agent：JSON 契约 + 用户级 Claude skill；人类也可在终端直接调用。

## 安装

要求：Windows + Python 3 + 已安装小米电脑管家。

```powershell
cd D:\claudebot\tools\midrop-cli
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

`install.ps1` 会：

1. 检查 `python` 在 PATH 中
2. 将本仓库根目录加入**用户** PATH（含 `midrop.cmd`）
3. 复制 skill 到 `%USERPROFILE%\.claude\skills\midrop-cli\`

新开终端后验证：

```text
midrop doctor --format json
midrop config set default_device Fold
```

若当前会话 PATH 未刷新：

```powershell
$env:Path = "D:\claudebot\tools\midrop-cli;" + $env:Path
```

## 命令

| 命令 | 说明 |
|------|------|
| `midrop send <path> [--device KW] [--timeout SEC] [--hold SEC] [--no-click]` | 发送文件；默认 UIA 点选设备 |
| `midrop devices [--timeout SEC]` | 枚举弹窗中的设备名（尽量不发送） |
| `midrop doctor` | 检查 Launch.exe、管家进程、配置、UIA |
| `midrop config path \| list \| get KEY \| set KEY VALUE` | 读写配置 |

全局：`--format json|text`（Agent 请始终用 `--format json`）。

配置文件：`%LOCALAPPDATA%\midrop\config.json`

| Key | 含义 | 默认 |
|-----|------|------|
| `default_device` | 默认设备名子串 | 空 |
| `launch_path` | Launch.exe 路径 | `C:\Program Files\MI\XiaomiPCManager\Launch.exe` |
| `hold_seconds` | 点击后保持共享内存秒数 | `8` |

### Exit code

| Code | 含义 |
|------|------|
| 0 | 成功 |
| 1 | 文件/参数/缺默认设备 |
| 2 | 环境不可用 |
| 3 | 弹窗或设备超时/未匹配 |
| 4 | 点击失败 |

## 示例

```bash
# 环境检查
midrop doctor --format json

# 设默认设备（手机/Fold 常用关键字）
midrop config set default_device Fold

# 发送（用默认设备）
midrop send "D:\tmp\photo.jpg" --format json

# 指定平板
midrop send "D:\tmp\photo.jpg" --device Pad --format json

# 只弹窗，不自动点击
midrop send "D:\tmp\photo.jpg" --device Fold --no-click --format json

# 列设备
midrop devices --format json
```

成功时 JSON 中 `clicked: true` 表示 **PC 已发起发送**。若手机端需要确认接收，请在手机上点同意。不要解读为「文件已保存到手机」。

## Claude skill

安装后 skill 路径：

```text
%USERPROFILE%\.claude\skills\midrop-cli\
  SKILL.md
  references\cli-contract.md
```

触发示例：发到我手机、互传、MiDrop、传到 Fold/Pad、发到平板。

Agent 应只调用 PATH 上的 `midrop`，禁止手写 `CreateFileMapping` / UIA 脚本。完整契约见 skill 内 `references/cli-contract.md`。

## 限制

- 仅 Windows + 小米电脑管家（MiDrop 右键互传链路）
- MVP：单文件；无传输进度；无「手机已保存」闭环
- UI 改版可能导致 UIA 树变化 → 用 `doctor` / `devices` 排查
- 不依赖 pywinauto 等第三方 GUI 库（ctypes + PowerShell .NET UIA）

## 与验证脚本的关系

早期验证脚本在 `hiker-rules/getav/tools/midrop_*.py`（半自动 / 全自动）。本仓库为产品化 CLI，请优先使用 `midrop`；旧脚本应视为废弃，避免双轨。

## 开发

```bash
cd D:\claudebot\tools\midrop-cli
python -m pytest -q
# 或直接：
python -m midrop_cli doctor --format json
```

布局：

```text
midrop-cli/
  midrop.cmd
  install.ps1
  midrop_cli/          # Python 包
  skill/               # Claude skill 源
  tests/
  README.md
```
