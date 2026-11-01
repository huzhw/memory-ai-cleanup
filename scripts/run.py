# -*- coding: utf-8 -*-
"""memory-ai 清理 · 一条命令跑完（体检 → 执行）。

前面不用你审：能自动判的（空壳 / 超期流水 / 超期复盘）直接办，
拿不准的进"待你拍板"清单，看报告回一句 1删 2留 3榨 就行。

用法：
  python run.py --discover F:\\            # 扫全盘所有 memory-ai 目录
  python run.py --roots D:\\proj\\a         # 只调某个仓
  python run.py --discover F:\\ --dry-run  # 只体检不删
"""
import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory  # noqa: E402  同目录脚本，按路径导入
import apply as apply_mod  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="memory-ai 清理 · 一条命令")
    ap.add_argument("--discover", action="append", default=[], help="自动找 memory-ai 的扫描根")
    ap.add_argument("--roots", action="append", default=[], help="项目根")
    ap.add_argument("--out", help="报告输出目录")
    ap.add_argument("--quarantine", default=apply_mod.DEFAULT_QUARANTINE, help="隔离区目录")
    ap.add_argument("--today", help="按哪天算天数")
    ap.add_argument("--dry-run", action="store_true", help="只体检，不动手")
    args = ap.parse_args(argv)

    today = datetime.date.fromisoformat(args.today) if args.today else datetime.date.today()

    inv_argv = []
    for d in args.discover:
        inv_argv += ["--discover", d]
    for r in args.roots:
        inv_argv += ["--roots", r]
    if args.today:
        inv_argv += ["--today", args.today]

    # 报告目录：没指定就沿用 inventory 的默认规则（首个根下的 tmp），两边算得一样才能接上
    out_dir = Path(args.out) if args.out else None
    if out_dir is None:
        first_root = None
        for r in args.roots:
            first_root = Path(r)
            break
        if first_root is None and args.discover:
            found = inventory.find_memory_ai_dirs(args.discover[0])
            first_root = found[0] if found else None
        if first_root is None:
            print("no root to place report; pass --out")
            return 2
        out_dir = first_root / "memory-ai" / "tmp" / f"memory-ai-cleanup-{today.isoformat()}"
    inv_argv += ["--out", str(out_dir)]

    rc = inventory.main(inv_argv)
    if rc != 0:
        print("inventory failed")
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
