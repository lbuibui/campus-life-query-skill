#!/usr/bin/env python3
"""数据库完整性校验：data/index.sqlite 与 data/ 镜像的一致性回归。

检查项（失败即退出码 1；上游固有的格式瑕疵只告警）：

  1. 结构自洽 —— 外键引用、极性取值域、问题编号域、回答顺序号唯一；
  2. 清单一致 —— schools 行与 nav.txt / 文件系统逐一对应（含归并条目）；
  3. 内容摘要 —— 库内 meta.content_digest 与按行重算结果一致（防止库被
     手改后与重建结果漂移）；
  4. 别名安全 —— 唯一别名不得等于另一所真实学校的全称（防劫持全称查询）；
  5. 覆盖度 —— 每所学校 25 个问题区块都应有回答（缺答告警）。

用法：
    python3 tools/verify.py           # 全量输出
    python3 tools/verify.py --quiet   # 只输出警告、失败项与汇总
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

import build_db
import polarity

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "index.sqlite"
N_QUESTIONS = polarity.N_QUESTIONS
VALID_POLARITY = {"yes", "no", "mixed", "unknown"}
FULL_NAME_MARKERS = ("大学", "学院", "学校", "中学", "小学", "公学", "校区", "分校",
                    "University", "College", "Institute", "School", "Academy",
                    "Universität", "Université", "Universidad", "Университет")

_failures: list[str] = []
_warnings: list[str] = []


def fail(msg: str) -> None:
    _failures.append(msg)


def warn(msg: str) -> None:
    _warnings.append(msg)


def check_structure(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT COUNT(*) FROM answers a LEFT JOIN schools s"
        " ON s.id = a.school_id WHERE s.id IS NULL").fetchone()[0]
    if rows:
        fail(f"answers 中 {rows} 行引用了不存在的学校")

    rows = conn.execute(
        "SELECT COUNT(*) FROM answers WHERE polarity NOT IN"
        " ('yes','no','mixed','unknown')").fetchone()[0]
    if rows:
        fail(f"answers 中 {rows} 行的极性取值越界")

    rows = conn.execute(
        "SELECT COUNT(*) FROM answers WHERE qid < 0 OR qid > ?",
        (N_QUESTIONS,)).fetchone()[0]
    if rows:
        fail(f"answers 中 {rows} 行的问题编号越界（合法域 0-{N_QUESTIONS}）")

    rows = conn.execute(
        "SELECT COUNT(*) FROM (SELECT school_id, qid, seq FROM answers"
        " GROUP BY school_id, qid, seq HAVING COUNT(*) > 1)").fetchone()[0]
    if rows:
        fail(f"answers 中 {rows} 组 (学校, 问题, 顺序号) 重复")

    rows = conn.execute(
        "SELECT COUNT(*) FROM sources a LEFT JOIN schools s"
        " ON s.id = a.school_id WHERE s.id IS NULL").fetchone()[0]
    if rows:
        fail(f"sources 中 {rows} 行引用了不存在的学校")

    rows = conn.execute(
        "SELECT COUNT(*) FROM questions").fetchone()[0]
    if rows != N_QUESTIONS:
        fail(f"questions 表应为 {N_QUESTIONS} 行，实际 {rows}")

    # 每个回答编号应能在同校来源列表里找到（上游偶有缺失，仅告警）
    rows = conn.execute(
        "SELECT COUNT(DISTINCT a.school_id || ':' || a.aid) FROM answers a"
        " LEFT JOIN sources s ON s.school_id = a.school_id AND s.aid = a.aid"
        " WHERE s.aid IS NULL").fetchone()[0]
    if rows:
        warn(f"{rows} 个 (学校, 回答编号) 组合不在数据来源列表中")

    rows = conn.execute(
        "SELECT COUNT(*) FROM answers WHERE aid < 1 OR aid > 99999").fetchone()[0]
    if rows:
        fail(f"answers 中 {rows} 行的回答编号越界")


def check_inventory(conn: sqlite3.Connection) -> None:
    nav_active = build_db.parse_nav(ROOT / "data" / "nav.txt", "active")
    nav_arch = build_db.parse_nav(ROOT / "data" / "archived" / "nav.txt",
                                  "archived")
    expected: dict[str, str] = {}
    for name, _p, f in nav_active:
        expected[f] = name
    for name, _p, f in nav_arch:
        expected[f] = name

    merged_src = set(build_db.MERGED_ENTRIES)
    expected = {f: n for f, n in expected.items() if f not in merged_src}

    db_files = {r["file"]: r["name"] for r in conn.execute(
        "SELECT file, name FROM schools")}
    missing = sorted(set(expected) - set(db_files))
    extra = sorted(set(db_files) - set(expected))
    if missing:
        fail(f"{len(missing)} 个导航文件未入库：{missing[:3]}")
    if extra:
        fail(f"{len(extra)} 个库内文件不在导航中：{extra[:3]}")
    renamed = [f for f in expected if f in db_files and db_files[f] != expected[f]]
    if renamed:
        fail(f"{len(renamed)} 个学校的库内校名与导航不一致：{renamed[:3]}")

    absent = [f for f in expected if not (ROOT / "data" / f).exists()]
    if absent:
        fail(f"{len(absent)} 个库内文件在 data/ 下不存在：{absent[:3]}")

    # 归并条目：源文件回答应全部挂在目标学校名下
    for src, target in build_db.MERGED_ENTRIES.items():
        tgt_rows = conn.execute(
            "SELECT id FROM schools WHERE name = ?", (target,)).fetchall()
        if len(tgt_rows) != 1:
            fail(f"归并目标「{target}」在库内不是唯一学校")
            continue
        n = conn.execute(
            "SELECT COUNT(*) FROM answers WHERE school_id = ?",
            (tgt_rows[0]["id"],)).fetchone()[0]
        if n <= (N_QUESTIONS + 1):
            fail(f"归并条目 {src} 的回答疑似未并入「{target}」")


def check_digest(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'content_digest'").fetchone()
    if row is None:
        fail("meta 表缺 content_digest")
        return
    got = build_db.content_digest(conn)
    if got != row["value"]:
        fail(f"内容摘要漂移：库内 {row['value'][:16]}… ≠ 重算 {got[:16]}…"
             f"（库被手改或构建器变更，需重跑 build_db.py）")


def check_aliases(conn: sqlite3.Connection) -> None:
    """唯一别名不得等于另一所真实学校的全称（历史教训：327 条劫持）。"""
    names = {r["name"]: r["id"] for r in
             conn.execute("SELECT id, name FROM schools")}
    hijacked = []
    for r in conn.execute(
            "SELECT alias, school_id FROM aliases").fetchall():
        target = names.get(r["alias"])
        if (target is not None and target != r["school_id"]
                and any(m in r["alias"] for m in FULL_NAME_MARKERS)):
            hijacked.append(r["alias"])
    if hijacked:
        fail(f"{len(hijacked)} 个别名劫持了真实校名全称：{sorted(set(hijacked))[:5]}")

    # 全称不作别名是生成器的约定：校名全等的别名行不应存在
    dup = conn.execute(
        "SELECT COUNT(*) FROM (SELECT alias FROM aliases"
        " GROUP BY alias, school_id HAVING COUNT(*) > 1)").fetchone()[0]
    if dup:
        fail(f"aliases 中 {dup} 组 (别名, 学校) 重复")
    selfnamed = conn.execute(
        "SELECT COUNT(*) FROM aliases a JOIN schools s ON s.id = a.school_id"
        " WHERE a.alias = s.name").fetchone()[0]
    if selfnamed:
        fail(f"{selfnamed} 条别名与所指学校全称相同（冗余，应剔除）")


def check_coverage(conn: sqlite3.Connection) -> None:
    """每所学校应有 25 个问题区块的回答；缺答只告警（上游固有瑕疵）。"""
    rows = conn.execute(
        "SELECT s.name, s.file, COUNT(DISTINCT a.qid) c FROM schools s"
        " LEFT JOIN answers a ON a.school_id = s.id AND a.qid > 0"
        " GROUP BY s.id HAVING c < ?", (N_QUESTIONS,)).fetchall()
    if rows:
        warn(f"{len(rows)} 所学校的问题回答不足 {N_QUESTIONS} 题"
             f"（上游固有，勿删改）：{[r['file'][:24] for r in rows[:5]]}")

    rows = conn.execute(
        "SELECT s.name, s.file FROM schools s LEFT JOIN answers a"
        " ON a.school_id = s.id WHERE a.school_id IS NULL").fetchall()
    if rows:
        warn(f"{len(rows)} 个空条目（无任何回答）：{[r['file'][:24] for r in rows[:5]]}")

    # 上游以整句说明文字作校名 / 简称占位条目：提示 Agent 不要把它们当规范校名
    # 口径：中文整句（含句读）或中文名不含任何学校类后缀（多为简称占位条目）；
    # 纯外文校名（如 University / Ollscoil …）不在此列，它们就是规范校名。
    odd = []
    for r in conn.execute("SELECT name, file FROM schools").fetchall():
        name = r["name"]
        has_cjk = bool(re.search(r"[\u4e00-\u9fff]", name))
        marker_hit = any(m.lower() in name.lower() for m in FULL_NAME_MARKERS)
        if (re.search(r"[，。！？；]", name)
                or (has_cjk and not marker_hit) or len(name) > 60):
            odd.append(f"{name[:18]}->{r['file'][:24]}")
    if odd:
        warn(f"{len(odd)} 个校名疑似说明文字 / 简称占位条目（勿直接当学校全名）："
             f"{sorted(odd)[:5]}")

    long_names = [r["file"] for r in
                  conn.execute("SELECT file FROM schools").fetchall()
                  if len(r["file"]) > 150]
    if long_names:
        warn(f"{len(long_names)} 个文件名超过 150 字符（路径长度风险）："
             f"{[f[:24] for f in long_names[:3]]}")

    empty = conn.execute(
        "SELECT COUNT(*) FROM answers WHERE TRIM(body) = ''").fetchone()[0]
    if empty:
        warn(f"{empty} 条空回答（问卷者跳过，未删改）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="只输出警告与失败项")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    args = ap.parse_args()

    if not args.db.exists():
        print(f"数据库不存在：{args.db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    checks = (
        ("结构自洽", check_structure),
        ("清单一致", check_inventory),
        ("内容摘要", check_digest),
        ("别名安全", check_aliases),
        ("覆盖度", check_coverage),
    )
    for label, fn in checks:
        before = len(_failures)
        fn(conn)
        if not args.quiet:
            state = "ok" if len(_failures) == before else "FAIL"
            print(f"[{state}] {label}")
    conn.close()

    for msg in _failures:
        print(f"失败: {msg}", file=sys.stderr)
    for msg in _warnings:
        print(f"警告: {msg}")
    print(f"== 结果：{len(_failures)} 项失败 / {len(_warnings)} 项警告 ==")
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
