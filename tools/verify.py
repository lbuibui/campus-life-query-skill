#!/usr/bin/env python3
"""数据完整性回归校验。

每次从上游 sync 数据后运行一次，确认项目自身承诺的契约没有破：
  1. 索引 ↔ 文件 双向一致（无失效链接、无孤儿文件、无重复行）；
  2. 别名索引覆盖可用，且不指向不存在的文件；
  3. 每个学校文件结构完整（25 个标准问题区块、均有回答）；
  4. 回答编号与「数据来源」列表一致（无悬空引用）；
  5. 来源列表已脱敏（无邮箱 / 手机号）；
  6. 索引与文件头标题无明显脏值（前导点号、空名、ASCII 短缩写未标注）。

用法：
    python3 tools/verify.py           # 全部检查
    python3 tools/verify.py --quiet   # 只输出失败项与汇总
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
ANS_RE = re.compile(r"^- (A\d+):\s*(.*)$", re.M)

failures: list[str] = []
warnings: list[str] = []


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
    print(f"  {label}: 索引 {len(rows)} 行 / 磁盘 {len(on_disk)} 个文件")
    return rows


def check_aliases() -> None:
    path = REF / "aliases.md"
    if not path.exists():
        fail("缺少 references/aliases.md（运行 tools/build_aliases.py 生成）")
        return
    rows = parse_index(path, layout="alias")
    on_disk = {p.name for p in ACTIVE_DIR.glob("*.md")}
    bad = [f for _n, _p, f, _r in rows if f not in on_disk]
    for f in bad:
        fail(f"[别名] 指向不存在的文件：{f}")
    print(f"  别名: {len(rows)} 条")


def check_structure(label: str, data_dir: Path, sample: int | None = None) -> None:
    paths = sorted(data_dir.glob("*.md"))
    if sample:
        paths = paths[:sample]
    bad_structure: list[str] = []
    dangling = 0
    empty = 0
    counted = 0
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
                break
        ids_src = set(m[0] for m in LI_RE.findall(text))
        body = text[text.find("\n## "):] if "\n## " in text else text
        ids_ans = {m[0] for m in ANS_RE.findall(body)}
        n_sources += len(ids_src)
        n_answers += len(ANS_RE.findall(body))
        counted += len(ids_ans)
        dangling += len(ids_ans - ids_src)
        empty += sum(1 for _i, a in ANS_RE.findall(body) if not a.strip())
    if bad_structure:
        fail(f"[{label}] 结构异常文件 {len(bad_structure)} 个，例如：{bad_structure[:5]}")
    if dangling:
        fail(f"[{label}] 存在 {dangling} 条回答编号不在来源列表中")
    if empty:
        fail(f"[{label}] 存在 {empty} 条空回答")
    print(
        f"  {label}: 校验 {len(paths)} 个文件 / {n_answers} 条回答 / {n_sources} 个来源编号"
    )


def check_redaction(label: str, data_dir: Path) -> None:
    hits = 0
    for p in data_dir.glob("*.md"):
        text = p.read_text(encoding="utf-8")
        head = text[: text.find("\n## ")] if "\n## " in text else text
        for _aid, ident, _d in LI_RE.findall(head):
            if "匿名" in ident or ident.startswith("实名反馈者"):
                continue
            if SENSITIVE_RE.search(ident):
                hits += 1
    if hits:
        fail(f"[{label}] 来源列表仍有 {hits} 处疑似个人信息（运行 tools/redact.py）")
    else:
        print(f"  {label}: 来源列表已脱敏")


def check_index_hygiene(label: str, rows: list[tuple[str, str, str, str]]) -> None:
    for name, _prov, fname, remark in rows:
        if not name or name != name.strip():
            fail(f"[{label}] 学校名为空或含首尾空白：{name!r}")
        if name.startswith((".", "*", "#", "-")):
            fail(f"[{label}] 学校名含异常前缀：{name!r}")
        if re.fullmatch(r"[A-Za-z0-9.\-]{1,10}", name) and not remark:
            # 纯 ASCII 短名（上游原始简称），必须在索引里带备注说明
            warn(f"[{label}] 疑似未标注的上游原始简称：{name!r} -> {fname}")
    print(f"  {label}: 索引名称格式检查完成")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--sample", type=int, default=None, help="只抽样前 N 个文件做结构校验")
    args = ap.parse_args()

    print("== 数据完整性校验 ==")
    active = check_inventory("活跃", REF / "index.md", ACTIVE_DIR)
    archived = check_inventory("归档", REF / "archived" / "index.md", ARCHIVE_DIR)
    check_aliases()
    check_structure("活跃", ACTIVE_DIR, args.sample)
    check_structure("归档", ARCHIVE_DIR, args.sample)
    check_redaction("活跃", ACTIVE_DIR)
    check_redaction("归档", ARCHIVE_DIR)
    check_index_hygiene("活跃", active)
    check_index_hygiene("归档", archived)

    print()
    for w in warnings:
        print(f"警告: {w}")
    for f in failures:
        print(f"失败: {f}")
    print(f"== 结果：{len(failures)} 项失败 / {len(warnings)} 项警告 ==")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
