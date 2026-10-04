#!/usr/bin/env python3
"""build_db.py 的解析层测试（nav / 学校文件 / 标题编号），纯函数级、不碰真实数据。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import build_db  # noqa: E402

NAV = """    - 北京:
      - 示例大学: universities/sample.md
      - 示例大学医学部: universities/sample-yi-xue-bu.md
    - 其他:
      - 海外大学: universities/overseas.md
"""

NAV_ARCHIVED = """    - 北京:
      - 归档大学 (已归档): archived/universities/archived.md
"""

SCHOOL = """# 示例大学

> 数据来源：

<details><summary>点击展开</summary>
<ul>
<li>A00001: 匿名 (2024 年 06 月)</li>
<li>A00002: someone@example.com (2025 年 06 月)</li>
</ul>
</details>

## Q: 教室和宿舍有没有空调？

- A00001: 宿舍有空调

- A00002: 教室没有，宿舍有

## Q: 每天断电断网吗，几点开始断？

- A00001: 不断电

- A00002:

## 自由补充部分

A00001: 补充一句

***

A00002: 第一段
第二段

***

A00003: 无
"""

MULTILINE = """# 多行大学

## Q: 有独立卫浴吗？没有独立浴室的话，澡堂离宿舍多远？

- A10001: 宿舍分校内和校外
校外公寓全部有
校内一部分有层浴

- A10002: 有
"""


class TestParseNav(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "nav.txt").write_text(NAV, encoding="utf-8")
        (self.root / "archived-nav.txt").write_text(NAV_ARCHIVED, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_active_nav(self):
        rows = build_db.parse_nav(self.root / "nav.txt", "active")
        self.assertEqual(rows, [
            ("示例大学", "北京", "universities/sample.md"),
            ("示例大学医学部", "北京", "universities/sample-yi-xue-bu.md"),
            ("海外大学", "其他", "universities/overseas.md"),
        ])

    def test_archived_nav_strips_suffix(self):
        rows = build_db.parse_nav(self.root / "archived-nav.txt", "archived")
        self.assertEqual(rows,
                         [("归档大学", "北京", "archived/universities/archived.md")])
        self.assertNotIn("已归档", rows[0][0])


class TestParseSchool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._old_data = build_db.DATA
        build_db.DATA = self.root
        (self.root / "sample.md").write_text(SCHOOL, encoding="utf-8")
        (self.root / "multi.md").write_text(MULTILINE, encoding="utf-8")

    def tearDown(self):
        build_db.DATA = self._old_data
        self.tmp.cleanup()

    def test_sources_dates_and_title(self):
        d = build_db.parse_school("sample.md")
        self.assertEqual(d["title"], "示例大学")
        self.assertEqual(d["sources"][0], ("A00001", "匿名", "2024 年 06 月"))
        self.assertEqual(d["dates"]["A00002"], "2025-06")

    def test_question_blocks_parsed(self):
        d = build_db.parse_school("sample.md")
        q2 = [b for b in d["blocks"] if "断电" in b["heading"]][0]
        self.assertEqual(len(q2["answers"]), 2)
        self.assertEqual(q2["answers"][0], ("A00001", "不断电"))

    def test_empty_answer_does_not_swallow_next(self):
        # 回归：答案正文为空时下一条回答不能被并入（也不能被空串吞掉）
        d = build_db.parse_school("sample.md")
        q2 = [b for b in d["blocks"] if "断电" in b["heading"]][0]
        self.assertEqual(q2["answers"][1], ("A00002", ""))

    def test_freeform_bare_prefix_and_star_separator(self):
        d = build_db.parse_school("sample.md")
        free = [b for b in d["blocks"] if "自由补充" in b["heading"]][0]
        self.assertEqual([a[0] for a in free["answers"]],
                         ["A00001", "A00002", "A00003"])
        self.assertEqual(free["answers"][0][1], "补充一句")

    def test_freeform_multiline_body_preserved(self):
        d = build_db.parse_school("sample.md")
        free = [b for b in d["blocks"] if "自由补充" in b["heading"]][0]
        self.assertEqual(free["answers"][1][1], "第一段\n第二段")

    def test_question_multiline_answer_preserved(self):
        # 旧解析器丢弃续行；这里多行回答必须完整保留
        d = build_db.parse_school("multi.md")
        q3 = d["blocks"][0]
        self.assertEqual(q3["answers"][0][1],
                         "宿舍分校内和校外\n校外公寓全部有\n校内一部分有层浴")
        self.assertEqual(q3["answers"][1], ("A10002", "有"))


class TestHeadingQid(unittest.TestCase):
    def test_canonical_headings_map_to_1_to_25(self):
        for i in range(1, 26):
            spec = __import__("polarity").spec_for_qid(i)
            self.assertEqual(build_db.heading_qid(f"Q: {spec.heading()}"), i)

    def test_freeform_is_zero(self):
        self.assertEqual(build_db.heading_qid("自由补充部分"), 0)

    def test_unknown_heading_is_none(self):
        self.assertIsNone(build_db.heading_qid("Q: 一个不存在的问题？"))


if __name__ == "__main__":
    unittest.main()
