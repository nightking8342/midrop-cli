---
name: midrop-cli
description: 把电脑上的文件通过小米互传（MiDrop）发到小米手机或平板。用户说「发到我手机」「互传」「传到 Fold/Pad」「发到平板」「MiDrop」时使用。通过 midrop CLI 执行，禁止手写共享内存、UIA 或 Frida 脚本。
---

# midrop CLI

用 PATH 上的 `midrop` 命令把文件发到小米设备。执行层是 CLI；本 skill 只负责路由与结果解读。

## 发送模式

- **默认 `noui`**：Frida 进程内调用 `HandleCreateSendTask`（可锁屏；不点 UI）
- **备选 `rpa`**：弹窗 + UIA 点设备（旧方式；锁屏易假成功）

## 列设备

`midrop devices` 默认读 `smart_share_log.txt` 最后一条 `current lyra devices` 快照。
返回的 `snapshot_age_sec` 越小越新；数十秒内可信。

```bash
midrop send "PATH" --device Fold --format json          # 默认 noui
midrop send "PATH" --device Pad --mode rpa --format json # 强制旧方式
midrop config set send_mode noui|rpa
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
   - noui 需要 **frida** 检查为 ok
2. 确认本地文件绝对路径存在
3. 设备参数：
   - 手机 / Fold / MIX → `--device Fold`
   - 平板 / Pad → `--device Pad`
   - 未指定 → 省略 `--device`（用 `default_device`）
4. 发送：`midrop send "ABS_PATH" [--device KW] --format json`
5. 解读：
   - exit 0 且 `ok: true` → **PC 已发起**（看 `mode` 字段：`noui` 或 `rpa`）
   - **禁止**说「手机已保存成功」
   - `mode=noui` 时看 `noui_invoked` / logs；`mode=rpa` 时 `clicked:true` 在锁屏下可能假成功
   - exit 2 → 环境（无管家 / 无 frida / 无 Launch）
   - exit 3 → 超时 / 设备未解析

## 禁止

- 禁止自己写 CreateFileMapping / Frida / UIA 脚本
- 禁止在 doctor 失败时循环重试 send
- 禁止未确认路径就发送

## 参考

- 命令契约见 `references/cli-contract.md`
- 研究笔记：仓库内 `docs/research-backend-api.md`
