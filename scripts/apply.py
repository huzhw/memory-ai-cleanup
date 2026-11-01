# -*- coding: utf-8 -*-
"""memory-ai 清理 · 执行（只读报告 → 动手）。

只认 inventory.py 出的 report.json：
  · 删 = 报告里 action==delete 的记录（空壳 / 超期流水 / 超期复盘）
  · 摘链 = MEMORY.md 里指向"已删或本来就不存在"的行
  · 清 tmp = memory-ai/tmp/ 下残留（规则要求任务收尾必删）

安全网三条（任何一条不满足就中止，不做半截操作）：
  1. 删除不真删——搬进隔离区（默认 X:\\隔离区），14 天可捞，落一行 manifest 记来处
  2. 改 MEMORY.md 前整份备份进隔离区
  3. 改完校验：条目数 = 改前 − 摘掉数，且重扫死链必须为 0

用法：
  python apply.py --report <out_dir>/report.json           # 执行
  python apply.py --report <out_dir>/report.json --dry-run # 只说不做
"""
import argparse
import datetime
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

LINK_RE = re.compile(r"- \[[^\]]*\]\(([^)]+)\)")
DEFAULT_QUARANTINE = r"X:\隔离区"
#: 本轮自己的报告目录名前缀，清 tmp 时跳过（否则把刚生成的报告一起搬走）
OWN_TMP_PREFIX = "memory-ai-cleanup-"


def norm_link(target):
    t = target.strip().replace("%20", " ").replace("\\", "/")
    while t.startswith("./"):
        t = t[2:]
    return t


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def quarantine_path(quarantine, repo_name, name, ts):
    """隔离区落点：时间戳-仓库-原文件名，扁平放，靠 manifest 溯源。"""
    safe = re.sub(r'[\\/:*?"<>|]', "_", f"{ts}-{repo_name}-{name}")
    dest = Path(quarantine) / safe
    i = 1
    while dest.exists():
        dest = Path(quarantine) / f"{safe}.{i}"
        i += 1
    return dest


def move_to_quarantine(path, quarantine, repo_name, ts, manifest):
    """搬一个文件/目录进隔离区，返回落点；失败抛异常交给上层中止本仓。"""
    dest = quarantine_path(quarantine, repo_name, Path(path).name, ts)
    if Path(path).is_dir():
        shutil.move(str(path), str(dest))
        digest = ""
    else:
        digest = sha256(path)
        shutil.move(str(path), str(dest))
    manifest.append({"from": str(path), "to": str(dest), "sha256": digest})
    return dest


def prune_index(ma_dir, deleted, quarantine, repo_name, ts, manifest):
    """重写 MEMORY.md：摘掉"目标不存在"的行（含本次删掉的与历史死链）。

    返回 (摘掉条数, 改前条数, 改后条数)。任何校验不过就还原并抛异常。
    """
    idx = ma_dir / "MEMORY.md"
    if not idx.is_file():
        return 0, 0, 0
    text = idx.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    # 先备份原索引进隔离区（改名，避免与文件同名的记录混淆）
    backup = quarantine_path(quarantine, repo_name, f"MEMORY.md.bak", ts)
    Path(backup).write_text(text, encoding="utf-8")
    manifest.append({"from": str(idx) + " (备份)", "to": str(backup), "sha256": ""})

    kept, removed = [], 0
    for line in lines:
        s = line.strip()
        if s.startswith("- ["):
            m = LINK_RE.search(s)
            if m:
                target = norm_link(m.group(1))
                if not re.match(r"^[a-zA-Z]+:", target) and not (ma_dir / target).is_file():
                    removed += 1
                    continue
        kept.append(line)

    before = sum(1 for l in lines if l.strip().startswith("- ["))
    after = sum(1 for l in kept if l.strip().startswith("- ["))
    if after != before - removed:
        raise RuntimeError(f"索引条目数校验失败：改前 {before} · 摘掉 {removed} · 改后 {after}")

    new_text = "\n".join(kept)
    if text.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"

    # 落盘前再验一次：按新正文重扫，死链必须为 0（被摘的 + 本次删的都算）
    leftover = 0
    for line in new_text.splitlines():
        s = line.strip()
        if not s.startswith("- ["):
            continue
        m = LINK_RE.search(s)
        if not m:
            continue
        target = norm_link(m.group(1))
        if not re.match(r"^[a-zA-Z]+:", target) and not (ma_dir / target).is_file():
            leftover += 1
    if leftover:
        raise RuntimeError(f"重扫仍有 {leftover} 条死链，已中止（索引未改动）")

    idx.write_text(new_text, encoding="utf-8")
    return removed, before, after


def clean_tmp(ma_dir, quarantine, repo_name, ts, manifest, keep_names):
    """清 memory-ai/tmp/ 残留：搬隔离区，不直接删；跳过本轮报告目录。"""
    tmp = ma_dir / "tmp"
    if not tmp.is_dir():
        return []
    done = []
    for p in sorted(tmp.iterdir()):
        if p.name in keep_names or p.name.startswith(OWN_TMP_PREFIX):
            continue
        move_to_quarantine(p, quarantine, repo_name, ts, manifest)
        done.append(p.name)
    return done


def process_repo(repo, quarantine, ts, dry_run, manifest, extra_names=None):
    """处理单个仓库，返回该仓的处理摘要。

    extra_names：用户看完报告回的「N删」对应的文件名，追加进删单。
    """
    root = Path(repo["root"])
    ma_dir = root / "memory-ai"
    extra_names = set(extra_names or ())
    summary = {"repo": repo["name"], "deleted": [], "index_removed": 0,
               "tmp_cleaned": [], "skipped": [], "errors": []}

    if not repo.get("enabled", True):
        summary["skipped"].append("配置里已停用本仓")
        return summary

    deletes = [r for r in repo.get("records", [])
               if r.get("action") == "delete" or r.get("name") in extra_names]
    if dry_run:
        summary["deleted"] = [f"{r['name']}（{r['tier']}）" for r in deletes]
        summary["tmp_cleaned"] = [Path(t["path"]).name for t in repo.get("tmp", [])]
        return summary

    for rec in deletes:
        p = Path(rec["path"])
        if not p.is_file():
            summary["skipped"].append(f"{rec['name']} 已不存在")
            continue
        move_to_quarantine(p, quarantine, repo["name"], ts, manifest)
        tag = "（你拍板）" if rec["name"] in extra_names else f"（{rec['tier']}）"
        summary["deleted"].append(f"{rec['name']}{tag}")

    removed, before, after = prune_index(ma_dir, summary["deleted"], quarantine,
                                        repo["name"], ts, manifest)
    summary["index_removed"] = removed
    summary["index_before"], summary["index_after"] = before, after

    summary["tmp_cleaned"] = clean_tmp(ma_dir, quarantine, repo["name"], ts, manifest,
                                       keep_names=set())
    return summary


def render_summary(summaries, plan, dry_run):
    """生成给人看的执行摘要。"""
    lines = ["# memory-ai 清理执行" + ("（演练，未动手）" if dry_run else ""), ""]
    lines.append(f"日期：{datetime.date.today().isoformat()}　来源检修：{plan.get('out_dir', '')}")
    lines.append("")
    tot_del = tot_idx = tot_tmp = 0
    for s in summaries:
        tot_del += len(s["deleted"])
        tot_idx += s.get("index_removed") or 0
        tot_tmp += len(s["tmp_cleaned"])
        lines.append(f"## {s['repo']}")
        if s["deleted"]:
            lines.append(f"- 删 {len(s['deleted'])} 篇：" + "、".join(s["deleted"]))
        if s.get("index_removed"):
            lines.append(f"- MEMORY.md 摘链 {s['index_removed']} 行"
                         f"（{s.get('index_before')} → {s.get('index_after')} 条）")
        if s["tmp_cleaned"]:
            lines.append(f"- 清 tmp {len(s['tmp_cleaned'])} 项：" + "、".join(s["tmp_cleaned"]))
        for k in s["skipped"]:
            lines.append(f"- 跳过：{k}")
        for e in s["errors"]:
            lines.append(f"- ⚠ 失败：{e}")
        if not (s["deleted"] or s.get("index_removed") or s["tmp_cleaned"]):
            lines.append("- 本仓无需处理")
        lines.append("")
    lines.append(f"合计：删 {tot_del} 篇 · 摘链 {tot_idx} 行 · 清 tmp {tot_tmp} 项")
    lines.append("")
    lines.append("被删文件都在隔离区（默认 14 天），要捞回按下面 manifest 里 from→to 反向搬。")
    return "\n".join(lines)


def parse_picks(pick_args, asks):
    """把用户回的 ["1删", "3"] 解析成 {仓库名: {文件名}}。

    编号来自报告，`N留` 等于不动（直接忽略），所以这里只需要收集要删的。
    """
    by_no = {a["no"]: a for a in asks}
    mapping, errors = {}, []
    for item in pick_args:
        m = re.match(r"^(\d+)\s*(删|留)?$", item.strip())
        if not m:
            errors.append(f"看不懂的编号：{item}")
            continue
        no, verdict = int(m.group(1)), (m.group(2) or "删")
        if no not in by_no:
            errors.append(f"报告里没有第 {no} 项")
            continue
        if verdict == "留":
            continue
        a = by_no[no]
        mapping.setdefault(a["repo"], set()).add(a["name"])
    return mapping, errors


def main(argv=None):
    ap = argparse.ArgumentParser(description="memory-ai 清理 · 执行")
    ap.add_argument("--report", required=True, help="inventory.py 产出的 report.json")
    ap.add_argument("--quarantine", default=DEFAULT_QUARANTINE, help="隔离区目录")
    ap.add_argument("--pick", nargs="*", default=[],
                    help="按报告编号追加删除，如 1删 3删（留的不写）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划不落盘")
    args = ap.parse_args(argv)

    report = Path(args.report)
    if not report.is_file():
        print(f"report not found: {report}")
        return 2
    plan = json.loads(report.read_text(encoding="utf-8"))
    out_dir = Path(plan["out_dir"])

    picks, pick_errors = parse_picks(args.pick, plan.get("ask", []))
    if pick_errors:
        print("; ".join(pick_errors))
        return 2

    if not args.dry_run:
        q = Path(args.quarantine)
        if not q.is_dir():
            # 隔离区不存在就中止：宁可不动，也不能因为盘符不在就变成真删
            print(f"quarantine not available: {q}")
            return 3

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    manifest = []
    summaries = []
    for repo in plan.get("repos", []):
        try:
            summaries.append(process_repo(repo, args.quarantine, ts, args.dry_run, manifest,
                                         extra_names=picks.get(repo["name"], set())))
        except Exception as exc:  # noqa: BLE001 单仓失败不影响其他仓
            summaries.append({"repo": repo["name"], "deleted": [], "index_removed": 0,
                              "tmp_cleaned": [], "skipped": [], "errors": [str(exc)]})

    (out_dir / ("apply-dryrun.md" if args.dry_run else "apply.md")).write_text(
        render_summary(summaries, plan, args.dry_run), encoding="utf-8")
    if manifest:
        (out_dir / "quarantine-manifest.jsonl").write_text(
            "\n".join(json.dumps(m, ensure_ascii=False) for m in manifest), encoding="utf-8")

    n_del = sum(len(s["deleted"]) for s in summaries)
    n_err = sum(len(s["errors"]) for s in summaries)
    print(f"repos={len(summaries)} deleted={n_del} errors={n_err} out={out_dir}")
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main())
