# -*- coding: utf-8 -*-
"""memory-ai 清理 · 一条命令跑完（体检 → 执行）。

默认只清「你正在干的这个仓」：从当前目录往上找 memory-ai/MEMORY.md，找到哪个就清哪个。
要一次清多个仓，显式加 --all <扫描根>，并且先配 --dry-run 看一眼——那是别人的地盘。

前面不用你审：能自动判的（空壳 / 超期流水 / 超期复盘）直接办，
拿不准的进"待你拍板"清单，看报告回一句 1删 2留 3榨 就行。

用法：
  python run.py                             # 只清当前仓库
  python run.py --dry-run                   # 只看不删
  python run.py --all "F:/"                 # 跨仓模式（谨慎）
  python run.py --out <目录> --dry-run       # 报告换个地方放
"""
import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory  # noqa: E402  同目录脚本，按路径导入
import apply as apply_mod  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="memory-ai 清理 · 一条命令（默认只清当前仓库）")
    ap.add_argument("--all", "--discover", dest="all_roots", action="append", default=[],
                    metavar="扫描根", help="跨仓模式：在该根下找所有 memory-ai；不给就只清当前仓库")
    ap.add_argument("--roots", action="append", default=[], help="项目根（含 memory-ai 的那层）")
    ap.add_argument("--out", help="报告输出目录")
    ap.add_argument("--quarantine", default=apply_mod.DEFAULT_QUARANTINE, help="隔离区目录")
    ap.add_argument("--today", help="按哪天算天数")
    ap.add_argument("--dry-run", action="store_true", help="只体检，不动手")
    args = ap.parse_args(argv)

    today = datetime.date.fromisoformat(args.today) if args.today else datetime.date.today()

    if args.all_roots and not args.dry_run:
        print("跨仓模式：接下来会改 --all 下所有仓的索引，建议先加 --dry-run 看一眼")

    inv_argv = []
    for d in args.all_roots:
        inv_argv += ["--all", d]
    for r in args.roots:
        inv_argv += ["--roots", r]
    if args.today:
        inv_argv += ["--today", args.today]

    # 报告目录：没指定就按 inventory 的默认规则算（当前仓的 tmp），两边一致才能接上
    out_dir = Path(args.out) if args.out else inventory.default_out_dir(today)
    inv_argv += ["--out", str(out_dir)]

    rc = inventory.main(inv_argv)
    if rc != 0:
        return rc

    report = out_dir / "report.json"
    if not report.is_file():
        print(f"report missing: {report}")
        return 2
    if args.dry_run:
        print(f"dry-run report: {out_dir / 'report.md'}")
        return 0

    apply_argv = ["--report", str(report), "--quarantine", args.quarantine]
    rc = apply_mod.main(apply_argv)
    print(f"report: {out_dir / 'report.md'}")
    print(f"summary: {out_dir / 'apply.md'}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
