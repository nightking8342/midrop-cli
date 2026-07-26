# MiDrop 后台 API 逆向笔记（2026-07-26）

## 结论摘要

| 问题 | 结论 |
|------|------|
| 内部是否存在「指定设备 + 文件列表 → 发送」API？ | **是** |
| 是否有进程外稳定入口（管道/HTTP/COM）？ | **未发现** |
| 当前 midrop CLI 能否改为无 UI 后台？ | **不能直接改**；需进程内调用 |
| 关屏/锁屏能否靠互传后台解决？ | **不能**（API 也在用户态管家进程里，锁屏仍无交互桌面） |

## 已证实的调用链

```
外部: FileMapping + Launch --contextmenu_dropfile=1
  → HandleMiDropFileMapping(path)
  → OpenFromMenuWindow()          // 弹 UI
  → (用户点设备)
  → HandleCreateSendTask(device_id, list<path>, ..., TaskFromType)
  → CreateTask(BleDeviceInfo, FileInfoData...)
  → MiDropByLyraBusinessMgr::SendFile / 信道传输
  → OnTaskSucceed
```

### HandleCreateSendTask（核心）

签名（demangle + 日志印证）：

```text
void midrop::MiDropBusinessMgr::HandleCreateSendTask(
    unsigned int device_id,
    std::list<std::wstring> paths,   // 文件路径列表
    ...                              // 可能还有 parent_dir / TaskFromType
)
```

运行日志格式（`smart_share_log.txt`）：

```text
[midrop] HandleCreateSendTask device_id <uint>, selected_parent_dir <path|empty>, size <n>, TaskFromType <n>
```

实测：

- 右键/菜单发送：`TaskFromType = 4`
- `size` = 文件个数
- `selected_parent_dir` 右键多文件时可能是父目录；CLI 触发时常为空

## 设备 ID 映射（本机实测）

| 设备 | Lyra 字符串 ID | `device_id` (uint) | 十六进制 |
|------|----------------|---------------------|----------|
| 我的 Xiaomi MIX Fold 3 | `D16E4A0F` | `3513666063` | `0xD16E4A0F` |
| 我的 Xiaomi Pad 7S Pro 12.5 | `347FBBC5` | `880786373` | `0x347FBBC5` |

关系：**`device_id == int(lyra_hex, 16)`**（同值不同进制）。

另有映射：

```text
OperateMidropIdToLyraId(lyraId, midropId)
```

日志示例：`lyraId=880786373 midropId=11833` —— 存在另一套 midrop 内部短 ID，但 **CreateSend 日志里用的是 Lyra uint 形式**。

设备在线列表来自 Lyra / BLE，写在进程内；磁盘上无稳定的「midrop 设备 JSON」可直接读作发送目标表。

## 导出入口

`MiSmartShareDLL.dll`：

- `GetMiDropBusiness@midrop` → `IMiDropBusiness*`
- `SetMiDropUI@midrop` → 注入 UI 回调

**必须在已初始化的 `XiaomiPcManager.exe` 地址空间内调用。**  
独立进程 `LoadLibrary` 拿不到已有设备会话。

## 未发现的东西

- 命名管道：`\\.\pipe\*midrop*` 类稳定入口未找到  
- `127.0.0.1:10001`：对本机 HTTP 探测不可用（非公开 REST）  
- `MiDropTransfer.dll` 的 `/api/1.0/file*`：传输会话内协议，非本机「发文件」API  
- 官方 CLI / 文档化 COM 发送接口  

`DistFile` / `GetDistFileBusiness` 是另一条「互联文件」业务（P2P toast 等），不是右键 MiDrop 主路径。

## 若要做真后台：必经路径

1. **枚举设备 ID**  
   - 解析 `smart_share_log` / 设备管理器日志中的 `OnDeviceChanged id=XXXXXXXX`  
   - 或注入后读进程内设备 map（更难）  
2. **注入 `XiaomiPcManager`（或调试附加）**  
3. **`GetMiDropBusiness()` → 调到 `HandleCreateSendTask(device_id, {paths})`**  
4. 确认线程模型（UI 线程？）与「设备须已在 local 列表」  
   - 失败日志：`HandleCreateSendTask can't find device info in local`  

### 风险

- 升级改符号/vtable 即挂  
- 注入可能被安全软件拦截  
- 仍依赖管家进程存活、Lyra/BLE/账号信任  
- **不解决锁屏**；灭屏也不等于「服务化后台」  

## 与产品 midrop CLI 的关系

| 模式 | 状态 |
|------|------|
| RPA：FileMapping + Launch + UIA | **已产品化** `midrop send` |
| 进程内 `HandleCreateSendTask` | **研究级**，未实现 |
| 无窗复刻 Lyra 协议 | 不现实（短期） |

建议产品路线：

1. 保持 RPA，补唤醒屏幕 + 锁屏检测  
2. Agent 关屏：ADB / Telegram 兜底  
3. 后台互传单独研究项：Frida 挂钩 `HandleCreateSendTask` 验证参数后，再评估注入 PoC  

## 验证用日志位置

- `C:\ProgramData\MI\AIoT\Log\smart_share_log.txt`  
- 关键字：`HandleCreateSendTask`、`OnTaskSucceed`、`device_id`  

## 参考二进制

- `C:\Program Files\MI\XiaomiPCManager\5.5.0.18\MiSmartShareDLL.dll`  
- Shell：`MiDropShellExt.dll` / `Launch.exe`  
- 传输：`MiDropTransfer.dll`、`midrop` Lyra 相关符号  
