#!/usr/bin/env python3
"""campus-life 问题查询 CLI（SQLite 后端，唯一查询入口）。

数据真源是 data/ 的上游 markdown 镜像；本工具查询 data/index.sqlite
（由 tools/build_db.py 构建，回答的极性判定在构建期算好）。功能：

    # 单校单维度（维度 = 问题编号 1-25 或问题关键词）
    python3 tools/query.py 北邮 --q 断电
    python3 tools/query.py 北京邮电大学 --q all --json

    # 跨校对比
    python3 tools/query.py --compare 北邮 华科 电子科技大学 --q 空调

    # 反向筛选：按生活条件找学校
    python3 tools/query.py --reverse 断电 --polarity no --limit 20
    python3 tools/query.py --reverse 独立卫浴 --polarity yes --min-yes 3

    # 按省份浏览 / 数据来源
    python3 tools/query.py --province 广东
    python3 tools/query.py --sources 北邮

    # 极性判定回归样例（离线）
    python3 tools/query.py --selftest

退出码：0 正常；2 参数 / 解析问题（未找到学校、歧义简称、无匹配维度等）。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import build_db
import polarity

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "index.sqlite"

N_QUESTIONS = polarity.N_QUESTIONS
FREEFORM_QID = 0
POLARITIES = ("yes", "no", "mixed", "unknown")


# ---------------------------------------------------------------------------
# 连接与解析
# ---------------------------------------------------------------------------
def connect(db: Path = DB_PATH) -> sqlite3.Connection:
    if not db.exists():
        raise SystemExit(f"数据库不存在：{db}，请先运行 python3 tools/build_db.py")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


def resolve(conn: sqlite3.Connection, q: str) -> tuple[list[dict], list[str]]:
    """把用户说法解析到学校 → (候选列表, 歧义候选)。

    优先级：唯一别名 → 校名 / 文件名子串。子串命中多校时，只有当查询字面
    本身是首位候选的全名（活跃库优先、同库短名优先）才直接选定；否则当作
    歧义列出候选，绝不猜。
    """
    q = q.strip()

    rows = conn.execute(
        "SELECT s.id, s.name, s.province, s.file, s.kind FROM aliases a"
        " JOIN schools s ON s.id = a.school_id WHERE a.alias = ?"
        " ORDER BY s.kind, s.file", (q,)).fetchall()
    if len(rows) > 1:
        return [], [r["name"] for r in rows]
    if rows:
        return [dict(rows[0])], []

    rows = conn.execute(
        "SELECT id, name, province, file, kind FROM schools"
        " WHERE name LIKE ? OR title LIKE ? OR file = ?"
        " ORDER BY (kind != 'active'), LENGTH(name), name",
        (f"%{q}%", f"%{q}%", f"{q}.md")).fetchall()
    hits = [dict(r) for r in rows]
    exact = [h for h in hits if h["name"] == q]
    if exact:
        # 全名全等命中不是猜：返回它；其余子串候选作为提示随行输出
        return exact + [h for h in hits if h["name"] != q], []
    if len(hits) > 1:
        return [], [h["name"] for h in hits]
    return hits, []


def match_qids(spec: str) -> list[int] | None:
    """--q 维度 → 问题编号列表；无法定位返回 None。

    数字按 1-25 精确匹配单个问题；关键词按问题标题与关键词路由（可能命中
    多个问题，属预期）；`all` 返回全部 25 题。
    """
    if spec == "all":
        return list(range(1, N_QUESTIONS + 1))
    if spec.isdigit():
        n = int(spec)
        return [n] if 1 <= n <= N_QUESTIONS else None
    keys = {spec}
    for qid, kws in polarity.KEYWORDS.items():
        heading = polarity.spec_for_qid(qid).heading()
        if spec in heading or any(spec in k or k in spec for k in kws):
            keys.update(kws)
            keys.add(heading)
    picked = []
    for qid in range(1, N_QUESTIONS + 1):
        heading = polarity.spec_for_qid(qid).heading()
        if any(k in heading for k in keys):
            picked.append(qid)
    return picked or None


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------
def fetch_answers(conn: sqlite3.Connection, school_id: int,
                  qid: int) -> list[dict]:
    rows = [dict(r) for r in conn.execute(
        "SELECT aid, seq, date, body, polarity FROM answers"
        " WHERE school_id = ? AND qid = ? ORDER BY seq", (school_id, qid))]
    for r in rows:
        r["aid"] = build_db.fmt_aid(r["aid"])
        r["date"] = build_db.fmt_date(r["date"])
    return rows


def summarize(rows: list[dict]) -> dict:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        buckets[r["polarity"]].append(r)
    years: dict[str, int] = defaultdict(int)
    for r in rows:
        years[(r["date"] or "")[:4] or "未知"] += 1
    return {
        "total": len(rows),
        "counts": {k: len(v) for k, v in sorted(buckets.items())},
        "buckets": {k: buckets.get(k, []) for k in POLARITIES},
        "years": dict(sorted(years.items())),
    }


LABELS = {
    "yes": "倾向肯定（{yes}）",
    "no": "倾向否定（{no}）",
    "mixed": "分化 / 分校区差异",
    "unknown": "其他 / 无法归类",
}


def render_question(qid: int, rows: list[dict], limit: int,
                    show: tuple[str, ...]) -> str:
    spec = polarity.spec_for_qid(qid) if qid else polarity.FREE
    s = summarize(rows)
    out = [f"### {spec.heading()}"]
    parts = " / ".join(f"{k}={v}" for k, v in s["counts"].items())
    out.append(f"共 {s['total']} 条回答（{parts or '无'}）")
    if spec.ex_yes or spec.ex_no or spec.yes or spec.no:
        out.append(f"判定口径：yes = 「{spec.yes_label}」，no = 「{spec.no_label}」")
    if s["years"]:
        out.append("年份分布：" + "，".join(f"{y} 年 {n} 条"
                                          for y, n in s["years"].items()))
    for key in show:
        items = s["buckets"].get(key) or []
        if not items:
            continue
        label = LABELS[key]
        if "{yes}" in label:
            label = label.format(yes=spec.yes_label)
        elif "{no}" in label:
            label = label.format(no=spec.no_label)
        out.append(f"\n**{label}**（{len(items)} 条）")
        for it in items[:limit]:
            date = f"（{it['date']}）" if it["date"] else ""
            out.append(f"- {it['aid']}{date}: {it['body']}")
        if len(items) > limit:
            out.append(f"- … 其余 {len(items) - limit} 条同类回答略")
    return "\n".join(out)


def question_payload(qid: int, rows: list[dict]) -> dict:
    spec = polarity.spec_for_qid(qid) if qid else polarity.FREE
    s = summarize(rows)
    return {
        "qid": qid,
        "heading": spec.heading(),
        "total": s["total"],
        "counts": s["counts"],
        "years": s["years"],
        "answers": [{"id": r["aid"], "date": r["date"], "text": r["body"],
                     "polarity": r["polarity"]} for r in rows],
    }


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------
def _pick(conn: sqlite3.Connection, name: str) -> tuple[dict | None, int]:
    """解析学校名；歧义 / 未找到时打印说明并返回 (None, 退出码)。"""
    hits, ambiguous = resolve(conn, name)
    if ambiguous:
        print(f"「{name}」可能指多所学校，请用更完整的名称：", file=sys.stderr)
        for cand in dict.fromkeys(ambiguous):
            print(f"  - {cand}", file=sys.stderr)
        return None, 2
    if not hits:
        print(f"未找到学校：{name}", file=sys.stderr)
        return None, 2
    # 候选顺序已由 resolve 定好（全名全等优先、活跃库优先、短名优先）
    extra = list(dict.fromkeys(h["name"] for h in hits[1:]
                               if h["name"] != hits[0]["name"]))
    if extra:
        shown = "、".join(extra)
        if len(shown) > 80:
            shown = shown[:80] + "…"
        print(f"（另有 {len(extra)} 个名称包含「{name}」的候选：{shown}）",
              file=sys.stderr)
    return hits[0], 0


def cmd_single(conn: sqlite3.Connection, args) -> int:
    school, code = _pick(conn, args.school[0])
    if school is None:
        return code
    qids = match_qids(args.q)
    if not qids:
        if args.q.isdigit():
            print(f"--q 编号 {args.q} 越界，请输入 1-{N_QUESTIONS}，"
                  f"或改用问题关键词", file=sys.stderr)
        else:
            print(f"在 {school['name']} 中未匹配到问题「{args.q}」", file=sys.stderr)
        return 2

    blocks = [(qid, fetch_answers(conn, school["id"], qid)) for qid in qids]
    freeform = fetch_answers(conn, school["id"], FREEFORM_QID)

    if args.json:
        payload = {
            "school": school["name"],
            "source": school["kind"],
            "file": school["file"],
            "questions": [question_payload(qid, rows) for qid, rows in blocks],
        }
        if freeform:
            payload["freeform"] = [
                {"id": r["aid"], "date": r["date"], "text": r["body"]}
                for r in freeform]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"# {school['name']}"
          + ("（归档数据：2023 年前，条件可能已过时）"
             if school["kind"] == "archived" else ""))
    print(f"数据文件：data/{school['file']}｜省份：{school['province']}")
    for qid, rows in blocks:
        print()
        print(render_question(qid, rows, args.limit, tuple(args.show)))
    if freeform and "unknown" in args.show:
        print()
        print(f"### 自由补充部分（{len(freeform)} 条，不作极性判定）")
        for r in freeform[:args.limit]:
            date = f"（{r['date']}）" if r["date"] else ""
            print(f"- {r['aid']}{date}: {r['body']}")
        if len(freeform) > args.limit:
            print(f"- … 其余 {len(freeform) - args.limit} 条略")
    return 0


def cmd_compare(conn: sqlite3.Connection, args) -> int:
    qids = match_qids(args.q)
    if not qids:
        print(f"--q 无法定位问题「{args.q}」，请用 1-{N_QUESTIONS} 编号或问题关键词",
              file=sys.stderr)
        return 2
    errors = 0
    for name in args.compare:
        school, code = _pick(conn, name)
        if school is None:
            errors += code or 2
            continue
        print(f"# {school['name']}"
              + ("（归档数据）" if school["kind"] == "archived" else ""))
        for qid in qids:
            rows = fetch_answers(conn, school["id"], qid)
            print(render_question(qid, rows, args.limit, tuple(args.show)))
            print()
        print("-" * 60)
    return 2 if errors else 0


def _polarity_want(pol: str, qids: list[int]) -> str:
    if pol == "mixed":
        return "分化 / 分校区差异"
    labels = []
    for qid in qids:
        spec = polarity.spec_for_qid(qid)
        labels.append(spec.yes_label if pol == "yes" else spec.no_label)
    return "、".join(dict.fromkeys(labels))


def cmd_reverse(conn: sqlite3.Connection, args) -> int:
    if args.reverse.isdigit():
        qids = match_qids(args.reverse)
        if not qids:
            print(f"--reverse 编号 {args.reverse} 越界，请输入 1-{N_QUESTIONS}，"
                  f"或改用问题关键词", file=sys.stderr)
            return 2
    else:
        qids = match_qids(args.reverse)
        if not qids:
            print(f"关键词「{args.reverse}」无法定位到任何标准问题；"
                  f"请改用 1-{N_QUESTIONS} 编号或 25 问关键词。", file=sys.stderr)
            return 2

    kinds = ("active", "archived") if args.include_archived else ("active",)
    marks = ",".join("?" * len(kinds))
    qmarks = ",".join("?" * len(qids))
    rows = conn.execute(
        f"SELECT s.id, s.name, s.province, s.kind, a.qid,"
        f" SUM(a.polarity = 'yes') AS n_yes, SUM(a.polarity = 'no') AS n_no,"
        f" SUM(a.polarity = 'mixed') AS n_mixed, SUM(a.polarity = 'unknown')"
        f" AS n_unknown, COUNT(*) AS total"
        f" FROM answers a JOIN schools s ON s.id = a.school_id"
        f" WHERE s.kind IN ({marks}) AND a.qid IN ({qmarks})"
        f" GROUP BY s.id, a.qid", (*kinds, *qids)).fetchall()

    threshold = max(args.min_yes, 1)
    hits: dict[int, dict] = {}
    for r in rows:
        ok = False
        if args.polarity == "yes":
            ok = r["n_yes"] >= threshold and r["n_yes"] > r["n_no"]
        elif args.polarity == "no":
            ok = r["n_no"] >= threshold and r["n_no"] > r["n_yes"]
        elif args.polarity == "mixed":
            ok = r["n_mixed"] > 0
        if not ok:
            continue
        row = hits.get(r["id"])
        if row is None:
            row = {"school": r["name"], "province": r["province"],
                   "source": r["kind"], "yes": 0, "no": 0, "mixed": 0,
                   "unknown": 0, "total": 0, "dims": 0}
            hits[r["id"]] = row
        for key in ("yes", "no", "mixed", "unknown"):
            row[key] += r[f"n_{key}"]
        row["total"] += r["total"]
        row["dims"] += 1

    out = list(hits.values())
    if args.polarity == "mixed":
        out.sort(key=lambda h: (-h["mixed"], h["school"]))
    elif args.polarity == "no":
        out.sort(key=lambda h: (-h["no"], h["school"]))
    else:
        out.sort(key=lambda h: (-h["yes"], h["school"]))

    if args.json:
        print(json.dumps({"keyword": args.reverse, "polarity": args.polarity,
                          "count": len(out), "results": out[:args.limit]},
                         ensure_ascii=False, indent=2))
        return 0

    want = _polarity_want(args.polarity, qids)
    print(f"# 反向筛选：{args.reverse} → 倾向「{args.polarity}：{want}」")
    print(f"命中 {len(out)} 所学校（按证据强度排序，最多显示 {args.limit} 所）")
    print()
    print("| 学校 | 省份 | 肯定 | 否定 | 分化 | 总回答 | 命中维度 | 来源 |")
    print("|---|---|---|---|---|---|---|---|")
    for h in out[:args.limit]:
        src = "归档" if h["source"] == "archived" else "活跃"
        print(f"| {h['school']} | {h['province']} | {h['yes']} | {h['no']} | "
              f"{h['mixed']} | {h['total']} | {h['dims']} | {src} |")
    if len(out) > args.limit:
        print(f"\n（其余 {len(out) - args.limit} 所略，可用 --limit 调整）")
    print("\n> 肯定/否定为按回答逐条分类的计数；「分化」表示同校存在分校区或年份差异，")
    print("> 建议对入围学校用 `--q` 读取原文后再下结论。")
    return 0


def cmd_province(conn: sqlite3.Connection, args) -> int:
    rows = conn.execute(
        "SELECT s.name, s.kind, COUNT(a.seq) AS n, MIN(a.date) AS d0,"
        " MAX(a.date) AS d1 FROM schools s LEFT JOIN answers a"
        " ON a.school_id = s.id WHERE s.province = ?"
        " GROUP BY s.id ORDER BY s.kind, s.file", (args.province,)).fetchall()
    if not rows:
        print(f"没有省份为「{args.province}」的学校", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([{"school": r["name"], "source": r["kind"],
                           "answers": r["n"],
                           "from": build_db.fmt_date(r["d0"]),
                           "to": build_db.fmt_date(r["d1"])}
                          for r in rows], ensure_ascii=False, indent=2))
        return 0
    print(f"# {args.province}：{len(rows)} 所学校")
    print()
    print("| 学校 | 回答数 | 回答时间 | 来源 |")
    print("|---|---|---|---|")
    for r in rows:
        span = f"{build_db.fmt_date(r['d0']) or '?'} ~ {build_db.fmt_date(r['d1']) or '?'}"
        src = "归档" if r["kind"] == "archived" else "活跃"
        print(f"| {r['name']} | {r['n']} | {span} | {src} |")
    return 0


def cmd_sources(conn: sqlite3.Connection, args) -> int:
    school, code = _pick(conn, args.sources)
    if school is None:
        return code
    rows = [dict(r) for r in conn.execute(
        "SELECT aid, label, date FROM sources WHERE school_id = ?"
        " ORDER BY date, aid", (school["id"],))]
    for r in rows:
        r["aid"] = build_db.fmt_aid(r["aid"])
        r["date"] = build_db.fmt_date(r["date"])
    if args.json:
        print(json.dumps({"school": school["name"], "sources": rows},
                         ensure_ascii=False, indent=2))
        return 0
    print(f"# {school['name']}：{len(rows)} 位回答者")
    for r in rows:
        date = f"（{r['date']}）" if r["date"] else ""
        print(f"- {r['aid']}: {r['label']}{date}")
    return 0


def run_selftest() -> int:
    """跑极性判定回归样例；不读取数据库，可离线执行。"""
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="大学生活质量结构化查询")
    ap.add_argument("school", nargs="*", help="学校名 / 简称")
    ap.add_argument("--q", default="all",
                    help="问题编号 1-25 或问题关键词，默认 all")
    ap.add_argument("--compare", nargs="+", metavar="SCHOOL", help="跨校对比")
    ap.add_argument("--reverse", metavar="KEYWORD", help="反向筛选关键词")
    ap.add_argument("--polarity", choices=("yes", "no", "mixed"), default="yes",
                    help="反向筛选的目标极性（默认 yes）")
    ap.add_argument("--min-yes", type=int, default=1,
                    help="反向筛选的最少目标极性回答数（默认 1）")
    ap.add_argument("--province", metavar="NAME", help="按省份浏览学校")
    ap.add_argument("--sources", metavar="SCHOOL", help="查看数据来源列表")
    ap.add_argument("--limit", type=int, default=5,
                    help="每类最多展示条数（默认 5）")
    ap.add_argument("--show", nargs="+", default=list(POLARITIES),
                    choices=POLARITIES, help="展示哪些极性分类")
    ap.add_argument("--include-archived", action="store_true",
                    help="反向筛选时包含归档库")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--db", type=Path, default=DB_PATH, help="数据库路径")
    ap.add_argument("--selftest", action="store_true",
                    help="运行极性判定回归样例后退出")
    args = ap.parse_args(argv)

    if args.selftest:
        return run_selftest()

    conn = connect(args.db)
    try:
        if args.reverse:
            return cmd_reverse(conn, args)
        if args.province:
            return cmd_province(conn, args)
        if args.sources:
            return cmd_sources(conn, args)
        if args.compare:
            return cmd_compare(conn, args)
        if args.school:
            return cmd_single(conn, args)
        ap.print_help()
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
