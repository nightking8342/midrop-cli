# midrop CLI

把本机文件通过小米互传（MiDrop）发到小米手机/平板。

- **默认 `noui`**：Frida 进程内 `HandleCreateSendTask`（可锁屏，不点 UI）
- **备选 `rpa`**：弹窗 + UIA（旧方式，代码保留）

## 安装

```powershell
cd D:\claudebot\tools\midrop-cli
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
pip install frida frida-tools   # noui 需要
```

```text
midrop doctor --format json
midrop config set default_device Fold
```

## 命令

| 命令 | 说明 |
|------|------|
| `midrop send <path> [--device KW] [--mode noui\|rpa]` | 发送（默认 noui） |
| `midrop devices [--source live\|uia]` | **默认 live**：实时 id_hex + device_id；`uia` 仅弹窗名 |
| `midrop doctor` | 环境检查（含 frida） |
| `midrop config …` | 配置 |

### 示例

```bash
# 默认 noui → 手机
midrop send "D:\tmp\a.txt" --device Fold --format json

# 平板
midrop send "D:\tmp\a.txt" --device Pad --format json

# 强制旧 RPA
midrop send "D:\tmp\a.txt" --device Fold --mode rpa --format json

# 默认模式
midrop config set send_mode noui
midrop config set send_mode rpa
```

### 配置键

| Key | 默认 | 含义 |
|-----|------|------|
| `default_device` | 空 | Fold / Pad 等 |
| `send_mode` | `noui` | noui \| rpa |
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
| **noui（默认）** | `core/noui.py` | Frida + CreateSend |
| **rpa（保留）** | `core/send_rpa.py` | 原 UIA 实现 |
| 调度 | `core/send.py` | 按 mode 分发 |

研究脚本（不删）：`tools/frida_noui_send.py` 等。  
逆向笔记：`docs/research-backend-api.md`。

## 限制

- noui 绑定当前管家 DLL 的 RVA；**升级管家后可能需重新标定**
- 需要本机 `frida` 与运行中的 `XiaomiPcManager`
- `ok: true` 只表示 PC 已发起，不是对端已保存

## 开发

```bash
cd D:\claudebot\tools\midrop-cli
PYTHONPATH=. python -m pytest tests/ -q
```
