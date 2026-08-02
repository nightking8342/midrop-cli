# midrop-cli 项目说明（给 Claude 读）

本文件记录 midrop-cli 的架构、边界与约定。**改这个仓库前先读**。

## 项目是什么

小米电脑管家「小米互传（MiDrop）」的命令行封装，面向 Agent。

- **发送**：进程内直调管家的 `HandleCreateSendTask`（Frida，可锁屏，**默认全程无弹窗**）
- **列设备**：读管家自己写的日志 `current lyra devices [...]`（无注入、无弹窗、~40ms）
- **兜底**：`--mode menu`（借菜单窗口进 UI 线程，会闪弹窗）

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
      popup.py                     枚举/关闭互传弹窗；pid_of
      uia.py                       UIA 列设备（仅 devices --source uia）
      devices.py                   别名→device_id 映射（Fold/Pad）
      silent.py                    Frida 挂 UI 线程消息泵，零弹窗（默认发送路径）
      menu.py                      Frida 借菜单窗口进 UI 线程（会闪弹窗，兜底）
      send.py                      按 --mode 分发到 silent / menu；含模式名归一
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
| `midrop send <path> [--device Fold\|Pad\|0xHEX] [--mode silent\|menu] [--timeout SEC] [--hold SEC] [--retry N] [--no-confirm]` | 发送文件（默认 silent） |
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
| `send_mode` | `silent` | `silent` \| `menu`（旧值 `noui`→menu，`rpa`→silent） |
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

## 发送两条路径

### silent（默认）— `core/silent.py`

```
Frida attach → hook user32!GetMessageW，按线程号过滤
   ↓ 同时不停给该线程 PostMessage(WM_NULL)（关键，见下）
在该线程调 HandleCreateSendTask(this, device_id, [path], "")
   ↓ 立即 detach
读 smart_share_log 确认 OnTaskSucceed
```

**不写共享内存、不调 Launch.exe、不弹任何窗口。**

原理：`OpenFromMenuWindow` 只是碰巧跑在管家 UI 线程上；直接挂那个线程的消息循环搭车
即可，不必为了拿线程上下文而演一遍菜单流程。**弹窗从来不是发送的必要条件。**

### 必须主动叫醒 UI 线程（2026-08-02 踩过的坑）

管家空闲缩在托盘时，UI 线程**阻塞在 `GetMessageW` 内部**等消息。hook 挂在函数入口，
线程不返回就永远不会再进入 —— 表现为 `confirm_timeout` +
`CreateSend never reached the UI thread pump`，logs 里只有 `ready`。

所以发送期间必须持续 `PostMessageW(hwnd, WM_NULL)` + `PostThreadMessageW(tid, WM_NULL)`
把它叫醒（`poke_thread`，每 150ms 一次）。实测对照：不 poke 15 秒无反应，poke 后
0.2 秒触发。

**这是最初版本的设计缺陷**：当时逆向时「小米互传」窗口开着，UI 线程被动画/定时器
持续驱动，所以「被动等 tick」碰巧能用；管家一旦闲下来就必然超时。别再把 poke 删掉。

UI 线程号**运行时探测**（`pick_ui_thread`：枚举管家窗口，取拥有最多非辅助类窗口的线程），
不要硬编码 —— 每次重启管家都会变（实测 18956 → 7320）。

2026-08-02 实测（管家托盘空闲）：Pad 2.9~3.9s 送达，连续三次成功。

### menu（兜底）— `core/menu.py`

写共享内存 + `Launch.exe --contextmenu_dropfile=1` → hook `OpenFromMenuWindow` 的
onLeave → 在 UI 线程调 CreateSend。**会闪一下设备弹窗**，且比 silent 慢一倍
（实测 9.7s vs 4.6s，多一次 Launch 往返）。silent 若因管家升级挂掉，用它兜底。

**这个模式原名 `noui`**。当时「no UI」指的是「不去点弹窗」，但它照样弹窗；silent
出现后这名字彻底误导，故改名 `menu`（借 menu window 进 UI 线程）。`--mode noui`
仍作废弃别名接受，输出里一律报 `menu`。

### 已删除：rpa

弹窗 + UIA 点设备的老路径（`core/send_rpa.py` + `uia.click_device`）**已删除**。
锁屏下会假成功，silent/menu 两条路都比它可靠。`--mode rpa` 现在直接报参数错误；
配置里残留的 `send_mode: rpa` 会自动落到 silent（`core/send.py: ALIASES`）。

UIA 只剩 `devices --source uia` 在用（`core/uia.py`），跟发送无关。

## 模式名归一

`core/send.py` 的 `resolve_mode` / `normalize_mode` 是唯一的模式名入口，config 和
CLI 都走它。加新模式或再改名时只动 `MODES` / `ALIASES`，别在各处散写字符串比较。

## 手机休眠：与路径无关的失败

手机深度休眠时，第一次连接会以
`OnChannelCreateFailed err_code=15033 "logical conn remote confirm timeout"`
（或 `15006 logical conn timeout`）失败，任务 `error 404`。

**这不是 silent 的问题** —— 2026-07-27 实测同一时刻 menu 路径同样失败。失败那次会把
手机唤醒，所以 silent 默认 `--retry 1` 再打一次。手机睡得深时两次都可能失败，属预期。

排查时务必做对照：`--mode menu` 也失败 = 手机的锅，不是代码回归。

## 成功判据：只认日志

`HandleCreateSendTask` 调用返回**不代表文件送到了**。menu 路径至今如此：手机没收到也
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
2. **不要**把 send 默认切回 menu；silent 已实测可靠、快一倍且零弹窗。
3. **不要**重新引入 RPA/UIA 点击发送（锁屏假成功，已删）。
4. **不要**硬编码 UI 线程号；管家重启即变，必须走 `silent.pick_ui_thread` 运行时探测。
5. **不要**删掉 `silent.poke_thread`；空闲管家的 UI 线程阻塞在 `GetMessageW` 里，不叫醒就必然超时。
6. **不要**把「CreateSend 返回了」当成功；只认日志里的 `OnTaskSucceed`。
7. RVA 若不匹配（管家升级），改 `core/silent.py` 的 `CREATE_SEND_RVA`（menu 还需 `OPEN_MENU_RVA`）；重新逆向方法见 `docs/research-backend-api.md`。
8. 中文输出必经 `output.emit()`；直接 `print()` 中文在 GBK 控制台会崩。
9. 新逻辑先写测试再写实现；`PYTHONPATH=. python -m pytest tests/ -q` 全绿再提。
10. Agent 使用契约在 `skill/`，改 CLI 记得同步。

## Skill 与外部关系

- 用户级 skill：`skill/SKILL.md` + `skill/references/cli-contract.md`
- `install.ps1` 会把 skill 复制到 `%USERPROFILE%\.claude\skills\midrop-cli\`
- 逆向来源脚本存在 `hiker-rules/getav/tools/midrop_*.py`（已废弃，只作参考）

## 常见任务

- **调试发送**：`midrop send FILE --device Fold --format json`；失败看 exit + logs
- **看设备**：`midrop devices --format json`；关注 `snapshot_age_sec`
- **换手机/换机器**：抓一次真实 `HandleCreateSendTask` 日志（`smart_share_log.txt`）拿新 `device_id`，写入 `config.device_map`
- **管家升级挂了**：跑 `midrop doctor`；若 send 报访问违规，八成 RVA 变了，重新逆向

## 已知不做

- 传输进度回调 / 「手机已保存」闭环
- 多文件批量发送
- 无管家进程发送（协议自实现）
- pip 发布
- 常驻服务

## 相关

- GitHub: https://github.com/nightking8342/midrop-cli
- 上游研究笔记: `docs/research-backend-api.md`
