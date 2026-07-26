# midrop CLI Contract

Agent 调用请始终加 `--format json`。

## Entry

| Item | Value |
|------|-------|
| Command | `midrop` |
| Resolver | `midrop.cmd` → `python -m midrop_cli` |
| Global | `--format json\|text` |
| Config | `%LOCALAPPDATA%\midrop\config.json` |

## Commands

### `midrop send <path> [--device KW] [--mode silent|menu] [--timeout SEC] [--hold SEC] [--retry N] [--no-confirm]`

| Flag | Meaning | Default |
|------|---------|---------|
| `path` | 本地文件 | required |
| `--device` | Fold/Pad/0xHEX/decimal | `config.default_device` |
| `--mode` | **`silent`**（默认）零弹窗；**`menu`** 闪弹窗兜底 | `config.send_mode` → silent |
| `--timeout` | 等待秒数 | `12` |
| `--hold` | 发送后保持映射（仅 menu） | `hold_seconds` |
| `--retry` | 仅 silent：设备休眠时的额外重试次数 | `1` |
| `--no-confirm` | 仅 silent：不等日志确认，调用成功即返回 | off |

**silent**：Frida 挂 `user32!GetMessageW`，在管家 UI 线程的常驻消息泵里调
`HandleCreateSendTask`。不写共享内存、不调 Launch.exe、**不弹任何窗口**，
并读日志确认 `OnTaskSucceed`。可锁屏。  
**menu**：FileMapping + Launch + hook `OpenFromMenuWindow`（**会闪弹窗**，慢一倍）。
silent 挂了才用。旧名 `noui` 仍作别名接受，但输出一律报 `menu`。

> `rpa`（弹窗 + UIA 点设备）**已删除**。`--mode rpa` 会被 argparse 拒绝；
> 配置里残留的 `send_mode: rpa` 自动落到 silent。

### `midrop devices [--source live|uia] [--timeout SEC]`

| Flag | Meaning | Default |
|------|---------|---------|
| `--source live` | 读 smart_share_log.txt 里最后一条 `current lyra devices`，返回 `name` + `id_hex` + `device_id` + `types` + `snapshot_age_sec` | **live** |
| `--source uia` | 弹窗 UIA，仅中文显示名（旧、会闪窗） | |

`live` 无注入、无弹窗、~40ms。管家在设备上下线时会自动写这条日志（可能延迟几秒），因此读到的即为当前在线状态；`snapshot_age_sec` 表示日志年龄，可作参考。

### `midrop doctor`

检查 Launch、进程、frida、uia、send_mode、配置。  
默认 silent 时 **healthy 需要 frida + 管家进程**（Launch.exe 仅 menu 需要，
silent 下缺失只报 warn）。uia 检查任何模式都不影响 healthy。

### `midrop config …`

| Key | Meaning | Default |
|-----|---------|---------|
| `default_device` | 默认设备别名 | 空 |
| `launch_path` | Launch.exe | 安装目录下 |
| `hold_seconds` | 保持映射秒数 | 8 |
| `send_mode` | `silent` \| `menu` | `silent` |
| `device_map` | JSON 别名→id 覆盖 | 空 |

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | 成功 |
| 1 | 文件/参数/缺设备 |
| 2 | 环境（无管家/无 Launch/无 frida） |
| 3 | 超时 / 设备未解析 |
| 4 | 调用/点击失败 |

## JSON send success (silent) — 实测样本

```json
{
  "ok": true,
  "action": "send",
  "mode": "silent",
  "file": "C:\\tmp\\a.txt",
  "device_query": "Pad",
  "device_id": 880786373,
  "device_hex": "0x347FBBC5",
  "device_matched": "Xiaomi Pad 7S Pro",
  "ui_tid": 18956,
  "popup_found": false,
  "clicked": false,
  "silent_invoked": true,
  "attempts": 1,
  "confirmed": true,
  "task_id": 36619,
  "elapsed_ms": 4263,
  "note": "手机已确认接收（OnTaskSucceed）"
}
```

`confirmed: true` + `task_id` = 管家日志里出现了 `OnTaskSucceed`，**这才是真送达**。

## JSON send failure (silent, 设备休眠) — 实测样本

```json
{
  "ok": false,
  "mode": "silent",
  "error": "send_failed",
  "message": "OnTaskFail task_id 14447, error 404; err_code=15006 logical conn timeout",
  "attempts": 2,
  "task_id": 14447,
  "exit_code": 4
}
```

设备深度休眠时第一次连接必超时（`15033 remote confirm timeout` 或 `15006 conn
timeout`），**与发送路径无关** —— 同一时刻 `--mode menu` 一样失败。失败那次会唤醒
设备，故默认 `--retry 1`。两次都失败就让用户点亮屏幕，别连环重试。

## menu 的 ok 语义不同

`mode=menu` 的 `ok: true` **只表示 PC 侧调用成功**，不读日志确认，手机没收到也会报
成功（已实测）。这个模式下只能说「已发起」，不能说「已送达」。

## Fallback

代码在 `midrop_cli/core/menu.py`，研究脚本在 `tools/frida_*.py`。  
切兜底：`midrop send PATH --mode menu` 或 `midrop config set send_mode menu`。
