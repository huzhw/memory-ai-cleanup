# memory-ai-cleanup — 按期扫掉各仓 memory-ai/ 里没用的 AI 记录

## 定位

给「AI 每个任务都往 `memory-ai/` 写记录」这个机制配一个**清道夫**。一条命令扫全部仓：过期的一次性流水删掉、`MEMORY.md` 里的死链摘掉、`tmp/` 残留清掉；判不准的列成清单问人。

只清"过期且没用"的，不动规则、口径、设计、凭据这类要给下一个人查的资产。

## 相关技能

- [agent-config-sync-check](https://github.com/huzhw/agent-config-sync-check)：八端同步守卫：链接/硬链接/README 同步检查与修复
- [code-check](https://github.com/huzhw/code-check-skill)：增量代码隐患检查
- [coding-rules](https://github.com/huzhw/coding-rules)：编码规则库（独立仓库，非 skill）
- [daily-merge-gitlab-excel](https://github.com/huzhw/daily-merge-gitlab-excel-skill)：日报合并（手动兜底，已由日报管家接管，不推荐）
- [daily-record-gitlab-md](https://github.com/huzhw/daily-record-gitlab-md-skill)：日报记录（第一步）
- [daily-report-panel](https://github.com/huzhw/daily-report-panel)：日报管家（关联仓库，非 skill，自动合并/导出/发件）
- [deepseek-harness-plugin-doctor](https://github.com/huzhw/deepseek-harness-plugin-doctor)：DeepSeek Harness 插件与升级体检医生
- [deepseek-harness-settings-curator](https://github.com/huzhw/deepseek-harness-settings-curator)：DeepSeek Harness 模型配置梳理
- [dev-env-upgrade](https://github.com/huzhw/dev-env-upgrade)：开发环境升级医生：版本体检/最新版查询/安全升级
- [git-commit](https://github.com/huzhw/git-commit-skill)：Git 提交规范
- [prd](https://github.com/huzhw/prd-skill)：PRD 生成器（一句话需求→结构化需求文档）
- [ralph](https://github.com/huzhw/ralph-skill)：PRD 转 prd.json（Ralph 自主执行格式）
- [reread-rules](https://github.com/huzhw/reread-rules-skill)：重载 CLAUDE.md / AGENTS.md 规则

## 解决了什么问题

`memory-ai/` 会持续膨胀，但真正让人难受的不是磁盘，是三件小事：

1. **索引死链**：文件删了、`MEMORY.md` 那行还在。实测 12 个仓 73 篇记录里有 **80 条死链**，其中一仓 71 条剩 12 条活的
2. **过期流水没人清**：发版记录、执行进度、验证结论这类一次性文档，过两周就没人看，但会一直躺着
3. **判过期的方法不可信**：文件 mtime 被整批复制刷成同一天，按 mtime 判等于闭眼删

本技能的做法：日期只认文件名后缀，档位只看标题，正文干货只用于"拦住自动删"，删除全进隔离区。

## 使用

```bash
cd F:\idea-workspase-skills\memory-ai-cleanup\scripts

python run.py --discover "F:/"           # 扫全盘，自动办事
python run.py --roots "D:/proj/a"        # 单仓
python run.py --discover "F:/" --dry-run # 只看不动
```

看完 `report.md` 的「待你拍板」，回编号执行：

```bash
python apply.py --report "<报告目录>/report.json" --pick 1删 3删
```

按仓调整档位：项目根放 `.memory-ai-cleanup.toml`（示例见 `SKILL.md`）。

## 文件结构

```
memory-ai-cleanup/
├── SKILL.md              技能说明：铁律 / 六档判定 / 报告怎么回 / 按仓配置 / 坑清单
├── README.md             本文件
├── JUNCTION说明.md        五端 junction 指向与回滚
├── .gitignore
└── scripts/
    ├── inventory.py      只读体检：扫记录、解析索引、判档、出报告
    ├── apply.py          执行：删（进隔离区）+ 摘死链 + 清 tmp，带三条校验
    ├── run.py            一条命令串起体检与执行
    └── selftest.py       自测：造临时假仓库跑全链路，37 条断言，不碰真文件
```

## 安装

```bash
git clone https://github.com/huzhw/memory-ai-cleanup.git ~/.claude/skills/memory-ai-cleanup
```

其他端同理，把 `~/.claude/skills/` 换成对应端目录（五端 junction 由 `agent-config-sync-check` 的 `sync-check.ps1 -Fix` 统一维护）。

## 许可

MIT
