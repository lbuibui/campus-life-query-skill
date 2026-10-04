#!/usr/bin/env python3
"""campus-life 结构化查询工具。

修复的核心问题：SKILL.md 原本教 Agent 用 `grep -rl "不断"` 做反向筛选。
字面命中率看似很高，但「不断电」既会命中真正不断电的学校，也会命中同一
文件里说「会断电」的回答——3,449 个活跃文件里 284 个同时含这两种说法。
行级匹配无法区分「这所学校不断电」和「这所学校有人提到断电」。

本工具改为：先定位问题区块 → 逐条解析回答 → 做极性分类 → 按校区/年份归组
输出，并把「分化/分校区」单独标出。宁可标为「其他」，也不替用户断言。

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

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "references"
ACTIVE_DIR = REF / "universities"
ARCHIVE_DIR = REF / "archived" / "universities"
INDEX = REF / "index.md"
ARCHIVE_INDEX = REF / "archived" / "index.md"
ALIASES = REF / "aliases.md"

# ---------------------------------------------------------------------------
# 25 个标准问题的关键词路由表
# ---------------------------------------------------------------------------
QUESTIONS: list[tuple[int, str, tuple[str, ...]]] = [
    (1, "宿舍是上床下桌吗", ("上床下桌", "床", "宿舍", "上床", "上下铺")),
    (2, "教室和宿舍有没有空调", ("空调",)),
    (3, "有独立卫浴吗，澡堂离宿舍多远", ("卫浴", "澡堂", "浴室", "洗澡间", "独卫")),
    (4, "有早自习、晚自习吗", ("自习", "早读")),
    (5, "有晨跑吗", ("晨跑", "早操", "跑操")),
    (6, "跑步打卡要求多少公里，可以骑车吗", ("跑步", "打卡", "公里", "骑车", "乐跑", "步道乐跑")),
    (7, "寒暑假放多久，小学期多长", ("寒暑假", "暑假", "寒假", "小学期", "假期")),
    (8, "允许点外卖吗，取外卖多远", ("外卖",)),
    (9, "交通便利吗，有地铁吗，在市区吗", ("交通", "地铁", "进城", "市区", "公交")),
    (10, "宿舍楼有洗衣机吗", ("洗衣机",)),
    (11, "校园网怎么样", ("校园网", "网络", "wifi", "WIFI", "宽带")),
    (12, "每天断电断网吗，几点开始断", ("断电", "断网", "熄灯")),
    (13, "食堂价格贵吗，会吃出异物吗", ("食堂", "异物", "饭菜", "吃饭")),
    (14, "洗澡热水供应时间", ("热水", "供水")),
    (15, "校园内可以骑电瓶车吗，电池在哪充电", ("电瓶车", "电动车", "充电")),
    (16, "宿舍限电情况", ("限电", "跳闸", "功率")),
    (17, "通宵自习有去处吗", ("通宵",)),
    (18, "大一能带电脑吗", ("电脑",)),
    (19, "学校里面用什么卡，饭堂怎样消费", ("校园卡", "饭卡", "一卡通", "刷卡")),
    (20, "学校会给学生发银行卡吗", ("银行卡",)),
    (21, "学校的超市怎么样", ("超市", "小卖部")),
    (22, "学校的收发快递政策怎么样", ("快递", "收发", "菜鸟")),
    (23, "学校里面的共享单车数目与种类如何", ("共享单车", "单车", "哈啰", "美团单车")),
    (24, "现阶段学校的门禁情况如何", ("门禁", "查证", "刷脸", "出入")),
    (25, "宿舍晚上查寝吗，封寝吗，晚归能回去吗", ("查寝", "封寝", "晚归")),
]

# 25 个问题在数据文件中的规范标题（`## Q: …？`）。编号 --q N 按此表精确匹配，
# 不走关键词模糊匹配。注意：必须与 tools/verify.py 的 CANONICAL_HEADINGS 保持一致。
CANONICAL_HEADINGS = [
    "宿舍是上床下桌吗？",
    "教室和宿舍有没有空调？",
    "有独立卫浴吗？没有独立浴室的话，澡堂离宿舍多远？",
    "有早自习、晚自习吗？",
    "有晨跑吗？",
    "每学期跑步打卡的要求是多少公里，可以骑车吗？",
    "寒暑假放多久，每年小学期有多长？",
    "学校允许点外卖吗，取外卖的地方离宿舍楼多远？",
    "学校交通便利吗，有地铁吗，在市区吗，不在的话进城要多久？",
    "宿舍楼有洗衣机吗？",
    "校园网怎么样？",
    "每天断电断网吗，几点开始断？",
    "食堂价格贵吗，会吃出异物吗？",
    "洗澡热水供应时间？",
    "校园内可以骑电瓶车吗，电池在哪能充电？",
    "宿舍限电情况？",
    "通宵自习有去处吗？",
    "大一能带电脑吗？",
    "学校里面用什么卡，饭堂怎样消费？",
    "学校会给学生发银行卡吗？",
    "学校的超市怎么样？",
    "学校的收发快递政策怎么样？",
    "学校里面的共享单车数目与种类如何？",
    "现阶段学校的门禁情况如何？",
    "宿舍晚上查寝吗，封寝吗，晚归能回去吗？",
]
N_QUESTIONS = len(CANONICAL_HEADINGS)


def _norm_heading(heading: str) -> str:
    """规范化区块标题：去掉 `Q:` 前缀与结尾问号，便于精确比较。"""
    h = heading.strip()
    if h.startswith("Q:"):
        h = h[2:]
    return h.strip().rstrip("？?").strip()

# 极性词典。NEG_FIRST 内部的短语本身含否定词，必须先于 NEG_TOKENS 判断。
NEG_FIRST = (
    "不断电", "不会断电", "不断网", "不会断网", "不查寝", "不封寝", "不封",
    "不限电", "不查", "不用", "不需要", "不允许", "不能骑", "不可以",
    "不可以点", "不能点", "不贵", "不便宜", "不难", "不严", "不熄灯",
    "不晚归", "不查卫生", "不打卡",
)
# 含「不/没」但实际不是否定该问题的说法，先从否定判断中排除
NOT_A_NEGATION = (
    "不计入", "不收费", "不要钱", "不花钱", "不包括", "不算", "不止",
    "不过", "不管", "不一定", "不固定", "不到", "不多", "不少",
    "不错", "不卡", "不差", "不赖",
)
# 含「不/无/有/发/多」等字但语义中性的词，做极性判断前先剔除，
# 否则「无线」「发现」「多久」会被误当成否定/肯定信号
NEUTRALIZE = ("无线", "发现", "出发", "沙发", "头发", "多少", "多久",
              "附近", "最近", "将近", "所有")
NEG_TOKENS = ("没有", "無", "无法", "不能", "不让", "不允许", "不给", "不是", "否", "无", "未", "没", "不")
POS_TOKENS = (
    "有", "是", "可以", "能", "允许", "提供", "配备", "支持", "发", "给",
    "方便", "免费", "充足", "多", "好", "便利", "近", "便宜",
)
HEDGE_TOKENS = (
    "部分", "有的", "有些", "看", "分校区", "不同", "一半", "多数", "少数",
    "有的校区", "各校区", "视", "取决于", "但", "不过", "然而", "但是",
    "有时", "好像", "勉强",
)
# 反问 / 语义不明：含这些标记时不做极性断言，交回原文给人判断
QUERY_TOKENS = (
    "什么是", "什么叫", "哪来", "哪有", "吗？", "吗?", "呢？", "呢?",
    "？", "?", "不清楚", "不知道", "忘了", "记不清", "据说", "听说",
    "答非所问", "无意义", "不懂",
)


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


def load_aliases() -> dict[str, tuple[str, str]]:
    """别名 -> (学校名, 文件名)。

    这里用 setdefault 处理重复别名；别名表的唯一性由 build_aliases.py 保证、
    并由 verify.py 强制检查（重复别名会让 verify.py 失败），因此不会静默取错。
    """
    out: dict[str, tuple[str, str]] = {}
    if not ALIASES.exists():
        return out
    for line in ALIASES.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0] in ("别名 / 简称", "简称"):
            continue
        if set(cells[0]) <= set("-: "):
            continue
        out.setdefault(cells[0], (cells[1], cells[3]))
    return out


def resolve(query: str, aliases: dict[str, tuple[str, str]],
            active: list[tuple[str, str, str]], archived: list[tuple[str, str, str]]) -> list[dict]:
    """把用户输入（全称/简称/文件名）解析为候选学校。

    顺序**有意**为先别名、后全称（与 SKILL.md 第 0 步一致）：别名表由
    build_aliases.py 保证「任何别名的文字都不等于另一所真实学校全称」，因此
    不会劫持全称查询；少数指向「上游简称占位条目」的别名（如「川农」「东华理工」）
    正是要优先命中真实学校。该不变式由 build_aliases.py 的兜底与 verify.py 的
    别名检查共同守护，若被破坏 verify.py 会直接失败。
    """
    q = query.strip()
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
ANSWER_RE = re.compile(r"^- (A\d+):[ \t]*(.*)$")


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


def classify(text: str) -> str:
    """粗粒度极性：yes / no / mixed / unknown。

    判定顺序（有意保守）：
      1. 反问 / 语义不明 → unknown，不替用户断言；
      2. 同时出现否定与肯定信号（「不断电但会跳闸」）→ mixed；
      3. 出现分校区 / 分化措辞 → mixed；
      4. 只有否定信号 → no；只有肯定信号 → yes；都没有 → unknown。

    词形处理（2026-10-04 修正）：判定前先剔除 NOT_A_NEGATION（不错/不收费…）
    与 NEUTRALIZE（无线/发现…）中的中性词，否则「很不错」「无线」「未发现」会被
    反向归类；计算肯定信号时先剥 NEG_FIRST 整短语、再剥 NEG_TOKENS，避免
    「不可以骑车」里的「不」被删后残留「可以」而误判为 mixed。

    说明：文本层面的极性判定不可能 100% 准确，因此工具始终把原文一并输出，
    并提醒用户「计数是回答条数，不是官方事实」。回归样例见 `--selftest`。
    """
    t = text.strip()
    if not t:
        return "unknown"
    # 含「不/没」但并不否定问题的说法（不计入、不收费…）先剔除，避免误判
    for keep in NOT_A_NEGATION:
        t = t.replace(keep, "")
    if not t.strip():
        return "unknown"
    if any(tok in t for tok in QUERY_TOKENS):
        return "unknown"

    # 含「不/无/有/发」但语义中性的词先剔除（无线、发现、多久…）
    scan = t
    for word in NEUTRALIZE:
        scan = scan.replace(word, "")

    has_neg = any(phr in scan for phr in NEG_FIRST) or any(
        tok in scan for tok in NEG_TOKENS if tok != "是"
    )
    # 抛掉否定短语与否定词后再看是否有肯定信号，避免「不」字本身被当成肯定
    t_pos = scan
    for phr in NEG_FIRST:
        t_pos = t_pos.replace(phr, "")
    for tok in NEG_TOKENS:
        t_pos = t_pos.replace(tok, "")
    has_pos = any(tok in t_pos for tok in POS_TOKENS)
    has_hedge = any(h in t for h in HEDGE_TOKENS)

    if has_neg and has_pos:
        return "mixed"
    if has_hedge and (has_neg or has_pos):
        return "mixed"
    if has_neg:
        return "no"
    if has_pos:
        return "yes"
    return "unknown"


def summarize(answers: list[dict], dates: dict[str, str]) -> dict:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for a in answers:
        pol = classify(a["text"])
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


def render_question(qa: dict, limit: int, show: tuple[str, ...]) -> str:
    s = qa["summary"]
    out = [f"### {qa['heading']}"]
    parts = " / ".join(f"{k}={v}" for k, v in sorted(s["counts"].items()))
    out.append(f"共 {s['total']} 条回答（{parts or '无'}）")
    if s["years"]:
        out.append("年份分布：" + "，".join(f"{y} 年 {n} 条" for y, n in s["years"].items()))
    labels = {"yes": "倾向肯定", "no": "倾向否定", "mixed": "分化 / 分校区差异", "unknown": "其他 / 无法归类"}
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


def cmd_single(args, aliases, active, archived) -> int:
    cands = resolve(args.school[0], aliases, active, archived)
    if not cands:
        print(f"未找到学校：{args.school[0]}", file=sys.stderr)
        return 2
    if len(cands) > 1 and cands[0]["name"] != args.school[0]:
        print(f"「{args.school[0]}」可能指多所学校，请用更完整的名称：", file=sys.stderr)
        for c in cands[:10]:
            print(f"  - {c['name']}（{c['source']}）", file=sys.stderr)
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
            {"heading": b["heading"], "summary": summarize(b["answers"], data["dates"])}
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
        qa = {"heading": b["heading"], "summary": summarize(b["answers"], data["dates"])}
        print(render_question(qa, args.limit, tuple(args.show)))
        print()
    return 0


def cmd_compare(args, aliases, active, archived) -> int:
    payload = []
    errors = 0
    for school in args.compare:
        cands = resolve(school, aliases, active, archived)
        if not cands:
            print(f"未找到学校：{school}", file=sys.stderr)
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
                {"heading": b["heading"], "summary": summarize(b["answers"], data["dates"])}
                for b in blocks
            ],
        })
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2 if errors else 0
    for item in payload:
        print(f"# {item['school']}" + ("（归档数据）" if item["source"] == "archived" else ""))
        for q in item["questions"]:
            print(render_question(q, args.limit, tuple(args.show)))
            print()
        print("-" * 60)
    return 2 if errors else 0


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
                s = summarize(b["answers"], data["dates"])
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

    print(f"# 反向筛选：{args.reverse} → 倾向「{args.polarity}」")
    print(f"命中 {len(hits)} 所学校（按证据强度排序，最多显示 {args.limit} 所）")
    print()
    print("| 学校 | 省份 | 肯定 | 否定 | 分化 | 总回答 | 来源 |")
    print("|---|---|---|---|---|---|---|")
    for h in hits[: args.limit]:
        src = "归档" if h["source"] == "archived" else "活跃"
        print(f"| {h['school']} | {h['province']} | {h['yes']} | {h['no']} | {h['mixed']} | {h['total']} | {src} |")
    if len(hits) > args.limit:
        print(f"\n（其余 {len(hits) - args.limit} 所略，可用 --limit 调整）")
    print("\n> 肯定/否定为按回答逐条分类的计数；「分化」表示同校存在分校区或年份差异，")
    print("> 建议对入围学校用 `--q` 读取原文后再下结论。")
    return 0


SELFTEST_CASES: list[tuple[str, str]] = [
    # (回答文本, 期望极性)：回归 2026-10-04 修正的词内误判
    ("很不错，基本全覆盖（要办校园卡）", "unknown"),
    ("有时很差", "mixed"),
    ("勉强能用，晚上经常断", "mixed"),
    ("宿舍无线接入约500Mbps", "unknown"),
    ("宿舍附近未发现充电地点", "no"),
    ("不可以骑车", "no"),
    ("不断电", "no"),
    ("没有空调", "no"),
    ("有空调", "yes"),
    ("能带电脑", "yes"),
    ("不能带电脑", "no"),
    ("不断电但会跳闸", "mixed"),
    ("部分宿舍有空调", "mixed"),
    ("", "unknown"),
]


def run_selftest() -> int:
    """跑极性判定回归样例；不读取数据文件，可离线执行。"""
    bad = 0
    for text, want in SELFTEST_CASES:
        got = classify(text)
        if got != want:
            bad += 1
        flag = "ok  " if got == want else "FAIL"
        print(f"  [{flag}] {text!r:44} want={want:7} got={got}")
    print(f"== query.py 极性回归：{len(SELFTEST_CASES) - bad}/{len(SELFTEST_CASES)} 通过 ==")
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
    active = load_index(INDEX)
    archived = load_index(ARCHIVE_INDEX)

    if args.reverse:
        return cmd_reverse(args, aliases, active, archived)
    if args.compare:
        return cmd_compare(args, aliases, active, archived)
    if not args.school:
        ap.print_help()
        return 2
    return cmd_single(args, aliases, active, archived)


if __name__ == "__main__":
    sys.exit(main())
