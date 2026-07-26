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

### `midrop send <path> [--device KW] [--mode noui|rpa] [--timeout SEC] [--hold SEC] [--no-click]`

| Flag | Meaning | Default |
|------|---------|---------|
| `path` | 本地文件 | required |
| `--device` | Fold/Pad/0xHEX/decimal | `config.default_device` |
| `--mode` | **`noui`**（默认）Frida 进程内；**`rpa`** 旧 UIA | `config.send_mode` → noui |
| `--timeout` | 等待秒数 | `12`（noui 建议 ≥12） |
| `--hold` | 发送后保持映射 | `hold_seconds` |
| `--no-click` | 仅 rpa：只弹窗 | off |

**noui**：FileMapping + Launch + Frida 在 UI 线程调 `HandleCreateSendTask`（可锁屏）。  
**rpa**：弹窗 + UIA 点设备（锁屏易假成功）。保留作 fallback。

### `midrop devices [--source live|uia] [--timeout SEC]`

| Flag | Meaning | Default |
|------|---------|---------|
| `--source live` | 读 smart_share_log.txt 里最后一条 `current lyra devices` 快照，返回 `name` + `id_hex` + `device_id` + `types` + `snapshot_age_sec` | **live** |
| `--source uia` | 弹窗 UIA，仅中文显示名（旧、会闪窗） | |

`live` 无注入、无弹窗；`snapshot_age_sec` 是这条快照的年龄。Xiaomi PC Manager 每次设备上下线都会写入这条日志，因此通常几秒内到几分钟内是新的。

### `midrop doctor`

检查 Launch、进程、frida、uia、send_mode、配置。  
默认 noui 时 **healthy 需要 frida + 进程 + Launch**（不强制 uia）。

### `midrop config …`

| Key | Meaning | Default |
|-----|---------|---------|
| `default_device` | 默认设备别名 | 空 |
| `launch_path` | Launch.exe | 安装目录下 |
| `hold_seconds` | 保持映射秒数 | 8 |
| `send_mode` | `noui` \| `rpa` | `noui` |
| `device_map` | JSON 别名→id 覆盖 | 空 |

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | 成功 |
| 1 | 文件/参数/缺设备 |
| 2 | 环境（无管家/无 Launch/无 frida） |
| 3 | 超时 / 设备未解析 |
| 4 | 调用/点击失败 |

## JSON send success (noui)

```json
{
  "ok": true,
  "action": "send",
  "mode": "noui",
  "file": "C:\\tmp\\a.txt",
  "device_query": "Pad",
  "device_id": 880786373,
  "device_hex": "0x347FBBC5",
  "device_matched": "Xiaomi Pad 7S Pro",
  "popup_found": true,
  "clicked": false,
  "noui_invoked": true,
  "elapsed_ms": 9000,
  "note": "PC 侧已发起（noui）；若手机需确认接收请在手机上同意"
}
```

`ok: true` 表示 PC 已发起，不是「对端已保存」。

## Legacy RPA

代码保留在 `midrop_cli/core/send_rpa.py`，研究脚本在 `tools/frida_*.py`。  
强制旧路径：`midrop send PATH --mode rpa` 或 `midrop config set send_mode rpa`。
