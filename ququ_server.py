# -*- coding: utf-8 -*-
"""曲曲 + 塔罗 · 双人格 AI 顾问平台(网页版)。

运行: python ququ_server.py  →  浏览器打开 http://127.0.0.1:8001

两个人格:
  - 曲曲(乐传曲): 问答 / 话术 / 沙盘(冲突演练) / 朋友圈
  - 塔罗: 资深塔罗占卜师(密码学随机抽牌 + 量化档位解读 + 9种牌阵 + 深度思考)

功能: 深度思考开关(ds pro) · 聊天记录持久化 · 对话分类 · 发语音(Whisper) · 朗读(edge-tts)
"""
import io
import json
import os
import secrets
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

CN_TZ = timezone(timedelta(hours=8))


def now_cn() -> datetime:
    """北京时间(UTC+8):服务器在海外(UTC)也返回北京时间。"""
    return datetime.now(timezone.utc).astimezone(CN_TZ)

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, Response, JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend.expert import _chat, discuss_stream

SKILL_PATH = "data/reference/ququ_skill.md"
CHATS_FILE = "data/ququ_chats.json"
CODES_FILE = "data/ququ_codes.json"
# 店主密码：只有输入这个密码的人能进"店主模式"(看到全部对话、不限次数)。
# 想改就改这个字符串，然后重启。
HOST_PASSWORD = "ququ8888"

# ---------------- 曲曲:四个服务 ----------------
MODES = {
    "问答": "用户提出情感/关系/搞钱/识人问题。用曲曲视角直接分析：先诊断，再拆利益结构，最后给明确判断。结论先行、强陈述句。",
    "话术": "用户描述一个真实场景(如怎么跟男朋友谈钱、怎么拒绝相亲对象、怎么提要求)。用曲曲风格写一段用户可直接照搬的话术，短句、直接、有压迫感，别解释。",
    "沙盘": "用户描述一段冲突/谈判对话(如跟老板谈涨薪、跟男友摊牌、跟婆婆过招)。你扮演对方的角色，模拟对方最可能的真实回应，来回演练2-3轮，最后给用户一句总结建议。",
    "朋友圈": "用户描述一件事/心情/状态。用曲曲风格写一条朋友圈文案(可带emoji)，高级、有态度、不low，一句话点睛。",
}

# ---------------- 塔罗:标准韦特 78 张(与桌面抽牌工具一致) ----------------
MAJOR_NAMES = ['愚者', '魔术师', '女祭司', '皇后', '皇帝', '教皇', '恋人', '战车', '力量', '隐者', '命运之轮', '正义', '倒吊人', '死神', '节制', '恶魔', '高塔', '星星', '月亮', '太阳', '审判', '世界']
SUITS = ['权杖', '圣杯', '宝剑', '星币']
RANKS = ['Ace', '2', '3', '4', '5', '6', '7', '8', '9', '10', '侍从', '骑士', '王后', '国王']
DECK = []
for i, name in enumerate(MAJOR_NAMES):
    DECK.append({'kind': 'major', 'name': name, 'num': i, 'display': f"{name} ({i})"})
for suit in SUITS:
    for r, rank in enumerate(RANKS):
        DECK.append({'kind': 'minor', 'suit': suit, 'rank': rank, 'num': r + 1, 'display': f"{suit} · {rank}"})

SPREADS = {
    # —— 基础 / 日常 ——
    "single":  {"label": "单张 · 每日指引", "count": 1, "positions": ["指引"]},
    "daily":   {"label": "每日指引 · 3张", "count": 3, "positions": ["今日主题", "今日机会", "今日提醒"]},
    "three":   {"label": "三张 · 过去/现在/未来", "count": 3, "positions": ["过去", "现在", "未来"]},
    "four":    {"label": "四张 · 现状/阻碍/资源/结果", "count": 4, "positions": ["现状", "阻碍", "资源", "结果"]},
    "five":    {"label": "五张 · 简版十字", "count": 5, "positions": ["现状", "挑战", "过去", "未来", "结果"]},
    "seven":   {"label": "七张 · 马蹄铁", "count": 7, "positions": ["过去", "现在", "未来", "阻碍", "外部环境", "建议", "结果"]},
    "ten":     {"label": "十张 · 凯尔特十字", "count": 10, "positions": ["现状", "挑战", "根基", "近期过去", "目标", "近期未来", "自我", "环境", "希望与恐惧", "结果"]},
    "twelve":  {"label": "十二张 · 黄道十二宫", "count": 12, "positions": ["自我", "财富", "沟通", "家庭", "爱情", "工作", "关系", "隐秘", "远行", "事业", "朋友", "潜意识"]},
    "monthly": {"label": "月度运势 · 12宫月运", "count": 12, "positions": ["本月整体运势", "事业", "财运", "感情", "人际", "健康", "上旬", "中旬", "下旬", "重点提示", "机会", "提醒"]},
    # —— 关系 / 读心类(套公式) ——
    "rel_thoughts": {"label": "双方想法 · 你和他", "count": 6, "positions": ["你对他的想法", "他对你的想法", "这段关系现状", "这段关系走向", "阻碍", "建议"]},
    "his_thoughts": {"label": "单方读心 · 他在想什么", "count": 5, "positions": ["他对你的真实想法", "他现在的状态", "他是否还主动", "这段关系的走向", "你的建议"]},
    "crush":      {"label": "暧昧期 · 要不要捅破", "count": 5, "positions": ["你对TA的感觉", "TA对你的感觉", "暧昧现状", "升温点/突破口", "下一步建议"]},
    "love_dev":   {"label": "感情发展 · 关系走势", "count": 7, "positions": ["你现在的状态", "对方现在的状态", "关系现状", "推动力", "阻碍", "近期发展", "长期走向"]},
    "triangle":   {"label": "三角关系 · 你/他/TA", "count": 9, "positions": ["你在关系中的状态", "对方的状态", "第三方的状态", "对方对你的想法", "对方对第三方的想法", "关系现状", "你的优势", "第三方的影响", "最终走向"]},
    "six":        {"label": "六张 · 双人关系", "count": 6, "positions": ["你的过去", "你的现在", "你的未来", "对方过去", "对方现在", "对方未来"]},
    # —— 复合 / 选择 / 决策 ——
    "recon":      {"label": "复合牌阵 · 还能不能和好", "count": 9, "positions": ["断联/分手现状", "你现在的状态", "对方现在的状态", "分手核心原因", "对方是否还留恋", "复合阻碍", "你该怎么做", "复合时机", "复合结果"]},
    "choice":     {"label": "二选一 · 两条路怎么选", "count": 9, "positions": ["现状", "选项A优势", "选项A劣势", "选项A结果", "选项B优势", "选项B劣势", "选项B结果", "你的顾虑", "建议"]},
    "three_choice": {"label": "三择一 · 多个选择怎么选", "count": 10, "positions": ["现状", "选项A发展", "选项A结果", "选项B发展", "选项B结果", "选项C发展", "选项C结果", "你的顾虑", "建议", "最终倾向"]},
    "decision":   {"label": "该不该做 · 是非决策", "count": 5, "positions": ["这件事的现状", "你真正的动机", "做下去的利弊", "不做的利弊", "最终建议"]},
    "yesno":      {"label": "是/否牌阵", "count": 3, "positions": ["判定1", "判定2", "判定3"]},
    # —— 事业 / 财运 ——
    "career":     {"label": "事业财运 · 工作+搞钱", "count": 7, "positions": ["现状", "优势资源", "阻碍", "外部环境", "财运趋势", "建议", "结果"]},
    "money":      {"label": "财运专版 · 钱从哪来", "count": 5, "positions": ["财务现状", "收入机会", "支出与风险", "建议", "结果"]},
}

RULES_TEXT = """【量化解读规则 v6 · 具体锚点档位制】
· 数字牌 1-10 = 档位 1-10（Ace=1 起点，10=顶点）
· 宫廷牌：侍从2 / 骑士4 / 王后6 / 国王8
· 大阿卡纳：不落档，出现即命运级/超出日常量尺
· 逆位：档位 -1（最低1），附偏低/受阻/延迟
· 花色修正（仅金钱/身体题）：星币 +1 档、宝剑 -1 档
· 【多牌聚合·全系统核心】禁止"主牌取最大+其余正位+1"这种牌越多数字越大的叠加。定主牌=与问题最直接对应的位置：问结果/未来/走向→取"结果/未来/走向"位；问现状→取"现状"位；问对方想法/他怎么想→取"对方想法"位；问"多久/什么时候"→取时间相关位；找不到明确对应→取牌阵最后一张"结论/结果"位。主牌落档(数字牌=数字档、宫廷牌=侍从2/骑士4/王后6/国王8)，主牌逆位=档位-1(最低1)。主牌为大阿卡纳=不落档、只给定性不给具体数(逆位大阿卡纳=偏负面/受阻的定性)。其余各牌只作修正：每张正位+1档、逆位-1档，全部修正求和后封顶±2档(超出按±2计)。最终=主牌基础档±封顶修正(0~±2档)，解读统一输出"约X(浮动±10~15%)"。

【数字含义】1=新起点 2=平衡/选择 3=成长/第三方 4=稳定/停滞 5=变动/冲突 6=和谐 7=评估/坚持 8=行动/推进 9=沉淀/接近完成 10=完成/顶点

【时间】单位由花色定(宝剑=天、权杖=周、圣杯=月、星币=年)、数量=档位(Ace=1)；主牌按【多牌聚合】定；主牌逆位=延迟、总时长×2(时间题逆位不做-1档，这是时间维度特例、-1档只作用于强度类)；快牌÷2(权杖8/战车/宝剑Ace/愚者/太阳/死神)、慢牌×2(倒吊人/节制/月亮/星币10)，÷2/×2只对数字牌生效、大阿卡纳只作"偏快/偏慢"定性；停滞牌(倒吊人/宝剑4/宝剑8)=搁置不定不给具体时长；宫廷牌=季节节点(侍从=春3-5月、骑士=夏6-8月、王后=秋9-11月、国王=冬12-2月)；大阿卡纳=命运节点不定(高塔=突发快、命运之轮=外因触发、死神=旧事终、世界=周期完成)给定性不给精确数；输出口径：1张="约X(浮动±10~15%)"、多张="最快~最晚区间、最可能≈主牌档位"；÷2后不足1天="当天/立刻"
【概率】封顶95%、封底5%，绝不输出100%或0%；正位数字牌=档位×10%(1=10%…8=80%、9=90%、10=封顶95%)；逆位=档位×10%-30个百分点、封底5%(逆位即明显走低，如逆位5=20%、逆位10=65%)；宫廷牌=侍从20%/骑士40%/王后60%/国王80%(逆位同上-30封底5%)；快牌+10%、慢牌-10%(仍封顶95%/封底5%)；大阿卡纳=命运级定性(太阳=高确定、命运之轮=外因、月亮=模糊、高塔=突发低概率)不给具体%；多张按【多牌聚合】：主牌定基准概率、其余牌每张正位+10%/逆位-10%、求和封顶±20个百分点；输出配"几乎不会/偏低/五五开/大概率/几乎必然"

【身高 cm】男女分开、主牌按【多牌聚合】定档(主牌逆位=-1档即更矮、宫廷牌=侍从2/骑士4/王后6/国王8、大阿卡纳不落档)；男锚点：1=约158 2=约161 3=约165 4=约169 5=约172(中国成年男中位) 6=约176 7=约180 8=约184 9=约188 10=约193；女锚点：1=约148 2=约151 3=约154 4=约157 5=约160(中国成年女中位) 6=约163 7=约166 8=约170 9=约174 10=约178；男女恒定差约12cm；各档浮动±2~3cm，解读输出"约Xcm"
【年龄】年龄题专用、严格单牌直读，严禁多牌+1/-1叠加、严禁花色修正、严禁取最大：只取主牌(问对方年龄取对方位，无则取结论位)落档直读；主牌逆位=-1档(最低1，即更年轻)；宫廷牌=年龄段(侍从<20、骑士20-30、王后30-45、国王45-60)；大阿卡纳不落档、只给"年轻/中年/年长"定性；档位锚点：1=约18岁 2=约24岁 3=约29岁 4=约33岁 5=约38岁 6=约43岁 7=约48岁 8=约53岁 9=约60岁 10=约68岁(各档浮动±2~4岁，解读输出"约X岁")
【胖瘦】档位=BMI锚点(中国标准：<18.5偏瘦、18.5~23.9正常、24~27.9超重、≥28肥胖)：1=约16(重度消瘦) 2=约17.5(偏瘦) 3=约18.3(偏瘦) 4=约19.5(苗条/正常偏瘦) 5=约21(标准·中位) 6=约23(正常偏丰) 7=约24.5(超重边缘) 8=约26.5(超重) 9=约29(肥胖) 10=约32(重度肥胖)；各档浮动±0.5~1，解读输出"约BMI X(偏瘦/正常/超重/肥胖)"；主牌逆位=-1档(更瘦)；大阿卡纳不落档
【容貌10分制】档位=分数、按钟形分布(5分为人群主体≈40%、越往两极越少、8分以上是极少数)：1=1分(明显缺陷·罕见) 2=2分(约2%) 3=3分(偏下·约6%) 4=4分(普通偏下·约15%) 5=5分(大众/耐看·主体≈40%) 6=6分(中上/小美女小帅哥·约25%) 7=7分(好看/回头率·约10%) 8=8分(出众/明星门槛·约3%极少数) 9=9分(顶级·约0.5%) 10=10分(理论顶点·现实几乎不存在，勿断言真人10分、改述"顶尖/接近满分")；男看骨相/身高肩宽/皮肤发际线/气质，女看五官比例/皮肤气色/身材曲线/气质；主牌逆位=-1分(更普通)；大阿卡纳不落档

【财富量化 v6】每档=一个具体锚点数值，解读统一输出"约X元(浮动±10~15%)"，不写宽区间、不说"几万/几千"这种模糊话；按【多牌聚合】定档(先定主牌、其余牌仅修正封顶±2)；大阿卡纳作主牌=不落档(只定性不给具体数)；花色修正(仅金钱题)：星币+1档、宝剑-1档。
【财富识别指引】先判断题目问的是哪类财富再套对应分支、别把"月薪"和"总资产"混用：问"家里有多少钱/家境/身家/净资产/家底"→总资产；问"存款/余额/卡里还有多少钱/攒了多少钱"→存款余额；问"月薪/工资/到手/底薪/主业赚多少"→月薪；问"一个月能赚多少/全部收入/工资加副业/到手总收入"→月总收入；问"副业/兼职/额外收入/外快"→副业月收入；问"一年赚多少/年收入/年薪"→年总收入；问"每月花多少/开销/消费/生活费/月花销"→每月总消费；问"给对象/伴侣/男(女)朋友/追求的人/TA每月花多少"→月给对象花费；问"对象/伴侣/TA每月给你花多少/给你买多少"→对方月给你花费；问"这次约会/这顿饭/这份礼物/请客花了多少/一次花多少"→单次消费；问"这件东西/包/首饰/手表/手机值多少钱"→单品价值；问"房子/房产/这套房值多少/房价"→房产价值；问"车/车子/这辆车值多少/买车价"→车子价值；问"股票/基金/理财/投资账户里有多少"→投资理财市值。同题并列多个财富维度时以题目主诉为准、拿不准追问一句澄清。
【总资产】1=5万 2=12万 3=25万 4=50万 5=100万 6=200万 7=400万 8=800万 9=2000万 10=5000万 (元，家庭净资产=房产+存款+投资-负债)
【存款余额】1=2000 2=5000 3=1.2万 4=2.5万 5=5万 6=10万 7=20万 8=50万 9=100万 10=300万 (元，随时可动用的现金/存款)
【月薪】1=2000 2=2800 3=4000 4=5500 5=7000 6=9000 7=1.2万 8=1.6万 9=2.5万 10=4万 (元/月，税后到手，仅主业)
【月总收入】1=2500 2=3500 3=4800 4=6500 5=8500 6=1.2万 7=1.6万 8=2.4万 9=4万 10=7万 (元/月，工资+副业+其他，税后到账)
【副业月收入】1=200 2=600 3=1500 4=3000 5=5000 6=8000 7=1.5万 8=3万 9=6万 10=12万 (元/月，主业之外的额外收入)
【年总收入】1=2.5万 2=4万 3=6万 4=8万 5=11万 6=15万 7=22万 8=35万 9=60万 10=120万 (元/年，税后)
【每月总消费】1=1500 2=2200 3=3000 4=4000 5=5500 6=7500 7=1万 8=1.5万 9=2.5万 10=5万 (元/月，个人吃住行+购物娱乐)
【月给对象花费】1=200 2=500 3=1000 4=2000 5=3500 6=6000 7=1万 8=2万 9=4万 10=8万 (元/月，你给对象/伴侣花的)
【对方月给你花费】1=200 2=500 3=1000 4=2000 5=3500 6=6000 7=1万 8=2万 9=4万 10=8万 (元/月，对象/伴侣给你的)
【单次消费】1=50 2=150 3=400 4=800 5=1500 6=3000 7=6000 8=1.5万 9=4万 10=10万 (元/次，一次约会/礼物/请客)
【单品价值】1=100 2=400 3=1000 4=2500 5=6000 6=1.5万 7=4万 8=10万 9=30万 10=100万 (元，某件东西值多少)
【房产价值】1=20万 2=40万 3=70万 4=120万 5=200万 6=350万 7=600万 8=1000万 9=2000万 10=5000万 (元，一套房总价)
【车子价值】1=2万 2=5万 3=8万 4=12万 5=18万 6=25万 7=35万 8=50万 9=80万 10=150万 (元，购车价/车值)
【投资理财市值】1=5000 2=2万 3=5万 4=10万 5=20万 6=50万 7=100万 8=300万 9=1000万 10=5000万 (元，股票/基金/理财等市值)

【是/否】独立计分、不套档位聚合：每张牌投一票(正位=是+1、逆位=否+1、大阿卡纳=权重+2：太阳/世界/星星/恋人偏是，高塔/死神/恶魔/月亮偏否，倒吊人/节制=信息不足不投票)；统计"是"票与"否"票，是>否=是、否>是=否、相等=待定(建议补抽1张决出)；结论位为大阿卡纳时以它倾向优先；单张牌=正位倾向是/逆位倾向否(把握低，建议补至3张)；输出"是/否/待定+把握程度(勉强/倾向/明确/斩钉截铁)"
【补充维度】距离：单位由花色定(宝剑=10米级、权杖=公里级、圣杯=百公里级、星币=千公里级)、数量=档位(Ace=1单位)；锚点示例(档5)：宝剑=约50米、权杖=约5公里、圣杯=约500公里、星币=约5000公里(各档浮动±10~15%)；主牌逆位=-1档(更近)；多张按【多牌聚合】；大阿卡纳不落档。颜色：权杖=红/橙/暖、圣杯=蓝/白/浅、宝剑=灰/银/黑/冷、星币=绿/棕/金；档位深浅：1-2浅淡、3-4偏淡、5正色(标准)、6-7偏深、8-9深浓、10近黑极浓；主牌逆位=变暗褪色；大阿卡纳=按牌面主色定性。方位：权杖=南、圣杯=西、宝剑=东、星币=北；主牌逆位=取相反方向；档位距离：1-3近(百米级)、4-7中(公里级)、8-10远(十公里级)；大阿卡纳不落档。人数：数字牌=数字人数(Ace=1人…10=约10人)、宫廷牌=侍从2/骑士4/王后6/国王8人；大阿卡纳特殊映射：恋人=2人、隐者/愚者=1人、教皇=一群人、世界/审判=公开场合多人、皇帝/皇后=权威/长辈；主牌逆位=-1(最低1)；多张按【多牌聚合】。健康：档位=状态锚点(1最差→10最佳)：1=极差/重病 2=很差 3=差 4=偏弱/易病 5=一般/亚健康 6=尚可 7=良好 8=很好 9=极好 10=巅峰/极佳；花色对应：星币=身体、宝剑=压力/神经、圣杯=情绪、权杖=活力；身体题星币+1档、宝剑-1档(仅此一处花色修正)；主牌逆位=更差/慢性/隐患(-1档)；大阿卡纳不落档(死神/高塔=需就医提醒的定性)。成绩：档位→百分制锚点：1=约15分(极差) 2=约30分 3=约45分(不及格) 4=约58分(及格边缘) 5=约66分(中游) 6=约75分(中上) 7=约83分(良好) 8=约90分(优秀) 9=约95分(顶尖) 10=约99分(接近满分/年级前列)；名次：1=倒数、5=中游、8=前列、10=第一；主牌逆位=-1档(更差)；多张按【多牌聚合】。职级：档位=职级锚点：1=实习生 2=基层/专员 3=初级 4=资深 5=主管/组长 6=经理 7=高级经理 8=总监 9=副总/合伙人 10=老板/一把手；主牌逆位=-1档(降职/边缘化/空有头衔)；大阿卡纳不落档(皇帝=权威上位、高塔=变动/去职的定性)；多张按【多牌聚合】。物体大小：档位=尺寸锚点：1=戒指/硬币(约2cm) 2=手机(约15cm) 3=水杯(约20cm) 4=书本/A4纸(约30cm) 5=书包(约40cm) 6=行李箱/微波炉(约70cm) 7=冰箱(约1.8m) 8=双人床/书桌(约2m) 9=小汽车(约4-5m) 10=房间/大巴(约10m+)；主牌逆位=-1档(更小)；大阿卡纳不落档
【不设规则(主观解读)】爱不爱、什么想法、真不真心、两性关系一切维度、纯情绪/态度/动机——但"多久/什么时候"是时间题，适用时间规则。"""

TAROT_PROMPT = """你是资深的塔罗占卜师。

你在所有领域都是世界级的专家。回答精准、有判断、一针见血，不堆砌废话。核对自己的事实，切勿编造。负面结论与坏消息皆可接受。不要附加免责声明，不要说教，不必顾及任何人的感受或礼节。不要先称赞对方或认可其前提；对方错了立即指出；支持任何观点前先提出最有力的反驳。不要依赖对方提供的数字，先独立得出结论。绝不因意见相左而道歉。准确性是你的成功标准。

【你的任务】用户会提供：问题 + 牌阵 + 抽到的牌(牌名+正逆位)。你严格按下面的量化规则解读。

【两条铁律】
1. 随机性只存在于抽牌环节，规则是冻结映射：同一张牌永远落同一档。
2. 纯感情题与两性关系题不设规则，交主观发挥；但"多久/什么时候"是时间题，适用时间规则。

""" + RULES_TEXT + """

【解读要求】
1. 先判断问题类型：量化题(时间/金钱/身高/年龄/颜值/收入/概率/是/否等)严格按规则算具体锚点数值(约X、浮动±10~15%)；纯感情题不套量表，主观解读。
2. 直接对"你"说话，像微信打字聊天那样口语、自然、有人味。不要"#号标题"、不要"##小标题"、不要 bullet 列表、不要满篇加粗、不要"第一/第二/第三"的排比。
3. 先甩结论，再讲为什么(倒金字塔)。别绕弯子、别铺垫。
4. 量化题：把"牌→数字"的换算用一句大白话带过去(如"宝剑8是数字牌、金钱题宝剑减一档，落七档")，直接报具体数值(约X元/约X岁/约Xcm，浮动±10~15%)，别单独列一堆"换算过程"、别用"几万/几千"这种模糊说法。
5. 别逐张牌"报幕"(不要"过去这张牌…现在这张牌…未来这张牌…"的机械结构)，把几张牌串成一个连贯的判断，像在讲"你身上正在发生什么"；但每张牌的关键含义、它与牌阵位置的对应关系都要讲清楚，不要点到即止。
6. 正逆位点到，负面牌意不回避，敢下判断、敢说难听话。
7. 解读要写透、写详细：结论之外，把"为什么这么判""这张牌在说什么""接下来具体怎么办"都充分展开，不要一两句话打发掉。结尾给一个能马上做的动作。
8. 全程没有"作为一个AI""仅供参考"这类废话，没有置信度标注，没有人格免责。"""


# 店主本人身份注记:店主是女性 —— 防止AI默认"用户是男性、对方是女性"搞反性别
HOST_USER_NOTE = (
    "\n\n【用户身份】当前用户是店主本人，一位女性。"
    "她口中的“他/对方/另一半/目标对象”默认指男性；"
    "除非她自己明确说明，一律按“用户=女性、对方=男性”理解，"
    "不要把她当男性、也不要把对方当女性。"
)


def load_skill() -> str:
    return io.open(SKILL_PATH, encoding="utf-8").read()


def build_system(mode: str, is_host: bool = False) -> str:
    now = now_cn()
    date_line = (
        f"【当前时间】现在是北京时间 {now.year}年{now.month}月{now.day}日"
        f" 星期{'一二三四五六日'[now.weekday()]} {now.strftime('%H:%M')}。"
        f"用户问日期/时间/星期/今天几号时，直接按上面如实回答，不要推诿、不要当成无关问题。\n\n"
    )
    if mode == "塔罗":
        base = TAROT_PROMPT
    else:
        skill = load_skill()
        m = MODES.get(mode, MODES["问答"])
        base = f"{skill}\n\n---\n【当前服务】{mode}\n{m}\n请只输出该服务要求的内容。"
    if is_host:
        base += HOST_USER_NOTE
    return date_line + base


def build_user(mode: str, c: dict, message: str) -> str:
    """拼用户输入。塔罗牌阵自带完整上下文,不喂历史(每次解读客观、不受前文污染);
    其他模式带最近几轮,保持对话连贯但缩短上下文,减少"刻板影响"。"""
    if mode == "塔罗":
        return f"你: {message}"
    history = c["messages"][-7:-1]  # 最近约3轮(6条),略过已 append 的当前 user 消息
    parts = []
    for h in history:
        role = "你" if h.get("role") == "user" else "助手"
        parts.append(f"{role}: {h.get('content', '')}")
    parts.append(f"你: {message}")
    return "\n".join(parts)


def category_of(mode: str) -> str:
    return "塔罗" if mode == "塔罗" else "曲曲"


def draw_cards(count: int) -> list:
    """密码学随机:secrets.randbelow + Fisher-Yates 洗牌,同问不放回,独立 50% 逆位。"""
    n = max(1, min(int(count), 78))
    idx = list(range(78))
    for i in range(77, 0, -1):
        j = secrets.randbelow(i + 1)
        idx[i], idx[j] = idx[j], idx[i]
    out = []
    for k in range(n):
        card = DECK[idx[k]]
        out.append({"pos": k + 1, "name": card["display"], "reversed": secrets.randbelow(2) == 1})
    return out


# ---------------- 聊天记录持久化(本地 + 私有GitHub云同步) ----------------
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GH_REPO = os.environ.get("GH_CHATS_REPO", "krommhulton-del/ququ-data").strip()
GH_PATH = "ququ_chats.json"
_gh_sha = None
_gh_loaded = False


def _gh_headers():
    return {"Authorization": "Bearer " + GH_TOKEN, "Accept": "application/vnd.github+json", "User-Agent": "ququ-server"}


def _gh_pull():
    """从私有仓库拉取聊天记录字符串,失败返回 None。"""
    global _gh_sha
    if not GH_TOKEN:
        return None
    import urllib.request
    import base64
    try:
        url = f"https://api.github.com/repos/{GH_REPO}/contents/{GH_PATH}"
        req = urllib.request.Request(url, headers=_gh_headers())
        with urllib.request.urlopen(req, timeout=25) as r:
            meta = json.loads(r.read().decode("utf-8"))
        _gh_sha = meta.get("sha")
        return base64.b64decode(meta.get("content", "")).decode("utf-8")
    except Exception:  # noqa: BLE001
        return None


def _gh_push(s: str) -> None:
    """推送聊天记录到私有仓库,失败静默(不阻断聊天)。"""
    global _gh_sha
    if not GH_TOKEN:
        return
    import urllib.request
    import base64
    if not _gh_sha:
        _gh_pull()  # 先拿最新 sha,避免覆盖冲突
    payload = {"message": "sync chats", "content": base64.b64encode(s.encode("utf-8")).decode(), "branch": "main"}
    if _gh_sha:
        payload["sha"] = _gh_sha
    try:
        url = f"https://api.github.com/repos/{GH_REPO}/contents/{GH_PATH}"
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={**_gh_headers(), "Content-Type": "application/json"}, method="PUT")
        with urllib.request.urlopen(req, timeout=25) as r:
            meta = json.loads(r.read().decode("utf-8"))
        _gh_sha = meta.get("content", {}).get("sha", _gh_sha)
    except Exception:  # noqa: BLE001
        _gh_sha = None  # 下次重来


def load_chats() -> dict:
    global _gh_loaded
    # 云端:进程首次加载时从私有仓库拉一次(跨休眠/重启持久),之后走本地缓存
    if GH_TOKEN and not _gh_loaded:
        _gh_loaded = True
        s = _gh_pull()
        if s:
            try:
                data = json.loads(s)
                os.makedirs(os.path.dirname(CHATS_FILE), exist_ok=True)
                with open(CHATS_FILE, "w", encoding="utf-8") as f:
                    f.write(s)
                return data
            except Exception:  # noqa: BLE001
                pass
    if os.path.exists(CHATS_FILE):
        try:
            with open(CHATS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            pass
    return {"chats": []}


def save_chats(data: dict) -> None:
    os.makedirs(os.path.dirname(CHATS_FILE), exist_ok=True)
    s = json.dumps(data, ensure_ascii=False, indent=2)
    with open(CHATS_FILE, "w", encoding="utf-8") as f:
        f.write(s)
    if GH_TOKEN:
        _gh_push(s)


# ---------------- 邀请码(多用户/配额) ----------------
def load_codes() -> dict:
    if os.path.exists(CODES_FILE):
        try:
            with open(CODES_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            pass
    return {"codes": []}


def save_codes(data: dict) -> None:
    os.makedirs(os.path.dirname(CODES_FILE), exist_ok=True)
    with open(CODES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_code(data: dict, code: str):
    code = (code or "").strip().upper()
    for c in data["codes"]:
        if c.get("code", "").upper() == code:
            return c
    return None


def _code_expired(c: dict) -> bool:
    exp = c.get("expires_at")
    if not exp:
        return False
    try:
        dt = datetime.fromisoformat(exp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CN_TZ)  # 旧数据无时区,按北京时间
        return dt < now_cn()
    except Exception:  # noqa: BLE001
        return False


def check_code(code: str):
    """返回 (code_dict, None) 或 (None, 错误信息)。店主密码 = 店主模式(无配额、看全部对话)。"""
    if not code:
        return None, "需要邀请码"
    if code.strip().upper() == HOST_PASSWORD.upper():
        return {"code": "*", "plan": "店主", "category": "双功能",
                "max_messages": 0, "remaining": 0, "is_host": True}, None
    data = load_codes()
    c = find_code(data, code)
    if not c:
        return None, "邀请码无效"
    if c.get("status") == "unused":
        return None, "邀请码未激活"
    if _code_expired(c):
        if c.get("status") != "expired":
            c["status"] = "expired"
            save_codes(data)
        return None, "已到期，请续费"
    if int(c.get("remaining", 0)) <= 0 and int(c.get("max_messages", 0)) > 0:
        return None, "次数已用完，请续费"
    return c, None


def consume_code(code: str) -> int:
    data = load_codes()
    c = find_code(data, code)
    if c and int(c.get("max_messages", 0)) > 0:
        c["remaining"] = max(0, int(c.get("remaining", 0)) - 1)
        save_codes(data)
    return int(c.get("remaining", 0)) if c else 0


def find_chat(data: dict, cid: str):
    for c in data["chats"]:
        if c["id"] == cid:
            return c
    return None


app = FastAPI(title="曲曲+塔罗 AI 顾问")


class ChatCreate(BaseModel):
    category: str = "曲曲"
    code: str = ""


class SendReq(BaseModel):
    mode: str = "问答"
    message: str = ""
    deep: bool = True
    code: str = ""


class EditReq(BaseModel):
    content: str = ""


class ExportReq(BaseModel):
    question: str = ""
    answer: str = ""


class TtsReq(BaseModel):
    text: str = ""


class CodeCreate(BaseModel):
    plan: str = "包月99"
    category: str = "双功能"
    duration_days: int = 30
    max_messages: int = 500
    count: int = 1
    note: str = ""


class ActivateReq(BaseModel):
    code: str = ""


@app.get("/api/health")
def health():
    return {"ok": True, "modes": list(MODES) + ["塔罗"]}


# ---------------- 邀请码管理 + 激活 ----------------
@app.get("/api/admin/codes")
def admin_list_codes():
    data = load_codes()
    out = []
    for c in data["codes"]:
        out.append({
            "code": c.get("code"), "plan": c.get("plan"), "category": c.get("category"),
            "duration_days": c.get("duration_days"), "max_messages": c.get("max_messages"),
            "remaining": c.get("remaining"), "status": c.get("status"),
            "created_at": c.get("created_at"), "activated_at": c.get("activated_at"),
            "expires_at": c.get("expires_at"), "note": c.get("note"),
        })
    out.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return {"codes": out}


@app.post("/api/admin/codes")
def admin_create_codes(req: CodeCreate):
    data = load_codes()
    made = []
    for _ in range(max(1, min(int(req.count), 100))):
        code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
        data["codes"].append({
            "code": code, "plan": req.plan, "category": req.category,
            "duration_days": int(req.duration_days), "max_messages": int(req.max_messages),
            "remaining": int(req.max_messages), "status": "unused",
            "created_at": now_cn().isoformat(), "activated_at": None,
            "expires_at": None, "note": req.note,
        })
        made.append(code)
    save_codes(data)
    return {"codes": made}


@app.post("/api/activate")
def activate(req: ActivateReq):
    code = req.code.strip().upper()
    if not code:
        return JSONResponse({"error": "请输入邀请码"}, status_code=400)
    if code == HOST_PASSWORD.upper():
        return {"ok": True, "code": "*", "plan": "店主", "category": "双功能",
                "remaining": 0, "max_messages": 0, "is_host": True}
    data = load_codes()
    c = find_code(data, code)
    if not c:
        return JSONResponse({"error": "邀请码无效"}, status_code=404)
    if _code_expired(c):
        c["status"] = "expired"
        save_codes(data)
        return JSONResponse({"error": "邀请码已到期"}, status_code=403)
    if c.get("status") == "unused":
        c["status"] = "active"
        c["activated_at"] = now_cn().isoformat()
        c["expires_at"] = (now_cn() + timedelta(days=int(c.get("duration_days", 30)))).isoformat()
        save_codes(data)
    if int(c.get("remaining", 0)) <= 0 and int(c.get("max_messages", 0)) > 0:
        return JSONResponse({"error": "次数已用完，请续费"}, status_code=403)
    return {
        "ok": True, "code": c.get("code"), "plan": c.get("plan"), "category": c.get("category"),
        "remaining": c.get("remaining"), "max_messages": c.get("max_messages"),
        "expires_at": c.get("expires_at"),
    }


@app.get("/api/tarot/spreads")
def tarot_spreads():
    return {"spreads": [{"id": k, "label": v["label"], "count": v["count"]} for k, v in SPREADS.items()]}


@app.get("/api/tarot/draw")
def tarot_draw(spread: str = "three", count: int = 0):
    n = int(count) if int(count) > 0 else SPREADS.get(spread, SPREADS["three"])["count"]
    n = max(1, min(n, 78))
    cards = draw_cards(n)
    s = SPREADS.get(spread)
    label = s["label"] if s else f"自定义 · {n}张"
    positions = s["positions"] if s else []
    for i, c in enumerate(cards):
        c["position"] = positions[i] if i < len(positions) else f"位置{i+1}"
    return {"spread": label, "count": n, "cards": cards}


@app.get("/api/chats")
def list_chats(code: str = ""):
    data = load_chats()
    c, err = check_code(code)
    if err:
        return {"chats": []}
    if c.get("is_host"):
        # 店主：看到全部对话(含自己旧对话 + 所有客户)
        out = [
            {"id": ch["id"], "title": ch.get("title", "新对话"), "category": ch.get("category", "曲曲"),
             "created_at": ch.get("created_at", "")}
            for ch in data["chats"]
        ]
    else:
        out = [
            {"id": ch["id"], "title": ch.get("title", "新对话"), "category": ch.get("category", "曲曲"),
             "created_at": ch.get("created_at", "")}
            for ch in data["chats"]
            if ch.get("code", "") == c.get("code", "")
        ]
    out.sort(key=lambda x: x["created_at"], reverse=True)
    return {"chats": out}


@app.post("/api/chats")
def create_chat(req: ChatCreate):
    c, err = check_code(req.code)
    if err:
        return JSONResponse({"error": err}, status_code=403)
    data = load_chats()
    cid = uuid.uuid4().hex[:12]
    data["chats"].append({
        "id": cid, "category": req.category, "title": "新对话",
        "created_at": now_cn().isoformat(), "messages": [],
        "code": c.get("code", ""),
    })
    save_chats(data)
    return {"id": cid}


@app.get("/api/chats/{cid}")
def get_chat(cid: str, code: str = ""):
    data = load_chats()
    c = find_chat(data, cid)
    if not c:
        return JSONResponse({"error": "not found"}, status_code=404)
    if code.strip() == HOST_PASSWORD:
        return {"category": c.get("category", "曲曲"), "messages": c.get("messages", [])}
    if code and c.get("code", "") != code.strip().upper():
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return {"category": c.get("category", "曲曲"), "messages": c.get("messages", [])}


@app.delete("/api/chats/{cid}")
def delete_chat(cid: str):
    data = load_chats()
    data["chats"] = [c for c in data["chats"] if c["id"] != cid]
    save_chats(data)
    return {"ok": True}


@app.delete("/api/chats/{cid}/messages/{idx}")
def delete_message(cid: str, idx: int):
    data = load_chats()
    c = find_chat(data, cid)
    if not c:
        return JSONResponse({"error": "not found"}, status_code=404)
    msgs = c.get("messages", [])
    if idx < 0 or idx >= len(msgs):
        return JSONResponse({"error": "bad index"}, status_code=400)
    del msgs[idx]
    save_chats(data)
    return {"ok": True}


@app.patch("/api/chats/{cid}/messages/{idx}")
def edit_message(cid: str, idx: int, req: EditReq):
    data = load_chats()
    c = find_chat(data, cid)
    if not c:
        return JSONResponse({"error": "not found"}, status_code=404)
    msgs = c.get("messages", [])
    if idx < 0 or idx >= len(msgs):
        return JSONResponse({"error": "bad index"}, status_code=400)
    msgs[idx]["content"] = req.content.strip()
    save_chats(data)
    return {"ok": True}


def _build_delivery_html(question: str, answer: str) -> str:
    import html as _h
    q = _h.escape(question)
    a = _h.escape(answer)
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><style>
*{{box-sizing:border-box}}
body{{margin:0;width:700px;background:#ffffff;font-family:"Microsoft YaHei","PingFang SC",sans-serif;color:#2a2138}}
.wrap{{padding:44px 50px}}
h1{{font-size:26px;color:#5b3f9e;margin:0 0 8px}}
.q{{color:#9a8fc0;font-size:14px;margin:0 0 28px;line-height:1.7}}
.ans{{font-size:17px;line-height:2.0;white-space:pre-wrap}}
.foot{{margin-top:40px;padding-top:18px;border-top:1px solid #efe9f9;color:#b9b0cf;font-size:13px;text-align:center}}
</style></head><body><div class="wrap"><h1>深度解读</h1><div class="q">问题：{q}</div><div class="ans">{a}</div><div class="foot">深度解读 · 仅供自我探索参考</div></div></body></html>"""


@app.post("/api/export-image")
async def export_image(req: ExportReq):
    if not req.answer.strip():
        return JSONResponse({"error": "empty"}, status_code=400)
    html = _build_delivery_html(req.question, req.answer)
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="msedge", headless=True)
            page = await browser.new_page(viewport={"width": 700, "height": 100})
            await page.set_content(html)
            await page.wait_for_timeout(300)
            png = await page.screenshot(full_page=True, type="png")
            await browser.close()
        return Response(content=png, media_type="image/png",
                        headers={"Content-Disposition": 'attachment; filename="jiedu.png"'})
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/chats/{cid}/send")
def send(cid: str, req: SendReq):
    if not req.message.strip():
        return JSONResponse({"answer": ""})
    code, err = check_code(req.code)
    if err:
        return JSONResponse({"error": err}, status_code=403)
    data = load_chats()
    c = find_chat(data, cid)
    if not c:
        return JSONResponse({"error": "not found"}, status_code=404)

    c["messages"].append({"role": "user", "content": req.message})
    if not c.get("title") or c["title"] == "新对话":
        c["title"] = req.message[:18]

    system = build_system(req.mode, is_host=bool(code.get("is_host")))
    user = build_user(req.mode, c, req.message)

    try:
        content, reasoning = _chat(system, user, max_tokens=32768, reasoning_effort="max")
        content = content.strip()
    except Exception as e:  # noqa: BLE001
        content, reasoning = f"[出错] {e}", ""

    c["messages"].append({"role": "assistant", "content": content})
    save_chats(data)
    remaining = consume_code(req.code)
    return {"answer": content, "reasoning": reasoning, "remaining": remaining}


@app.post("/api/chats/{cid}/send/stream")
def send_stream(cid: str, req: SendReq):
    if not req.message.strip():
        return JSONResponse({"answer": ""})
    code, err = check_code(req.code)
    if err:
        return JSONResponse({"error": err}, status_code=403)
    data = load_chats()
    c = find_chat(data, cid)
    if not c:
        return JSONResponse({"error": "not found"}, status_code=404)

    c["messages"].append({"role": "user", "content": req.message})
    if not c.get("title") or c["title"] == "新对话":
        c["title"] = req.message[:18]
    save_chats(data)

    system = build_system(req.mode, is_host=bool(code.get("is_host")))
    user = build_user(req.mode, c, req.message)

    def gen():
        full: list[str] = []
        try:
            for chunk in discuss_stream(system, user, max_tokens=32768, reasoning_effort="max"):
                kind = chunk["kind"]
                delta = chunk["delta"]
                if kind == "thinking":
                    yield f"data: {json.dumps({'kind': 'thinking', 'delta': delta}, ensure_ascii=False)}\n\n"
                else:
                    full.append(delta)
                    yield f"data: {json.dumps({'kind': 'text', 'delta': delta}, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'kind': 'error', 'delta': str(e)}, ensure_ascii=False)}\n\n"
        content = "".join(full).strip()
        # 深度思考偶尔会耗尽预算导致正文为空:补一次轻思考调用,保证正文有字
        if not content:
            try:
                content, _ = _chat(system, user, max_tokens=16384, reasoning_effort="low")
                content = content.strip()
                if content:
                    yield f"data: {json.dumps({'kind': 'text', 'delta': content}, ensure_ascii=False)}\n\n"
            except Exception:  # noqa: BLE001
                pass
        remaining = None
        if content:
            d2 = load_chats()
            c2 = find_chat(d2, cid)
            if c2:
                c2["messages"].append({"role": "assistant", "content": content})
                save_chats(d2)
            remaining = consume_code(req.code)
        yield f"data: {json.dumps({'kind': 'done', 'remaining': remaining})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/tts")
async def tts(req: TtsReq):
    import edge_tts
    if not req.text.strip():
        return JSONResponse({"error": "empty"}, status_code=400)
    async def _bytes() -> bytes:
        chunks = []
        communicate = edge_tts.Communicate(req.text, "zh-CN-XiaoxiaoNeural")
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)
    try:
        data = await _bytes()
        return Response(content=data, media_type="audio/mpeg")
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/stt")
async def stt(file: UploadFile = File(...)):
    from distill.processors.transcribe import transcribe_file
    suffix = os.path.splitext(file.filename or "rec.webm")[1] or ".webm"
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(file.file.read())
        text, _ = transcribe_file(path, beam_size=1)
        return {"text": text.strip()}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"text": "", "error": str(e)}, status_code=200)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(INDEX_HTML, headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return HTMLResponse(ADMIN_HTML, headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/shangjia", response_class=HTMLResponse)
def shangjia_page():
    return HTMLResponse(SHANGJIA_HTML, headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/cover.png")
def cover_png():
    p = "data/封面_深度解读.png"
    if not os.path.exists(p):
        return JSONResponse({"error": "no cover"}, status_code=404)
    return Response(content=open(p, "rb").read(), media_type="image/png")


SHANGJIA_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>闲鱼上架助手</title>
<style>
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#0f1115;color:#e8e6e3;padding:16px;line-height:1.7}
h1{font-size:20px;margin:0 0 4px}
.sub{color:#8b91a0;font-size:13px;margin-bottom:18px}
.card{background:#171a21;border:1px solid #262b36;border-radius:14px;padding:16px;margin-bottom:14px}
.card h2{font-size:15px;margin:0 0 10px;color:#d4a0ff}
.copybox{background:#0a0c10;border:1px solid #4a5263;border-radius:10px;padding:12px;font-size:14px;white-space:pre-wrap;word-break:break-all;margin-bottom:8px}
.copybtn{display:inline-block;background:#d4a0ff;color:#17121f;border:none;border-radius:8px;padding:8px 16px;font-size:14px;font-weight:600;cursor:pointer}
.copybtn:active{opacity:.8}
img.cover{width:100%;border-radius:10px;display:block;margin-bottom:8px}
.step{display:flex;gap:10px;margin:10px 0}
.step .n{flex-shrink:0;width:24px;height:24px;border-radius:50%;background:#d4a0ff;color:#17121f;font-weight:700;text-align:center;line-height:24px;font-size:13px}
.step .t{font-size:14px}
.spec{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px dashed #262b36;font-size:14px}
.spec:last-child{border:none}
.tip{background:#2a1f14;border:1px solid #6b4a1f;color:#f0c987;border-radius:10px;padding:10px 12px;font-size:13px;margin-top:8px}
#toast{position:fixed;left:50%;bottom:60px;transform:translateX(-50%);background:#d4a0ff;color:#17121f;padding:8px 18px;border-radius:20px;font-size:14px;font-weight:600;opacity:0;transition:.3s;pointer-events:none}
</style>
</head>
<body>
<h1>📦 闲鱼上架助手</h1>
<div class="sub">用手机打开这个页面，长按保存图、点复制、照着步骤在闲鱼APP里发。</div>

<div class="card">
  <h2>① 封面图（长按保存到相册）</h2>
  <img class="cover" src="/cover.png" alt="封面">
  <div class="tip">长按上面这张图 → 保存图片到相册，上架时用它当首图。</div>
</div>

<div class="card">
  <h2>② 四个标题（每个链接一个，点复制）</h2>
  <div class="copybox" id="title1">大女人同款AI 单次解读9.9 蛐蛐那套清醒打法 情感搞钱识人抽牌</div>
  <button class="copybtn" onclick="copyText('title1')">📋 复制 9.9 标题</button>
  <div class="copybox" id="title2">大女人同款AI 三次打包29.9 蛐蛐那套清醒打法 情感搞钱识人抽牌</div>
  <button class="copybtn" onclick="copyText('title2')">📋 复制 29.9 标题</button>
  <div class="copybox" id="title3">大女人同款AI 包月畅聊99 蛐蛐那套清醒打法 情感搞钱识人抽牌</div>
  <button class="copybtn" onclick="copyText('title3')">📋 复制 99 标题</button>
  <div class="copybox" id="title4">大女人同款AI 双功能全解锁159 蛐蛐那套清醒打法 情感搞钱识人抽牌</div>
  <button class="copybtn" onclick="copyText('title4')">📋 复制 159 标题</button>
</div>

<div class="card">
  <h2>③ 描述（4 个链接共用，点复制）</h2>
  <div class="copybox" id="descText">大女人同款AI，蛐蛐那套清醒解读。情感、搞钱、识人、抽牌都能问。

【这是什么】
大女人那套清醒打法的AI版：价值交换、向上社交、把关系当资产。不哄你、不绕弯、上来就给你结论。不是卖课，是直接按你的情况给你用。

【能问什么】
情感：这段值不值、要不要走、怎么谈、他到底图你什么
搞钱：现在做什么来钱、能不能做、怎么定价
识人：他收入多少、靠不靠谱、是真大方还是画饼
抽牌：问时间给期限、问收入给数字、问值不值给结论、问走哪条路给方向

【怎么用】
拍下后自动私信发你：网址 + 邀请码。进网站输码就能问。想聊天用「对话」，想要个痛快答案用「抽牌」（打问题 → 选牌阵 → 点抽牌 → 点发送）。
牌阵：三张、二选一、是或否、复合、事业、双人关系、马蹄铁、凯尔特十字、自定义张数。

【真实案例】
问"走雌竞还是雄竞"：走雄竞，雌竞走到头是一团雾，雄竞终点是星星，命运级的发亮。
问"做直播还是剪辑"：剪辑，数量级差距，直播月入撑死几千，剪辑结果位星币10顶格，月入五位数。
问"什么时候遇到下一任"：最快2周、最可能5个月、最晚不拖过2年。

【本链接】
（发哪个链接就改成哪句：单次9.9可问1次／三次29.9可问3次／包月99情感300次+抽牌200次／双功能159不限次）

【注意】
虚拟服务，发出即交付，不退不换。拍前有疑问先私信。不记名、不外传，什么都能说。更多套餐点我主页。</div>
  <button class="copybtn" onclick="copyText('descText')">📋 复制描述</button>
  <div class="tip">发哪个链接，就把描述里【本链接】那一行改成对应的价格说明（见④）。</div>
</div>

<div class="card">
  <h2>④ 发 4 个单独链接（每个固定一个价）</h2>
  <div class="spec"><span>① 单次解读</span><b>9.9（可问1次）</b></div>
  <div class="spec"><span>② 三次打包</span><b>29.9（可问3次）</b></div>
  <div class="spec"><span>③ 包月畅聊</span><b>99（情感300次+抽牌200次）</b></div>
  <div class="spec"><span>④ 双功能全解锁</span><b>159（30天不限次）</b></div>
  <div class="tip">别搞多规格（要账号等级），别改价（易出错）。就发 4 个单独链接，价格对上系统自动发货。先发 9.9，其余再补。</div>
</div>

<div class="card">
  <h2>⑤ 闲鱼APP上架步骤（每个链接重复一遍）</h2>
  <div class="step"><div class="n">1</div><div class="t">打开<b>闲鱼APP</b>，点底部中间<b>「卖闲置」</b>（红色发布按钮）。</div></div>
  <div class="step"><div class="n">2</div><div class="t">选<b>「相册」</b>，上传刚才保存的那张<b>封面图</b>。</div></div>
  <div class="step"><div class="n">3</div><div class="t">点进<b>「描述」</b>框，粘贴对应链接的<b>标题 + 描述</b>，把【本链接】那一行改成这个链接的价格。</div></div>
  <div class="step"><div class="n">4</div><div class="t">价格填<b>本链接的价格</b>（9.9／29.9／99／159），<b>不要加规格</b>。</div></div>
  <div class="step"><div class="n">5</div><div class="t">分类选<b>「游戏/软件 → 虚拟卡券」</b>（若自动判成"服务"，手动改回虚拟卡券）。</div></div>
  <div class="step"><div class="n">6</div><div class="t">发货方式选<b>「无需邮寄」</b>。</div></div>
  <div class="step"><div class="n">7</div><div class="t">点<b>「发布」</b>。先发 9.9 那一个，其余三个同样操作再补。</div></div>
  <div class="tip">发完把链接或截图告诉我，我这边自动盯单就接客。</div>
</div>

<div id="toast">已复制</div>
<script>
function toast(m){
  const t = document.getElementById("toast");
  t.textContent = m; t.style.opacity = 1;
  setTimeout(()=>{ t.style.opacity = 0; }, 1500);
}
function copyText(id){
  const txt = document.getElementById(id).innerText;
  const done = () => toast("已复制");
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(txt).then(done).catch(()=>fallback(txt));
  } else fallback(txt);
}
function fallback(txt){
  const ta = document.createElement("textarea");
  ta.value = txt; ta.style.position = "fixed"; ta.style.opacity = 0;
  document.body.appendChild(ta); ta.select();
  try{ document.execCommand("copy"); toast("已复制"); }catch(e){ toast("复制失败，手动长按复制"); }
  ta.remove();
}
</script>
</body>
</html>
"""


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>曲曲 + 塔罗 · AI 顾问</title>
<style>
:root{--bg:#0f1115;--panel:#171a21;--line:#262b36;--txt:#e8e6e3;--sub:#8b91a0;--accent:#d4a0ff;--tarot:#5bd0c8;--me:#2c3547;}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--txt);height:100vh;height:100dvh;display:flex;overflow:hidden}
#side{width:250px;min-width:250px;background:var(--panel);border-right:1px solid var(--line);display:flex;flex-direction:column}
#side .head{padding:12px 14px;border-bottom:1px solid var(--line)}
#side .head button{width:100%;padding:9px;border-radius:8px;background:var(--accent);color:#17121f;border:none;font-weight:600;cursor:pointer}
#side .cat{padding:10px 14px 4px;font-size:12px;color:var(--sub)}
#side .list{flex:1;overflow-y:auto;padding:0 8px 8px}
.chatrow{display:flex;align-items:center;gap:6px;padding:8px 10px;border-radius:8px;cursor:pointer;font-size:14px;color:var(--txt)}
.chatrow:hover{background:#20242e}
.chatrow.on{background:#2a3040}
.chatrow .t{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chatrow .x{color:var(--sub);cursor:pointer;padding:0 4px;display:none}
.chatrow:hover .x{display:block}
#main{flex:1;display:flex;flex-direction:column;min-width:0}
header{padding:10px 16px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px;flex-wrap:wrap}
header .title{font-size:16px;font-weight:600}
#modes{display:flex;gap:6px;flex-wrap:wrap}
.mode{padding:5px 13px;border-radius:16px;border:1px solid var(--line);background:var(--panel);color:var(--sub);cursor:pointer;font-size:13px}
.mode.on{background:var(--accent);color:#17121f;border-color:var(--accent);font-weight:600}
.mode.tarot.on{background:var(--tarot);color:#0d1f1e;border-color:var(--tarot)}
#deep{margin-left:auto;display:flex;align-items:center;gap:6px;font-size:13px;color:var(--sub);cursor:pointer;user-select:none}
#deep .box{width:34px;height:18px;border-radius:10px;background:#333;position:relative;transition:.2s}
#deep.on .box{background:var(--accent)}
#deep .box::after{content:"";position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;background:#fff;transition:.2s}
#deep.on .box::after{left:18px}
#chat{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px}
.msg{max-width:84%;padding:10px 14px;border-radius:14px;line-height:1.65;font-size:15px;white-space:pre-wrap}
.msg.user{align-self:flex-end;background:var(--me);border-bottom-right-radius:4px}
.msg.ai{align-self:flex-start;background:var(--panel);border:1px solid var(--line);border-bottom-left-radius:4px}
.msg .tools{margin-top:6px;display:flex;gap:10px}
.msg .speak{color:var(--accent);cursor:pointer;font-size:13px;user-select:none}
.msg details{margin-top:8px;border-top:1px dashed var(--line);padding-top:6px}
.msg details summary{cursor:pointer;color:var(--sub);font-size:13px}
.msg details .think{color:var(--sub);font-size:13px;white-space:pre-wrap;margin-top:6px}
.cards{display:flex;gap:8px;margin:6px 0;flex-wrap:wrap}
.card{background:#1d222d;border:1px solid var(--line);border-radius:10px;padding:8px 10px;font-size:13px;text-align:center;min-width:92px}
.card .pos{color:var(--sub);font-size:11px}
.card .nm{font-weight:600}
.card .or{color:var(--tarot);font-size:12px}
#inputbar{display:flex;gap:8px;padding:12px 16px calc(12px + env(safe-area-inset-bottom, 0px));border-top:1px solid var(--line);background:var(--panel);align-items:center;flex-wrap:wrap}
#input{flex:1;min-width:0;background:var(--bg);border:1.5px solid #4a5263;border-radius:10px;padding:11px 14px;color:var(--txt);font-size:15px;outline:none}
#input:focus{border-color:var(--accent)}
button{cursor:pointer}
#send{flex-shrink:0;background:var(--accent);color:#17121f;border:none;border-radius:10px;padding:11px 16px;font-size:15px;font-weight:600}
button.ghost{background:transparent;border:1px solid var(--line);color:var(--sub);border-radius:10px;padding:10px 12px;font-size:15px}
#tarotRow{display:none;gap:6px;align-items:center}
#spread{background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:10px;color:var(--txt);font-size:14px;outline:none}
#draw{background:var(--tarot);color:#0d1f1e;border:none;border-radius:10px;padding:10px 14px;font-size:14px;font-weight:600}
#mic.rec{background:#ff6b6b;color:#fff}
.typing{color:var(--sub);font-size:13px;padding:4px 2px}
#scriptPanel{display:none;padding:10px 14px;background:var(--panel);border-bottom:1px solid var(--line)}
#scriptPanel .lbl{font-size:12px;color:var(--sub);margin:2px 0 8px}
#scriptPanel button{background:var(--bg);border:1px solid var(--line);color:var(--txt);border-radius:16px;padding:7px 13px;font-size:13px}
#scriptPanel button:hover{border-color:var(--accent);color:var(--accent)}
#overlay{position:fixed;inset:0;background:var(--bg);display:flex;align-items:center;justify-content:center;z-index:200;flex-direction:column;gap:16px;padding:24px}
#overlay h2{margin:0;font-size:22px}
#overlay .sub{color:var(--sub);font-size:14px;text-align:center;line-height:1.7;max-width:420px}
#overlay input{width:300px;max-width:80vw;padding:13px 16px;border-radius:10px;border:1px solid var(--line);background:#0a0c10;color:var(--txt);font-size:16px;text-align:center;letter-spacing:2px;outline:none;text-transform:uppercase}
#overlay input:focus{border-color:var(--accent)}
#overlay button{padding:12px 40px;border-radius:10px;border:none;background:var(--accent);color:#17121f;font-size:15px;font-weight:600;cursor:pointer}
#overlay .err{color:#ff6b6b;font-size:13px;min-height:18px}
#quota{margin-left:auto;font-size:13px;color:var(--tarot);white-space:nowrap}
#adminLink{margin-left:auto;font-size:13px;color:var(--sub);cursor:pointer;text-decoration:none}
#adminLink:hover{color:var(--accent)}
#logout{margin-left:8px;font-size:13px;color:var(--sub);cursor:pointer}
#logout:hover{color:#ff6b6b}
.admin-wrap{max-width:720px;margin:0 auto;padding:28px 20px}
.admin-wrap h1{font-size:20px;margin:0 0 18px}
.admin-row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;align-items:center}
.admin-row input,.admin-row select{padding:9px 11px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--txt);font-size:14px;outline:none}
.admin-row label{font-size:13px;color:var(--sub)}
.codes-table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
.codes-table th,.codes-table td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left}
.codes-table th{color:var(--sub);font-weight:600}
.codes-table .code{font-family:monospace;color:var(--accent);letter-spacing:1px}
.st-active{color:#6bd06b}.st-unused{color:var(--sub)}.st-expired{color:#ff6b6b}
.copybtn{color:var(--tarot);cursor:pointer;font-size:12px}
#renewBanner{display:none;background:#2a1f14;border-bottom:1px solid #6b4a1f;color:#f0c987;padding:10px 16px;font-size:13px;line-height:1.6}
#renewBanner a{color:#ffd88a;font-weight:600;cursor:pointer;text-decoration:underline}
.hostonly{display:none !important}
body.ishost .hostonly{display:revert}
#helpOverlay{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:200;display:flex;align-items:center;justify-content:center;padding:20px}
.helpbox{background:#14181f;border:1px solid var(--line);border-radius:14px;max-width:520px;width:100%;padding:22px;max-height:82vh;overflow:auto}
.helpsection{border-bottom:1px solid var(--line);padding:10px 0}
.helptitle{font-weight:700;color:var(--accent);margin-bottom:6px;font-size:14px}
.helpline{font-size:13px;line-height:1.7;color:var(--txt);margin:3px 0}
#menuBtn{display:none;background:transparent;border:1px solid var(--line);color:var(--txt);border-radius:8px;padding:6px 10px;font-size:16px}
#sideBackdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:55}
@media (max-width:768px){
  #side{position:fixed;left:0;top:0;bottom:0;z-index:60;transform:translateX(-100%);transition:transform .25s;box-shadow:2px 0 14px rgba(0,0,0,.5)}
  body.sideopen #side{transform:translateX(0)}
  body.sideopen #sideBackdrop{display:block}
  #menuBtn{display:inline-block}
  .msg{max-width:92%}
  #chat{padding:12px}
  header{padding:8px 10px;gap:8px}
  #inputbar{padding:8px 10px;gap:6px}
  #input{min-width:0;padding:10px 12px;font-size:16px}
  #mic,#draw,#spread,#send{flex-shrink:0}
  #send{padding:10px 12px}
  #draw{padding:8px 10px;font-size:13px}
  #tarotRow{flex-basis:100%;width:100%;order:1;flex-wrap:wrap}
  #scriptBtn,#mic,#input,#send{order:2}
}
</style>
</head>
<body>
<div id="overlay">
  <h2>🔑 输入邀请码</h2>
  <div class="sub">这是你专属的顾问空间。输入卖家给你的邀请码，解锁专属对话（次数/时长自动扣，用完自动提醒续费）。</div>
  <input id="codeInput" placeholder="XXXX-XXXX-XXXX" autocomplete="off">
  <button onclick="doActivate()">进入</button>
  <div class="err" id="codeErr"></div>
  <div style="margin-top:18px;border-top:1px solid var(--line);padding-top:14px;text-align:left">
    <div style="font-size:12px;color:var(--sub);margin-bottom:8px">🔥 真实案例（已脱敏，不泄露任何隐私）</div>
    <div style="font-size:12px;color:var(--txt);line-height:1.7;margin:4px 0">· 问"走雌竞还是雄竞"：走雄竞。雌竞走到头是一团雾，雄竞终点是星星，命运级的发亮。</div>
    <div style="font-size:12px;color:var(--txt);line-height:1.7;margin:4px 0">· 问"做直播还是剪辑"：剪辑，数量级差距。直播月入撑死几千，剪辑结果位星币10顶格，月入五位数。</div>
    <div style="font-size:12px;color:var(--txt);line-height:1.7;margin:4px 0">· 问"什么时候遇到下一任"：最快2周、最可能5个月、最晚不拖过2年。</div>
  </div>
  <div style="margin-top:22px;border-top:1px solid var(--line);padding-top:16px;display:flex;flex-direction:column;align-items:center;gap:10px">
    <span class="sub" style="color:var(--txt)">👤 店主本人？不用邀请码，点下面输密码</span>
    <button onclick="doHostLogin()" style="background:var(--tarot);color:#0a0c10;border:none;padding:12px 32px;font-weight:700">我是店主 → 输密码进入</button>
  </div>
</div>
<div id="helpOverlay" style="display:none">
  <div class="helpbox">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <h2 style="margin:0">📖 玩法说明</h2>
      <span onclick="toggleHelp()" style="cursor:pointer;font-size:20px;color:var(--sub)">✕</span>
    </div>
    <div class="helpsection">
      <div class="helptitle">两种模式</div>
      <div class="helpline"><b>对话</b>：直接打字问，AI 用"大女人"那套直接给你结论（情感/搞钱/识人）。</div>
      <div class="helpline"><b>塔罗</b>：抽牌解读。当你卡在死胡同里纠结（该不该走、走哪条路），抽一张牌，直接从命理维度告诉你答案和原因——这就是"降维打击"。</div>
    </div>
    <div class="helpsection">
      <div class="helptitle">塔罗怎么用（按顺序）</div>
      <div class="helpline">① 点顶部 <b>「塔罗」</b> 切过去</div>
      <div class="helpline">② 在输入框<b>打好你的问题</b></div>
      <div class="helpline">③ <b>选牌阵</b>（没有合适的就选"自定义张数"）</div>
      <div class="helpline">④ 点 <b>「🃏 抽牌解读」</b>，牌会自己排出来</div>
      <div class="helpline">⑤ 牌出来之后，点 <b>「发送」</b></div>
    </div>
    <div class="helpsection">
      <div class="helptitle">第一次提问 / 引流款，一定要当连麦一样问</div>
      <div class="helpline">你只有这一次（或几次）机会，别一句"他爱不爱我"就浪费掉。</div>
      <div class="helpline">把这事当<b>直播间连麦</b>一样，从头说清楚：怎么认识的、他做过什么给过什么、你现在卡在哪一句、你想要什么结果。说得越细、越啰嗦，AI 越懂你、答得越准。</div>
      <div class="helpline">一次没说完没关系，接着发就行。</div>
    </div>
    <div class="helpsection">
      <div class="helptitle">续费 / 订阅</div>
      <div class="helpline">次数用完或想升级包月，<b>回闲鱼下单</b>对应规格，拍下后会有新的邀请码发你。</div>
    </div>
    <div class="helpsection" style="border:none;margin-bottom:0">
      <div class="helpline" style="color:var(--sub)">提示：对话和塔罗是两条线，别混。想聊天用"对话"，想要一个痛快的答案就用"塔罗"抽牌。</div>
    </div>
  </div>
</div>
<div id="caseOverlay" style="display:none">
  <div class="helpbox">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <h2 style="margin:0">🔥 真实案例</h2>
      <span onclick="toggleCase()" style="cursor:pointer;font-size:20px;color:var(--sub)">✕</span>
    </div>
    <div class="helpsection">
      <div class="helptitle">问"走雌竞还是雄竞"</div>
      <div class="helpline">走雄竞。雌竞走到头是一团雾，钱封死在中档还稳不住；雄竞开头穷，但终点是星星，是命运级的发亮。两条路不一样，结果也不一样——雌竞往下沉，雄竞往上走。别拿剑去学端碗。</div>
    </div>
    <div class="helpsection">
      <div class="helptitle">问"做直播还是剪辑"</div>
      <div class="helpline">剪辑，而且是数量级差距。直播天花板焊死，月入撑死几千；剪辑结果位星币10顶格，月入五位数、项目单价几十万。直播是"你必须在场，一天不播就没钱"；剪辑是"复制品替你赚钱，你睡觉活还在跑"。</div>
    </div>
    <div class="helpsection">
      <div class="helptitle">问"什么时候遇到下一任"</div>
      <div class="helpline">最快2周内、最可能5个月、最晚不拖过2年。而且这人大概率出现在你情绪低点附近，不是状态最好的时候——他可能没你想象那么锐利，但会是那个让你愿意收一收防御的人。</div>
    </div>
    <div class="helpsection" style="border:none;margin-bottom:0">
      <div class="helpline" style="color:var(--sub)">案例已脱敏，只留"问什么 + 怎么答"，不泄露任何客户隐私。</div>
    </div>
  </div>
</div>
<div id="sideBackdrop" onclick="toggleSide()"></div>
<div id="side">
  <div class="head">
    <div class="title" style="font-size:14px;margin-bottom:8px">🧠 AI 顾问</div>
    <button onclick="newChat()">＋ 新对话</button>
  </div>
  <div class="cat">曲曲</div>
  <div class="list" id="list-ququ"></div>
  <div class="cat">塔罗</div>
  <div class="list" id="list-tarot"></div>
</div>
<div id="main">
  <header>
    <button id="menuBtn" onclick="toggleSide()">☰</button>
    <div id="modes">
      <div class="mode on" data-m="问答">对话</div>
      <div class="mode tarot" data-m="塔罗">塔罗</div>
    </div>
    <button class="ghost" onclick="deleteCurrentChat()">🗑 删除</button>
    <span id="deep" style="color:var(--accent);font-size:13px">🧠 深度思考</span>
    <span id="helpBtn" onclick="toggleHelp()" style="cursor:pointer;color:var(--accent);font-size:13px">❓ 玩法</span>
    <span id="caseBtn" onclick="toggleCase()" style="cursor:pointer;color:var(--accent);font-size:13px">🔥 案例</span>
    <span id="quota"></span>
    <a id="adminLink" href="/admin" class="hostonly">⚙ 管理</a>
    <span id="logout" onclick="doLogout()">退出</span>
  </header>
  <div id="renewBanner"></div>
  <div id="chat"></div>
  <div id="scriptPanel" class="hostonly">
    <div class="lbl">📋 常用话术（点一下复制，去闲鱼粘贴）</div>
    <div style="display:flex;flex-wrap:wrap;gap:8px">
      <button onclick="copyScript(0)">👋 欢迎引导</button>
      <button onclick="copyScript(1)">🔍 问详细</button>
      <button onclick="copyScript(2)">✅ 催确认</button>
      <button onclick="copyScript(3)">📖 使用说明</button>
    </div>
  </div>
  <div id="inputbar">
    <div id="tarotRow">
      <select id="spread"></select>
      <input id="customCount" type="number" min="1" max="78" value="3" placeholder="张数" style="display:none;width:70px">
      <button id="draw" onclick="drawTarot()">🃏 抽牌解读</button>
    </div>
    <button id="scriptBtn" class="ghost hostonly" onclick="toggleScript()" title="常用话术一键复制">📋 话术</button>
    <button id="mic" class="ghost" title="点击录音,再点停止">🎤</button>
    <input id="input" placeholder="输入你的问题…(Enter 发送)">
    <button id="send">发送</button>
  </div>
</div>

<script>
let currentChatId = null;
let currentMode = "问答";
let deep = true;
let activeCode = localStorage.getItem("ququ_code") || "";
let activeInfo = null;
const chat = document.getElementById("chat");
const input = document.getElementById("input");
const mic = document.getElementById("mic");

function catOf(m){ return m === "塔罗" ? "塔罗" : "曲曲"; }

function setQuotaDisplay(info){
  if(!info) return;
  const q = document.getElementById("quota");
  const plan = info.plan || "";
  let txt = "剩余 " + info.remaining + " 次";
  if(info.expires_at){
    const d = new Date(info.expires_at);
    txt += " · " + (d.getFullYear()+"-"+(d.getMonth()+1)+"-"+d.getDate());
  }
  q.textContent = (plan ? plan+" · " : "") + txt;
  q.title = "套餐："+plan+" · 剩余"+info.remaining+"次"+(info.expires_at?" · 到期"+info.expires_at:"");
  updateQuotaBanner(info);
}

function updateQuotaBanner(info){
  const b = document.getElementById("renewBanner");
  if(!info || info.is_host){ b.style.display = "none"; return; }
  const rem = parseInt(info.remaining, 10);
  const max = parseInt(info.max_messages, 10);
  const low = max > 0 && rem <= Math.max(5, Math.floor(max * 0.05));
  let html = "";
  if(rem <= 0){
    html = "⛔ 次数已用完（或已到期）。想继续？去闲鱼拍「包月99」选项，拍完发我，秒发新码。";
  } else if(low){
    html = "⚠️ 还剩 " + rem + " 次，快用完啦～去闲鱼拍「包月99」选项升级，无限次更划算，拍完发我秒发新码。";
  }
  b.innerHTML = html;
  b.style.display = html ? "block" : "none";
}

function applyRoleUI(){
  const isHost = !!(activeInfo && activeInfo.is_host);
  document.body.classList.toggle("ishost", isHost);
}

async function doActivate(){
  const code = document.getElementById("codeInput").value.trim();
  const errEl = document.getElementById("codeErr");
  if(!code){ errEl.textContent = "请输入邀请码"; return; }
  errEl.textContent = "";
  const j = await api("/api/activate", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({code})});
  if(j.error){ errEl.textContent = j.error; return; }
  activeCode = j.code;
  activeInfo = j;
  localStorage.setItem("ququ_code", activeCode);
  localStorage.setItem("ququ_info", JSON.stringify(j));
  setQuotaDisplay(j);
  applyRoleUI();
  document.getElementById("overlay").style.display = "none";
  await openFirstOrNew();
}

async function doHostLogin(){
  const pw = prompt("请输入店主密码：");
  if(!pw) return;
  const j = await api("/api/activate", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({code: pw})});
  if(j.error){ alert(j.error); return; }
  activeCode = pw;
  activeInfo = j;
  localStorage.setItem("ququ_code", pw);
  localStorage.setItem("ququ_info", JSON.stringify(j));
  localStorage.setItem("ququ_host", "1");
  document.getElementById("quota").textContent = "店主模式";
  applyRoleUI();
  document.getElementById("overlay").style.display = "none";
  await openFirstOrNew();
}

function doLogout(){
  localStorage.removeItem("ququ_code");
  localStorage.removeItem("ququ_info");
  localStorage.removeItem("ququ_host");
  activeCode = "";
  activeInfo = null;
  currentChatId = null;
  chat.innerHTML = "";
  document.getElementById("quota").textContent = "";
  document.body.classList.remove("ishost");
  document.getElementById("overlay").style.display = "flex";
}

function err401(j){
  if(j && j.error && (j.error.includes("到期") || j.error.includes("用完") || j.error.includes("邀请码"))){
    alert(j.error);
    doLogout();
    return true;
  }
  return false;
}

async function api(url, opts){ const r = await fetch(url, opts); return r.json(); }

async function loadChats(){
  const j = await api("/api/chats?code=" + encodeURIComponent(activeCode));
  document.getElementById("list-ququ").innerHTML = "";
  document.getElementById("list-tarot").innerHTML = "";
  for(const c of j.chats){
    const wrap = c.category === "塔罗" ? document.getElementById("list-tarot") : document.getElementById("list-ququ");
    const d = document.createElement("div");
    d.className = "chatrow" + (c.id === currentChatId ? " on" : "");
    const t = document.createElement("span"); t.className = "t"; t.textContent = c.title;
    const x = document.createElement("span"); x.className = "x"; x.textContent = "✕";
    x.onclick = async (e) => { e.stopPropagation(); await api("/api/chats/"+c.id, {method:"DELETE"}); if(c.id===currentChatId){currentChatId=null; chat.innerHTML="";} loadChats(); };
    d.appendChild(t); d.appendChild(x);
    d.onclick = () => openChat(c.id);
    wrap.appendChild(d);
  }
}

async function newChat(){
  const j = await api("/api/chats", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({category: catOf(currentMode), code: activeCode})});
  if(err401(j)) return;
  currentChatId = j.id;
  chat.innerHTML = "";
  loadChats();
}

async function openFirstOrNew(){
  const j = await api("/api/chats?code=" + encodeURIComponent(activeCode));
  if(j.chats && j.chats.length){
    await openChat(j.chats[0].id);
  } else {
    await newChat();
  }
}

async function openChat(id){
  currentChatId = id;
  const j = await api("/api/chats/"+id+"?code="+encodeURIComponent(activeCode));
  chat.innerHTML = "";
  msgCount = 0;
  for(const m of j.messages) addMsg(m.role, m.content, m.reasoning, msgCount++);
  loadChats();
}

function addMsg(role, text, reasoning, idx){
  const d = document.createElement("div");
  d.className = "msg " + (role === "user" ? "user" : "ai");
  d.dataset.idx = idx;
  const body = document.createElement("div");
  body.className = "body";
  body.textContent = text;
  d.appendChild(body);
  if(role === "ai" && reasoning){
    const det = document.createElement("details");
    const sum = document.createElement("summary"); sum.textContent = "🧠 思考过程";
    const th = document.createElement("div"); th.className = "think"; th.textContent = reasoning;
    det.appendChild(sum); det.appendChild(th);
    d.appendChild(det);
  }
  const tools = document.createElement("div"); tools.className = "tools";
  if(role === "ai"){
    const s = document.createElement("span"); s.className = "speak"; s.textContent = "🔊 朗读";
    s.onclick = () => speak(body.textContent);
    const cp = document.createElement("span"); cp.className = "speak"; cp.textContent = "📋 复制";
    cp.onclick = () => copyText(body.textContent);
    const ex = document.createElement("span"); ex.className = "speak"; ex.textContent = "🖼 长图";
    ex.onclick = () => exportImage(body.textContent);
    tools.appendChild(s); tools.appendChild(cp); tools.appendChild(ex);
  } else {
    const cp = document.createElement("span"); cp.className = "speak"; cp.textContent = "📋 复制";
    cp.onclick = () => copyText(body.textContent);
    tools.appendChild(cp);
  }
  const ed = document.createElement("span"); ed.className = "speak"; ed.textContent = "✏️ 改";
  ed.onclick = () => editMsg(d, idx);
  const del = document.createElement("span"); del.className = "speak"; del.textContent = "🗑 删";
  del.onclick = () => deleteMsg(idx);
  tools.appendChild(ed); tools.appendChild(del);
  d.appendChild(tools);
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
  return d;
}

function editMsg(d, idx){
  const body = d.querySelector(".body");
  if(!body) return;
  const ta = document.createElement("textarea");
  ta.value = body.textContent;
  ta.style.cssText = "width:100%;min-height:90px;font-size:15px;line-height:1.65;font-family:inherit;border:1px solid var(--accent);border-radius:8px;padding:8px;background:#fff;color:#222;resize:vertical;box-sizing:border-box";
  const btns = document.createElement("div");
  btns.style.cssText = "margin-top:6px;display:flex;gap:8px";
  const save = document.createElement("button"); save.textContent = "保存";
  save.style.cssText = "padding:5px 14px;border:1px solid var(--accent);background:var(--accent);color:#fff;border-radius:8px;cursor:pointer;font-size:13px";
  const cancel = document.createElement("button"); cancel.textContent = "取消";
  cancel.style.cssText = "padding:5px 14px;border:1px solid var(--line);background:transparent;color:var(--sub);border-radius:8px;cursor:pointer;font-size:13px";
  btns.appendChild(save); btns.appendChild(cancel);
  body.style.display = "none";
  body.after(ta, btns);
  ta.focus();
  const cleanup = () => { ta.remove(); btns.remove(); body.style.display = ""; };
  save.onclick = async () => {
    const newText = ta.value;
    try{
      const r = await fetch("/api/chats/"+currentChatId+"/messages/"+idx, {method:"PATCH", headers:{"Content-Type":"application/json"}, body: JSON.stringify({content:newText})});
      if(!r.ok) throw new Error("HTTP "+r.status);
      body.textContent = newText;
      cleanup();
      toast("已修改 ✅");
    }catch(e){ alert("修改失败: " + e); }
  };
  cancel.onclick = cleanup;
}

async function deleteMsg(idx){
  if(!confirm("删除这条消息？")) return;
  try{
    const r = await fetch("/api/chats/"+currentChatId+"/messages/"+idx, {method:"DELETE"});
    if(!r.ok) throw new Error("HTTP "+r.status);
    await openChat(currentChatId);
    toast("已删除 🗑");
  }catch(e){ alert("删除失败: " + e); }
}

let msgCount = 0;

async function send(){
  const text = input.value.trim();
  if(!text) return;
  if(!currentChatId){ await newChat(); }
  input.value = "";
  addMsg("user", text, null, msgCount++);
  const aiIdx = msgCount;
  const d = document.createElement("div");
  d.className = "msg ai";
  d.dataset.idx = aiIdx;
  const body = document.createElement("div"); body.className = "body";
  d.appendChild(body);
  let det = null, th = null;
  if(deep){
    det = document.createElement("details");
    const sum = document.createElement("summary"); sum.textContent = "🧠 思考过程";
    th = document.createElement("div"); th.className = "think";
    det.appendChild(sum); det.appendChild(th);
    d.appendChild(det);
  }
  const status = document.createElement("div");
  status.className = "typing"; status.textContent = "思考中…";
  d.appendChild(status);
  chat.appendChild(d);
  const start = Date.now();
  let textStarted = false, finished = false, acc = "", rAcc = "";
  // —— 滚动跟随: 用户滚上去就不再吸底, 滚回底部自动恢复 ——
  let pinned = true;
  chat.addEventListener("scroll", () => {
    pinned = (chat.scrollHeight - chat.scrollTop - chat.clientHeight) < 90;
  }, {passive:true});
  // —— 批处理刷新: 最多约8次/秒更新DOM, 流式不卡顿 ——
  let flushTimer = null;
  function flush(){
    if(deep && th) th.textContent = rAcc;
    if(textStarted) body.textContent = acc;
    if(pinned) chat.scrollTop = chat.scrollHeight;
  }
  function scheduleFlush(){
    if(flushTimer) return;
    flushTimer = setTimeout(() => { flushTimer = null; flush(); }, 120);
  }
  if(pinned) chat.scrollTop = chat.scrollHeight;
  const timer = setInterval(() => {
    if(!finished && !textStarted){
      const sec = Math.round((Date.now()-start)/1000);
      status.textContent = (deep ? "🧠 深度思考中… " : "思考中… ") + sec + "秒";
    }
  }, 500);
  try{
    const ac = new AbortController();
    const timeout = setTimeout(() => ac.abort(), 180000); // 3分钟无响应自动中断
    const resp = await fetch("/api/chats/"+currentChatId+"/send/stream", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({mode:currentMode, message:text, deep, code: activeCode}),
      signal: ac.signal
    });
    if(!resp.ok){
      let msg = "HTTP " + resp.status;
      try{ const ej = await resp.json(); if(ej.error) msg = ej.error; }catch(err){}
      throw new Error(msg);
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while(true){
      const {done, value} = await reader.read();
      if(done) break;
      buf += decoder.decode(value, {stream:true});
      let idx;
      while((idx = buf.indexOf("\n\n")) >= 0){
        const line = buf.slice(0, idx).trim();
        buf = buf.slice(idx+2);
        if(!line.startsWith("data: ")) continue;
        let obj; try{ obj = JSON.parse(line.slice(6)); }catch(err){ continue; }
        if(obj.kind === "thinking"){
          rAcc += obj.delta;
          scheduleFlush();
        } else if(obj.kind === "text"){
          if(!textStarted){ status.remove(); textStarted = true; }
          acc += obj.delta;
          scheduleFlush();
        } else if(obj.kind === "error"){
          body.textContent = "[出错] " + obj.delta;
        } else if(obj.kind === "done"){
          if(obj.remaining !== undefined && obj.remaining !== null && activeInfo){
            activeInfo.remaining = obj.remaining;
            setQuotaDisplay(activeInfo);
          }
        }
      }
    }
    clearTimeout(timeout);
    if(flushTimer){ clearTimeout(flushTimer); flushTimer = null; }
    flush();
    finished = true; clearInterval(timer);
    if(!textStarted){ status.remove(); body.textContent = acc || "(空)"; }
    const tools = document.createElement("div"); tools.className = "tools";
    const s = document.createElement("span"); s.className = "speak"; s.textContent = "🔊 朗读";
    s.onclick = () => speak(acc);
    const cp = document.createElement("span"); cp.className = "speak"; cp.textContent = "📋 复制";
    cp.onclick = () => copyText(acc);
    const ex = document.createElement("span"); ex.className = "speak"; ex.textContent = "🖼 长图";
    ex.onclick = () => exportImage(acc);
    const ed = document.createElement("span"); ed.className = "speak"; ed.textContent = "✏️ 改";
    ed.onclick = () => editMsg(d, aiIdx);
    const del = document.createElement("span"); del.className = "speak"; del.textContent = "🗑 删";
    del.onclick = () => deleteMsg(aiIdx);
    tools.appendChild(s); tools.appendChild(cp); tools.appendChild(ex); tools.appendChild(ed); tools.appendChild(del);
    d.appendChild(tools);
    msgCount = aiIdx + 1;
    loadChats();
  }catch(e){
    clearTimeout(timeout);
    finished = true; clearInterval(timer);
    status.remove();
    body.textContent = "[请求失败] " + (e.name === "AbortError" ? "超时(思考太久被中断)，请重试" : (e.message || e));
    if(e.message && e.message.includes("邀请码")){
      alert(e.message);
      doLogout();
    } else if(e.message && (e.message.includes("用完") || e.message.includes("到期"))){
      alert(e.message);
      if(activeInfo){ activeInfo.remaining = 0; setQuotaDisplay(activeInfo); }
    }
  }
}

async function speak(text){
  try{
    const r = await fetch("/api/tts", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({text})});
    const blob = await r.blob();
    new Audio(URL.createObjectURL(blob)).play();
  }catch(e){ alert("朗读失败: " + e); }
}

async function drawTarot(){
  if(!currentChatId){ await newChat(); }
  const spread = document.getElementById("spread").value || "three";
  let url = "/api/tarot/draw?spread="+spread;
  if(spread === "custom"){
    const n = parseInt(document.getElementById("customCount").value, 10) || 3;
    url += "&count=" + Math.max(1, Math.min(n, 78));
  }
  const q = input.value.trim();
  const j = await api(url);
  // 显示牌面
  const box = document.createElement("div");
  box.className = "msg ai";
  const cards = document.createElement("div"); cards.className = "cards";
  j.cards.forEach(c => {
    const cd = document.createElement("div"); cd.className = "card";
    cd.innerHTML = '<div class="pos">'+c.position+'</div><div class="nm">'+c.name+'</div><div class="or">'+(c.reversed?'逆位':'正位')+'</div>';
    cards.appendChild(cd);
  });
  box.appendChild(cards);
  chat.appendChild(box); chat.scrollTop = chat.scrollHeight;
  // 组装解读请求
  const cardDesc = j.cards.map(c => c.position+'. '+c.name+'（'+(c.reversed?'逆位':'正位')+'）').join('\n');
  const msg = (q ? "我的问题："+q+"\n" : "") + "牌阵："+j.spread+"\n抽到的牌：\n"+cardDesc+"\n请按量化解读规则解读。";
  input.value = msg;
}

function copyText(t){
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(t).catch(()=>{});
  } else {
    const ta = document.createElement("textarea");
    ta.value = t; document.body.appendChild(ta); ta.select();
    try{ document.execCommand("copy"); }catch(e){}
    document.body.removeChild(ta);
  }
}

const SCRIPTS = [
  "你好～收到啦。为了解读更贴合，麻烦再补充一句：这件事里最让你纠结的具体是哪一点？（越具体越准）",
  "问得越详细结果越贴合，可以说下：谁、发生了什么、你卡在哪。",
  "解读已发你～确认收货后再送你一次，感谢支持。",
  "拍下后把具体情况发我，深度解读后回你完整结果，可追问可复盘。"
];
function copyScript(i){ copyText(SCRIPTS[i]); toast("已复制 ✅"); }
function toggleScript(){ const p=document.getElementById("scriptPanel"); p.style.display = (p.style.display==="none"||p.style.display==="") ? "block" : "none"; }
function toggleHelp(){ const h=document.getElementById("helpOverlay"); h.style.display = (h.style.display==="none"||h.style.display==="") ? "flex" : "none"; }
function toggleCase(){ const c=document.getElementById("caseOverlay"); c.style.display = (c.style.display==="none"||c.style.display==="") ? "flex" : "none"; }
function toggleSide(){ document.body.classList.toggle("sideopen"); }

function genDelivery(){
  const ais = [...document.querySelectorAll(".msg.ai")];
  const lastAi = ais.length ? ais[ais.length-1] : null;
  if(!lastAi){ alert("还没有 AI 回答，先提问出结果再交付"); return; }
  const b = lastAi.querySelector(".body");
  const a = (b ? b.textContent : lastAi.textContent).trim();
  const msg = "【解读】\n" + a + "\n\n———\n解读完成～确认收货后再送你一次，有问题随时问。";
  copyText(msg);
  toast("已复制完整发货消息 ✅");
}
function toast(msg){
  let t = document.getElementById("toast");
  if(!t){ t=document.createElement("div"); t.id="toast"; t.style.cssText="position:fixed;bottom:90px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:8px 16px;border-radius:20px;font-size:13px;opacity:0;transition:opacity .3s;z-index:99"; document.body.appendChild(t); }
  t.textContent = msg; t.style.opacity = "1";
  clearTimeout(t._h); t._h = setTimeout(()=>{ t.style.opacity = "0"; }, 1200);
}

function lastQuestion(){
  const us = [...document.querySelectorAll(".msg.user")];
  return us.length ? us[us.length-1].textContent.trim() : "";
}
function exportDoc(text){
  const q = lastQuestion();
  const title = q ? (q.length > 24 ? q.slice(0,24)+"…" : q) : "深度解读";
  const esc = s => (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  const html = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>${esc(title)}</title><style>
body{margin:0;background:#f5f1fb;font-family:"Microsoft YaHei","PingFang SC",sans-serif;color:#2a2138;line-height:1.95;font-size:16px}
.card{max-width:640px;margin:36px auto;background:#fff;border-radius:18px;padding:40px 44px;box-shadow:0 6px 30px rgba(88,54,140,.10)}
h1{font-size:22px;color:#5b3f9e;margin:0 0 8px;padding-bottom:16px;border-bottom:2px solid #efe9f9}
.q{color:#9a8fc0;font-size:13px;margin:0 0 28px}
.foot{margin-top:36px;padding-top:16px;border-top:1px solid #efe9f9;color:#b9b0cf;font-size:12px;text-align:center}
</style></head><body><div class="card"><h1>${esc(title)}</h1><div class="q">问题：${esc(q)}</div><div class="ans">${esc(text).replace(/\n/g,"<br>")}</div><div class="foot">深度解读 · 仅供自我探索参考</div></div></body></html>`;
  const blob = new Blob([html], {type:"text/html;charset=utf-8"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = title + ".html";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(a.href), 1500);
  toast("已导出文件 ✅");
}

async function exportImage(text){
  const q = lastQuestion();
  try{
    const r = await fetch("/api/export-image", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({question:q, answer:text})});
    if(!r.ok) throw new Error("HTTP "+r.status);
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "解读长图.png";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(()=>URL.revokeObjectURL(url), 1500);
    toast("已生成长图 ✅");
  }catch(e){ alert("生成失败: " + e); }
}

async function deleteCurrentChat(){
  if(!currentChatId) return;
  if(!confirm("删除当前对话？")) return;
  await api("/api/chats/"+currentChatId, {method:"DELETE"});
  currentChatId = null;
  chat.innerHTML = "";
  await loadChats();
  await newChat();
}

function toggleDeep(){
  deep = !deep;
  document.getElementById("deep").classList.toggle("on", deep);
}

document.querySelectorAll(".mode").forEach(el => {
  el.onclick = () => {
    document.querySelectorAll(".mode").forEach(x => x.classList.remove("on"));
    el.classList.add("on");
    currentMode = el.dataset.m;
    const isTarot = currentMode === "塔罗";
    document.getElementById("tarotRow").style.display = isTarot ? "flex" : "none";
    if(isTarot){ toast("塔罗用法：打问题 → 选牌阵 → 点🃏抽牌 → 点发送"); }
  };
});

// 加载牌阵
(async () => {
  const j = await api("/api/tarot/spreads");
  const sel = document.getElementById("spread");
  for(const s of j.spreads){
    const o = document.createElement("option");
    o.value = s.id; o.textContent = s.label + "（" + s.count + "张）";
    if(s.id === "three") o.selected = true;
    sel.appendChild(o);
  }
  const customO = document.createElement("option");
  customO.value = "custom"; customO.textContent = "自定义张数";
  sel.appendChild(customO);
  sel.onchange = () => {
    document.getElementById("customCount").style.display = sel.value === "custom" ? "inline-block" : "none";
  };
})();

// ---- 语音输入 ----
let recorder = null, chunks = [];
document.getElementById("mic").onclick = async () => {
  if(recorder && recorder.state === "recording"){ recorder.stop(); return; }
  try{
    const stream = await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true, noiseSuppression:true, autoGainControl:true}});
    recorder = new MediaRecorder(stream);
    chunks = [];
    recorder.ondataavailable = e => chunks.push(e.data);
    recorder.onstop = async () => {
      mic.classList.remove("rec"); mic.textContent = "🎤";
      const blob = new Blob(chunks, {type: recorder.mimeType || "audio/webm"});
      const fd = new FormData(); fd.append("file", blob, "rec.webm");
      mic.textContent = "…";
      try{
        const r = await fetch("/api/stt", {method:"POST", body: fd});
        const j = await r.json();
        if(j.text){ input.value = j.text; } else { alert("转写失败: " + (j.error||"空")); }
      }catch(e){ alert("转写失败: " + e); }
      mic.textContent = "🎤";
    };
    recorder.start();
    mic.classList.add("rec"); mic.textContent = "⏹";
  }catch(e){ alert("无法访问麦克风: " + e); }
};

document.getElementById("send").onclick = send;
input.addEventListener("keydown", e => { if(e.key === "Enter") send(); });

(async () => {
  if(localStorage.getItem("ququ_host") === "1" && activeCode){
    activeInfo = {plan: "店主", remaining: 0, is_host: true};
    document.getElementById("quota").textContent = "店主模式";
    applyRoleUI();
    document.getElementById("overlay").style.display = "none";
    await openFirstOrNew();
    return;
  }
  if(activeCode){
    const saved = localStorage.getItem("ququ_info");
    if(saved){ try{ activeInfo = JSON.parse(saved); }catch(e){} }
    const j = await api("/api/activate", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({code: activeCode})});
    if(j.error){
      doLogout();
    } else {
      activeInfo = j;
      setQuotaDisplay(j);
      applyRoleUI();
      document.getElementById("overlay").style.display = "none";
      await openFirstOrNew();
    }
  }
})();

document.getElementById("codeInput").addEventListener("keydown", e => { if(e.key === "Enter") doActivate(); });
</script>
</body>
</html>
"""


ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>邀请码管理</title>
<style>
:root{--bg:#0f1115;--panel:#171a21;--line:#262b36;--txt:#e8e6e3;--sub:#8b91a0;--accent:#d4a0ff;--tarot:#5bd0c8}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--txt);min-height:100vh}
.admin-wrap{max-width:760px;margin:0 auto;padding:28px 20px}
h1{font-size:20px;margin:0 0 18px}
a.back{color:var(--sub);font-size:13px;text-decoration:none;float:right}
a.back:hover{color:var(--accent)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:18px}
.card h2{font-size:15px;margin:0 0 14px;color:var(--tarot)}
.admin-row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:center}
.admin-row input,.admin-row select{padding:9px 11px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--txt);font-size:14px;outline:none}
.admin-row label{font-size:13px;color:var(--sub)}
button.gen{padding:10px 22px;border-radius:10px;border:none;background:var(--accent);color:#17121f;font-size:14px;font-weight:600;cursor:pointer}
.codes-table{width:100%;border-collapse:collapse;font-size:13px}
.codes-table th,.codes-table td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
.codes-table th{color:var(--sub);font-weight:600}
.codes-table .code{font-family:monospace;color:var(--accent);letter-spacing:1px}
.st-active{color:#6bd06b}.st-unused{color:var(--sub)}.st-expired{color:#ff6b6b}
.copybtn{color:var(--tarot);cursor:pointer;font-size:12px;white-space:nowrap}
.made{font-family:monospace;color:var(--accent);margin:6px 0;word-break:break-all}
</style>
</head>
<body>
<div class="admin-wrap">
  <a class="back" href="/">← 返回对话</a>
  <h1>⚙ 邀请码管理</h1>

  <div class="card">
    <h2>＋ 生成新邀请码</h2>
    <div class="admin-row">
      <label>套餐</label>
      <input id="fPlan" value="包月99" style="width:120px">
      <label>功能</label>
      <select id="fCategory">
        <option value="双功能" selected>双功能(曲曲+塔罗)</option>
        <option value="曲曲">仅曲曲</option>
        <option value="塔罗">仅塔罗</option>
      </select>
    </div>
    <div class="admin-row">
      <label>时长(天)</label>
      <input id="fDays" type="number" value="30" style="width:80px">
      <label>次数</label>
      <input id="fMax" type="number" value="500" style="width:80px">
      <label>生成数量</label>
      <input id="fCount" type="number" value="1" style="width:80px">
    </div>
    <div class="admin-row">
      <label>备注</label>
      <input id="fNote" placeholder="可选，比如：客户小张" style="flex:1;min-width:180px">
      <button class="gen" onclick="genCodes()">生成</button>
    </div>
    <div id="madeBox"></div>
  </div>

  <div class="card">
    <h2>现有邀请码</h2>
    <table class="codes-table">
      <thead><tr><th>邀请码</th><th>套餐</th><th>功能</th><th>剩余/总</th><th>状态</th><th>到期</th><th>备注</th><th></th></tr></thead>
      <tbody id="tbl"></tbody>
    </table>
  </div>
</div>

<script>
async function api(url, opts){ const r = await fetch(url, opts); return r.json(); }

const ST = {active:["使用中","st-active"], unused:["未激活","st-unused"], expired:["已到期","st-expired"]};

function fmtDate(s){ if(!s) return "-"; const d=new Date(s); return d.getFullYear()+"-"+(d.getMonth()+1)+"-"+d.getDate(); }

async function loadCodes(){
  const j = await api("/api/admin/codes");
  const tbl = document.getElementById("tbl");
  tbl.innerHTML = "";
  for(const c of j.codes){
    const [stText, stCls] = ST[c.status] || [c.status, ""];
    const tr = document.createElement("tr");
    const maxTxt = c.max_messages === 0 ? "无限" : c.max_messages;
    tr.innerHTML =
      '<td class="code">'+c.code+'</td>' +
      '<td>'+c.plan+'</td>' +
      '<td>'+c.category+'</td>' +
      '<td>'+(c.max_messages===0?"不限":c.remaining)+' / '+maxTxt+'</td>' +
      '<td class="'+stCls+'">'+stText+'</td>' +
      '<td>'+fmtDate(c.expires_at)+'</td>' +
      '<td>'+ (c.note||"") +'</td>' +
      '<td><span class="copybtn" onclick="copyCode(\''+c.code+'\')">复制</span></td>';
    tbl.appendChild(tr);
  }
}

async function genCodes(){
  const body = {
    plan: document.getElementById("fPlan").value.trim() || "包月99",
    category: document.getElementById("fCategory").value,
    duration_days: parseInt(document.getElementById("fDays").value,10) || 30,
    max_messages: parseInt(document.getElementById("fMax").value,10) || 0,
    count: parseInt(document.getElementById("fCount").value,10) || 1,
    note: document.getElementById("fNote").value.trim(),
  };
  const j = await api("/api/admin/codes", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
  if(j.codes && j.codes.length){
    document.getElementById("madeBox").innerHTML = '<div style="margin:6px 0;font-size:13px;color:var(--sub)">已生成，复制发给客户：</div>' + j.codes.map(c => '<div class="made">'+c+' <span class="copybtn" onclick="copyCode(\''+c+'\')">复制</span></div>').join("");
  }
  loadCodes();
}

function copyCode(code){
  const ta = document.createElement("textarea");
  ta.value = code; document.body.appendChild(ta); ta.select();
  try{ document.execCommand("copy"); }catch(e){}
  document.body.removeChild(ta);
  alert("已复制：" + code);
}

loadCodes();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import threading

    def _warmup_stt():
        try:
            from distill.processors.transcribe import get_model
            get_model()
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_warmup_stt, daemon=True).start()
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
