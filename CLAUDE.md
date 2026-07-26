# midrop-cli 项目说明（给 Claude 读）

本文件记录 midrop-cli 的架构、边界与约定。**改这个仓库前先读**。

## 项目是什么

小米电脑管家「小米互传（MiDrop）」的命令行封装，面向 Agent。

- **发送**：进程内直调管家的 `HandleCreateSendTask`（Frida，可锁屏，不点 UI）
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
      noui.py                      Frida 进程内 CreateSend（默认发送路径）
      send_rpa.py                  旧 RPA 发送（保留可切）
      send.py                      按 --mode 分发到 noui / rpa
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
| `midrop send <path> [--device Fold\|Pad\|0xHEX] [--mode noui\|rpa] [--timeout SEC] [--hold SEC] [--no-click]` | 发送文件（默认 noui） |
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
| `send_mode` | `noui` | `noui` \| `rpa` |
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

### noui（默认）— `core/noui.py`

```
写共享内存(路径) + Launch.exe --contextmenu_dropfile=1
   ↓（弹菜单前）
Frida attach → hook OpenFromMenuWindow 的 onLeave
   ↓（进入 UI 线程）
在同一线程调 HandleCreateSendTask(this, device_id, [path], "")
   ↓
不点弹窗；管家自己走 Lyra 通道发文件
```

优点：可锁屏、不点 UI、快。  
限制：需 Frida、管家进程；RVA 版本绑定。

### rpa（保留）— `core/send_rpa.py`

弹窗 + UIA 点设备。锁屏易假成功，作 fallback。

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
2. **不要**把 send 默认切回 rpa；noui 已实测可靠且锁屏可用。
3. RVA 若不匹配（管家升级），改 `core/noui.py` 顶部的 `CREATE_SEND_RVA` / `OPEN_MENU_RVA`；重新逆向方法见 `docs/research-backend-api.md`。
4. 中文输出必经 `output.emit()`；直接 `print()` 中文在 GBK 控制台会崩。
5. 新逻辑先写测试再写实现；`PYTHONPATH=. python -m pytest tests/ -q` 全绿再提。
6. Agent 使用契约在 `skill/`，改 CLI 记得同步。

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
