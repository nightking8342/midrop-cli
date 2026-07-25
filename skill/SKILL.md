---
name: midrop-cli
description: 把电脑上的文件通过小米互传（MiDrop）发到小米手机或平板。用户说「发到我手机」「互传」「传到 Fold/Pad」「发到平板」「MiDrop」时使用。通过 midrop CLI 执行，禁止手写共享内存或 UIA 脚本。
---

# midrop CLI

用 PATH 上的 `midrop` 命令把文件发到小米设备。执行层是 CLI；本 skill 只负责路由与结果解读。

## 何时使用

- 用户要求把本机文件发到手机/平板
- 提及：小米互传、MiDrop、互传、发到 Fold/MIX/Pad

## 何时不用

- 非小米互传渠道（Telegram 传文件、adb push 等）
- 用户未给出且对话中没有明确文件路径时——先问路径，禁止猜测

## 工作流

1. 环境不确定 → `midrop doctor --format json`
   - `healthy: false` 或 exit 2 → 摘要 checks，让用户打开小米电脑管家，不要盲目重试 send
2. 确认本地文件绝对路径存在
3. 选择设备参数：
   - 手机 / Fold / MIX → `--device Fold`（或用户说过的关键字）
   - 平板 / Pad → `--device Pad`
   - 未指定 → 不传 `--device`（用 default_device）
4. 关键字不确定 → `midrop devices --format json`，用返回的 `name` 再 send
5. 发送：`midrop send "ABS_PATH" [--device KW] --format json`
6. 解读：
   - exit 0 且 `clicked: true` → 告诉用户 **PC 已发起发送** 到 `device_matched`；若手机需确认请在手机上点接收。**禁止**说「已保存到手机成功」
   - exit 3 → 弹窗/设备超时或未匹配，展示 message 与 candidates
   - exit 2 → 环境问题，建议 doctor
   - exit 4 → 点击失败，可请用户手动点弹窗

## 禁止

- 禁止自己写 CreateFileMapping / Launch.exe 脚本
- 禁止在 doctor 失败时循环重试 send
- 禁止未确认路径就发送

## 参考

- 命令契约见 `references/cli-contract.md`
