#!/usr/bin/env python3
"""campus-life 结构化查询工具。

修复的核心问题：SKILL.md 原本教 Agent 用 `grep -rl "不断"` 做反向筛选。
字面命中率看似很高，但「不断电」既会命中真正不断电的学校，也会命中同一
文件里说「会断电」的回答——3,449 个活跃文件里 284 个同时含这两种说法。
行级匹配无法区分「这所学校不断电」和「这所学校有人提到断电」。

本工具改为：先定位问题区块 → 逐条解析回答 → 做极性分类 → 按校区/年份归组
输出，并把「分化/分校区」单独标出。极性判定已独立到 `polarity.py`，按 25
个问题各自的语义规格判定（而不是通用词表），详见该模块文档。

用法：
    # 单校
    python3 tools/query.py 北邮 --q 断电
    python3 tools/query.py 北京邮电大学 --q all --json

    # 跨校对比
    python3 tools/query.py --compare 北邮 华科 --q 空调

    # 反向筛选：哪些学校不断电
    python3 tools/query.py --reverse 断电 --polarity no --limit 20
    python3 tools/query.py --reverse 独立卫浴 --polarity yes --min-yes 3

    # 极性判定回归样例（离线，不读数据）
    python3 tools/query.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import polarity
from polarity import classify  # 兼容旧调用：query.classify(text) 走通用规格

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "references"
ACTIVE_DIR = REF / "universities"
ARCHIVE_DIR = REF / "archived" / "universities"
INDEX = REF / "index.md"
ARCHIVE_INDEX = REF / "archived" / "index.md"
ALIASES = REF / "aliases.md"

# ---------------------------------------------------------------------------
# 25 个标准问题的关键词路由表（问题语义规格见 polarity.py）
# ---------------------------------------------------------------------------
CANONICAL_HEADINGS = list(polarity.CANONICAL_HEADINGS)
N_QUESTIONS = polarity.N_QUESTIONS
QUESTIONS: list[tuple[int, str, tuple[str, ...]]] = [
    (s.qid, s.heading(), polarity.KEYWORDS[s.qid]) for s in polarity.SPECS
]


def _norm_heading(heading: str) -> str:
    """规范化区块标题：去掉 `Q:` 前缀与结尾问号，便于精确比较。"""
    h = heading.strip()
    if h.startswith("Q:"):
        h = h[2:]
    return h.strip().rstrip("？?").strip()


def load_index(path: Path) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] in ("学校名", "别名 / 简称"):
            continue
        if set(cells[0]) <= set("-: "):
            continue
        rows.append((cells[0], cells[1], cells[2]))
    return rows


def load_aliases(path: Path = ALIASES) -> dict[str, tuple[str, str]]:
    """别名 -> (学校名, 文件名)。

    这里用 setdefault 处理重复别名；别名表的唯一性由 build_aliases.py 保证、
    并由 verify.py 强制检查（重复别名会让 verify.py 失败），因此不会静默取错。
    """
    out: dict[str, tuple[str, str]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0] in ("别名 / 简称", "简称"):
            continue
        if set(cells[0]) <= set("-: "):
            continue
        out.setdefault(cells[0], (cells[1], cells[3]))
    return out


def load_ambiguous(path: Path = ALIASES) -> dict[str, tuple[str, ...]]:
    """读取 aliases.md 末尾的「歧义简称」小表：简称 -> 候选学校名。

    该表由 build_aliases.py 生成，是两列表格（简称 | 候选学校），不会被
    load_aliases 的 4 列解析误收。解析不到时返回空字典。
    """
    out: dict[str, tuple[str, ...]] = {}
    if not path.exists():
        return out
    in_section = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_section = "歧义" in line
            continue
        if not in_section or not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0] == "简称" or set(cells[0]) <= set("-: "):
            continue
        names = tuple(n for n in re.split(r"[；;、,，]", cells[1]) if n)
        if len(names) >= 2:
            out[cells[0]] = names
    return out


def resolve(query: str, aliases: dict[str, tuple[str, str]],
            active: list[tuple[str, str, str]], archived: list[tuple[str, str, str]],
            ambiguous: dict[str, tuple[str, ...]] | None = None) -> list[dict]:
    """把用户输入（全称/简称/文件名）解析为候选学校。

    顺序**有意**为先歧义词、后唯一别名、最后全称（与 SKILL.md 第 0 步一致）：
    唯一别名表由 build_aliases.py 保证「任何别名的文字都不等于另一所真实学校
    全称」，因此不会劫持全称查询；少数指向「上游简称占位条目」的别名（如
    「川农」「东华理工」）正是要优先命中真实学校。歧义简称（地大/华师/华农/
    中国地质大学/中国石油大学）不猜学校，直接返回多个候选交由调用方提示澄清。
    该不变式由 build_aliases.py 的兜底与 verify.py 的别名检查共同守护。
    """
    q = query.strip()
    if ambiguous and q in ambiguous:
        cands: list[dict] = []
        for name in ambiguous[q]:
            for src, rows in (("active", active), ("archived", archived)):
                hit = next(((n, f) for n, _p, f in rows if n == name), None)
                if hit:
                    cands.append({"name": name, "file": hit[1], "source": src,
                                  "matched": q})
                    break
        if len(cands) >= 2:
            return cands
    if q in aliases:
        name, f = aliases[q]
        return [{"name": name, "file": f, "source": "active", "matched": q}]

    for src, rows in (("active", active), ("archived", archived)):
        for name, _prov, f in rows:
            if q == name or q == f or q == f[:-3]:
                return [{"name": name, "file": f, "source": src, "matched": name}]

    hits = []
    for src, rows in (("active", active), ("archived", archived)):
        for name, _prov, f in rows:
            if q and (q in name or q in f):
                hits.append({"name": name, "file": f, "source": src, "matched": name})
    # 精确子串优先，且优先活跃库
    hits.sort(key=lambda h: (h["source"] != "active", len(h["name"])))
    return hits


# ---------------------------------------------------------------------------
# 文件解析
# ---------------------------------------------------------------------------
# 只吃掉行内空白，不能用 `\s*`：空回答后紧跟空行时 `\s*` 会跨行吞掉下一条
# 回答行，导致该条被并入上一条、回答总数偏少。
# 前缀 `- ` 可选：25 个问题区块用 `- A123: …`，「自由补充部分」用裸 `A123: …`。
ANSWER_RE = re.compile(r"^(?:- )?(A\d+):[ \t]*(.*)$")


def parse_school(path: Path) -> dict:
    """解析为 {meta, blocks:[{heading, answers:[{id,text}]}], extra}"""
    text = path.read_text(encoding="utf-8")
    head, _, body = text.partition("\n## ")

    dates: dict[str, str] = {}
    for aid, ident, date in re.findall(
        r"<li>(A\d+):\s*(.*?)\s*\(([^)]*)\)</li>", head
    ):
        dates[aid] = date.strip()

    blocks: list[dict] = []
    for chunk in ("## " + body).split("\n## "):
        chunk = chunk.strip()
        if not chunk:
            continue
        lines = chunk.splitlines()
        heading = lines[0].lstrip("# ").strip()
        answers = []
        for line in lines[1:]:
            m = ANSWER_RE.match(line.strip())
            if m:
                answers.append({"id": m.group(1), "text": m.group(2).strip()})
        blocks.append({"heading": heading, "answers": answers})
    return {"dates": dates, "blocks": blocks}


def match_questions(blocks: list[dict], spec: str) -> list[dict]:
    """按关键词/编号/all 选出问题区块。

    编号（`--q 1`…`--q 25`）按 CANONICAL_HEADINGS 精确匹配，且只返回该一个问题；
    关键词则按 QUESTIONS 的关键词路由（可能命中多个区块，属预期）。
    编号越界返回空列表，由调用方给出明确报错。
    """
    if spec == "all":
        return blocks
    if spec.isdigit():
        n = int(spec)
        if not 1 <= n <= N_QUESTIONS:
            return []
        want = _norm_heading(CANONICAL_HEADINGS[n - 1])
        return [b for b in blocks if _norm_heading(b["heading"]) == want]
    picked: list[dict] = []
    keys: set[str] = {spec}
    for _qn, _title, kw in QUESTIONS:
        if spec in _title or spec in kw or any(spec in k for k in kw):
            keys.update(kw)
            keys.add(_title)
    for b in blocks:
        if any(k in b["heading"] for k in keys):
            picked.append(b)
    return picked


def summarize(answers: list[dict], dates: dict[str, str], spec: polarity.Spec) -> dict:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for a in answers:
        pol = polarity.classify(a["text"], spec)
        buckets[pol].append({**a, "date": dates.get(a["id"], "")})
    year_hist = Counter((dates.get(a["id"], "")[:4] or "未知") for a in answers)
    return {
        "total": len(answers),
        "counts": {k: len(v) for k, v in buckets.items()},
        "yes": buckets.get("yes", []),
        "no": buckets.get("no", []),
        "mixed": buckets.get("mixed", []),
        "unknown": buckets.get("unknown", []),
        "years": dict(sorted(year_hist.items())),
    }


def render_question(qa: dict, limit: int, show: tuple[str, ...],
                    spec: polarity.Spec) -> str:
    s = qa["summary"]
    out = [f"### {qa['heading']}"]
    parts = " / ".join(f"{k}={v}" for k, v in sorted(s["counts"].items()))
    out.append(f"共 {s['total']} 条回答（{parts or '无'}）")
    if spec.ex_yes or spec.ex_no or spec.yes or spec.no:
        out.append(f"判定口径：yes = 「{spec.yes_label}」，no = 「{spec.no_label}」")
    if s["years"]:
        out.append("年份分布：" + "，".join(f"{y} 年 {n} 条" for y, n in s["years"].items()))
    labels = {
        "yes": f"倾向肯定（{spec.yes_label}）",
        "no": f"倾向否定（{spec.no_label}）",
        "mixed": "分化 / 分校区差异",
        "unknown": "其他 / 无法归类",
    }
    for key in show:
        items = s.get(key) or []
        if not items:
            continue
        out.append(f"\n**{labels[key]}**（{len(items)} 条）")
        for it in items[:limit]:
            date = f"（{it['date']}）" if it["date"] else ""
            out.append(f"- {it['id']}{date}: {it['text']}")
        if len(items) > limit:
            out.append(f"- … 其余 {len(items) - limit} 条同类回答略")
    return "\n".join(out)


def _no_match_message(school: str, spec: str) -> str:
    if spec.isdigit() and not (1 <= int(spec) <= N_QUESTIONS):
        return f"--q 编号 {spec} 越界，请输入 1-{N_QUESTIONS}，或改用问题关键词"
    return f"在 {school} 中未匹配到问题「{spec}」"


def _is_ambiguous(school: str, cands: list[dict]) -> bool:
    """候选多于一个且首个不是查询字面本身 → 需要用户澄清。"""
    return len(cands) > 1 and cands[0]["name"] != school


def _print_ambiguous(school: str, cands: list[dict]) -> None:
    print(f"「{school}」可能指多所学校，请用更完整的名称：", file=sys.stderr)
    seen: set[str] = set()
    for c in cands:
        if c["name"] in seen:
            continue
        seen.add(c["name"])
        print(f"  - {c['name']}（{c['source']}）", file=sys.stderr)
        if len(seen) >= 10:
            break


def cmd_single(args, aliases, active, archived, ambiguous) -> int:
    cands = resolve(args.school[0], aliases, active, archived, ambiguous)
    if not cands:
        print(f"未找到学校：{args.school[0]}", file=sys.stderr)
        return 2
    if _is_ambiguous(args.school[0], cands):
        _print_ambiguous(args.school[0], cands)
        return 2

    c = cands[0]
    base = ACTIVE_DIR if c["source"] == "active" else ARCHIVE_DIR
    path = base / c["file"]
    if not path.exists():
        print(f"索引指向的文件不存在：{path}", file=sys.stderr)
        return 2
    data = parse_school(path)
    blocks = match_questions(data["blocks"], args.q)
    if not blocks:
        print(_no_match_message(c["name"], args.q), file=sys.stderr)
        return 2

    result = {
        "school": c["name"],
        "file": str(path.relative_to(ROOT)),
        "source": c["source"],
        "alias_used": c.get("matched"),
        "questions": [
            {"heading": b["heading"],
             "summary": summarize(b["answers"], data["dates"],
                                    polarity.spec_for_heading(b["heading"]))}
            for b in blocks
        ],
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    header = f"# {c['name']}"
    if c["source"] == "archived":
        header += "（归档数据：2023 年前，条件可能已过时）"
    print(header)
    print(f"数据文件：{result['file']}")
    print()
    for b in blocks:
        qa = {"heading": b["heading"],
              "summary": summarize(b["answers"], data["dates"],
                                     polarity.spec_for_heading(b["heading"]))}
        print(render_question(qa, args.limit, tuple(args.show),
                              polarity.spec_for_heading(b["heading"])))
        print()
    return 0


def cmd_compare(args, aliases, active, archived, ambiguous) -> int:
    payload = []
    errors = 0
    for school in args.compare:
        cands = resolve(school, aliases, active, archived, ambiguous)
        if not cands:
            print(f"未找到学校：{school}", file=sys.stderr)
            errors += 1
            continue
        if _is_ambiguous(school, cands):
            _print_ambiguous(school, cands)
            errors += 1
            continue
        c = cands[0]
        base = ACTIVE_DIR if c["source"] == "active" else ARCHIVE_DIR
        path = base / c["file"]
        if not path.exists():
            print(f"索引指向的文件不存在：{path}", file=sys.stderr)
            errors += 1
            continue
        data = parse_school(path)
        blocks = match_questions(data["blocks"], args.q)
        if not blocks:
            print(_no_match_message(c["name"], args.q), file=sys.stderr)
            errors += 1
            continue
        payload.append({
            "school": c["name"],
            "source": c["source"],
            "file": str(path.relative_to(ROOT)),
            "questions": [
                {"heading": b["heading"],
                 "summary": summarize(b["answers"], data["dates"],
                                        polarity.spec_for_heading(b["heading"]))}
                for b in blocks
            ],
        })
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2 if errors else 0
    for item in payload:
        print(f"# {item['school']}" + ("（归档数据）" if item["source"] == "archived" else ""))
        for q in item["questions"]:
            print(render_question(q, args.limit, tuple(args.show),
                                  polarity.spec_for_heading(q["heading"])))
            print()
        print("-" * 60)
    return 2 if errors else 0


def _aggregate_hits(hits: list[dict]) -> list[dict]:
    """把同一学校在多个目标问题上的命中合并为一行。

    关键词可能同时命中多个问题（如「宿舍」→ 7 个问题），若不合并，同一学校会
    重复出现多次，且「命中 N 所学校」会按行数虚高（实测 15176 行对应 3424 所）。
    合并后 yes/no/mixed/total 为各目标问题上的计数之和，`dims` 为命中问题数。
    """
    agg: dict[tuple[str, str], dict] = {}
    for h in hits:
        key = (h["source"], h["school"])
        row = agg.get(key)
        if row is None:
            row = {"school": h["school"], "province": h["province"],
                   "source": h["source"], "file": h["file"],
                   "yes": 0, "no": 0, "mixed": 0, "total": 0, "questions": []}
            agg[key] = row
        row["yes"] += h["yes"]
        row["no"] += h["no"]
        row["mixed"] += h["mixed"]
        row["total"] += h["total"]
        row["questions"].append(h["heading"])
    out = list(agg.values())
    for row in out:
        row["dims"] = len(row["questions"])
    return out


def _polarity_want(pol: str, specs: list[polarity.Spec]) -> str:
    """输出「倾向某极性」的人话说明；mixed 不再复用 no_label。"""
    if pol == "mixed":
        return "分化 / 分校区差异"
    labels = ((s.yes_label if pol == "yes" else s.no_label) for s in specs)
    return "、".join(dict.fromkeys(labels))


def cmd_reverse(args, aliases, active, archived) -> int:
    """反向筛选：扫描全部学校，对目标问题做极性统计后筛选。"""
    # 目标区块：编号直接用规范标题；关键词用第一个可读的活跃文件做探针。
    # 不再无条件用 active[0]——空索引、缺文件或该文件缺区块都会让整轮扫描静默失真。
    if args.reverse.isdigit():
        n = int(args.reverse)
        if not 1 <= n <= N_QUESTIONS:
            print(f"--reverse 编号 {n} 越界，请输入 1-{N_QUESTIONS}，或改用问题关键词",
                  file=sys.stderr)
            return 2
        target_headings = {CANONICAL_HEADINGS[n - 1]}
    else:
        probe_file = next(
            (ACTIVE_DIR / f for _n, _p, f in active if (ACTIVE_DIR / f).exists()), None
        )
        if probe_file is None:
            print("活跃库为空或索引中的文件缺失，无法解析关键词", file=sys.stderr)
            return 2
        probe_blocks = match_questions(parse_school(probe_file)["blocks"], args.reverse)
        if not probe_blocks:
            print(f"关键词「{args.reverse}」无法定位到任何标准问题区块；"
                  f"请改用 1-25 编号或 25 问关键词。", file=sys.stderr)
            return 2
        target_headings = {b["heading"] for b in probe_blocks}
    targets = {_norm_heading(h) for h in target_headings}
    target_specs = list({s.qid: s for s in
                         (polarity.spec_for_heading(h) for h in sorted(target_headings))}.values())

    hits = []
    for rows, base, src in ((active, ACTIVE_DIR, "active"), (archived, ARCHIVE_DIR, "archived")):
        if not args.include_archived and src == "archived":
            continue
        for name, prov, fname in rows:
            path = base / fname
            try:
                data = parse_school(path)
            except OSError:
                continue
            for b in data["blocks"]:
                if _norm_heading(b["heading"]) not in targets:
                    continue
                s = summarize(b["answers"], data["dates"],
                              polarity.spec_for_heading(b["heading"]))
                n_yes = s["counts"].get("yes", 0)
                n_no = s["counts"].get("no", 0)
                n_mixed = s["counts"].get("mixed", 0)
                ok = False
                if args.polarity == "yes":
                    ok = n_yes >= max(args.min_yes, 1) and n_yes > n_no
                elif args.polarity == "no":
                    ok = n_no >= max(args.min_yes, 1) and n_no > n_yes
                elif args.polarity == "mixed":
                    ok = n_mixed > 0
                if ok:
                    hits.append({
                        "school": name, "province": prov, "source": src, "file": fname,
                        "heading": b["heading"],
                        "yes": n_yes, "no": n_no, "mixed": n_mixed, "total": s["total"],
                    })
    hits = _aggregate_hits(hits)

    def rank(h: dict) -> tuple:
        if args.polarity == "mixed":
            return (-h["mixed"], h["school"])
        if args.polarity == "no":
            return (-h["no"], h["school"])
        return (-h["yes"], h["school"])

    hits.sort(key=rank)
    if args.json:
        print(json.dumps({"keyword": args.reverse, "polarity": args.polarity,
                          "count": len(hits), "results": hits[: args.limit]},
                         ensure_ascii=False, indent=2))
        return 0

    want = _polarity_want(args.polarity, target_specs)
    print(f"# 反向筛选：{args.reverse} → 倾向「{args.polarity}：{want}」")
    print(f"命中 {len(hits)} 所学校（按证据强度排序，最多显示 {args.limit} 所）")
    print()
    print("| 学校 | 省份 | 肯定 | 否定 | 分化 | 总回答 | 命中维度 | 来源 |")
    print("|---|---|---|---|---|---|---|---|")
    for h in hits[: args.limit]:
        src = "归档" if h["source"] == "archived" else "活跃"
        print(f"| {h['school']} | {h['province']} | {h['yes']} | {h['no']} | "
              f"{h['mixed']} | {h['total']} | {h['dims']} | {src} |")
    if len(hits) > args.limit:
        print(f"\n（其余 {len(hits) - args.limit} 所略，可用 --limit 调整）")
    print("\n> 肯定/否定为按回答逐条分类的计数；「分化」表示同校存在分校区或年份差异，")
    print("> 建议对入围学校用 `--q` 读取原文后再下结论。")
    return 0


def run_selftest() -> int:
    """跑极性判定回归样例；不读取数据文件，可离线执行。

    样例定义在 `polarity.SELFTEST_CASES`（每条带所属问题编号），完整回归在
    `tests/test_polarity.py`。
    """
    cases = polarity.SELFTEST_CASES
    bad = 0
    for qid, text, want in cases:
        got = polarity.classify(text, polarity.spec_for_qid(qid))
        if got != want:
            bad += 1
        flag = "ok  " if got == want else "FAIL"
        print(f"  [{flag}] Q{qid:02d} {text!r:44} want={want:7} got={got}")
    print(f"== polarity 回归：{len(cases) - bad}/{len(cases)} 通过 ==")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="大学生活质量结构化查询")
    ap.add_argument("school", nargs="*", help="学校名 / 简称 / 文件名")
    ap.add_argument("--q", default="all", help="问题关键词或 1-25 编号，默认 all")
    ap.add_argument("--compare", nargs="+", metavar="SCHOOL", help="跨校对比")
    ap.add_argument("--reverse", metavar="KEYWORD", help="反向筛选关键词")
    ap.add_argument("--polarity", choices=("yes", "no", "mixed"), default="yes",
                    help="反向筛选目标极性，默认 yes")
    ap.add_argument("--min-yes", type=int, default=1,
                    help="反向筛选中该极性回答的最少条数（默认 1）")
    ap.add_argument("--limit", type=int, default=5, help="每类最多展示条数（默认 5）")
    ap.add_argument("--show", nargs="+", default=["yes", "no", "mixed", "unknown"],
                    choices=("yes", "no", "mixed", "unknown"), help="展示哪些分类")
    ap.add_argument("--include-archived", action="store_true", help="反向筛选时包含归档库")
    ap.add_argument("--selftest", action="store_true", help="运行极性判定回归样例后退出")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    if args.selftest:
        return run_selftest()

    aliases = load_aliases()
    ambiguous = load_ambiguous()
    active = load_index(INDEX)
    archived = load_index(ARCHIVE_INDEX)

    if args.reverse:
        return cmd_reverse(args, aliases, active, archived)
    if args.compare:
        return cmd_compare(args, aliases, active, archived, ambiguous)
    if not args.school:
        ap.print_help()
        return 2
    return cmd_single(args, aliases, active, archived, ambiguous)


if __name__ == "__main__":
    sys.exit(main())
