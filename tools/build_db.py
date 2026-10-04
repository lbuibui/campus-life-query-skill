#!/usr/bin/env python3
"""从 data/ 上游镜像构建 SQLite 查询索引（确定性构建）。

数据真源是 `data/` 下的上游 markdown 镜像（CollegesChat/university-information
generated 分支，原样保留）；本脚本把它解析成结构化行，极性判定（polarity.py）
在构建期一次性算好存入 answers.polarity，查询期零分类开销。

确定性：所有表按固定顺序插入、不写入任何墙钟时间，重复构建产生逻辑一致的
数据库；`--check` 重建到临时文件并比较内容摘要（sha256 over 规范化行序列），
与提交版本不一致即退出码 1。摘要口径与 sqlite 版本无关，比逐字节比较稳健。

用法：
    python3 tools/build_db.py                 # 构建 data/index.sqlite
    python3 tools/build_db.py --check         # 重建并比对内容摘要（不写库）
    python3 tools/build_db.py --out /tmp/x.db # 指定输出（测试用）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

import polarity

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = DATA / "index.sqlite"

ANSWER_RE = re.compile(r"^\s*(?:- )?(A\d+):[ \t]*(.*)$")
SOURCE_RE = re.compile(r"<li>(A\d+):\s*(.*?)\s*\(([^)]*)\)</li>")
DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月")
NAV_PROVINCE_RE = re.compile(r"^    - (.+):$")
NAV_SCHOOL_RE = re.compile(r"^      - (.+): (\S+\.md)$")

# 上游有个别问卷把说明文字写进了校名字段，形成「错放条目」：文件内容是某所
# 学校的数据，但校名是一整句说明。这里在**建库期**归并到正确学校（数据文件
# 保持上游原样，不改写），避免查询「广东轻工职业技术大学」时命中两个候选。
# 键 = data/ 下的相对文件路径，值 = 归并目标的规范校名（须存在于 nav 中）。
MERGED_ENTRIES: dict[str, str] = {
    "universities/yuan-xiao-ming-yan-dong-qing-gong-zhi-ye-ji-zhu-xue-yuan-"
    "xue-xiao-sheng-ben-liao-xiao-ming-gai-wei-yan-dong-qing-gong-zhi-ye-ji-"
    "zhu-da-xue.md": "广东轻工职业技术大学",
}

N_QUESTIONS = polarity.N_QUESTIONS
FREEFORM_QID = 0

SCHEMA = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE schools (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL,
    title    TEXT NOT NULL,
    file     TEXT NOT NULL UNIQUE,
    province TEXT NOT NULL,
    kind     TEXT NOT NULL          -- 'active' | 'archived'
);
CREATE TABLE questions (
    qid      INTEGER PRIMARY KEY,  -- 1..25
    heading  TEXT NOT NULL,
    keywords TEXT NOT NULL         -- 逗号分隔
);
CREATE TABLE answers (
    school_id INTEGER NOT NULL REFERENCES schools(id),
    qid       INTEGER NOT NULL,    -- 1..25；0 = 自由补充部分
    seq       INTEGER NOT NULL,    -- 块内顺序
    aid       INTEGER NOT NULL,    -- 问卷编号（A12345 存 12345）
    date      INTEGER,             -- YYYYMM，取自数据来源列表
    body      TEXT NOT NULL,
    polarity  TEXT NOT NULL,       -- yes / no / mixed / unknown
    PRIMARY KEY (school_id, qid, seq)
) WITHOUT ROWID;
CREATE TABLE sources (
    school_id INTEGER NOT NULL REFERENCES schools(id),
    aid       INTEGER NOT NULL,
    label     TEXT NOT NULL,       -- 来源列表原始标注（匿名 / 联系方式）
    date      INTEGER,
    PRIMARY KEY (school_id, aid)
) WITHOUT ROWID;
CREATE TABLE aliases (
    alias     TEXT NOT NULL,
    school_id INTEGER NOT NULL REFERENCES schools(id),
    PRIMARY KEY (alias, school_id)
);
CREATE INDEX idx_answers_qid_polarity ON answers (qid, polarity);
CREATE INDEX idx_schools_province ON schools (province);
"""


def fmt_aid(aid: int) -> str:
    """问卷编号整数 → 展示用 `A12345`。"""
    return f"A{aid}"


def fmt_date(d: int | None) -> str:
    """YYYYMM 整数 → 展示用 `YYYY-MM`。"""
    return f"{d // 100:04d}-{d % 100:02d}" if d else ""


def parse_aid(aid: str) -> int:
    return int(aid[1:]) if aid.startswith("A") else int(aid)


def parse_date(date: str) -> int | None:
    """接受 `2024 年 06 月`（原始来源格式）与 `2024-06`（解析器归一格式）。"""
    if not date:
        return None
    m = DATE_RE.search(date)
    if m:
        return int(m.group(1)) * 100 + int(m.group(2))
    m = re.fullmatch(r"(\d{4})-(\d{2})", date.strip())
    return int(m.group(1)) * 100 + int(m.group(2)) if m else None


# ---------------------------------------------------------------------------
# markdown 解析
# ---------------------------------------------------------------------------
def parse_nav(path: Path, kind: str) -> list[tuple[str, str, str]]:
    """解析 nav.txt → [(校名, 省份, 相对路径)]。

    归档导航的校名带「 (已归档)」后缀，这里剥掉，kind 列区分库别。
    """
    rows: list[tuple[str, str, str]] = []
    province = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        m = NAV_PROVINCE_RE.match(line)
        if m:
            province = m.group(1).strip()
            continue
        m = NAV_SCHOOL_RE.match(line)
        if m:
            name = m.group(1).strip()
            if kind == "archived":
                name = re.sub(r"\s*\(已归档\)$", "", name)
            rows.append((name, province, m.group(2)))
    return rows


def parse_school(path: str) -> dict:
    """解析单个学校文件 → {title, sources, blocks}。

    回答条目从 `- A123: …`（问题区块）或裸 `A123: …`（自由补充部分）开始，
    一直到下一条回答 / `***` 分隔线 / 新标题为止的**所有**行都是该条回答的
    正文（上游存在多行回答，旧解析器会丢弃续行，这里保留）。回答之间以
    空行分隔不作为边界——边界只由回答起始行、`***`、标题决定。
    """
    text = (DATA / path).read_text(encoding="utf-8")

    title = ""
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break

    head, sep, body = text.partition("\n## ")
    sources: list[tuple[str, str, str]] = []
    dates: dict[str, str] = {}
    for aid, label, date in SOURCE_RE.findall(head):
        sources.append((aid, label.strip(), date.strip()))
        m = DATE_RE.search(date)
        if m:
            dates[aid] = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"

    blocks: list[dict] = []
    if sep:
        for chunk in ("## " + body).split("\n## "):
            chunk = chunk.strip("\n")
            if not chunk:
                continue
            lines = chunk.splitlines()
            heading = lines[0].lstrip("# ").strip()
            answers: list[tuple[str, str]] = []
            cur: list[str] | None = None

            def flush() -> None:
                nonlocal cur
                if cur is not None:
                    answers.append((cur[0], "\n".join(cur[1:]).strip()))
                    cur = None

            for line in lines[1:]:
                m = ANSWER_RE.match(line)
                if m:
                    flush()
                    cur = [m.group(1), m.group(2)]
                elif line.strip() == "***":
                    flush()
                elif cur is not None:
                    cur.append(line)
                # 回答之前的游离行（上游几乎不存在）直接忽略
            flush()
            blocks.append({"heading": heading, "answers": answers})

    return {"title": title, "sources": sources, "dates": dates, "blocks": blocks}


def heading_qid(heading: str) -> int | None:
    """区块标题 → 问题编号；自由补充部分返回 0；未识别返回 None。"""
    h = heading.strip()
    if h.startswith("Q:"):
        h = h[2:]
    h = h.strip().rstrip("？?").strip()
    if h == "自由补充部分":
        return FREEFORM_QID
    want = polarity.CANONICAL_HEADINGS
    for i in range(N_QUESTIONS):
        w = want[i]
        if w.startswith("Q:"):
            w = w[2:]
        if w.strip().rstrip("？?").strip() == h:
            return i + 1
    return None


# ---------------------------------------------------------------------------
# 构建
# ---------------------------------------------------------------------------
def build(out: Path) -> dict:
    """构建数据库，返回统计信息。所有插入顺序固定（按文件名 / 编号排序）。"""
    nav_active = parse_nav(DATA / "nav.txt", "active")
    nav_arch = parse_nav(DATA / "archived" / "nav.txt", "archived")
    schools = [(n, p, f, "active") for n, p, f in nav_active] + [
        (n, p, f, "archived") for n, p, f in nav_arch
    ]

    # 归并错放条目：目标校名必须已存在，否则报错而不是静默丢数据
    names_by_file = {f: n for n, _p, f, _k in schools}
    file_of_name = {n: f for f, n in names_by_file.items()}
    merged_targets: dict[str, str] = {}  # 源文件 -> 目标文件
    for f, target in MERGED_ENTRIES.items():
        if f not in names_by_file:
            raise SystemExit(f"归并源文件不在导航中：{f}")
        if target not in file_of_name:
            raise SystemExit(f"归并目标校名不存在：{target}")
        merged_targets[f] = file_of_name[target]

    schools = [s for s in schools if s[2] not in merged_targets]
    schools.sort(key=lambda s: (s[3], s[2]))  # (kind, file)：确定性顺序

    if out.exists():
        out.unlink()
    conn = sqlite3.connect(out)
    conn.executescript(SCHEMA)

    school_id: dict[str, int] = {}
    for i, (name, province, f, kind) in enumerate(schools, 1):
        school_id[f] = i
        data = parse_school(f)
        conn.execute(
            "INSERT INTO schools (id, name, title, file, province, kind)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (i, name, data["title"], f, province, kind),
        )

    for qid in range(1, N_QUESTIONS + 1):
        spec = polarity.spec_for_qid(qid)
        conn.execute(
            "INSERT INTO questions (qid, heading, keywords) VALUES (?, ?, ?)",
            (qid, spec.heading(), ",".join(polarity.KEYWORDS[qid])),
        )

    # 归并条目追加到目标学校；顺序：目标文件在前、归并来源在后
    targets: dict[str, list[str]] = {}
    for f in sorted(school_id):
        targets.setdefault(f, []).append(f)
    for src in sorted(merged_targets):
        targets[merged_targets[src]].append(src)

    n_answers = n_freeform = n_sources = 0
    for tgt in sorted(targets):
        sid = school_id[tgt]
        seq_of: dict[int, int] = {}  # 合并多文件时顺序号连续，避免 (校,题,序) 重复
        for f in sorted(targets[tgt]):
            data = parse_school(f)
            for aid, label, date in data["sources"]:
                conn.execute(
                    "INSERT OR REPLACE INTO sources (school_id, aid, label, date)"
                    " VALUES (?, ?, ?, ?)",
                    (sid, parse_aid(aid), label, parse_date(date)),
                )
                n_sources += 1
            for block in data["blocks"]:
                qid = heading_qid(block["heading"])
                if qid is None:
                    continue
                spec = polarity.spec_for_qid(qid) if qid else polarity.FREE
                for aid, body_text in block["answers"]:
                    seq = seq_of.get(qid, 0)
                    seq_of[qid] = seq + 1
                    pol = polarity.classify(body_text, spec)
                    conn.execute(
                        "INSERT INTO answers"
                        " (school_id, qid, seq, aid, date, body, polarity)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (sid, qid, seq, parse_aid(aid),
                         parse_date(data["dates"].get(aid, "")), body_text, pol),
                    )
                    if qid == FREEFORM_QID:
                        n_freeform += 1
                    else:
                        n_answers += 1

    # 别名表：只覆盖活跃库（与旧版口径一致，避免同名归档条目稀释唯一性）；
    # 歧义简称同一别名多行，查询期按行数识别、列出候选。
    import alias_seed

    active_names = sorted({n for n, _p, _f, k in schools if k == "active"})
    all_names = sorted({n for n, _p, _f, _k in schools})
    unique, ambiguous, warnings = alias_seed.build_aliases(active_names, all_names)
    id_of_name = {n: school_id[f] for n, _p, f, k in schools if k == "active"}
    n_alias = 0
    for alias in sorted(unique):
        sid = id_of_name.get(unique[alias])
        if sid is None:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO aliases (alias, school_id) VALUES (?, ?)",
            (alias, sid),
        )
        n_alias += 1
    for nick in sorted(ambiguous):
        for cand in sorted(set(ambiguous[nick])):
            sid = id_of_name.get(cand)
            if sid is None:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO aliases (alias, school_id) VALUES (?, ?)",
                (nick, sid),
            )
            n_alias += 1

    stats = {
        "schools_active": sum(1 for *_x, k in schools if k == "active"),
        "schools_archived": sum(1 for *_x, k in schools if k == "archived"),
        "answers": n_answers,
        "freeform": n_freeform,
        "sources": n_sources,
        "alias_rows": n_alias,
        "merged_entries": len(merged_targets),
        "alias_warnings": warnings,
    }
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('content_digest', ?)",
        (content_digest(conn),),
    )
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('counts', ?)",
        (json.dumps({k: v for k, v in stats.items() if k != "alias_warnings"},
                    ensure_ascii=False, sort_keys=True),),
    )
    conn.commit()
    conn.execute("PRAGMA optimize")
    conn.close()
    return stats


# ---------------------------------------------------------------------------
# 内容摘要：与 sqlite 版本 / 页面布局无关的逻辑指纹
# ---------------------------------------------------------------------------
DIGEST_TABLES = (
    ("schools", ("id", "name", "title", "file", "province", "kind")),
    ("questions", ("qid", "heading", "keywords")),
    ("answers", ("school_id", "qid", "seq", "aid", "date", "body", "polarity")),
    ("sources", ("school_id", "aid", "label", "date")),
    ("aliases", ("alias", "school_id")),
)


def content_digest(conn: sqlite3.Connection) -> str:
    h = hashlib.sha256()
    for table, cols in DIGEST_TABLES:
        h.update(table.encode())
        for row in conn.execute(
            f"SELECT {', '.join(cols)} FROM {table} ORDER BY {', '.join(cols[:2])}"
        ):
            h.update(json.dumps(tuple(row), ensure_ascii=False,
                                default=str).encode("utf-8"))
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="重建到临时文件并比对内容摘要，不写正式库")
    ap.add_argument("--out", type=Path, default=DB_PATH, help="输出路径")
    args = ap.parse_args(argv)

    if args.check:
        import tempfile

        if not args.out.exists():
            print(f"[check] {args.out} 不存在，需要先构建", file=sys.stderr)
            return 1
        want = sqlite3.connect(args.out).execute(
            "SELECT value FROM meta WHERE key='content_digest'").fetchone()[0]
        with tempfile.TemporaryDirectory() as tmp:
            tmpdb = Path(tmp) / "index.sqlite"
            build(tmpdb)
            got = sqlite3.connect(tmpdb).execute(
                "SELECT value FROM meta WHERE key='content_digest'").fetchone()[0]
        if want == got:
            print(f"[check] 内容摘要一致：{got[:16]}…")
            return 0
        print(f"[check] 内容摘要不一致：库内 {want[:16]}… ≠ 重建 {got[:16]}…",
              file=sys.stderr)
        return 1

    stats = build(args.out)
    try:
        shown = args.out.relative_to(ROOT)
    except ValueError:
        shown = args.out
    print(f"写入 {shown}：")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
