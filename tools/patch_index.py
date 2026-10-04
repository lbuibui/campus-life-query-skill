#!/usr/bin/env python3
"""对上游生成的索引施加本项目的本地修正（幂等）。

为什么需要它：`references/index.md` 是上游生成物，但本项目对其有两类必要
修正——(1) 上游数据瑕疵（校名前导点号、无法识别的原始简称需要标注）；
(2) 本地事实（学校总数、日期戳、上游 SHA、口径说明）。做数据同步时若用
`git checkout` 回退索引，这些修正会一并丢失。本脚本把它们固化下来，任何
时候重跑都能恢复到正确状态。

用法：
    python3 tools/patch_index.py           # 施加修正（幂等）
    python3 tools/patch_index.py --check   # 只检查是否需要修正
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACTIVE = ROOT / "references" / "index.md"
ARCH = ROOT / "references" / "archived" / "index.md"

UP_SHA = "0abf14dfc897838b5e9b11231766f64719a1bdf2"
UP_DATE = "2026-09-19"

# 学校名前导点号（上游数据瑕疵）
DOT_FIX = (
    "| .山东省德州市庆云县云天职业技术学院 | 其他 |",
    "| 山东省德州市庆云县云天职业技术学院 | 其他 |",
)

# 上游原始简称：无法识别为学校，需在索引里标注（加备注列）
ABBREV = ["swpu", "tj", "xn"]
ABBREV_NOTE = "上游原始简称，未识别出学校；仅 1 位问卷者、25 条编码回答，请勿据此描述学校"


def fix_active(text: str, n_active: int, n_other: int) -> tuple[str, list[str]]:
    """施加活跃索引的本地修正，返回 (新文本, 实际生效的修正标签列表)。

    只有**文本真的变了**才记一笔，避免 --check 少报（改了却没计数）或多报
    （锚点没命中却计数）——两者都会让 --check 的结论不可信。
    """
    marks: list[str] = []

    if DOT_FIX[0] in text:
        text = text.replace(DOT_FIX[0], DOT_FIX[1], 1)
        marks.append("school-name-leading-dot")

    for ab in ABBREV:
        # 整行匹配后重写：即使备注文案改过，也能幂等地更新为当前文案
        pattern = rf"^\| {re.escape(ab)} \| 其他 \| {re.escape(ab)}\.md \|.*$"
        new, n = re.subn(
            pattern, lambda m: f"| {ab} | 其他 | {ab}.md | {ABBREV_NOTE} |",
            text, count=1, flags=re.M,
        )
        if n and new != text:
            text = new
            marks.append(f"abbrev-note:{ab}")

    # 日期戳 + 上游 SHA
    new = re.sub(
        r"数据更新日期：\d{4}-\d{2}-\d{2}\n(?:上游版本（generated 分支）：[0-9a-f]+\n)?",
        f"数据更新日期：{UP_DATE}\n上游版本（generated 分支）：{UP_SHA[:12]}\n",
        text,
        count=1,
    )
    if new != text:
        text = new
        marks.append("date+sha")

    # 覆盖范围表述
    new = re.sub(
        r"共 \d+ 所学校（含分校区）[^\n]*\n",
        f"共 {n_active} 所学校（含分校区）：中国大陆 31 个省级行政区，"
        f"另有 {n_other} 所标为「其他」（多为海外院校或上游未能归类的学校）。\n",
        text,
        count=1,
    )
    if new != text:
        text = new
        marks.append("coverage-count")

    # 检索说明（含别名索引指引与本地修正说明）
    if "先用 `references/aliases.md` grep" not in text:
        new = re.sub(
            r"当用户提到[^\n]*先在本索引中用 grep 搜索确定文件名，再读取对应目录下文件。\n",
            "当用户提到学校名称时，先用 `references/aliases.md` grep 简称/别名；"
            "本索引只收录中文全称，可用全称或关键词 grep 确定文件名，再读取对应目录下文件。\n",
            text,
            count=1,
        )
        if new != text:
            text = new
            marks.append("grep-wording")
    note = (
        "\n> 说明：本文件的「数据来源」列表已脱敏，原问卷填写者留下的邮箱等标识统一替换为「实名反馈者 N」。\n"
        "> 索引中标注「上游原始简称，未识别出学校」的条目（`tj`、`xn`、`swpu`）保留上游原始标识，未做猜测性改名。\n"
        "> 上游曾有 1 个 141 字符的拼音文件名（问卷者把校名变更说明填进了校名字段），该文件仅 1 位问卷者、"
        "25 条回答 + 1 条自由补充，已由 `tools/consolidate.py` 归并进「广东轻工职业技术大学」。\n"
    )
    anchor = "再读取对应目录下文件。\n"
    if "校名变更说明" not in text:
        if anchor in text:
            text = text.replace(anchor, anchor + note, 1)
            marks.append("local-note")
        else:
            print("  [警告] 找不到注入本地说明的锚点，索引结构可能已被改动，请人工检查")

    return text, marks


def fix_archived(text: str, n_arch: int, n_other: int) -> tuple[str, list[str]]:
    marks: list[str] = []
    new = re.sub(
        r"数据更新日期：\d{4}-\d{2}-\d{2}\n(?:上游版本（generated 分支）：[0-9a-f]+\n)?",
        f"数据更新日期：{UP_DATE}\n上游版本（generated 分支）：{UP_SHA[:12]}\n",
        text,
        count=1,
    )
    if new != text:
        text = new
        marks.append("date+sha")
    new = re.sub(
        r"共 \d+ 所已归档学校（含分校区）[^\n]*\n",
        f"共 {n_arch} 所已归档学校（含分校区），覆盖 31 个省级行政区"
        f"（另有 {n_other} 所标为「其他」）。\n",
        text,
        count=1,
    )
    if new != text:
        text = new
        marks.append("coverage-count")
    if "已脱敏（见 `tools/redact.py`）" not in text:
        anchor = "目录下对应文件。\n"
        if anchor in text:
            text = text.replace(
                anchor,
                anchor + "\n> 说明：本目录文件的「数据来源」列表已脱敏（见 `tools/redact.py`），"
                "答复时仍需注明数据为 2023 年前、条件可能已过时。\n",
                1,
            )
            marks.append("local-note")
        else:
            print("  [警告] 找不到注入脱敏说明的锚点，归档索引结构可能已被改动")
    return text, marks


def count_rows(path: Path, layout: str) -> tuple[int, int]:
    """返回 (行数, 「其他」行数)。"""
    a = other = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] in ("学校名", "别名 / 简称", "简称"):
            continue
        if set(cells[0]) <= set("-: "):
            continue
        a += 1
        if layout == "school" and cells[1] == "其他":
            other += 1
    return a, other


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    n_active, n_other_a = count_rows(ACTIVE, "school")
    n_arch, n_other_ar = count_rows(ARCH, "school")

    total = 0
    for path, fn, args_ in (
        (ACTIVE, fix_active, (n_active, n_other_a)),
        (ARCH, fix_archived, (n_arch, n_other_ar)),
    ):
        text = path.read_text(encoding="utf-8")
        new, marks = fn(text, *args_)
        total += len(marks)
        if marks and not args.check:
            path.write_text(new, encoding="utf-8")
        detail = f"（{', '.join(marks)}）" if marks else ""
        print(f"{path.relative_to(ROOT)}: {'需修正' if marks else '已是最新'}{detail}")

    if args.check:
        print(f"[check] 共需修正 {total} 处")
        return 1 if total else 0
    print(f"共修正 {total} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
