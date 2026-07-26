# midrop-cli 项目说明（给 Claude 读）

本文件记录 midrop-cli 的架构、边界与约定。**改这个仓库前先读**。

## 项目是什么

小米电脑管家「小米互传（MiDrop）」的命令行封装，面向 Agent。

- **发送**：进程内直调管家的 `HandleCreateSendTask`（Frida，可锁屏，**默认全程无弹窗**）
- **列设备**：读管家自己写的日志 `current lyra devices [...]`（无注入、无弹窗、~40ms）
- **兜底**：保留旧 RPA（弹窗 + UIA 点设备）作为 `--mode rpa`

面向 Windows + Xiaomi PC Manager 5.5.x + Python 3.10+。

## 目录

```
midrop-cli/
  midrop.cmd                       Windows PATH 入口 → python -m midrop_cli
  install.ps1                      加 PATH + 复制 skill
  midrop_cli/
    __main__.py / cli.py           argparse + 子命令分发
    config.py                      %LOCALAPPDATA%\midrop\config.json
    output.py                      统一 json/text 输出（防 GBK 崩）
    core/
      mapping.py                   共享内存 Local\MiDropFileMappingObject
      launch.py                    Launch.exe --contextmenu_dropfile=1
      popup.py                     枚举/关闭互传弹窗（RPA 用）
      uia.py                       UIA 列/点设备（RPA 用）
      devices.py                   别名→device_id 映射（Fold/Pad）
      silent.py                    Frida 挂 UI 线程消息泵，零弹窗（默认发送路径）
      noui.py                      Frida 借菜单窗口进 UI 线程（会闪弹窗，保留可切）
      send_rpa.py                  旧 RPA 发送（保留可切）
      send.py                      按 --mode 分发到 silent / noui / rpa
      live_devices.py              纯读日志的设备列表
      doctor.py                    环境检查（含 frida）
  tools/                           研究/挂钩脚本（frida_*.py），不进 CLI
  skill/                           Claude skill（安装到 ~/.claude/skills/midrop-cli/）
  tests/                           pytest 单测
  docs/research-backend-api.md     逆向笔记（RVA、结构布局、试错记录）
```

## 命令

| 命令 | 说明 |
|------|------|
| `midrop send <path> [--device Fold\|Pad\|0xHEX] [--mode silent\|noui\|rpa] [--timeout SEC] [--hold SEC] [--retry N] [--no-confirm] [--no-click]` | 发送文件（默认 silent） |
| `midrop devices [--source live\|uia] [--timeout SEC]` | 列设备（默认 live=读日志） |
| `midrop doctor` | 检查 Launch.exe、管家进程、Frida、UIA、配置 |
| `midrop config path \| list \| get KEY \| set KEY VALUE` | 配置读写 |

全局 `--format json|text`（Agent 一律 json）。

### Exit code

| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 1 | 文件/参数/缺 default_device |
| 2 | 环境（无管家/无 Launch/无 Frida） |
| 3 | 超时 / 无设备匹配 |
| 4 | 点击/调用失败 |

## 配置键（`%LOCALAPPDATA%\midrop\config.json`）

| Key | 默认 | 说明 |
|-----|------|------|
| `default_device` | 空 | 别名或十六进制 |
| `send_mode` | `silent` | `silent` \| `noui` \| `rpa` |
| `launch_path` | 管家 Launch.exe | |
| `hold_seconds` | 8 | 发送后保持映射秒数 |
| `device_map` | 空 | JSON 对象，别名→id 覆盖默认表 |

## 逆向关键值（版本 5.5.0.18）

**改动小米管家版本很可能要重新标定这些**：

| 名称 | 位置 | 用途 |
|------|------|------|
| `MiSmartShareDLL.dll + 0x1465F0` | `midrop::MiDropBusinessMgr::HandleCreateSendTask(this, u32 device_id, list<wstring> paths, wstring parent_dir)` | 真正发送 |
| `MiSmartShareDLL.dll + 0x148260` | `OpenFromMenuWindow` | Frida onLeave 时进入 UI 线程，能安全调 CreateSend |
| 导出 `?GetMiDropBusiness@midrop@@YAPEAVIMiDropBusiness@1@XZ` | 拿 `this` 单例 |
| `Local\MiDropFileMappingObject` | 共享内存名 | 写 UTF-16LE 绝对路径 |
| Launch 参数 | `--contextmenu_dropfile=1` | 触发菜单流程 |
| 日志 | `C:\ProgramData\MI\AIoT\Log\smart_share_log.txt` | 匹配 `current lyra devices [...]` |

设备 ID（本机实测，别处不同）：Fold=`0xD16E4A0F`、Pad=`0x347FBBC5`。别人机器需要重录。

## 发送三条路径

### silent（默认）— `core/silent.py`

```
Frida attach → hook user32!GetMessageW，按线程号过滤
   ↓（管家 UI 线程的常驻消息泵下一次 tick）
在该线程调 HandleCreateSendTask(this, device_id, [path], "")
   ↓ 立即 detach
读 smart_share_log 确认 OnTaskSucceed
```

**不写共享内存、不调 Launch.exe、不弹任何窗口。**

原理：`OpenFromMenuWindow` 只是碰巧跑在管家 UI 线程上；而那个线程（本机 tid 18956，
拥有「小米互传」主窗口）本身就有常驻消息泵，管家活着就一直在跑。所以不需要为了拿
线程上下文而演一遍菜单流程 —— 直接挂消息泵搭车即可。**弹窗从来不是发送的必要条件。**

UI 线程号**运行时探测**（`pick_ui_thread`：枚举管家窗口，取拥有最多非辅助类窗口的线程），
不要硬编码 —— 每次重启管家都会变。

2026-07-27 实测：Pad 4.3s 送达，日志链 `kWaitReceive → kConnecting → kFileSending →
kDone → OnTaskSucceed` 完整。

### noui（保留）— `core/noui.py`

写共享内存 + `Launch.exe --contextmenu_dropfile=1` → hook `OpenFromMenuWindow` 的
onLeave → 在 UI 线程调 CreateSend。**会闪一下设备弹窗**，且比 silent 慢（多一次
Launch 往返）。silent 若因管家升级挂掉，用它兜底。

### rpa（保留）— `core/send_rpa.py`

弹窗 + UIA 点设备。锁屏易假成功，作最后兜底。

## 手机休眠：与路径无关的失败

手机深度休眠时，第一次连接会以
`OnChannelCreateFailed err_code=15033 "logical conn remote confirm timeout"`
（或 `15006 logical conn timeout`）失败，任务 `error 404`。

**这不是 silent 的问题** —— 2026-07-27 实测同一时刻 noui 路径同样失败。失败那次会把
手机唤醒，所以 silent 默认 `--retry 1` 再打一次。手机睡得深时两次都可能失败，属预期。

排查时务必做对照：`--mode noui` 也失败 = 手机的锅，不是代码回归。

## 成功判据：只认日志

`HandleCreateSendTask` 调用返回**不代表文件送到了**。老的 noui 路径就会在手机没收到时
照样报 `ok: True` / exit 0（已实测）。

silent 路径改为读 `smart_share_log.txt` 找 `OnTaskSucceed task_id N` 才算成功，返回
`confirmed: true` + `task_id`。`--no-confirm` 可跳过等待（只保证已发起）。

## 列设备（`core/live_devices.py`）

**只读日志**，不注入、不弹窗、~40ms。

- 数据源：`smart_share_log.txt` 最后一条 `[smart_share][device_mgr][lyra] current lyra devices [...]`
- 管家在**设备上下线时**自动写这条（可能延迟数秒）
- 返回 `snapshot_age_sec` 给调用方判断新鲜度

试过又删掉的方案（别再走回头路）：

- ❌ Frida 全内存扫 `[HEX]` 字符串：**堆残留导致假在线**  
- ❌ 常驻 daemon 收 `OnLyraDisplayedFeatureAdd/Removed`：能用但要常驻进程  
- ❌ 假发送 + hook `IsDeviceSameAccount` / `GenerateDeviceName`：5.5.0.18 picker 已在 .NET (`PcControlCenter.dll`)，native 路径不再被调  
- ❌ 弹窗强制刷新日志：设备无变化时管家不会重写

## 开发约定

1. **不要**再实现堆扫描或 daemon 版设备列表（前面证明不可靠或过重）。
2. **不要**把 send 默认切回 rpa 或 noui；silent 已实测可靠、更快且零弹窗。
3. **不要**硬编码 UI 线程号；管家重启即变，必须走 `silent.pick_ui_thread` 运行时探测。
4. **不要**把「CreateSend 返回了」当成功；只认日志里的 `OnTaskSucceed`。
5. RVA 若不匹配（管家升级），改 `core/silent.py` 的 `CREATE_SEND_RVA`（noui 还需 `OPEN_MENU_RVA`）；重新逆向方法见 `docs/research-backend-api.md`。
6. 中文输出必经 `output.emit()`；直接 `print()` 中文在 GBK 控制台会崩。
7. 新逻辑先写测试再写实现；`PYTHONPATH=. python -m pytest tests/ -q` 全绿再提。
8. Agent 使用契约在 `skill/`，改 CLI 记得同步。

## Skill 与外部关系

- 用户级 skill：`skill/SKILL.md` + `skill/references/cli-contract.md`
- `install.ps1` 会把 skill 复制到 `%USERPROFILE%\.claude\skills\midrop-cli\`
- 逆向来源脚本存在 `hiker-rules/getav/tools/midrop_*.py`（已废弃，只作参考）

## 常见任务

- **调试发送**：`midrop send FILE --device Fold --format json`；失败看 exit + logs
- **看设备**：`midrop devices --format json`；关注 `snapshot_age_sec`
- **换手机/换机器**：抓一次真实 `HandleCreateSendTask` 日志（`smart_share_log.txt`）拿新 `device_id`，写入 `config.device_map`
- **管家升级挂了**：跑 `midrop doctor`；若 send/noui 报访问违规，八成 RVA 变了，重新逆向

## 已知不做

- 传输进度回调 / 「手机已保存」闭环
- 多文件批量发送
- 无管家进程发送（协议自实现）
- pip 发布
- 常驻服务

## 相关

- GitHub: https://github.com/nightking8342/midrop-cli
- 上游研究笔记: `docs/research-backend-api.md`
