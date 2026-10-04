#!/usr/bin/env python3
"""query.py 的解析与索引测试（纯函数级 + CLI 冒烟）。"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import polarity  # noqa: E402
import query  # noqa: E402

SAMPLE_SCHOOL = """# 示例大学

> 数据来源：

<details><summary>点击展开</summary>
<ul>
<li>A00001: 匿名 (2024 年 06 月)</li>
<li>A00002: 实名反馈者 1 (2025 年 06 月)</li>
</ul>
</details>

## Q: 教室和宿舍有没有空调？

- A00001: 宿舍有空调

- A00002: 教室没有，宿舍有

## Q: 每天断电断网吗，几点开始断？

- A00001: 不断电

- A00002: 11 点断网

## 自由补充部分

A00001: 补充一句
"""


def build_index(path: Path) -> None:
    path.write_text(
        "# 大学索引\n\n"
        "共 2 所学校。\n\n"
        "| 学校名 | 省份 | 文件 |\n"
        "|--------|------|------|\n"
        "| 示例大学 | 北京 | sample.md |\n"
        "| 另外大学 | 上海 | other.md |\n",
        encoding="utf-8",
    )


def build_aliases(path: Path) -> None:
    path.write_text(
        "# 学校别名 / 简称索引\n\n"
        "| 别名 / 简称 | 学校全名 | 省份 | 文件 |\n"
        "|---|---|---|---|\n"
        "| 示例 | 示例大学 | 北京 | sample.md |\n",
        encoding="utf-8",
    )


class TestParseSchool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sample.md"
        self.path.write_text(SAMPLE_SCHOOL, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_dates_and_blocks(self):
        data = query.parse_school(self.path)
        self.assertEqual(data["dates"]["A00001"], "2024 年 06 月")
        self.assertEqual(data["dates"]["A00002"], "2025 年 06 月")
        headings = [b["heading"] for b in data["blocks"]]
        self.assertIn("Q: 教室和宿舍有没有空调？", headings)
        self.assertIn("自由补充部分", headings)

    def test_empty_answer_does_not_swallow_next(self):
        # 回归：答案正文为空、后面紧跟空行时，下一条回答不能被并入
        data = query.parse_school(self.path)
        q2 = next(b for b in data["blocks"] if "断电断网" in b["heading"])
        self.assertEqual(len(q2["answers"]), 2)
        self.assertEqual(q2["answers"][0]["text"], "不断电")
        self.assertEqual(q2["answers"][1]["text"], "11 点断网")

    def test_free_form_bare_answers_are_parsed(self):
        # 「自由补充部分」的条目不带 `- ` 前缀，也应被解析
        data = query.parse_school(self.path)
        free = next(b for b in data["blocks"] if "自由补充" in b["heading"])
        self.assertEqual([a["text"] for a in free["answers"]], ["补充一句"])
        self.assertEqual(polarity.spec_for_heading("自由补充部分"), polarity.FREE)


class TestMatchQuestions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sample.md"
        self.path.write_text(SAMPLE_SCHOOL, encoding="utf-8")
        self.blocks = query.parse_school(self.path)["blocks"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_by_number(self):
        picked = query.match_questions(self.blocks, "2")
        self.assertEqual(len(picked), 1)
        self.assertIn("空调", picked[0]["heading"])

    def test_by_keyword(self):
        picked = query.match_questions(self.blocks, "断电")
        self.assertTrue(any("断电断网" in b["heading"] for b in picked))

    def test_all_returns_every_block(self):
        self.assertEqual(len(query.match_questions(self.blocks, "all")), len(self.blocks))

    def test_out_of_range_number(self):
        self.assertEqual(query.match_questions(self.blocks, "99"), [])
        self.assertEqual(query.match_questions(self.blocks, "0"), [])

    def test_no_match_message_reports_range(self):
        self.assertIn("1-25", query._no_match_message("示例大学", "99"))
        self.assertIn("未匹配", query._no_match_message("示例大学", "不存在的问题"))


class TestIndexParsing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.index = Path(self.tmp.name) / "index.md"
        self.aliases = Path(self.tmp.name) / "aliases.md"
        build_index(self.index)
        build_aliases(self.aliases)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_index_skips_header_and_separator(self):
        rows = query.load_index(self.index)
        self.assertEqual(rows, [("示例大学", "北京", "sample.md"),
                                ("另外大学", "上海", "other.md")])

    def test_load_aliases_parses_target_file(self):
        aliases = query.load_aliases(self.aliases)
        self.assertEqual(aliases["示例"], ("示例大学", "sample.md"))

    def test_norm_heading(self):
        self.assertEqual(query._norm_heading("Q: 有空调？"), "有空调")
        self.assertEqual(query._norm_heading(" 有空调 "), "有空调")


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.aliases = {"示例": ("示例大学", "sample.md")}
        self.active = [("示例大学", "北京", "sample.md"),
                       ("示例大学分校", "北京", "sample-branch.md")]
        self.archived = [("归档大学", "河北", "archived.md")]

    def test_alias_wins(self):
        hit = query.resolve("示例", self.aliases, self.active, self.archived)
        self.assertEqual(hit[0]["name"], "示例大学")
        self.assertEqual(hit[0]["source"], "active")

    def test_exact_full_name(self):
        hit = query.resolve("归档大学", self.aliases, self.active, self.archived)
        self.assertEqual(hit[0]["source"], "archived")

    def test_filename_without_extension(self):
        hit = query.resolve("sample", self.aliases, self.active, self.archived)
        self.assertEqual(hit[0]["file"], "sample.md")

    def test_substring_returns_candidates(self):
        hits = query.resolve("大学", self.aliases, self.active, self.archived)
        names = {h["name"] for h in hits}
        self.assertIn("示例大学", names)
        self.assertIn("示例大学分校", names)

    def test_ambiguous_nickname_returns_candidates(self):
        ambiguous = {"地大": ("中国地质大学北京", "中国地质大学武汉")}
        active = [("中国地质大学北京", "北京", "a.md"),
                  ("中国地质大学武汉", "湖北", "b.md")]
        cands = query.resolve("地大", {}, active, [], ambiguous)
        self.assertEqual({c["name"] for c in cands},
                         {"中国地质大学北京", "中国地质大学武汉"})
        self.assertEqual({c["source"] for c in cands}, {"active"})

    def test_ambiguous_nickname_not_in_alias_table_does_not_hijack(self):
        # 只有歧义表时返回多候选；不传歧义表则退回普通逻辑（不静默选一）
        ambiguous = {"地大": ("中国地质大学北京", "中国地质大学武汉")}
        active = [("中国地质大学北京", "北京", "a.md"),
                  ("中国地质大学武汉", "湖北", "b.md")]
        self.assertEqual(len(query.resolve("地大", {}, active, [], None)), 0)

    def test_load_ambiguous_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "amb.md"
            path.write_text(
                "# 别名\n\n"
                "| 别名 / 简称 | 学校全名 | 省份 | 文件 |\n"
                "|---|---|---|---|\n"
                "| 北邮 | 北京邮电大学 | 北京 | a.md |\n"
                "\n## 歧义简称（指向多所学校）\n\n"
                "| 简称 | 候选学校 |\n"
                "|---|---|\n"
                "| 地大 | 中国地质大学北京；中国地质大学武汉 |\n",
                encoding="utf-8",
            )
            amb = query.load_ambiguous(path)
            self.assertEqual(amb, {"地大": ("中国地质大学北京", "中国地质大学武汉")})
            # 唯一别名表不应把两列的歧义表行也收进来
            self.assertNotIn("地大", query.load_aliases(path))


class TestSummarize(unittest.TestCase):
    def test_counts_by_spec(self):
        answers = [{"id": "A1", "text": "有空调"},
                   {"id": "A2", "text": "没有空调"},
                   {"id": "A3", "text": "部分宿舍有空调"}]
        dates = {"A1": "2024 年 06 月", "A2": "2024 年 06 月", "A3": "2025 年 06 月"}
        summary = query.summarize(answers, dates, polarity.spec_for_qid(2))
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["counts"], {"yes": 1, "no": 1, "mixed": 1})
        self.assertEqual(summary["years"], {"2024": 2, "2025": 1})


class TestReverseHelpers(unittest.TestCase):
    def test_aggregate_merges_same_school(self):
        hits = [
            {"school": "A", "province": "北京", "source": "active", "file": "a.md",
             "heading": "Q1", "yes": 1, "no": 0, "mixed": 0, "total": 2},
            {"school": "A", "province": "北京", "source": "active", "file": "a.md",
             "heading": "Q2", "yes": 2, "no": 1, "mixed": 0, "total": 3},
            {"school": "B", "province": "上海", "source": "active", "file": "b.md",
             "heading": "Q1", "yes": 1, "no": 0, "mixed": 0, "total": 1},
        ]
        agg = query._aggregate_hits(hits)
        self.assertEqual(len(agg), 2)
        a = next(r for r in agg if r["school"] == "A")
        self.assertEqual((a["yes"], a["no"], a["total"], a["dims"]), (3, 1, 5, 2))

    def test_polarity_want_labels(self):
        specs = [polarity.spec_for_qid(2)]
        self.assertEqual(query._polarity_want("yes", specs), "有空调")
        self.assertEqual(query._polarity_want("no", specs), "没有空调")
        self.assertIn("分化", query._polarity_want("mixed", specs))


class TestCliSmoke(unittest.TestCase):
    """在真实数据上做一次端到端冒烟（只读一所学校，很快）。"""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(TOOLS / "query.py"), *args],
                              capture_output=True, text=True, cwd=ROOT)

    def test_selftest_exit_zero(self):
        proc = self._run("--selftest")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("通过", proc.stdout)

    def test_single_school_query(self):
        rows = query.load_index(query.INDEX)
        self.assertTrue(rows, "索引为空")
        name, _prov, _file = rows[0]
        proc = self._run(name, "--q", "2", "--limit", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("### Q:", proc.stdout)
        self.assertIn("判定口径", proc.stdout)

    def test_unknown_school_exit_two(self):
        proc = self._run("这所学校一定不存在大学", "--q", "2")
        self.assertEqual(proc.returncode, 2)

    def test_ambiguous_nickname_exit_two(self):
        proc = self._run("地大", "--q", "2")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("中国地质大学", proc.stderr)

    def test_compare_with_ambiguous_school_exit_two(self):
        proc = self._run("--compare", "地大", "华科", "--q", "2")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("可能指多所学校", proc.stderr)


if __name__ == "__main__":
    unittest.main()
