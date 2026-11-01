# -*- coding: utf-8 -*-
"""memory-ai 清理 · 只读体检。

职责边界（重要）：
  本脚本只产「事实 + 机械判档」，不擅自动任何文件。
  机械判档只在证据明确时给 delete（空壳 / 超期流水 / 超期复盘），
  带高价值特征的记录一律留；「像流水但又有干货」的丢进待确认清单交人拍板。

判档依据全部来自文件本身，不看 mtime —— 多仓文件被整批复制过，mtime 不可信。

用法（默认只清当前仓）：
  python inventory.py                                  # 从当前目录往上找本仓的 memory-ai
  python inventory.py --all "F:/"                      # 跨仓模式：该根下所有 memory-ai
  python inventory.py --roots "D:/proj/a"              # 直接指定项目根（可重复）
  可选：--out <目录>  --today YYYY-MM-DD
"""
import argparse
import datetime
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------- 常量

#: 资产类：标题就说明这是给下一个人查的东西（规则/口径/设计/凭据），永不算流水
ASSET_KW = re.compile(r"(规则|纪律|规范|口径|设计|方案|手册|语义|指南|标准|约定|架构|"
                      r"密码|账号|口令|凭据|清单|坑|陷阱|踩坑|速查)")
#: 一次性流水：发版记录 / 执行进度 / 验证结论 / 回归报告
FLOW_KW = re.compile(r"(发版记录|上线记录|部署记录|执行记录|验证结论|回归|进度|检查报告|"
                     r"今日|批次|完成情况)")
#: 事故复盘：排查 / 复盘 / 补数
RETRO_KW = re.compile(r"(排查|事故|复盘|补数|问题定位)")
#: 陈旧待办：草稿/待办/临时笔记，到点就该没
STALE_KW = re.compile(r"(待办|TODO|草稿|临时|笔记)")
#: 正文里写了"能救下一个人"的东西 —— 流水里埋了这种，就不敢自动删，交人拍板
RICH_KW = re.compile(r"(坑|陷阱|禁止|必须|口径|铁律|注意|教训|结论是)")
#: 本轮自己的报告目录名前缀，不算残留（apply 也跳过）
OWN_TMP_PREFIX = "memory-ai-cleanup-"

DATE_SUFFIX = re.compile(r"-(\d{4})-(\d{2})-(\d{2})\.md$")
DATE_PREFIX = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-")
LINK_RE = re.compile(r"- \[[^\]]*\]\(([^)]+)\)")
TITLE_RE = re.compile(r"^#+\s*(.+)$", re.M)

SKIP_DIRS = {"node_modules", ".git", "target", "dist", "build", ".idea", ".next", "vendor"}
#: 单份记录读入上限，防超大文件拖慢体检
MAX_READ = 512 * 1024

DEFAULT_CONFIG = {
    "repo": {"enabled": True},
    "tiers": {
        "shell": {"enabled": True},              # 空壳：正文极短且无任何可执行信息
        "flow": {"enabled": True, "days": 15},   # 流水：发版/执行/进度/验证结论
        "retro": {"enabled": True, "days": 30},  # 复盘：事故/排查/补数
        "stale": {"enabled": True, "days": 15},  # 陈旧待办：草稿/待办/临时笔记
        "dup": {"enabled": True},                # 重复：同标题有更新版
    },
    "custom": [],   # 本仓专属档位：[{name, action, match[], priority}]
    "protect": {"patterns": []},
}


# ---------------------------------------------------------------- 工具

def read_text(path, limit=MAX_READ):
    """按 UTF-8 读文本，坏字节替换掉；读不到返回空串（体检不该因为单个文件崩掉）。"""
    try:
        with open(path, "rb") as f:
            raw = f.read(limit)
        return raw.decode("utf-8", errors="replace")
    except OSError:
        return ""


def file_date(name):
    """从文件名取日期：支持后缀 -YYYY-MM-DD.md 与前缀 YYYY-MM-DD-。取不到返回 None。"""
    m = DATE_SUFFIX.search(name)
    if m:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = DATE_PREFIX.match(name)
    if m:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def norm_link(target):
    """归一化索引里的链接目标：去 ./ 前缀、统一斜杠、解 %20。"""
    t = target.strip().replace("%20", " ").replace("\\", "/")
    while t.startswith("./"):
        t = t[2:]
    return t


def title_of(text, fallback):
    m = TITLE_RE.search(text)
    return m.group(1).strip() if m else fallback


def base_title(title):
    """去掉日期与括号补充，得到"主题名"，用于判重。"""
    t = re.sub(r"\d{4}-\d{2}-\d{2}", "", title)
    t = re.sub(r"[（(][^）)]*[）)]", "", t)
    t = re.sub(r"[\s\-—_·:：]+", "", t)
    return t


# ---------------------------------------------------------------- 配置

def load_config(root):
    """读 <项目根>/.memory-ai-cleanup.toml；没有就用出厂默认。

    TOML 天生支持注释，Python 3.11+ 自带 tomllib，不引第三方依赖。
    配置写坏了不抛异常——退回默认并记一条 warning，绝不让体检因配置崩掉。
    """
    cfg_path = Path(root) / ".memory-ai-cleanup.toml"
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # 深拷贝
    if not cfg_path.is_file():
        return cfg, None
    try:
        import tomllib
        with open(cfg_path, "rb") as f:
            user = tomllib.load(f)
    except Exception as exc:  # noqa: BLE001 配置错误只降级不阻塞
        return cfg, f"配置解析失败已退回默认：{exc}"
    for key, val in user.items():
        if key in ("tiers", "repo", "protect"):
            if isinstance(val, dict):
                cfg[key].update(val)
        elif key == "custom" and isinstance(val, list):
            cfg["custom"] = val
        else:
            cfg[key] = val
    return cfg, None


def match_custom(rec, custom_tiers):
    """按 priority 从高到低匹配本仓专属档位，命中即返回该档。"""
    for tier in sorted(custom_tiers, key=lambda t: -int(t.get("priority", 0))):
        for kw in tier.get("match", []):
            if kw and kw in rec["title"] + rec["name"]:
                return tier
    return None


def protected(rec, cfg):
    """保护名单：通配符按子串/前后缀简化匹配，命中永不进删单。"""
    import fnmatch
    name = rec["name"]
    for pat in cfg.get("protect", {}).get("patterns", []):
        if fnmatch.fnmatch(name, pat) or pat in name:
            return pat
    return None


# ---------------------------------------------------------------- 扫描

def find_memory_ai_dirs(scan_root, max_depth=4):
    """在扫描根下找 memory-ai 目录（跳过依赖/构建目录），返回其所在项目根列表。"""
    roots = []
    scan_root = Path(scan_root)
    base_depth = len(scan_root.parts)
    for cur, dirs, _files in os.walk(scan_root):
        cur_p = Path(cur)
        depth = len(cur_p.parts) - base_depth
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        if depth >= max_depth:
            dirs[:] = []
        if cur_p.name == "memory-ai" and (cur_p / "MEMORY.md").is_file():
            parent = cur_p.parent
            if parent not in roots:
                roots.append(parent)
            dirs[:] = []
    return roots


def resolve_project_root(start=None):
    """从当前目录往上找带 memory-ai/MEMORY.md 的项目根；找不到返回 None。

    口径：技能只清「你正在干的这个仓」，所以默认从 cwd 往上找，
    而不是掉头把整块盘扫一遍（别的仓不归这次清理管）。
    """
    cur = Path(start or os.getcwd()).resolve()
    for p in [cur] + list(cur.parents):
        ma = p / "memory-ai"
        if ma.is_dir() and (ma / "MEMORY.md").is_file():
            return p
    return None


def default_out_dir(today):
    """报告目录：优先落当前仓的 memory-ai/tmp，当前目录不在任何仓里就落系统临时目录。"""
    name = f"{OWN_TMP_PREFIX}{today.isoformat()}"
    here = resolve_project_root()
    if here is not None:
        return here / "memory-ai" / "tmp" / name
    return Path(tempfile.gettempdir()) / name


def scan_records(ma_dir):
    """列出 memory-ai 根目录下的正式记录（.md，排除索引本身）。"""
    out = []
    for p in sorted(ma_dir.iterdir()):
        if p.is_file() and p.suffix.lower() == ".md" and p.name.lower() != "memory.md":
            out.append(p)
    return out


def scan_tmp(ma_dir):
    """列出 tmp/ 下的残留（规则要求任务收尾必删，这里的都是没人认领的）。"""
    tmp = ma_dir / "tmp"
    if not tmp.is_dir():
        return []
    items = []
    for p in sorted(tmp.iterdir()):
        if p.name.startswith(OWN_TMP_PREFIX):   # 本轮报告目录，不算残留
            continue
        if p.is_dir():
            files = [q for q in p.rglob("*") if q.is_file()]
            items.append({"path": p, "is_dir": True,
                          "size_kb": round(sum(q.stat().st_size for q in files) / 1024, 1),
                          "file_count": len(files)})
        else:
            items.append({"path": p, "is_dir": False,
                          "size_kb": round(p.stat().st_size / 1024, 1), "file_count": 1})
    return items


def parse_index(ma_dir):
    """解析 MEMORY.md：返回 {链接名: 原行}、死链列表、重复链接。"""
    idx = ma_dir / "MEMORY.md"
    if not idx.is_file():
        return {"exists": False, "entries": {}, "dead": [], "dup": []}
    text = read_text(idx, 4 * 1024 * 1024)
    entries, dup = {}, []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("- ["):
            continue
        m = LINK_RE.search(s)
        if not m:
            continue
        target = norm_link(m.group(1))
        if re.match(r"^[a-zA-Z]+:", target):     # 外链，跳过
            continue
        fname = os.path.basename(target)
        if fname in entries:
            dup.append(fname)
        entries[fname] = s
    dead = [n for n in entries if not (ma_dir / n).is_file()]
    return {"exists": True, "size_kb": round(idx.stat().st_size / 1024, 1),
            "entries": entries, "dead": dead, "dup": dup}


def build_corpus(root, ma_dir):
    """收集项目内其他 md 正文，用于统计"被谁引用"；单文件上限 2MB，免得扫爆。"""
    corpus = []
    root = Path(root)
    for cur, dirs, files in os.walk(root):
        cur_p = Path(cur)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if not name.lower().endswith(".md"):
                continue
            p = cur_p / name
            if p.parent == ma_dir:      # 索引本身与被统计文件自己不算引用
                continue
            try:
                if p.stat().st_size > 2 * 1024 * 1024:
                    continue
            except OSError:
                continue
            corpus.append((p, read_text(p, 2 * 1024 * 1024)))
    return corpus


# ---------------------------------------------------------------- 判档

def classify(rec, cfg):
    """给单份记录定档。

    返回 (tier, action, reason)：
      action = delete（进删单）/ keep（留）/ ask（进待确认清单）

    判定顺序（顺序就是权重，别乱调）：
      保护名单 > 本仓专属档位 > 标题是资产类 > 空壳 > 超期流水 > 超期复盘 > 默认留
    "资产类优先"是关键：`发版规则-xxx` 这类标题同时含"发版"和"规则"，
    但它是给下一个人查的规矩，不是一次发版的流水账。
    """
    tiers = cfg.get("tiers", {})
    title = rec["title"]
    head = rec["head"][:1500]
    days = rec["days"]

    hit_protect = protected(rec, cfg)
    if hit_protect:
        return "资产", "keep", f"命中保护名单 {hit_protect}"

    custom = match_custom(rec, cfg.get("custom", []))
    if custom:
        act = custom.get("action", "ask")
        # 专属档位默认只给 keep/ask；要自动删必须配置里显式写 delete
        return custom.get("name", "专属"), act, f"命中专属档位（{','.join(custom.get('match', []))}）"

    hit_asset = ASSET_KW.search(title)
    if hit_asset:
        return "资产", "keep", f"标题属资产类（{hit_asset.group(1)}），长期留"

    # 空壳：正文极短、无代码块、也没写任何"能救下一个人"的东西
    if tiers.get("shell", {}).get("enabled", True) and len(rec["head"].strip()) < 300 \
            and rec["fences"] == 0 and not RICH_KW.search(head):
        return "空壳", "delete", f"正文仅 {len(rec['head'].strip())} 字，没留下任何东西"

    flow = bool(FLOW_KW.search(title))
    retro = bool(RETRO_KW.search(title))
    stale = bool(STALE_KW.search(title))

    for tier_id, tier_cn, hit, default_days in (
        ("flow", "流水", flow, 15),
        ("retro", "复盘", retro, 30),
        ("stale", "陈旧待办", stale, 15),
    ):
        if not hit or not tiers.get(tier_id, {}).get("enabled", True):
            continue
        limit = int(tiers.get(tier_id, {}).get("days", default_days))
        if days is None or days <= limit:
            continue
        rich = RICH_KW.search(head)
        if rich:
            # 流水里埋了干货 —— 自动删不得，进待确认清单让人一句话定
            return "四不像", "ask", f"{tier_cn}壳子但正文有干货（「{rich.group(1)}」），{days} 天"
        return tier_cn, "delete", f"一次性{tier_cn}，已 {days} 天 > {limit} 天"

    return "资产", "keep", "没有过期特征，先留"


def find_dups(recs):
    """同标题（去日期/括号）多份 → 除最新一份外标为重复候选，进待确认清单。"""
    groups = {}
    for r in recs:
        key = base_title(r["title"])
        if not key:
            continue
        groups.setdefault(key, []).append(r)
    dups = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda r: (r["date"] or "", r["name"]), reverse=True)
        for old in items[1:]:
            dups.append(old)
    return dups


# ---------------------------------------------------------------- 单仓体检

def scan_repo(root, today):
    root = Path(root)
    ma_dir = root / "memory-ai"
    cfg, warn = load_config(root)
    repo = {"root": str(root), "name": root.name, "warn": warn,
            "enabled": cfg.get("repo", {}).get("enabled", True),
            "has_config": (root / ".memory-ai-cleanup.toml").is_file()}
    if not repo["enabled"]:
        repo["records"], repo["tmp"], repo["index"] = [], [], {}
        repo["note"] = "配置里已停用本仓"
        return repo, cfg

    index = parse_index(ma_dir)
    corpus = build_corpus(root, ma_dir)
    recs = []
    for p in scan_records(ma_dir):
        text = read_text(p)
        d = file_date(p.name)
        name = p.name
        refs = sum(1 for cp, ctext in corpus
                   if cp.name != name and name[:-3] in ctext)
        recs.append({
            "name": name,
            "path": str(p),
            "kb": round(p.stat().st_size / 1024, 1),
            "date": d.isoformat() if d else "",
            "days": (today - d).days if d else None,
            "indexed": name in index["entries"],
            "refs": refs,
            "fences": len(re.findall(r"^```", text, re.M)) // 2,
            "title": title_of(text, p.stem),
            "head": text,
            "named_ok": bool(d),
        })

    for r in recs:
        tier, action, reason = classify(r, cfg)
        r["tier"], r["action"], r["reason"] = tier, action, reason
    for d in find_dups(recs):
        d["tier"], d["action"] = "重复", "ask"
        d["reason"] = "同主题有更新版本，可删旧的"

    repo["records"] = recs
    repo["tmp"] = scan_tmp(ma_dir)
    repo["index"] = {k: v for k, v in index.items() if k != "entries"}
    repo["index_entries"] = index["entries"]
    repo["orphans"] = [r["name"] for r in recs if not r["indexed"]]
    return repo, cfg


# ---------------------------------------------------------------- 报告

def build_asks(repos):
    """给"待你拍板"清单编号（报告里回 `1删` 靠这个号对上 apply --pick）。

    编号顺序必须和 render_report 里的遍历顺序一致，否则用户回的 1 会指向别的文件。
    """
    asks = []
    for repo in repos:
        for r in repo["records"]:
            if r["action"] != "ask":
                continue
            asks.append({
                "no": len(asks) + 1,
                "repo": repo["name"],
                "name": r["name"],
                "path": r["path"],
                "tier": r["tier"],
                "days": r["days"],
                "reason": r["reason"],
            })
    return asks


def age_txt(rec):
    """年龄文案：没有日期后缀的写"无日期"（这种只提示改名，不删）。"""
    return f"{rec['days']} 天" if rec.get("days") is not None else "无日期"


def render_report(repos, today, asks):
    """把体检结果渲染成给人看的 md：按仓分节，先概览后明细。"""
    lines = [f"# memory-ai 清理体检 — {today.isoformat()}", ""]
    total = {"rec": 0, "del": 0, "ask": 0, "keep": 0, "dead": 0, "tmp": 0}
    for repo in repos:
        if not repo["records"] and repo.get("note"):
            continue
        total["rec"] += len(repo["records"])
        total["del"] += sum(1 for r in repo["records"] if r["action"] == "delete")
        total["ask"] += sum(1 for r in repo["records"] if r["action"] == "ask")
        total["keep"] += sum(1 for r in repo["records"] if r["action"] == "keep")
        total["dead"] += len(repo["index"].get("dead", []))
        total["tmp"] += len(repo["tmp"])

    lines.append("## 概览")
    lines.append("")
    lines.append("| 仓库 | 记录 | 删 | 问你 | 留 | 索引死链 | tmp 残留 |")
    lines.append("|---|---|---|---|---|---|---|")
    for repo in repos:
        if not repo["records"] and repo.get("note"):
            continue
        n_del = sum(1 for r in repo["records"] if r["action"] == "delete")
        n_ask = sum(1 for r in repo["records"] if r["action"] == "ask")
        n_keep = sum(1 for r in repo["records"] if r["action"] == "keep")
        lines.append(f"| {repo['name']} | {len(repo['records'])} | {n_del} | {n_ask} | "
                     f"{n_keep} | {len(repo['index'].get('dead', []))} | {len(repo['tmp'])} |")
    lines.append("")
    lines.append(f"合计：{total['rec']} 篇 → 删 {total['del']} / 问你 {total['ask']} / "
                 f"留 {total['keep']}；死链 {total['dead']} 条；tmp 残留 {total['tmp']} 项")
    lines.append("")

    lines.append("## 待你拍板")
    lines.append("")
    for a in asks:
        advice = "建议删（同主题有更新版）" if a["tier"] == "重复" else "你扫一眼再定"
        lines.append(f"{a['no']}. `{a['repo']}/{a['name']}`（{a['tier']}，{age_txt(a)}）"
                     f" — {a['reason']}。{advice}：回 **{a['no']}删** 或 **{a['no']}留**")
    if not asks:
        lines.append("（本轮没有需要你判断的，全部按规则自动处理）")
    lines.append("")

    lines.append("## 明细（按仓）")
    lines.append("")
    for repo in repos:
        if not repo["records"] and not repo["tmp"] and repo.get("note") is None:
            continue
        lines.append(f"### {repo['name']}")
        if repo.get("note"):
            lines.append(f"- {repo['note']}")
            lines.append("")
            continue
        if repo.get("warn"):
            lines.append(f"- ⚠ {repo['warn']}")
        for r in sorted(repo["records"], key=lambda x: (x["action"] != "delete", -(x["days"] or -1))):
            mark = {"delete": "删", "ask": "问", "keep": "留"}[r["action"]]
            named = "" if r["named_ok"] else "　⚠ 文件名缺日期后缀，只在报告里提示、不改名"
            lines.append(f"- {mark} `{r['name']}` {r['kb']}KB {age_txt(r)} — "
                         f"{r['tier']}：{r['reason']}{named}")
        for t in repo["tmp"]:
            lines.append(f"- 删 `tmp/{Path(t['path']).name}` {t['size_kb']}KB（tmp 残留）")
        dead = repo["index"].get("dead", [])
        if dead:
            lines.append(f"- 摘链 {len(dead)} 条：{('、'.join(dead[:5]))}"
                         f"{' 等' if len(dead) > 5 else ''}")
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="memory-ai 清理 · 只读体检（默认只查当前仓库）")
    ap.add_argument("--all", "--discover", dest="all_roots", action="append", default=[],
                    metavar="扫描根", help="跨仓模式：在该根下自动找所有 memory-ai 目录；不给就只查当前仓库")
    ap.add_argument("--roots", action="append", default=[], help="项目根（含 memory-ai 的那层）")
    ap.add_argument("--out", help="报告输出目录")
    ap.add_argument("--today", help="按哪天算天数，默认今天")
    args = ap.parse_args(argv)

    today = datetime.date.fromisoformat(args.today) if args.today else datetime.date.today()

    roots = [Path(r) for r in args.roots]
    for base in args.all_roots:
        roots.extend(find_memory_ai_dirs(base))

    # 口径：默认只清「你正在干的这个仓」，不给 --all 就不许回头看别的仓
    if not roots and not args.all_roots:
        here = resolve_project_root()
        if here is None:
            print("当前目录及上层找不到 memory-ai/MEMORY.md —— 本技能默认只清当前仓库；"
                  "要跨仓请显式加 --all <扫描根>")
            return 2
        roots = [here]

    roots = list(dict.fromkeys(roots))     # 去重保序
    if not roots:
        print("no memory-ai dir found")
        return 2

    repos = []
    for root in roots:
        repo, _cfg = scan_repo(root, today)
        repos.append(repo)

    asks = build_asks(repos)
    out_dir = Path(args.out) if args.out else default_out_dir(today)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(render_report(repos, today, asks), encoding="utf-8")
    plan = {"today": today.isoformat(), "out_dir": str(out_dir), "repos": repos, "ask": asks}
    (out_dir / "report.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    n_del = sum(1 for rp in repos for r in rp["records"] if r["action"] == "delete")
    n_ask = sum(1 for rp in repos for r in rp["records"] if r["action"] == "ask")
    scope = "all" if args.all_roots else ("roots" if args.roots else "current")
    print(f"scope={scope} repos={len(repos)} delete={n_del} ask={n_ask} out={out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
