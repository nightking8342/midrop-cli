# midrop CLI

把本机文件通过小米互传（MiDrop）发到小米手机/平板。

- **默认 `silent`**：Frida 挂管家 UI 线程消息泵调 `HandleCreateSendTask`。
  **全程零弹窗**、可锁屏，并读管家日志确认真送达
- **兜底 `menu`**：借菜单窗口进 UI 线程（会闪弹窗，慢一倍）。旧名 `noui`

## 安装

```powershell
cd D:\claudebot\tools\midrop-cli
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
pip install frida frida-tools   # 两种模式都需要
```

```text
midrop doctor --format json
midrop config set default_device Fold
```

## 命令

| 命令 | 说明 |
|------|------|
| `midrop send <path> [--device KW] [--mode silent\|menu] [--retry N] [--no-confirm]` | 发送（默认 silent） |
| `midrop devices [--source live\|uia]` | **默认 live**：读管家日志最后一条 `current lyra devices`，返回 id_hex + device_id + types + snapshot_age_sec（无弹窗）；`uia` 走弹窗仅名字 |
| `midrop doctor` | 环境检查（含 frida） |
| `midrop config …` | 配置 |

### 示例

```bash
# 默认 silent（零弹窗）→ 手机
midrop send "D:\tmp\a.txt" --device Fold --format json

# 平板
midrop send "D:\tmp\a.txt" --device Pad --format json

# silent 挂了才用兜底（会闪弹窗）
midrop send "D:\tmp\a.txt" --device Fold --mode menu --format json

# 默认模式
midrop config set send_mode silent
midrop config set send_mode menu
```

### 配置键

| Key | 默认 | 含义 |
|-----|------|------|
| `default_device` | 空 | Fold / Pad 等 |
| `send_mode` | `silent` | silent \| menu |
| `launch_path` | 管家 Launch.exe | |
| `hold_seconds` | 8 | 发送后保持映射 |
| `device_map` | 空 | JSON 覆盖别名→id |

### 设备 ID（本机实测，可 config 覆盖）

| 别名 | id |
|------|-----|
| Fold / phone / mix | `0xD16E4A0F` |
| Pad / tablet | `0x347FBBC5` |

## 架构

| 路径 | 模块 | 说明 |
|------|------|------|
| **silent（默认）** | `core/silent.py` | 挂 UI 线程消息泵 + CreateSend；读日志确认 |
| **menu（兜底）** | `core/menu.py` | FileMapping + Launch + hook OpenFromMenuWindow |
| 调度 | `core/send.py` | 按 mode 分发；模式名归一 |

旧的 `rpa`（UIA 点设备）已删除 —— 锁屏下会假成功。  
研究脚本（不删）：`tools/frida_noui_send.py` 等。  
逆向笔记：`docs/research-backend-api.md`。

## 限制

- 绑定当前管家 DLL 的 RVA；**升级管家后可能需重新标定**
- 需要本机 `frida` 与运行中的 `XiaomiPcManager`
- silent：`confirmed: true` + `task_id` 才是真送达（日志里有 `OnTaskSucceed`）
- menu：`ok: true` 只表示 PC 已发起，不是对端已保存
- 设备深度休眠时首次连接必超时，与模式无关；silent 默认自动重试一次

## 开发

```bash
cd D:\claudebot\tools\midrop-cli
PYTHONPATH=. python -m pytest tests/ -q
```
