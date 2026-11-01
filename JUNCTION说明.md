# JUNCTION 说明 — memory-ai-cleanup

> 本目录已与各端全局 skill 目录建立 junction，**实时双向同步，改哪边都一样**。

## 指向关系

| 项 | 路径 |
|----|------|
| 全局路径（junction，Claude Code） | `C:\Users\Administrator\.claude\skills\memory-ai-cleanup` |
| 全局路径（junction，DeepSeek Harness） | `C:\Users\Administrator\.dsh\skills\memory-ai-cleanup` |
| 全局路径（junction，Codex） | `C:\Users\Administrator\.codex\skills\memory-ai-cleanup` |
| 全局路径（junction，Zcode） | `C:\Users\Administrator\.zcode\skills\memory-ai-cleanup` |
| 全局路径（junction，Qoder CN） | `C:\Users\Administrator\.qoder-cn\skills\memory-ai-cleanup` |
| 实际目录（F 仓库） | `F:\idea-workspase-skills\memory-ai-cleanup` |
| 创建日期 | 2026-11-01 |

## 说明

- 全局目录是指向 F 仓库的 junction，与 F 仓库是**同一个目录**，不是副本。
- 修改 F 仓库，全局立刻生效；在全局路径下改文件，F 仓库同步变化。
- 日常维护只改 F 仓库（git 提交推送后全局自动一致），**不需要手动复制同步**。
- 五端 junction 由 `agent-config-sync-check/scripts/sync-check.ps1 -Fix` 自动补建与校验。

## 检查是否正常

```bash
cmd /c dir "C:\Users\Administrator\.claude\skills" | findstr memory-ai-cleanup
cmd /c dir "C:\Users\Administrator\.dsh\skills" | findstr memory-ai-cleanup
cmd /c dir "C:\Users\Administrator\.codex\skills" | findstr memory-ai-cleanup
cmd /c dir "C:\Users\Administrator\.zcode\skills" | findstr memory-ai-cleanup
cmd /c dir "C:\Users\Administrator\.qoder-cn\skills" | findstr memory-ai-cleanup
```

正常应显示 5 个 `<JUNCTION>  ...  memory-ai-cleanup`。

## 回滚方法（恢复成独立副本）

```bat
rd "C:\Users\Administrator\.claude\skills\memory-ai-cleanup"
rd "C:\Users\Administrator\.dsh\skills\memory-ai-cleanup"
rd "C:\Users\Administrator\.codex\skills\memory-ai-cleanup"
rd "C:\Users\Administrator\.zcode\skills\memory-ai-cleanup"
rd "C:\Users\Administrator\.qoder-cn\skills\memory-ai-cleanup"
```

> 注意：`rd` 不要加 `/s`，否则可能递归进 F 源目录。删除 junction 只删链接，不删 F 源目录。

最后修改：2026-11-01
