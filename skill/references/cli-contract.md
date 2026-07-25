# midrop CLI Contract

Agent 调用请始终加 `--format json`。

## Entry

| Item | Value |
|------|-------|
| Command | `midrop` |
| Resolver | `midrop.cmd` → `python -m midrop_cli` |
| Global | `--format json\|text`（默认：非 TTY→json，TTY→text） |
| Config file | `%LOCALAPPDATA%\midrop\config.json` |

## Commands

### `midrop send <path> [--device KW] [--timeout SEC] [--hold SEC] [--no-click]`

写共享内存 → Launch.exe 弹窗 →（默认）UIA 点选设备。

| Flag | Meaning | Default |
|------|---------|---------|
| `path` | 本地文件绝对路径 | required |
| `--device` | 设备名子串 | `config.default_device`；都无则 exit 1 |
| `--timeout` | 等弹窗/设备秒数 | `12` |
| `--hold` | 点击后保持映射秒数 | `config.hold_seconds`（8） |
| `--no-click` | 只弹窗不点 | off |

### `midrop devices [--timeout SEC]`

临时文件触发弹窗 → UIA 枚举设备名 → 尽量关窗（不发送）。

### `midrop doctor`

检查 Launch.exe、XiaomiPcManager 进程、配置、UIA 程序集。

### `midrop config path | list | get KEY | set KEY VALUE`

| Key | Meaning | Default |
|-----|---------|---------|
| `default_device` | 默认设备子串 | 空 |
| `launch_path` | Launch.exe 路径 | `C:\Program Files\MI\XiaomiPCManager\Launch.exe` |
| `hold_seconds` | 点击后保持映射 | `8` |

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | 成功 |
| 1 | 通用失败（文件/参数/缺默认设备） |
| 2 | 环境不可用（无管家 / 无 Launch） |
| 3 | 超时：无弹窗或设备未匹配 |
| 4 | 找到目标但点击失败 |

## JSON shapes

### send success

```json
{
  "ok": true,
  "action": "send",
  "file": "D:\\photo.jpg",
  "device_matched": "我的Xiaomi MIX Fold 3",
  "device_query": "Fold",
  "popup_found": true,
  "clicked": true,
  "elapsed_ms": 4200,
  "note": "PC 侧已发起；若手机需确认接收请在手机上同意"
}
```

`clicked: true` 只表示 **PC 已发起**，不是「手机已保存」。

### failure (any action)

```json
{
  "ok": false,
  "action": "send",
  "error": "device_not_found",
  "message": "未匹配到设备关键字 'Phone'",
  "candidates": ["我的Xiaomi MIX Fold 3", "我的Xiaomi Pad 7S Pro 12.5"]
}
```

### devices success

```json
{
  "ok": true,
  "action": "devices",
  "devices": [
    {"name": "我的Xiaomi MIX Fold 3"},
    {"name": "我的Xiaomi Pad 7S Pro 12.5"}
  ]
}
```

### doctor

```json
{
  "ok": true,
  "action": "doctor",
  "healthy": true,
  "checks": { "...": "..." }
}
```

`healthy: false` 或 exit 2 → 环境问题，先让用户开小米电脑管家。

## error 枚举

| error | exit | 场景 |
|-------|------|------|
| `file_not_found` | 1 | 文件不存在 |
| `device_required` | 1 | 无 default 且无 `--device` |
| `environment` | 2 | 无 Launch / 无进程 |
| `popup_timeout` | 3 | 弹窗超时 |
| `device_not_found` | 3 | 关键字无匹配（附 `candidates`） |
| `click_failed` | 4 | 点击脚本失败 |
| `config_error` | 1 | 配置键/值非法 |

## Agent quick rules

1. 环境不明 → `midrop doctor --format json`
2. 无路径 → 问用户，禁止猜测
3. 手机/Fold/MIX → `--device Fold`；平板/Pad → `--device Pad`；未指定 → 不传 `--device`
4. 关键字不定 → `midrop devices --format json` 后再 send
5. 成功话术：PC 已发起；若手机需确认请用户点接收。禁止说「已保存到手机」
