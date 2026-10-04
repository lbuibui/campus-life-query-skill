#!/usr/bin/env python3
"""极性判定器的回归测试。

用标准库 unittest 编写，既可 `python3 -m unittest discover -s tests`，
也可被 pytest 直接收集。测试内容分四类：

1. 规格完整性：25 个问题都有规格、编号/标题/关键词一致；
2. 数据驱动回归：`polarity.SELFTEST_CASES` 以及逐题的真实回答样例；
3. 问题感知：同一句话在不同问题下应得到不同结论（这是重写判定器的理由）；
4. 边界：空回答、反问、全角、纯短答、转折与分化措辞。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import polarity as P  # noqa: E402


class TestSpecs(unittest.TestCase):
    def test_exactly_25_specs_for_qid_1_to_25(self):
        self.assertEqual(len(P.SPECS), 25)
        self.assertEqual([s.qid for s in P.SPECS], list(range(1, 26)))

    def test_canonical_headings_match_verify_list(self):
        # 与 tools/verify.py 的 CANONICAL_HEADINGS 是同一份契约
        self.assertEqual(len(P.CANONICAL_HEADINGS), 25)
        for i, heading in enumerate(P.CANONICAL_HEADINGS, 1):
            self.assertTrue(heading.endswith("？"), heading)
            self.assertEqual(P.spec_for_qid(i).heading(), heading)

    def test_every_spec_has_a_predicate_and_labels(self):
        for spec in P.SPECS:
            with self.subTest(qid=spec.qid):
                self.assertTrue(spec.predicate)
                self.assertTrue(spec.yes_label)
                self.assertTrue(spec.no_label)
                self.assertTrue(spec.ex_yes or spec.ex_no or spec.yes or spec.no,
                                "规格没有任何判定模式")

    def test_keywords_cover_all_questions(self):
        self.assertEqual(set(P.KEYWORDS), set(range(1, 26)))
        for qid, words in P.KEYWORDS.items():
            self.assertTrue(words, f"Q{qid} 关键词为空")

    def test_spec_for_heading_tolerates_prefix_and_trailing_mark(self):
        for heading in P.CANONICAL_HEADINGS:
            stripped = heading.rstrip("？")
            self.assertIs(P.spec_for_heading(f"Q: {heading}"), P.spec_for_qid(
                P.CANONICAL_HEADINGS.index(heading) + 1))
            self.assertIs(P.spec_for_heading(stripped), P.spec_for_qid(
                P.CANONICAL_HEADINGS.index(heading) + 1))

    def test_free_form_heading_maps_to_free(self):
        self.assertIs(P.spec_for_heading("自由补充部分"), P.FREE)
        self.assertEqual(P.FREE.qid, 0)

    def test_truly_unknown_heading_falls_back_to_generic(self):
        self.assertIs(P.spec_for_heading("张三的碎碎念"), P.GENERIC)
        self.assertEqual(P.GENERIC.qid, 0)


class TestSelftestCases(unittest.TestCase):
    def test_all_selftest_cases(self):
        for qid, text, want in P.SELFTEST_CASES:
            with self.subTest(qid=qid, text=text):
                self.assertEqual(P.classify(text, P.spec_for_qid(qid)), want)


# 逐题的真实回答样例（来自 references/universities 抽样），期望值为人工核对结论。
PER_QUESTION_CASES: tuple[tuple[int, str, str], ...] = (
    # Q1 上床下桌
    (1, "是", P.YES),
    (1, "不是", P.NO),
    (1, "部分是", P.MIXED),
    (1, "是上下铺", P.NO),
    (1, "不是上床下桌", P.NO),
    (1, "不是传统的上床下桌", P.NO),
    (1, "上床下桌但不是一人一桌", P.MIXED),
    (1, "少部分是", P.MIXED),
    (1, "有的是有的不是", P.MIXED),
    (1, "分专业和男女，有的专业男生上床下桌", P.MIXED),
    # Q2 空调
    (2, "有", P.YES),
    (2, "无", P.NO),
    (2, "宿舍都有空调还有电风扇", P.YES),
    (2, "教室随机，宿舍有空调", P.YES),
    (2, "宿舍没有空调，普通教室没有空调，机房会有", P.MIXED),
    (2, "部分教室有，大部分没有。宿舍有空调", P.MIXED),
    # Q3 独立卫浴
    (3, "有", P.YES),
    (3, "没有独立卫浴", P.NO),
    (3, "无，三百米", P.NO),
    (3, "没有，澡堂距离宿舍400米左右", P.NO),
    (3, "有独立卫浴", P.YES),
    (3, "二校区澡堂在宿舍楼中，一校区1公寓有独立卫浴", P.MIXED),
    (3, "新北有，其他公寓大都在-1层", P.UNKNOWN),
    # Q4 早晚自习
    (4, "有", P.YES),
    (4, "没有", P.NO),
    (4, "大一有，大二没了", P.MIXED),
    (4, "大一有晚自习", P.YES),
    (4, "没有早自习，大一有晚自习", P.MIXED),
    (4, "没有统一早晚自习", P.NO),
    # Q5 晨跑
    (5, "无", P.NO),
    (5, "没有", P.NO),
    (5, "有", P.YES),
    (5, "大一有", P.YES),
    # Q6 跑步打卡
    (6, "无", P.NO),
    (6, "没有", P.NO),
    (6, "没有，不可以骑车", P.NO),
    (6, "85，可以骑车，没人管", P.YES),
    (6, "女生一次两公里，不允许骑车", P.YES),
    (6, "没有跑步打卡", P.NO),
    # Q7 小学期
    (7, "无小学期", P.NO),
    (7, "没小学期", P.NO),
    (7, "小学期一个月", P.YES),
    (7, "寒假2.5个月，暑假两个月，应无小学期", P.NO),
    (7, "就是正常的放假", P.UNKNOWN),
    # Q8 外卖
    (8, "允许", P.YES),
    (8, "允许点外卖，不远就100m", P.YES),
    (8, "不允许", P.NO),
    (8, "可以，送到楼上", P.YES),
    (8, "不清楚", P.UNKNOWN),
    # Q9 交通
    (9, "便利", P.YES),
    (9, "有地铁", P.YES),
    (9, "不便利，没地铁，在郊区", P.NO),
    (9, "交通便利，附近有两个地铁站，在市区", P.YES),
    (9, "不便利 地铁分校区 不在", P.MIXED),
    # Q10 洗衣机
    (10, "有", P.YES),
    (10, "无", P.NO),
    (10, "北区要自己买，其他好像有公共洗衣机也有洗衣房", P.MIXED),
    # Q11 校园网
    (11, "不怎么样 又贵又不好用", P.NO),
    (11, "很快，20M/s左右", P.YES),
    (11, "很卡", P.NO),
    (11, "还行", P.YES),
    (11, "一般", P.UNKNOWN),
    (11, "宿舍无线接入约500Mbps", P.UNKNOWN),
    # Q12 断电断网
    (12, "不断电", P.NO),
    (12, "11点断网，11.30断电", P.YES),
    (12, "不断电不断网", P.NO),
    (12, "不会哦！可爽了", P.NO),
    (12, "不断，但是十点半要熄灯", P.MIXED),
    (12, "不断电但会跳闸", P.MIXED),
    (12, "11点", P.UNKNOWN),
    (12, "什么是断电，什么是断网", P.UNKNOWN),
    # Q13 食堂
    (13, "价格便宜，味道一般", P.YES),
    (13, "超级贵有异物", P.NO),
    (13, "不贵，也没吃出过异物", P.YES),
    (13, "有点贵", P.NO),
    (13, "价格适中", P.YES),
    # Q14 热水
    (14, "全天", P.YES),
    (14, "一直有", P.YES),
    (14, "早上十点到晚上十点半", P.UNKNOWN),
    (14, "不清楚", P.UNKNOWN),
    # Q15 电瓶车
    (15, "不可以", P.NO),
    (15, "不能", P.NO),
    (15, "现在不可以骑了", P.NO),
    (15, "可以，有充电桩", P.YES),
    # Q16 限电
    (16, "800w", P.YES),
    (16, "不限电", P.NO),
    (16, "不能用大功率电器", P.YES),
    (16, "禁用大功率电器", P.YES),
    (16, "不清楚", P.UNKNOWN),
    # Q17 通宵自习
    (17, "没有", P.NO),
    (17, "有，寝室自习室", P.YES),
    (17, "图书馆十点关门", P.NO),
    (17, "通常没有，除非考研季节", P.NO),
    # Q18 电脑
    (18, "能", P.YES),
    (18, "不能", P.NO),
    (18, "可以，甚至可以外接显示器", P.YES),
    (18, "部分专业的辅导员有限制", P.MIXED),
    # Q19 校园卡
    (19, "校园卡", P.YES),
    (19, "一卡通", P.YES),
    (19, "不用卡", P.NO),
    # Q20 银行卡
    (20, "会", P.YES),
    (20, "不会", P.NO),
    (20, "会让你自己申请", P.NO),
    (20, "会，北部湾银行卡", P.YES),
    (20, "统一办理农业银行的", P.YES),
    # Q21 超市
    (21, "有点小贵", P.NO),
    (21, "挺多超市的，光711就有两个", P.YES),
    (21, "不知道", P.UNKNOWN),
    # Q22 快递
    (22, "方便", P.YES),
    (22, "不方便", P.NO),
    (22, "有驿站", P.YES),
    # Q23 共享单车
    (23, "有", P.YES),
    (23, "没有", P.NO),
    (23, "无", P.NO),
    # Q24 门禁
    (24, "十一点门禁", P.YES),
    (24, "没有门禁", P.NO),
    (24, "需要刷卡", P.YES),
    (24, "随便进出", P.NO),
    # Q25 查寝
    (25, "查寝", P.YES),
    (25, "不查", P.NO),
    (25, "偶尔查寝，会封寝", P.MIXED),
    (25, "不会 晚归登记能回", P.NO),
    (25, "不查，不封，可以", P.NO),
)


class TestPerQuestionCases(unittest.TestCase):
    def test_cases(self):
        for qid, text, want in PER_QUESTION_CASES:
            with self.subTest(qid=qid, text=text):
                self.assertEqual(P.classify(text, P.spec_for_qid(qid)), want)


class TestQuestionAwareness(unittest.TestCase):
    """同一句话在不同问题下结论可以不同——通用词表做不到这一点。"""

    def test_same_text_different_questions(self):
        text = "没有，有两个澡堂，步行距离都在五分钟内"
        self.assertEqual(P.classify(text, P.spec_for_qid(3)), P.NO)

    def test_negation_shadowing(self):
        # 「不断电」不能被当成「断电」肯定；「没有空调」不能被当成「有」肯定
        self.assertEqual(P.classify("不断电", P.spec_for_qid(12)), P.NO)
        self.assertEqual(P.classify("没有空调", P.spec_for_qid(2)), P.NO)

    def test_positive_negation_not_flipped(self):
        # 「不贵」在食堂问题里是肯定，不能被「贵」抢走
        self.assertEqual(P.classify("不贵", P.spec_for_qid(13)), P.YES)
        self.assertEqual(P.classify("不算贵", P.spec_for_qid(13)), P.YES)

    def test_qualified_yes_is_mixed(self):
        self.assertEqual(P.classify("是，但是该校分专业区分上床下桌", P.spec_for_qid(1)),
                         P.MIXED)


class TestEdgeCases(unittest.TestCase):
    def test_empty_and_whitespace(self):
        for text in ("", "   ", "\n"):
            self.assertEqual(P.classify(text, P.spec_for_qid(2)), P.UNKNOWN)

    def test_noise(self):
        for text in (".", "。", "略", "同上", "yes", "no"):
            self.assertEqual(P.classify(text, P.spec_for_qid(2)), P.UNKNOWN)

    def test_force_unknown_rhetorical(self):
        self.assertEqual(P.classify("什么是断电，什么是断网", P.spec_for_qid(12)),
                         P.UNKNOWN)
        self.assertEqual(P.classify("答非所问", P.spec_for_qid(2)), P.UNKNOWN)

    def test_unknown_phrase_but_real_signal_remains(self):
        # 「不清楚」被剔除后仍能从后半句得到结论；转折词把结论降级为分化
        self.assertEqual(
            P.classify("不清楚，但是我之前插了个蒸蛋器就跳闸了", P.spec_for_qid(16)),
            P.MIXED)

    def test_bare_short_answers(self):
        self.assertEqual(P.classify("不", P.spec_for_qid(12)), P.NO)
        self.assertEqual(P.classify("无", P.spec_for_qid(10)), P.NO)
        self.assertEqual(P.classify("有", P.spec_for_qid(10)), P.YES)

    def test_fullwidth_normalization(self):
        # 全角字母经 NFKC 归一化后仍能命中「w」
        self.assertEqual(P.classify("８００Ｗ", P.spec_for_qid(16)), P.YES)

    def test_hedge_without_polarity_is_mixed(self):
        self.assertEqual(P.classify("看学院", P.spec_for_qid(4)), P.MIXED)

    def test_generic_spec_when_none(self):
        self.assertEqual(P.classify("有空调"), P.YES)
        self.assertEqual(P.classify("没有空调"), P.NO)

    def test_free_spec_never_asserts(self):
        # 自由补充部分的规格没有任何判定模式，短答/分化措辞也不得产生结论
        self.assertEqual(P.classify("补充一句：图书馆很好", P.FREE), P.UNKNOWN)
        self.assertEqual(P.classify("没", P.FREE), P.UNKNOWN)
        self.assertEqual(P.classify("部分宿舍", P.FREE), P.UNKNOWN)

    def test_classify_all_alias(self):
        self.assertEqual(
            P.classify_all("有", P.spec_for_qid(2)),
            P.classify("有", P.spec_for_qid(2)))


class TestHelpers(unittest.TestCase):
    def test_strip_spans_handles_overlap(self):
        text = "abcdef"
        # 重叠片段按并集剔除（[0,3)），不重复删字符
        self.assertEqual(P._strip_spans(text, [(0, 2), (1, 3)]), "def")
        self.assertEqual(P._strip_spans(text, [(2, 4)]), "abef")
        self.assertEqual(P._strip_spans(text, []), text)

    def test_normalize_nfkc_and_strip(self):
        self.assertEqual(P.normalize("  ８００Ｗ  "), "800W")


if __name__ == "__main__":
    unittest.main()
