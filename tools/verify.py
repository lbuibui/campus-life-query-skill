#!/usr/bin/env python3
"""数据完整性回归校验。

每次从上游 sync 数据后运行一次，确认项目自身承诺的契约没有破：
  1. 索引 ↔ 文件 双向一致（无失效链接、无孤儿文件、无重复行），且索引正文声明的
     院校 / 「其他」总数与实际行数一致；
  2. 别名索引：目标文件存在、别名唯一，且**不劫持**任何真实学校全称；
  3. 每个学校文件结构完整（25 个标准问题区块，且每个区块至少 1 条回答）；
  4. 回答编号与「数据来源」列表一致（无悬空引用）；
  5. 来源列表已脱敏（扫描文件头所有 `<li>` 行，异常格式也覆盖）；
  6. 索引与文件头标题无明显脏值（前导点号、空名、ASCII / 中文简称未标注、
     H1 与索引校名不一致）。

说明：个别回答正文为空（问卷者跳过）属于上游原始数据，本项目不删改，因此只作为
**警告**列出，不计入失败项；简称占位条目、H1 与索引不一致同样以警告列出。

用法：
    python3 tools/verify.py           # 全部检查
    python3 tools/verify.py --quiet   # 只输出警告、失败项与汇总
退出码 0 表示全部通过，1 表示存在失败项。
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "references"
ACTIVE_DIR = REF / "universities"
ARCHIVE_DIR = REF / "archived" / "universities"

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

SENSITIVE_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|\b1[3-9]\d{9}\b"
)
LI_RE = re.compile(r"<li>(A\d+):\s*(.*?)\s*\(([^)]*)\)</li>")
# 只吃掉行内空白，不能用 `\s*`：空回答后紧跟空行时 `\s*` 会跨行吞掉下一条
# 回答行，导致回答计数偏少、空回答漏检、回答编号集合缺项。
ANS_RE = re.compile(r"^- (A\d+):[ \t]*(.*)$", re.M)
# 含这些词的校名视为「真实学校全称」，用于区分上游以简称命名的占位条目
FULL_NAME_MARKERS = ("大学", "学院", "学校", "中学", "小学", "公学", "校区", "分校")

failures: list[str] = []
warnings: list[str] = []
QUIET = False


def info(msg: str) -> None:
    """常规进度输出；--quiet 时静默，只保留警告、失败项与汇总。"""
    if not QUIET:
        print(msg)


def fail(msg: str) -> None:
    failures.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def parse_index(path: Path, layout: str = "school") -> list[tuple[str, str, str, str]]:
    """解析 Markdown 表格，返回 (名称, 省份, 文件名)。

    layout:
      "school"  —— 学校索引：名称|省份|文件（允许行尾多一个备注列）
      "alias"   —— 别名索引：别名|学校|省份|文件
      "auto"    —— 按列数推断
    """
    rows: list[tuple[str, str, str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] in ("学校名", "别名 / 简称", "简称"):
            continue
        if set(cells[0]) <= set("-: "):
            continue
        if layout == "alias":
            if len(cells) < 4:
                continue
            rows.append((cells[0], cells[2], cells[3], ""))
        else:
            # 学校索引：文件固定在第 3 列，其后为可选备注列
            rows.append((cells[0], cells[1], cells[2], " ".join(cells[3:])))
    return rows


def check_inventory(label: str, index_path: Path, data_dir: Path) -> list[tuple[str, str, str, str]]:
    rows = parse_index(index_path)
    names = [r[0] for r in rows]
    files = [r[2] for r in rows]
    on_disk = {p.name for p in data_dir.glob("*.md")}

    for n, c in Counter(names).items():
        if c > 1:
            fail(f"[{label}] 索引中学校名重复 {c} 次：{n}")
    for f, c in Counter(files).items():
        if c > 1:
            fail(f"[{label}] 索引中文件名重复 {c} 次：{f}")
    for f in files:
        if f not in on_disk:
            fail(f"[{label}] 索引指向不存在的文件：{f}")
    for f in sorted(on_disk - set(files)):
        fail(f"[{label}] 文件未收录进索引：{f}")
    # 索引正文里声明的院校 / 「其他」总数必须与实际一致（由 patch_index.py 写入）
    text = index_path.read_text(encoding="utf-8")
    m = re.search(r"共 (\d+) 所学校", text) or re.search(r"共 (\d+) 所已归档学校", text)
    if m and int(m.group(1)) != len(rows):
        fail(f"[{label}] 索引正文声明 {m.group(1)} 所学校，实际 {len(rows)} 行")
    mo = re.search(r"另有 (\d+) 所标为「其他」", text)
    if mo:
        n_other = sum(1 for r in rows if r[1] == "其他")
        if int(mo.group(1)) != n_other:
            fail(f"[{label}] 索引正文声明 {mo.group(1)} 所「其他」，实际 {n_other} 行")
    info(f"  {label}: 索引 {len(rows)} 行 / 磁盘 {len(on_disk)} 个文件")
    return rows


def check_aliases() -> None:
    path = REF / "aliases.md"
    if not path.exists():
        fail("缺少 references/aliases.md（运行 tools/build_aliases.py 生成）")
        return
    rows = parse_index(path, layout="alias")
    on_disk = {p.name for p in ACTIVE_DIR.glob("*.md")}
    bad = [f for _a, _p, f, _r in rows if f not in on_disk]
    for f in bad:
        fail(f"[别名] 指向不存在的文件：{f}")
    for a, c in Counter(r[0] for r in rows).items():
        if c > 1:
            fail(f"[别名] 别名重复 {c} 次：{a}")
    # 别名不得等于另一所**真实**学校的全称，否则会把全称查询劫持到别的学校。
    # 指向上游「简称占位条目」（如「川农」→ 四川农业大学）是有意为之，放行。
    file_of = {r[0]: r[2] for r in parse_index(REF / "index.md")}
    for alias, _prov, fname, _r in rows:
        shadowed = file_of.get(alias)
        if shadowed and shadowed != fname and _looks_like_full_school_name(alias):
            fail(f"[别名] 「{alias}」是另一所学校（{shadowed}）的全称，"
                 f"会把查询劫持到 {fname}")
    info(f"  别名: {len(rows)} 条")


def _looks_like_full_school_name(name: str) -> bool:
    return any(marker in name for marker in FULL_NAME_MARKERS)


def check_structure(label: str, data_dir: Path, sample: int | None = None) -> None:
    paths = sorted(data_dir.glob("*.md"))
    if sample:
        paths = paths[:sample]
    bad_structure: list[str] = []
    dangling = 0
    empty: list[str] = []
    no_answer_blocks: list[str] = []
    n_answers = 0
    n_sources = 0
    for p in paths:
        text = p.read_text(encoding="utf-8")
        heads = [h.strip() for h in re.findall(r"^##\s*(.+)$", text, re.M)]
        q_heads = [h for h in heads if h.startswith("Q:")]
        if len(q_heads) != 25:
            bad_structure.append(f"{p.name}({len(q_heads)} 个问题区块)")
        for canon in CANONICAL_HEADINGS:
            if f"Q: {canon}" not in text:
                bad_structure.append(f"{p.name}(缺 {canon[:12]}…)")
        # 每个问题区块必须至少 1 条回答（docstring 承诺的「均有回答」）
        for chunk in text.split("\n## ")[1:]:
            lines = chunk.splitlines()
            if not lines:
                continue
            head = lines[0].strip().lstrip("# ").strip()
            if not head.startswith("Q:"):
                continue
            if not any(ANS_RE.match(line.strip()) for line in lines[1:]):
                no_answer_blocks.append(f"{p.name}:{head[:16]}")
        ids_src = set(m[0] for m in LI_RE.findall(text))
        body = text[text.find("\n## "):] if "\n## " in text else text
        ids_ans = {m[0] for m in ANS_RE.findall(body)}
        n_sources += len(ids_src)
        n_answers += len(ANS_RE.findall(body))
        dangling += len(ids_ans - ids_src)
        empty += [f"{p.name}:{aid}" for aid, a in ANS_RE.findall(body) if not a.strip()]
    if bad_structure:
        fail(f"[{label}] 结构异常文件 {len(bad_structure)} 个，例如：{bad_structure[:5]}")
    if no_answer_blocks:
        fail(f"[{label}] {len(no_answer_blocks)} 个问题区块没有任何回答：{no_answer_blocks[:5]}")
    if dangling:
        fail(f"[{label}] 存在 {dangling} 条回答编号不在来源列表中")
    if empty:
        warn(f"[{label}] 存在 {len(empty)} 条空回答（上游原始数据即如此，未删改）：{empty[:5]}")
    info(
        f"  {label}: 校验 {len(paths)} 个文件 / {n_answers} 条回答 / {n_sources} 个来源编号"
    )


def check_redaction(label: str, data_dir: Path) -> None:
    """来源列表脱敏检查。

    直接扫描文件头里**所有** `<li>…</li>` 行，而不是先按严格格式解析：这样
    缺日期、带尾空格等异常格式也逃不掉（严格的 LI_RE 会静默跳过它们）。
    """
    li_any = re.compile(r"<li>(.*?)</li>")
    hits = 0
    for p in data_dir.glob("*.md"):
        text = p.read_text(encoding="utf-8")
        head = text[: text.find("\n## ")] if "\n## " in text else text
        for raw in li_any.findall(head):
            if "匿名" in raw or "实名反馈者" in raw:
                continue
            if SENSITIVE_RE.search(raw):
                hits += 1
    if hits:
        fail(f"[{label}] 来源列表仍有 {hits} 处疑似个人信息（运行 tools/redact.py）")
    else:
        info(f"  {label}: 来源列表已脱敏")


def check_index_hygiene(label: str, rows: list[tuple[str, str, str, str]], data_dir: Path) -> None:
    ascii_short: list[str] = []
    cjk_short: list[str] = []
    for name, _prov, fname, remark in rows:
        if not name:
            fail(f"[{label}] 学校名为空：{fname}")
        if name.startswith((".", "*", "#", "-")):
            fail(f"[{label}] 学校名含异常前缀：{name!r}")
        if remark:
            continue
        if re.fullmatch(r"[A-Za-z0-9.\-]{1,10}", name):
            # 纯 ASCII 短名（上游原始简称），必须在索引里带备注说明
            ascii_short.append(f"{name}->{fname}")
        elif not _looks_like_full_school_name(name) and len(name) <= 6:
            # 中文简称占位条目（如「川农」「港中深」）同样需要标注
            cjk_short.append(f"{name}->{fname}")
    if ascii_short:
        warn(f"[{label}] {len(ascii_short)} 个未标注的上游原始简称"
             f"（建议加索引备注）：{ascii_short[:5]}")
    if cjk_short:
        warn(f"[{label}] {len(cjk_short)} 个未标注的简称占位条目"
             f"（上游以简称命名、答案多为编码值，勿当正常学校）：{cjk_short[:5]}")
    # 上游把说明文字/整句话写进「学校名」字段的条目：不是学校名，需人工判断
    sentence = [f"{name[:20]}…" for name, _p, _f, _r in rows
                if re.search(r"[，。！？；、,;]", name) or len(name) > 30]
    if sentence:
        warn(f"[{label}] {len(sentence)} 个索引名疑似说明文字/超长（非规范校名，勿直接当学校）："
             f"{sentence[:5]}")
    # 过长的文件名在 Windows 上有路径长度风险
    long_names = [f for _n, _p, f, _r in rows if len(f) > 150]
    if long_names:
        warn(f"[{label}] {len(long_names)} 个文件名超过 150 字符（路径长度风险）："
             f"{[f[:40] + '…' for f in long_names[:3]]}")
    # 文件 H1 必须与索引校名一致（归档库 H1 统一带「 (已归档)」后缀）
    mismatches: list[str] = []
    for name, _prov, fname, _remark in rows:
        p = data_dir / fname
        if not p.exists():
            continue
        first = p.read_text(encoding="utf-8").splitlines()
        h1 = first[0].lstrip("# ").strip() if first else ""
        h1 = re.sub(r"\s*\(已归档\)$", "", h1)
        if h1 != name:
            mismatches.append(f"{fname}:索引={name!r}/H1={h1!r}")
    if mismatches:
        warn(f"[{label}] {len(mismatches)} 个文件 H1 与索引不一致：{mismatches[:5]}")
    info(f"  {label}: 索引名称格式检查完成")


def main() -> int:
    global QUIET
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="只输出警告、失败项与汇总")
    ap.add_argument("--sample", type=int, default=None, help="只抽样前 N 个文件做结构校验")
    args = ap.parse_args()
    QUIET = args.quiet

    info("== 数据完整性校验 ==")
    active = check_inventory("活跃", REF / "index.md", ACTIVE_DIR)
    archived = check_inventory("归档", REF / "archived" / "index.md", ARCHIVE_DIR)
    check_aliases()
    check_structure("活跃", ACTIVE_DIR, args.sample)
    check_structure("归档", ARCHIVE_DIR, args.sample)
    check_redaction("活跃", ACTIVE_DIR)
    check_redaction("归档", ARCHIVE_DIR)
    check_index_hygiene("活跃", active, ACTIVE_DIR)
    check_index_hygiene("归档", archived, ARCHIVE_DIR)

    if warnings or failures:
        print()
    for w in warnings:
        print(f"警告: {w}")
    for f in failures:
        print(f"失败: {f}")
    print(f"== 结果：{len(failures)} 项失败 / {len(warnings)} 项警告 ==")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
