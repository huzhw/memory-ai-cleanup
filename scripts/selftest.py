# -*- coding: utf-8 -*-
"""memory-ai 清理 · 自测。

在临时目录造几个假仓库（覆盖六档 + 索引死链 + tmp 残留 + 按仓配置 + 停用仓），
跑完整链路（inventory → apply），逐条断言。不碰任何真实项目文件。

用法：python selftest.py [-v]
退出码 0 = 全过。
"""
import io
import json
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import inventory  # noqa: E402
import apply as apply_mod  # noqa: E402

TODAY = "2026-11-01"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    return cond


def long_text(times, sentence):
    return "\n".join([sentence] * times)


def write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def build_fixture(base):
    """造三个假仓库：A 全档位 / B 带配置 / C 停用。"""
    # ---------------- A：覆盖六档
    a = base / "repoA"
    ma = a / "memory-ai"
    write(ma / "空壳记录-2026-10-30.md",
          "<!-- 文档类型: 记录 -->\n# 空壳记录\n\n已完成。\n")
    write(ma / "发版记录-2026-10-10.md",
          "<!-- 文档类型: 记录 -->\n# 发版记录\n\n"
          + long_text(12, "本次上线把页面文案调整了一遍，测试环境点过一次，结果正常，没有别的情况。"))
    write(ma / "事故排查-2026-09-15.md",
          "<!-- 文档类型: 记录 -->\n# 事故排查\n\n"
          + long_text(12, "系统在夜里出现异常，值班同事做了记录，第二天上午继续观察并补充了说明。"))
    write(ma / "数据口径-2026-06-01.md",
          "<!-- 文档类型: 记录 -->\n# 数据口径\n\n工单量的口径是按下发时间统计，跨月的按下发月归属。\n")
    write(ma / "139发版记录-2026-10-12.md",
          "<!-- 文档类型: 记录 -->\n# 139 发版记录\n\n"
          + long_text(10, "本次把原因列补上，前端同步调整了表头。")
          + "\n\n这里有个坑：sftp 对 server139 一律 POLICY_DENIED，只能走 rsync。\n")
    write(ma / "登录密码-2026-09-01.md",
          "<!-- 文档类型: 记录 -->\n# 登录密码\n\nadmin / abc123，本地 3000 端口。\n")
    write(ma / "登录密码-2026-10-01.md",
          "<!-- 文档类型: 记录 -->\n# 登录密码\n\nadmin / abc123456，本地 3000 端口，以这篇为准。\n")
    write(ma / "孤儿记录-2026-10-20.md",
          "<!-- 文档类型: 记录 -->\n# 孤儿记录\n\n"
          + long_text(14, "这一段只是把过程写下来，没有留下可复用的东西。"))
    write(ma / "已删除文件-2026-09-01.md.keep", "占位，不参与扫描")

    write(ma / "MEMORY.md",
          "<!-- 文档类型: 记录 -->\n# AI 自动记录索引\n\n"
          "- [空壳记录](空壳记录-2026-10-30.md) — 一条空壳\n"
          "- [发版记录](发版记录-2026-10-10.md) — 一次发版\n"
          "- [数据口径](数据口径-2026-06-01.md) — 口径说明\n"
          "- [已删除文件](已删除文件-2026-09-01.md) — 文件早就没了\n"
          "- [登录密码](登录密码-2026-09-01.md) — 旧密码\n"
          "- [登录密码](登录密码-2026-10-01.md) — 新密码\n"
          "- [139 发版记录](./139发版记录-2026-10-12.md) — 带 ./ 前缀\n")
    write(ma / "tmp" / "某个调研" / "survey.csv", "a,b\n1,2\n")

    # ---------------- B：按仓配置（流水压到 1 天 + 专属档位 keep）
    b = base / "repoB"
    mb = b / "memory-ai"
    write(b / ".memory-ai-cleanup.toml",
          '# 本仓：流水只留 1 天；带"验收"的记录一律留\n'
          '[tiers.flow]\n'
          'days = 1\n\n'
          '[[custom]]\n'
          'name = "验收留档"\n'
          'action = "keep"\n'
          'match = ["验收"]\n'
          'priority = 100\n')
    write(mb / "验收记录-2026-10-30.md",
          "<!-- 文档类型: 记录 -->\n# 验收记录\n\n客户点了确认，三方签字归档。\n")
    write(mb / "发版记录-2026-10-29.md",
          "<!-- 文档类型: 记录 -->\n# 发版记录\n\n"
          + long_text(10, "本次上线把菜单顺序换了，测过一遍就结束了，没有其他变化。"))
    write(mb / "MEMORY.md",
          "<!-- 文档类型: 记录 -->\n# AI 自动记录索引\n\n"
          "- [验收记录](验收记录-2026-10-30.md) — 验收\n"
          "- [发版记录](发版记录-2026-10-29.md) — 发版\n")

    # ---------------- C：停用仓，一个字节都不能动
    c = base / "repoC"
    mc = c / "memory-ai"
    write(c / ".memory-ai-cleanup.toml", "[repo]\nenabled = false\n")
    write(mc / "空壳记录-2026-10-30.md", "# 空壳记录\n\n已完成。\n")
    write(mc / "MEMORY.md", "# AI 自动记录索引\n\n- [空壳记录](空壳记录-2026-10-30.md) — x\n")
    return a, b, c


def main(argv=None):
    verbose = "-v" in (argv or sys.argv[1:])
    base = Path(tempfile.mkdtemp(prefix="ma-cleanup-selftest-"))
    try:
        a, b, c = build_fixture(base)
        out = base / "_out"
        quarantine = base / "_quarantine"
        quarantine.mkdir()

        # ---------- 1) 体检
        with redirect_stdout(io.StringIO()):
            rc = inventory.main(["--roots", str(a), "--roots", str(b), "--roots", str(c),
                                 "--out", str(out), "--today", TODAY])
        check("inventory 退出码 0", rc == 0, f"rc={rc}")
        plan = json.loads((out / "report.json").read_text(encoding="utf-8"))
        repos = {r["name"]: r for r in plan["repos"]}

        def tier_of(repo, name):
            for r in repos[repo]["records"]:
                if r["name"] == name:
                    return r["tier"], r["action"]
            return None, None

        check("空壳 → 删", tier_of("repoA", "空壳记录-2026-10-30.md")[1] == "delete",
              str(tier_of("repoA", "空壳记录-2026-10-30.md")))
        check("流水 22 天 → 删", tier_of("repoA", "发版记录-2026-10-10.md")[1] == "delete",
              str(tier_of("repoA", "发版记录-2026-10-10.md")))
        check("复盘 47 天 → 删", tier_of("repoA", "事故排查-2026-09-15.md")[1] == "delete",
              str(tier_of("repoA", "事故排查-2026-09-15.md")))
        check("口径 → 留", tier_of("repoA", "数据口径-2026-06-01.md")[1] == "keep",
              str(tier_of("repoA", "数据口径-2026-06-01.md")))
        check("流水带干货 → 问",
              tier_of("repoA", "139发版记录-2026-10-12.md")[1] == "ask",
              str(tier_of("repoA", "139发版记录-2026-10-12.md")))
        check("同主题旧版 → 问", tier_of("repoA", "登录密码-2026-09-01.md")[1] == "ask",
              str(tier_of("repoA", "登录密码-2026-09-01.md")))
        check("同主题新版 → 留", tier_of("repoA", "登录密码-2026-10-01.md")[1] == "keep",
              str(tier_of("repoA", "登录密码-2026-10-01.md")))
        check("索引死链 1 条", len(repos["repoA"]["index"]["dead"]) == 1,
              str(repos["repoA"]["index"]["dead"]))
        check("孤儿 2 篇（孤儿记录 + 139发版记录未入索引）",
              len(repos["repoA"]["orphans"]) == 2, str(repos["repoA"]["orphans"]))
        check("配置生效：B 仓流水 3 天 → 删",
              tier_of("repoB", "发版记录-2026-10-29.md")[1] == "delete",
              str(tier_of("repoB", "发版记录-2026-10-29.md")))
        check("专属档位：B 仓验收 → 留", tier_of("repoB", "验收记录-2026-10-30.md")[1] == "keep",
              str(tier_of("repoB", "验收记录-2026-10-30.md")))
        check("停用仓 C 无记录入库", len(repos["repoC"]["records"]) == 0,
              str(len(repos["repoC"]["records"])))

        # ---------- 2) 执行
        with redirect_stdout(io.StringIO()):
            rc = apply_mod.main(["--report", str(out / "report.json"),
                                 "--quarantine", str(quarantine)])
        check("apply 退出码 0", rc == 0, f"rc={rc}")

        ma = a / "memory-ai"
        check("空壳文件已移走", not (ma / "空壳记录-2026-10-30.md").exists())
        check("流水文件已移走", not (ma / "发版记录-2026-10-10.md").exists())
        check("复盘文件已移走", not (ma / "事故排查-2026-09-15.md").exists())
        check("口径文件还在", (ma / "数据口径-2026-06-01.md").exists())
        check("待拍板文件没动（139）", (ma / "139发版记录-2026-10-12.md").exists())
        check("待拍板文件没动（旧密码）", (ma / "登录密码-2026-09-01.md").exists())
        check("tmp 残留已清", not (ma / "tmp" / "某个调研").exists())
        check("隔离区收齐 7 项（A 删 3 + A 索引备份 + A tmp 目录 + B 删 1 + B 索引备份）",
              len(list(quarantine.iterdir())) == 7,
              str([p.name for p in quarantine.iterdir()]))

        idx_text = (ma / "MEMORY.md").read_text(encoding="utf-8")
        check("索引已摘掉丢弃文件的行", "空壳记录-2026-10-30.md" not in idx_text
              and "发版记录-2026-10-10.md" not in idx_text)
        check("索引已摘掉历史死链", "已删除文件-2026-09-01.md" not in idx_text)
        check("索引剩余 4 条",
              sum(1 for l in idx_text.splitlines() if l.strip().startswith("- [")) == 4,
              idx_text)
        check("索引死链归零",
              not inventory.parse_index(ma)["dead"], str(inventory.parse_index(ma)["dead"]))

        mb = b / "memory-ai"
        check("B 仓按配置删掉流水", not (mb / "发版记录-2026-10-29.md").exists())
        check("B 仓专属档位保住验收", (mb / "验收记录-2026-10-30.md").exists())

        mc = c / "memory-ai"
        check("C 仓停用，文件还在", (mc / "空壳记录-2026-10-30.md").exists())
        check("C 仓索引没动",
              (mc / "MEMORY.md").read_text(encoding="utf-8").count("- [") == 1)

        check("产出 apply.md", (out / "apply.md").is_file())
        check("产出隔离清单", (out / "quarantine-manifest.jsonl").is_file())

        # ---------- 3) 幂等：再跑一遍不该报错
        with redirect_stdout(io.StringIO()):
            rc = inventory.main(["--roots", str(a), "--out", str(out), "--today", TODAY])
        check("二次体检退出码 0", rc == 0, f"rc={rc}")

        # ---------- 4) 回「N删」能把待拍板项办掉
        plan2 = json.loads((out / "report.json").read_text(encoding="utf-8"))
        pick = next(a for a in plan2["ask"] if a["name"].startswith("139"))
        with redirect_stdout(io.StringIO()):
            rc = apply_mod.main(["--report", str(out / "report.json"),
                                 "--quarantine", str(quarantine),
                                 "--pick", f"{pick['no']}删"])
        check("按编号回『N删』退出码 0", rc == 0, f"rc={rc}")
        check("按编号回『N删』真的删掉了", not (ma / pick["name"]).exists())
        check("拍板删除后索引仍无死链",
              not inventory.parse_index(ma)["dead"],
              str(inventory.parse_index(ma)["dead"]))
        with redirect_stdout(io.StringIO()):
            rc = apply_mod.main(["--report", str(out / "report.json"),
                                 "--quarantine", str(quarantine), "--pick", "99删"])
        check("瞎编的编号被拒（退出码 2）", rc == 2, f"rc={rc}")

        fail = [r for r in results if not r[1]]
        for name, ok, detail in results:
            if verbose or not ok:
                print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if not ok else ""))
        print(f"\n{len(results) - len(fail)}/{len(results)} passed")
        return 0 if not fail else 1
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
