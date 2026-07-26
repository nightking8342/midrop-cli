---
name: midrop-cli
description: 把电脑上的文件通过小米互传（MiDrop）发到小米手机或平板。用户说「发到我手机」「互传」「传到 Fold/Pad」「发到平板」「MiDrop」时使用。通过 midrop CLI 执行，禁止手写共享内存、UIA 或 Frida 脚本。
---

# midrop CLI

用 PATH 上的 `midrop` 命令把文件发到小米设备。执行层是 CLI；本 skill 只负责路由与结果解读。

## 发送模式

- **默认 `silent`**：Frida 挂 UI 线程消息泵调 `HandleCreateSendTask`。
  **全程零弹窗**、可锁屏，并读管家日志确认 `OnTaskSucceed`
- **备选 `noui`**：借菜单窗口进 UI 线程（会闪一下设备弹窗）；silent 挂了才用
- **兜底 `rpa`**：弹窗 + UIA 点设备（旧方式；锁屏易假成功）

## 列设备

`midrop devices` 默认读 `smart_share_log.txt` 最后一条 `current lyra devices` 快照。
无注入、无弹窗、~40ms 返回。管家在设备上下线时会自动写这条日志（可能延迟几秒）。

```bash
midrop send "PATH" --device Fold --format json           # 默认 silent，零弹窗
midrop send "PATH" --device Pad --mode noui --format json # silent 挂了才退到 noui
midrop config set send_mode silent|noui|rpa
```

## 何时使用

- 用户要求把本机文件发到手机/平板
- 提及：小米互传、MiDrop、互传、发到 Fold/MIX/Pad

## 何时不用

- 非小米互传渠道（Telegram 传文件、adb push 等）
- 用户未给出且对话中没有明确文件路径时——先问路径，禁止猜测

## 工作流

1. 环境不确定 → `midrop doctor --format json`
   - `healthy: false` 或 exit 2 → 摘要 checks（管家进程、frida、Launch）
   - silent / noui 都需要 **frida** 检查为 ok
2. 确认本地文件绝对路径存在
3. 设备参数：
   - 手机 / Fold / MIX → `--device Fold`
   - 平板 / Pad → `--device Pad`
   - 未指定 → 省略 `--device`（用 `default_device`）
4. 发送：`midrop send "ABS_PATH" [--device KW] --format json`
5. 解读（先看 `mode`，判据不同）：
   - `mode=silent` + `confirmed: true` + 有 `task_id`
     → **管家日志已确认设备接收**（`OnTaskSucceed`），可以说「已送达」
   - `mode=silent` + `ok: false`：
     - `error: send_failed` 且 message 含 `15033` / `15006` timeout
       → **设备休眠没确认连接**。已自动重试过（看 `attempts`）。
       让用户点亮手机屏幕后重发，不要连环重试
     - `error: confirm_timeout` → 已发起但日志没等到终态，状态未知
   - `mode=noui` / `rpa`：`ok: true` **只代表 PC 侧调用成功**，
     不等于手机收到 —— 此时**禁止**说「已送达」，只说「已发起」
   - exit 2 → 环境（无管家 / 无 frida / 无 Launch）
   - exit 3 → 超时 / 设备未解析
   - exit 4 → 发送失败（silent 下多为设备侧超时）

## 禁止

- 禁止自己写 CreateFileMapping / Frida / UIA 脚本
- 禁止在 doctor 失败时循环重试 send
- 禁止未确认路径就发送

## 参考

- 命令契约见 `references/cli-contract.md`
- 研究笔记：仓库内 `docs/research-backend-api.md`
