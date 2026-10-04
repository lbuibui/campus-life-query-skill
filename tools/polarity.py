#!/usr/bin/env python3
"""大学生活质量回答的极性判定器（按问题区分，纯标准库）。

为什么单独成模块、并按问题区分：

原实现是一个与问题无关的词表分类器（`query.classify`），它只看回答里有没有
「不 / 没 / 无 / 有 / 是」这些字。这在一个问题上勉强够用，在 25 个语义各异的
问题上则系统性失准。最典型的两类错误：

1. **主谓不分**。「不断电」在「每天断电断网吗」里是明确的否定，可到了「有独立
   卫浴吗」里，「不」字却出现在「不超过一千米」中，与卫浴无关；
2. **正反问不分**。「是上下铺」说的是「不是上床下桌」，但通用词表会同时命中
   「是」与「不是」，判成 mixed；「不贵」在「食堂贵吗」里是肯定，通用词表却先
   命中「贵」。

本模块的做法是把「判定什么」交给每个问题自己的规格（`Spec`）：

- `ex_yes` / `ex_no`：**专属名词**，一旦出现就基本定调
  （如「上床下桌」vs「上下铺」、「独立卫浴」vs「公共澡堂」、「限电」vs「不限电」）；
- `yes` / `no`：**通用说法**，用于补足不重复名词的省略回答
  （如「有」「可以」「没有」），但在判定前先剔除已被 `ex_no` / `no` 覆盖的片段，
  这样「不断电」里的「断电」、「没有空调」里的「有」不会再被当成肯定信号；
- 分校区 / 分化措辞（「部分」「有的」「看学院」）与转折词（「但」「不过」）会
  把结论降级为 `mixed`，因为这类回答本来就同时包含正反两面。

判定顺序是有意保守的：宁可给出 `unknown`（交回原文给人判断），也不替用户断言。
回归样例见 `tools/query.py --selftest` 与 `tests/test_polarity.py`。

用法：
    from polarity import classify, spec_for_heading, SPECS
    classify("不断电", spec_for_heading("每天断电断网吗，几点开始断？"))  # -> "no"
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Pattern

YES = "yes"
NO = "no"
MIXED = "mixed"
UNKNOWN = "unknown"
POLARITIES = (YES, NO, MIXED, UNKNOWN)

# 25 个问题在数据文件中的规范标题（不含 `Q:` 前缀与结尾问号），
# 必须与 tools/verify.py 的 CANONICAL_HEADINGS 一致。
CANONICAL_HEADINGS: tuple[str, ...] = (
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
)
N_QUESTIONS = len(CANONICAL_HEADINGS)


def _r(patterns: Iterable[str]) -> tuple[Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


# 分化 / 分校区措辞：命中即说明回答者不在断言单一结论
HEDGE = re.compile(
    r"部分|有的(?!话)|有些|一半|多数|少数|个别|大多|大部分|绝大部分|分校区|各校区"
    r"|不同校区|视(情况|校区|专业|学院)|取决于|看情况|看学院|看专业|看导员"
    r"|不一|不一定|有时|偶尔|好像|据说|听说|勉强"
)
# 转折：前后结论相反，整体按「分化」处理
CONTRAST = re.compile(r"但|不过|然而|可是|只是|除了|唯一")
# 明确表示「不知道 / 无法回答」的措辞：先剔除，再看剩下的内容有没有信号
UNKNOWN_PHRASES = re.compile(
    r"不清楚|不知道|不了解|不确定|记不清|记不太清|忘了|不好说"
)
# 含判定字形但语义中性的词（「有点小贵」里的「有」、「有没有」里的「有」），
# 在进入任何判定前统一剔除，避免被当成肯定信号
GLOBAL_NEUTRAL = re.compile(r"有点|有没有|有人说|有的话|有啊")
# 反问 / 元问题（「什么是断电，什么是断网」）：整条回答没有信息量，直接 unknown
FORCE_UNKNOWN = re.compile(r"什么是|什么叫|无意义|答非所问|怎么会有|这问题")
# 纯占位 / 无信息内容
NOISE = re.compile(r"^[\s.。…、,，\-—/\\|]+$|^(yes|no|无内容|略|同上|见上)$", re.IGNORECASE)
# 极短回答（整个回答只有这些字）：直接定调，避免「不」「无」落到 unknown
BARE_NO = frozenset({"不", "不是", "否", "没", "没有", "无", "🈚", "從來沒有", "从来没有"})
BARE_YES = frozenset({"是", "是的", "有", "能", "可以", "可", "行", "会", "当然"})


@dataclass(frozen=True)
class Spec:
    """一个问题（或某类自由文本）的判定规格。

    qid=0 表示非标准问题（如「自由补充部分」），此时不产生极性结论。
    """

    qid: int
    predicate: str
    yes_label: str
    no_label: str
    ex_yes: tuple[Pattern[str], ...] = ()
    ex_no: tuple[Pattern[str], ...] = ()
    yes: tuple[Pattern[str], ...] = ()
    no: tuple[Pattern[str], ...] = ()
    neutral: tuple[Pattern[str], ...] = field(default=())

    def heading(self) -> str:
        if 1 <= self.qid <= N_QUESTIONS:
            return CANONICAL_HEADINGS[self.qid - 1]
        return "自由补充部分"


def _make(
    qid: int,
    predicate: str,
    yes_label: str,
    no_label: str,
    *,
    ex_yes: Iterable[str] = (),
    ex_no: Iterable[str] = (),
    yes: Iterable[str] = (),
    no: Iterable[str] = (),
    neutral: Iterable[str] = (),
) -> Spec:
    return Spec(
        qid=qid,
        predicate=predicate,
        yes_label=yes_label,
        no_label=no_label,
        ex_yes=_r(ex_yes),
        ex_no=_r(ex_no),
        yes=_r(yes),
        no=_r(no),
        neutral=_r(neutral),
    )


# --- 通用兜底（非标准问题 / 无规格时） -------------------------------------
GENERIC = _make(
    0,
    predicate="（未指定问题）",
    yes_label="肯定",
    no_label="否定",
    ex_yes=(r"有|是|可以|能|允许|提供|配备|支持|发|给|方便|免费|充足|多|好|便利|近|便宜",),
    ex_no=(r"没有|無|无法|不能|不让|不允许|不给|不是|否|未|没(?![有事])",),
)
# 自由补充部分：不是问题，不做极性判定，一律 unknown
FREE = _make(0, "自由补充（不作极性判定）", "（不作判定）", "（不作判定）")

# --- 25 个问题的规格 --------------------------------------------------------
SPECS: tuple[Spec, ...] = (
    # Q01 上床下桌
    _make(
        1, "是上床下桌", "是上床下桌", "不是上床下桌",
        ex_yes=[r"上床下桌"],
        ex_no=[r"不是上床下桌|没有上床下桌|无上床下桌|非上床下桌",
               r"不是.{0,6}上床下桌|没有.{0,6}上床下桌|无.{0,6}上床下桌|非.{0,6}上床下桌",
               r"(?:是|为|成|属)?上下铺|(?:是|为|成|属)?上下床"],
        yes=[r"是的|是(?![上下])|有"],
        no=[r"不是|否|没有|沒|没(?![有事])|無|无|🈚"],
    ),
    # Q02 空调
    _make(
        2, "有空调", "有空调", "没有空调",
        ex_yes=[r"有空调|空调全覆盖|空调.*有"],
        ex_no=[r"没有空调|没空调|无空调|未装空调|没装空调|不装空调|没有装空调"],
        yes=[r"有|装了|配备|提供|覆盖"],
        no=[r"没有|沒有|没(?![有事])|無|无|🈚|否|未"],
    ),
    # Q03 独立卫浴
    _make(
        3, "有独立卫浴", "有独立卫浴", "无独立卫浴",
        ex_yes=[r"独立卫浴|独立浴室|独立卫生间|独卫|独浴"],
        ex_no=[r"没有独立|无独立|不是独立|公共浴室|公共卫浴|公共澡堂|大澡堂|澡堂|浴池|层浴"],
        yes=[r"有独立|有独卫|有.*卫浴|有.*浴室|有.*卫生间"],
        no=[r"没有|沒有|没(?![有事])|無|无|🈚|否"],
    ),
    # Q04 早晚自习
    _make(
        4, "有早晚自习", "有早晚自习", "无早晚自习",
        ex_yes=[r"有早晚自习|有早自习|有晚自习|早晚自习|早自习|晚自习|早读"],
        ex_no=[r"没有早晚自习|没有早自习|没有晚自习|无早晚自习|不设自习|没有自习|无自习",
               r"没有.{0,4}自习"],
        yes=[r"有|自习"],
        no=[r"没有|沒有|没(?![有事])|無|无|🈚|否"],
    ),
    # Q05 晨跑
    _make(
        5, "有晨跑", "有晨跑", "无晨跑",
        ex_yes=[r"有晨跑|有早操|有跑操|晨跑|早操|跑操"],
        ex_no=[r"没有晨跑|无晨跑|没有早操|无早操|不跑操"],
        yes=[r"有|跑"],
        no=[r"没有|沒有|没(?![有事])|無|无|🈚|否|不需要"],
    ),
    # Q06 跑步打卡
    _make(
        6, "有跑步打卡要求", "有跑步打卡要求", "无跑步打卡要求",
        ex_yes=[r"步道乐跑|乐跑|校园跑|有.*打卡|打卡.*(公里|km|次)|跑步.*(要求|公里|km)"],
        ex_no=[r"没有跑步打卡|没有打卡|无打卡|没有跑步|无跑步|没有要求|无要求|不要求|不需要"],
        yes=[r"打卡|公里|km|跑步|乐跑|校园跑|步道|\d+\s*(公里|km|次|圈)|^\d{2,}$|^\s*\d{2,}"],
        no=[r"没有|沒有|無|无|🈚|否|不要求|不需要|不用"],
    ),
    # Q07 小学期（假期长度本身不作极性断言，只判断「有没有小学期」）
    _make(
        7, "有小学期", "有小学期", "无小学期",
        ex_yes=[r"小学期"],
        ex_no=[r"没有小学期|无小学期|没小学期|不设小学期|无短学期|没有短学期"],
        yes=[],
        no=[],
    ),
    # Q08 外卖
    _make(
        8, "允许点外卖", "允许点外卖", "不允许点外卖",
        ex_yes=[r"允许点外卖|可以点外卖|能点外卖|允许外卖|支持.*外卖|允许|可以.*外卖"],
        ex_no=[r"不允许|不可以点|不能点外卖|禁止外卖|不让点|不能点|禁止.*外卖|没有外卖"],
        yes=[r"允许|可以|能|支持|送到|外卖"],
        no=[r"不允许|不可以|不能|禁止|不让|没有|無|无|否"],
    ),
    # Q09 交通
    _make(
        9, "交通便利", "交通便利", "交通不便利",
        ex_yes=[r"交通便利|很便利|便利|方便|有地铁|地铁站|市中心|在市区|校门口.*地铁"],
        ex_no=[r"不便利|不方便|很偏|偏远|郊区|深山|没有地铁|没地铁|无地铁|不在市区|没有公交"],
        yes=[r"便利|方便|有地铁|地铁站|市区|公交|近|直达|市中心"],
        no=[r"没有|沒有|没(?![有事])|無|无|🈚|否"],
    ),
    # Q10 洗衣机
    _make(
        10, "有洗衣机", "有洗衣机", "无洗衣机",
        ex_yes=[r"有洗衣机|洗衣机|洗衣房|洗衣桶"],
        ex_no=[r"没有洗衣机|无洗衣机|没洗衣机|没有洗衣|无洗衣"],
        yes=[r"有"],
        no=[r"没有|沒有|没(?![有事])|無|无|🈚|否"],
    ),
    # Q11 校园网（好坏）
    _make(
        11, "校园网好", "校园网好", "校园网差",
        ex_yes=[r"不错|很好|挺好的|很好用|很快|速度快|流畅|稳定|够用|尚可|还行|覆盖",
                r"免费|完美|nb|yyds"],
        ex_no=[r"垃圾|很差|差|不好|难用|很卡|卡顿|经常断|不稳定|不稳|不怎么样|不怎样",
               r"又贵|太贵|坑|拉胯|不行|烂|龟速|掉线"],
        yes=[r"好|快|稳定|流畅|够用|免费"],
        no=[r"差|卡|慢|断|不稳|贵|难用|垃圾"],
        neutral=[r"无线|无线网|没用过|没办"],
    ),
    # Q12 断电断网
    _make(
        12, "会断电断网", "会断电断网", "不会断电断网",
        ex_no=[r"不断电|不会断电|不断网|不会断网|不断(?![电网])|不会(?![断])|都不断|不熄灯",
               r"没有断电|没断电|无断电|没有断网|没断网"],
        ex_yes=[r"断电|断网|熄灯|会断"],
        yes=[r"断|熄灯"],
        no=[r"没有|沒有|没(?![有事])|無|无|🈚|否"],
    ),
    # Q13 食堂（贵 / 有异物）
    _make(
        13, "食堂贵或有异物", "贵/有异物", "不贵/无异物",
        ex_yes=[r"不贵|不算贵|很便宜|便宜|实惠|亲民|价格正常|价格适中|价格不高|卫生|好吃|干净",
                r"无异物|没吃出|没有吃出|没发现.*异物|没有发现.*异物"],
        ex_no=[r"(?<!不)(?<!算)贵|不便宜|涨价|虫子|苍蝇|钢丝|卫生差|不卫生|难吃|拉稀|生肉",
               r"(?<!没吃出过)(?<!没吃出)(?<!没有)(?<!无)(?<!发现)异物"],
        yes=[r"好吃|便宜|适中|正常|可以|干净"],
        no=[r"没有|沒有|没(?![有事])|無|无|否"],
    ),
    # Q14 洗澡热水
    _make(
        14, "全天有热水", "全天有热水", "无热水",
        ex_yes=[r"全天|24\s*小时|24h|一直有|一直供应|都有|不限时|随时"],
        ex_no=[r"没有热水|没热水|无热水|不供应热水|停热水"],
        yes=[r"供应|有|开放|可用"],
        no=[r"没有|沒有|没(?![有事])|無|无|否"],
    ),
    # Q15 电瓶车
    _make(
        15, "可以骑电瓶车", "可以骑电瓶车", "不可以骑电瓶车",
        ex_yes=[r"可以骑|能骑|可以.*电瓶车|能.*电瓶车|可以.*电动车|有充电桩|充电桩"],
        ex_no=[r"不可以|不能骑|禁止|不让|不行|禁电瓶|不让骑|禁止电瓶|不可以.*电瓶车|不允许充电"],
        yes=[r"可以|能|可|有充电"],
        no=[r"不可以|不能|禁止|不让|不行|没有|無|无|否"],
    ),
    # Q16 限电
    _make(
        16, "宿舍限电", "限电", "不限电",
        ex_yes=[r"限电|限制功率|限制.*(瓦|w)|跳闸|不允许大功率|禁用大功率|不能用大功率",
                r"不能用大型|不能使用.*电器|禁.*大功率|功率上限"],
        ex_no=[r"不限电|没有限电|没限电|不限制|不限功率"],
        yes=[r"\d+\s*[wW]|\d+\s*万?瓦|功率|瓦"],
        no=[r"没有|沒有|沒|無|无|否|不限|^没$"],
    ),
    # Q17 通宵自习
    _make(
        17, "有通宵自习去处", "有去处", "无去处",
        ex_yes=[r"有自习室|自习室|通宵|24\s*小时|24h|不关门|开放|可以去"],
        ex_no=[r"没有通宵|无通宵|不可通宵|不允许通宵|没有自习室|关门|封寝|必须回"],
        yes=[r"有|自习室|通宵|开放"],
        no=[r"没有|沒有|沒|無|无|否"],
    ),
    # Q18 电脑
    _make(
        18, "大一能带电脑", "能带电脑", "不能带电脑",
        ex_yes=[r"能带|可以带|当然可以|没人管|允许带"],
        ex_no=[r"不能带|不可以带|不让带|禁止带|禁止.*电脑|不能|不可以|不让|限制"],
        yes=[r"能|可以|可|允许|没人管"],
        no=[r"不能|不可以|不让|禁止|不行|没有|無|无|否"],
    ),
    # Q19 校园卡
    _make(
        19, "可用校园卡", "有校园卡", "无校园卡",
        ex_yes=[r"校园卡|一卡通|饭卡|学生卡|校园码|实体卡"],
        ex_no=[r"不用卡|无卡|没有卡|没有校园卡|无校园卡"],
        yes=[r"校园卡|一卡通|饭卡|学生卡"],
        no=[r"没有|沒有|沒|無|无|否|不用卡"],
    ),
    # Q20 银行卡
    _make(
        20, "学校发银行卡", "学校发银行卡", "不发银行卡",
        ex_yes=[r"会发|发.*银行卡|统一办|统一办理|学校发|会统一|发放|会给|会发一张|会发两张"],
        ex_no=[r"不会|不发|没有|无卡|自己办|自行办理|自己申请|自己申办|不统一",
               r"会让你|让你自己|要你自己|要自己办|自己去办"],
        yes=[r"会|统一办|发.*卡|有"],
        no=[r"不会|不发|没有|沒有|沒|無|无|否|自己办|自己申请|自行"],
    ),
    # Q21 超市
    _make(
        21, "超市好", "超市好", "超市差",
        ex_yes=[r"不错|很好|挺好的|方便|便宜|挺大|很大|东西全|挺全|种类多|挺多"],
        ex_no=[r"贵|小|差|少|破|坑|关门|空|没什么"],
        yes=[r"有|多|全|方便|好"],
        no=[r"没有|沒有|沒|無|无|否"],
    ),
    # Q22 快递
    _make(
        22, "快递方便", "快递方便", "快递不方便",
        ex_yes=[r"方便|可以收|能收|有驿站|菜鸟|快递点|快递柜|送到|免费|正常"],
        ex_no=[r"不方便|不送|不能送|要出去|校外|自取|禁止|没有驿站|没有快递点"],
        yes=[r"方便|驿站|菜鸟|快递|能收|可以|有"],
        no=[r"不方便|没有|沒有|沒|無|无|否|不能"],
    ),
    # Q23 共享单车
    _make(
        23, "有共享单车", "有共享单车", "无共享单车",
        ex_yes=[r"有共享单车|共享单车|哈啰|哈罗|美团单车|青桔|共享电单车"],
        ex_no=[r"没有共享|无共享|禁止共享|没有单车|无单车|没有共享单车"],
        yes=[r"有|单车|哈啰|青桔"],
        no=[r"没有|沒有|沒|無|无|否|禁止"],
    ),
    # Q24 门禁
    _make(
        24, "有门禁", "有门禁", "无门禁",
        ex_yes=[r"有门禁|门禁|刷卡|刷脸|查证|闸机|登记|凭证"],
        ex_no=[r"没有门禁|无门禁|没人管|不查|随便|自由出入"],
        yes=[r"门禁|刷卡|刷脸|查|闸机"],
        no=[r"没有|沒有|沒|無|无|否|不查"],
    ),
    # Q25 查寝
    _make(
        25, "会查寝", "查寝", "不查寝",
        ex_yes=[r"查寝|查卫生|封寝|点名|签到|查晚归"],
        ex_no=[r"不查寝|不查卫生|不封寝|不封|不会(?!查)|没有查|无查寝|不点名"],
        yes=[r"查|封寝|点名|签到"],
        no=[r"不查|不封|没有|沒有|沒|無|无|否"],
    ),
)

# 问题关键词路由表：用户用关键词问某个维度时，靠它定位到问题区块。
# 与 SPECS 同步维护；编号 1..25。
KEYWORDS: dict[int, tuple[str, ...]] = {
    1: ("上床下桌", "床", "宿舍", "上床", "上下铺"),
    2: ("空调",),
    3: ("卫浴", "澡堂", "浴室", "洗澡间", "独卫"),
    4: ("自习", "早读"),
    5: ("晨跑", "早操", "跑操"),
    6: ("跑步", "打卡", "公里", "骑车", "乐跑", "步道乐跑"),
    7: ("寒暑假", "暑假", "寒假", "小学期", "假期"),
    8: ("外卖",),
    9: ("交通", "地铁", "进城", "市区", "公交"),
    10: ("洗衣机",),
    11: ("校园网", "网络", "wifi", "宽带"),
    12: ("断电", "断网", "熄灯"),
    13: ("食堂", "异物", "饭菜", "吃饭"),
    14: ("热水", "供水"),
    15: ("电瓶车", "电动车", "充电"),
    16: ("限电", "跳闸", "功率"),
    17: ("通宵",),
    18: ("电脑",),
    19: ("校园卡", "饭卡", "一卡通", "刷卡"),
    20: ("银行卡",),
    21: ("超市", "小卖部"),
    22: ("快递", "收发", "菜鸟"),
    23: ("共享单车", "单车", "哈啰", "美团单车"),
    24: ("门禁", "查证", "刷脸", "出入"),
    25: ("查寝", "封寝", "晚归"),
}
assert set(KEYWORDS) == {s.qid for s in SPECS}, "KEYWORDS 与 SPECS 的问题编号必须一致"

# qid -> Spec（1..25），以及规范标题 -> Spec
BY_QID: dict[int, Spec] = {s.qid: s for s in SPECS}
assert len(BY_QID) == N_QUESTIONS, f"规格数量应为 {N_QUESTIONS}，实际 {len(BY_QID)}"


def _norm_heading(heading: str) -> str:
    """去掉 `Q:` 前缀、结尾问号与空白，便于标题匹配。"""
    h = heading.strip()
    if h.startswith("Q:"):
        h = h[2:]
    return h.strip().rstrip("？?").strip()


_BY_HEADING: dict[str, Spec] = {
    _norm_heading(s.heading()): s for s in SPECS
}
# 「自由补充部分」不是标准问题，单独指向 FREE（不作极性断言）
_BY_HEADING[_norm_heading("自由补充部分")] = FREE


def spec_for_heading(heading: str) -> Spec:
    """按区块标题取规格；自由补充部分返回 FREE，其余未识别标题返回 GENERIC。"""
    return _BY_HEADING.get(_norm_heading(heading), GENERIC)


def spec_for_qid(qid: int) -> Spec:
    return BY_QID.get(qid, GENERIC)


def normalize(text: str) -> str:
    """NFKC 归一化（全角→半角）+ 去首尾空白。"""
    return unicodedata.normalize("NFKC", text).strip()


def _spans(text: str, patterns: Iterable[Pattern[str]]) -> list[tuple[int, int]]:
    found: list[tuple[int, int]] = []
    for rx in patterns:
        for m in rx.finditer(text):
            found.append((m.start(), m.end()))
    return found


def _strip_spans(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text
    out: list[str] = []
    pos = 0
    for s, e in sorted(spans):
        if s > pos:
            out.append(text[pos:s])
        pos = max(pos, e)
    out.append(text[pos:])
    return "".join(out)


def _any(patterns: Iterable[Pattern[str]], text: str) -> bool:
    return any(rx.search(text) for rx in patterns)


def classify(text: str, spec: Spec | None = None) -> str:
    """把一条回答判定为 yes / no / mixed / unknown。

    判定顺序（有意保守，宁可 unknown 也不错判）：

    1. 归一化、剔除噪音与「不知道」类措辞；剩余为空则 unknown；
    2. 专属名词（`ex_no` / `ex_yes`）优先；命中 `ex_no` 时先把其覆盖的片段
       从文本中剔除，再判断是否仍有 `ex_yes`——这样「不是上床下桌」被整段判否，
       而「上床下桌但不是一人一桌」仍判是；
    3. 通用说法（`no` / `yes`）同理，先剔除 `no` 覆盖的片段再找肯定信号，
       避免「不断电」中的「断电」、「没有空调」中的「有」被反向计入；
    4. 正反同时出现、或出现分校区 / 转折措辞，一律降级为 mixed。
    """
    if spec is None:
        spec = GENERIC

    t = normalize(text)
    if not t or NOISE.search(t) or FORCE_UNKNOWN.search(t):
        return UNKNOWN
    for rx in (GLOBAL_NEUTRAL, *spec.neutral):
        t = rx.sub("", t)
    t = UNKNOWN_PHRASES.sub("", t).strip()
    if not t:
        return UNKNOWN
    # 没有任何判定模式的规格（如 FREE / 自由补充部分）一律 unknown，
    # 不因短答（「没」「无」）或分化措辞而产生极性结论。
    if not (spec.ex_yes or spec.ex_no or spec.yes or spec.no):
        return UNKNOWN
    if t in BARE_NO:
        return NO
    if t in BARE_YES:
        return YES

    hedge = bool(HEDGE.search(t)) or bool(CONTRAST.search(t))

    def generic_decide(segment: str) -> str | None:
        """在给定文本上做通用说法判定；无信号返回 None。"""
        spans = _spans(segment, spec.no)
        rest = _strip_spans(segment, spans) if spans else segment
        has_yes = _any(spec.yes, rest)
        if spans and has_yes:
            return MIXED
        if spans:
            return MIXED if hedge else NO
        if has_yes:
            return MIXED if hedge else YES
        return None

    # --- 第二层：专属名词 ---
    ex_no_spans = _spans(t, spec.ex_no)
    if ex_no_spans:
        rest = _strip_spans(t, ex_no_spans)
        # 「不是上床下桌」被整段剔除；「二校区有澡堂，一校区有独立卫浴」剩下肯定 → 分化
        if _any(spec.ex_yes, rest):
            return MIXED
        decided = generic_decide(rest)
        if decided in (YES, MIXED):
            return MIXED
        return MIXED if hedge else NO
    if _any(spec.ex_yes, t):
        return MIXED if hedge else YES

    # --- 第三层：通用说法 ---
    decided = generic_decide(t)
    if decided is not None:
        return decided

    # --- 第四层：没有任何极性信号 ---
    return MIXED if hedge else UNKNOWN


def classify_all(text: str, spec: Spec) -> str:
    """classify 的别名，保留给需要显式语义的调用方。"""
    return classify(text, spec)


# ---------------------------------------------------------------------------
# 回归样例：每条附带所属问题编号，供 --selftest 与 tests/ 共用
# ---------------------------------------------------------------------------
SELFTEST_CASES: tuple[tuple[int, str, str], ...] = (
    # 通用的正/反/分化
    (2, "有空调", YES),
    (2, "没有空调", NO),
    (2, "部分宿舍有空调", MIXED),
    (2, "教室随机，宿舍有空调", YES),
    (2, "宿舍没有空调，普通教室没有空调，机房会有", MIXED),
    (2, "无", NO),
    # 「是 / 不是」与专属名词：不能用通用词表
    (1, "少部分是", MIXED),
    (1, "是上下铺", NO),
    (1, "不是上床下桌", NO),
    (1, "上床下桌但不是一人一桌", MIXED),
    (1, "有的是有的不是", MIXED),
    # 反问 / 无法回答
    (12, "什么是断电，什么是断网", UNKNOWN),
    (12, "", UNKNOWN),
    # 关键词遮蔽：「不断电」不能被当成「断电」
    (12, "不断电", NO),
    (12, "不断电不断网", NO),
    (12, "不会哦！可爽了", NO),
    (12, "11点断网，11.30断电", YES),
    (12, "不断，但是十点半要熄灯", MIXED),
    (12, "不断电但会跳闸", MIXED),
    # 省略名词 + 转折
    (3, "没有独立卫浴，公共浴池最远不超过一千米", NO),
    (3, "有独立卫浴", YES),
    (3, "二校区澡堂在宿舍楼中，一校区1公寓有独立卫浴", MIXED),
    # 质量类问题：好坏方向由问题规格决定
    (11, "不怎么样 又贵又不好用", NO),
    (11, "很快，20M/s左右", YES),
    (11, "很卡", NO),
    (11, "宿舍无线接入约500Mbps", UNKNOWN),
    (13, "超级贵有异物", NO),
    (13, "价格便宜，味道一般", YES),
    (13, "不贵，有个食堂会", YES),
    # 不能骑车 / 能带电脑 / 发卡
    (6, "没有，不可以骑车", NO),
    (18, "能带电脑", YES),
    (18, "不能带电脑", NO),
    (20, "不会", NO),
    (20, "会，北部湾银行卡", YES),
    (20, "会让你自己申请", NO),
    (20, "不清楚", UNKNOWN),
)
