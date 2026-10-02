# -*- coding: utf-8 -*-
"""东方玄学算卦核心逻辑：梅花易数、小六壬、六爻
全部采用民间实战派断法，大白话解读，不用晦涩术语
"""
import datetime
import secrets

# ==================== 基础数据 ====================
# 八卦：五行、属性、对应数字
TRIGRAMS = {
    1: {"name": "乾", "element": "金", "nature": "天", "attr": "刚健、领导、父亲、男性"},
    2: {"name": "兑", "element": "金", "nature": "泽", "attr": "喜悦、口舌、少女、口才"},
    3: {"name": "离", "element": "火", "nature": "火", "attr": "光明、文书、中女、眼睛"},
    4: {"name": "震", "element": "木", "nature": "雷", "attr": "动、长男、名声、惊吓"},
    5: {"name": "巽", "element": "木", "nature": "风", "attr": "入、长女、生意、漂泊"},
    6: {"name": "坎", "element": "水", "nature": "水", "attr": "险、中男、智慧、奔波"},
    7: {"name": "艮", "element": "土", "nature": "山", "attr": "止、少男、房屋、阻碍"},
    8: {"name": "坤", "element": "土", "nature": "地", "attr": "顺、母亲、包容、大众"},
}

# 五行生克
ELEMENT_SHENG = {"金": "水", "水": "木", "木": "火", "火": "土", "土": "金"}
ELEMENT_KE = {"金": "木", "木": "土", "土": "水", "水": "火", "火": "金"}

# 64卦表：(上卦数, 下卦数) -> 卦名、卦辞
HEXAGRAMS = {
    (1,1): ("乾为天", "元亨利贞，刚健中正，诸事可成，但忌刚愎自用"),
    (1,2): ("天泽履", "如履薄冰，谨慎行事则吉，妄动则有险"),
    (1,3): ("天火同人", "与人合作，志同道合，谋事可成，利交友"),
    (1,4): ("天雷无妄", "不要妄动，顺其自然则吉，强求则招祸"),
    (1,5): ("天风姤", "偶遇，不期而遇，女子强势，防口舌是非"),
    (1,6): ("天水讼", "争讼，宜和解，不宜硬刚，退一步海阔天空"),
    (1,7): ("天山遁", "退避，暂时隐退则吉，急流勇退，不宜冒进"),
    (1,8): ("天地否", "闭塞，不通，诸事不顺，宜守不宜攻，等待时机"),
    (2,1): ("泽天夬", "决断，当断则断，去除小人，果敢则吉"),
    (2,2): ("兑为泽", "喜悦，口舌，利口才交际，防争执"),
    (2,3): ("泽火革", "变革，改变现状，破旧立新，宜变不宜守"),
    (2,4): ("泽雷随", "随从，顺势而为，跟随他人则吉，不宜固执"),
    (2,5): ("泽风大过", "过度，压力大，承担过重，宜量力而行"),
    (2,6): ("泽水困", "困境，受困，暂时不顺，守得云开见月明"),
    (2,7): ("泽山咸", "感应，两情相悦，利感情，心有灵犀"),
    (2,8): ("泽地萃", "聚集，聚会，利团队合作，人脉广则事成"),
    (3,1): ("火天大有", "大有收获，财运亨通，诸事顺遂，吉卦"),
    (3,2): ("火泽睽", "背离，意见不合，貌合神离，宜求同存异"),
    (3,3): ("离为火", "光明，依附，利文书名声，需要依附强者"),
    (3,4): ("火雷噬嗑", "咬合，排除障碍，果断处理，刑讼则吉"),
    (3,5): ("火风鼎", "鼎新，稳定，事业有成，利名声地位"),
    (3,6): ("火水未济", "未完成，事情还没成，差最后一步，坚持则成"),
    (3,7): ("火山旅", "旅行，漂泊，在外奔波，宜稳不宜动"),
    (3,8): ("火地晋", "晋升，进步，事业上升，前途光明"),
    (4,1): ("雷天大壮", "大壮，气势盛，宜守不宜攻，盛极必衰"),
    (4,2): ("雷泽归妹", "归妹，婚嫁，感情归宿，宜顺其自然"),
    (4,3): ("雷火丰", "丰盛，收获大，盛极一时，防乐极生悲"),
    (4,4): ("震为雷", "震动，惊动，有突发变动，临危不乱则吉"),
    (4,5): ("雷风恒", "恒久，持久，持之以恒则成，宜守不宜变"),
    (4,6): ("雷水解", "解除，困难解除，麻烦消散，吉卦"),
    (4,7): ("雷山小过", "小过，小的过失，宜小事不宜大事，低调行事"),
    (4,8): ("雷地豫", "预备，安乐，提前准备则吉，利享乐"),
    (5,1): ("风天小畜", "小畜，小的积累，暂时受阻，积蓄力量等待时机"),
    (5,2): ("风泽中孚", "中孚，诚信，诚实守信则吉，利合作"),
    (5,3): ("风火家人", "家人，家庭，利家事，内部团结则成"),
    (5,4): ("风雷益", "增益，受益，有好处，利投资助人"),
    (5,5): ("巽为风", "顺从，谦逊，顺势而为，宜低调"),
    (5,6): ("风水涣", "涣散，离散，人心散，宜凝聚，防破财"),
    (5,7): ("风山渐", "渐进，循序渐进，一步一步来，急则不成"),
    (5,8): ("风地观", "观察，观望，先看后动，不宜贸然行动"),
    (6,1): ("水天需", "需，等待，需要耐心，时机未到，等则吉"),
    (6,2): ("水泽节", "节制，节约，克制欲望，适度则吉"),
    (6,3): ("水火既济", "既济，已经完成，事情成了，防盛极而衰"),
    (6,4): ("水雷屯", "屯，艰难，起步难，万事开头难，坚持则成"),
    (6,5): ("水风井", "井，滋养，源源不断，利长期事业"),
    (6,6): ("坎为水", "坎，险，困难重重，步步为营，守正则吉"),
    (6,7): ("水山蹇", "蹇，艰难，行路难，宜退不宜进，等待时机"),
    (6,8): ("水地比", "比，亲近，依附贵人，与人亲近则吉"),
    (7,1): ("山天大畜", "大畜，大的积累，积蓄丰厚，利长期发展"),
    (7,2): ("山泽损", "损，损失，先损后益，吃亏是福，宜付出"),
    (7,3): ("山火贲", "贲，装饰，外表好看，重内在，防华而不实"),
    (7,4): ("山雷颐", "颐，养生，饮食，注意健康，宜修身养性"),
    (7,5): ("山风蛊", "蛊，腐败，问题积累，需要整治，宜清理旧弊"),
    (7,6): ("山水蒙", "蒙，蒙昧，迷茫，需要学习，请教他人则吉"),
    (7,7): ("艮为山", "艮，止，停止，宜静不宜动，停下来思考"),
    (7,8): ("山地剥", "剥，剥落，衰败，宜守不宜攻，防损失"),
    (8,1): ("地天泰", "泰，通泰，诸事顺遂，上下一心，大吉卦"),
    (8,2): ("地泽临", "临，临近，好运将至，主动出击则吉"),
    (8,3): ("地火明夷", "明夷，光明受损，怀才不遇，宜韬光养晦"),
    (8,4): ("地雷复", "复，复归，循环，好事重来，失而复得"),
    (8,5): ("地风升", "升，上升，步步高升，事业上升，吉卦"),
    (8,6): ("地水师", "师，军队，竞争，需要团队，领导有方则成"),
    (8,7): ("地山谦", "谦，谦虚，谦逊低调则吉，人人敬重"),
    (8,8): ("坤为地", "坤，柔顺，包容，厚德载物，宜顺从不宜强争"),
}

# 64卦世爻位置（标准：世应隔两爻）
SHI_POS = {
    (1,1):6, (1,2):3, (1,3):1, (1,4):4, (1,5):5, (1,6):2, (1,7):4, (1,8):3,
    (2,1):4, (2,2):6, (2,3):3, (2,4):2, (2,5):1, (2,6):4, (2,7):2, (2,8):1,
    (3,1):5, (3,2):4, (3,3):6, (3,4):3, (3,5):2, (3,6):1, (3,7):4, (3,8):3,
    (4,1):4, (4,2):3, (4,3):2, (4,4):6, (4,5):5, (4,6):2, (4,7):3, (4,8):1,
    (5,1):3, (5,2):4, (5,3):5, (5,4):4, (5,5):6, (5,6):2, (5,7):3, (5,8):4,
    (6,1):2, (6,2):3, (6,3):1, (6,4):3, (6,5):4, (6,6):6, (6,7):5, (6,8):2,
    (7,1):3, (7,2):2, (7,3):4, (7,4):3, (7,5):4, (7,6):1, (7,7):6, (7,8):5,
    (8,1):2, (8,2):1, (8,3):3, (8,4):1, (8,5):4, (8,6):2, (8,7):3, (8,8):6,
}

# ==================== 梅花易数 ====================
def meihua_by_numbers(n1: int, n2: int, n3: int = None):
    """梅花易数：数字起卦（标准算法）
    n1: 第一个数，n2: 第二个数，n3: 第三个数（不传则用n1+n2算动爻）
    标准：第一个数÷8取余定上卦，第二个数÷8取余定下卦，两数之和÷6取余定动爻
    """
    n1 = abs(int(n1)) % 8 or 8
    n2 = abs(int(n2)) % 8 or 8
    if n3 is None:
        n3 = (abs(int(n1)) + abs(int(n2))) % 6 or 6
    else:
        n3 = abs(int(n3)) % 6 or 6

    upper = TRIGRAMS[n1]
    lower = TRIGRAMS[n2]
    hex_name, hex_ci = HEXAGRAMS[(n1, n2)]

    # 体用：动爻所在的卦为用卦，另一卦为体卦（标准规则）
    # 动爻在1-3爻（下卦）→ 下卦为用，上卦为体
    # 动爻在4-6爻（上卦）→ 上卦为用，下卦为体
    if n3 <= 3:
        ti = upper
        yong = lower
    else:
        ti = lower
        yong = upper

    # 体用生克判断吉凶
    ti_el = ti["element"]
    yong_el = yong["element"]
    if ELEMENT_SHENG[yong_el] == ti_el:
        luck = "大吉"
        luck_desc = "用卦生体卦，这事有人帮你，顺水推舟，很容易成"
    elif ELEMENT_KE[yong_el] == ti_el:
        luck = "大凶"
        luck_desc = "用卦克体卦，这事阻碍大，有人跟你作对，硬上容易吃亏"
    elif ELEMENT_SHENG[ti_el] == yong_el:
        luck = "小凶"
        luck_desc = "体卦生用卦，你要付出很多才能成，耗精力耗钱，性价比不高"
    elif ELEMENT_KE[ti_el] == yong_el:
        luck = "小吉"
        luck_desc = "体卦克用卦，你能掌控这事，但是要费点力气，努力就能成"
    else:
        luck = "平"
        luck_desc = "体用比和，势均力敌，不凶不吉，按部就班就行"

    # 变卦
    # 动爻位置：从下往上数，n3是第几爻
    # 八卦二进制：乾111, 兑110, 离101, 震100, 巽011, 坎010, 艮001, 坤000
    trigram_bin = {1: "111", 2: "110", 3: "101", 4: "100", 5: "011", 6: "010", 7: "001", 8: "000"}
    bin_to_trigram = {v: k for k, v in trigram_bin.items()}

    upper_bin = list(trigram_bin[n1])
    lower_bin = list(trigram_bin[n2])
    if n3 <= 3:
        # 动爻在下卦
        idx = 3 - n3
        lower_bin[idx] = "1" if lower_bin[idx] == "0" else "0"
        new_lower = bin_to_trigram["".join(lower_bin)]
        new_upper = n1
    else:
        # 动爻在上卦
        idx = 6 - n3
        upper_bin[idx] = "1" if upper_bin[idx] == "0" else "0"
        new_upper = bin_to_trigram["".join(upper_bin)]
        new_lower = n2

    bian_name, bian_ci = HEXAGRAMS[(new_upper, new_lower)]

    # 应期（大白话）
    if luck in ["大吉", "小吉"]:
        yingqi = f"吉应：快的话{ti_el}对应时间（木=1-2个月/春季，火=夏天/3个月，土=辰戌丑未月，金=秋天/4个月，水=冬天/半年），慢的话看卦数{n1+n2}个月左右"
    else:
        yingqi = f"凶应：阻碍在{yong_el}当令的时候最明显（木=春季，火=夏天，土=三六九腊月，金=秋天，水=冬天），过了这个时间段就会缓解"

    return {
        "method": "梅花易数",
        "ben_gua": hex_name,
        "ben_ci": hex_ci,
        "bian_gua": bian_name,
        "bian_ci": bian_ci,
        "ti": ti["name"],
        "yong": yong["name"],
        "luck": luck,
        "luck_desc": luck_desc,
        "yingqi": yingqi,
        "dongyao": f"第{n3}爻动",
    }


def meihua_by_time():
    """梅花易数：时间起卦（标准算法）
    标准：年月日相加÷8取上卦，年月日时相加÷8取下卦，年月日时相加÷6取动爻
    注：传统用农历，这里简化用公历，民间也常用，不影响准确性
    """
    now = datetime.datetime.now()
    year_num = now.year % 12 or 12  # 年支数，简化用年模12
    n1 = (year_num + now.month + now.day) % 8 or 8
    n2 = (year_num + now.month + now.day + (now.hour + 1)) % 8 or 8
    n3 = (year_num + now.month + now.day + (now.hour + 1)) % 6 or 6
    return meihua_by_numbers(n1, n2, n3)


# ==================== 小六壬 ====================
XIAOLIUREN = [
    {"name": "大安", "luck": "大吉", "desc": "身不动，事安稳，失物不远，病者无妨，有贵人帮，诸事可成", "time": "很快，几天内"},
    {"name": "留连", "luck": "小凶", "desc": "事难成，反反复复，剪不断理还乱，没有进展，宜缓不宜急，别折腾", "time": "慢，拖延，几个月甚至更久"},
    {"name": "速喜", "luck": "大吉", "desc": "喜事临门，来得快，意料之外的惊喜，求财向南，失物能找回，利感情", "time": "很快，马上，几天内就有消息"},
    {"name": "赤口", "luck": "大凶", "desc": "主口舌是非，吵架官司，惹祸上身，防争执，不宜硬刚，出门注意安全", "time": "很快就会有麻烦，当天/几天内"},
    {"name": "小吉", "luck": "吉", "desc": "最吉昌，好事将近，有人帮，谋事可成，利感情利财运", "time": "半个月到一个月"},
    {"name": "空亡", "luck": "凶", "desc": "事不成，落空，白忙活一场，谋事无结果，宜守不宜动，不要抱太大期望", "time": "成不了，没有结果"},
]

def xiaoliuren_by_numbers(n1: int, n2: int, n3: int):
    """小六壬：三个数字起卦，分别对应月、日、时"""
    def get_idx(n):
        return (abs(int(n)) - 1) % 6

    i1 = get_idx(n1)
    i2 = (i1 + get_idx(n2)) % 6
    i3 = (i2 + get_idx(n3)) % 6

    r1 = XIAOLIUREN[i1]
    r2 = XIAOLIUREN[i2]
    r3 = XIAOLIUREN[i3]

    # 综合判断：看最后一个为主，前面两个为过程
    main = r3
    # 叠加判断
    bad_count = sum(1 for r in [r1, r2, r3] if r["luck"] in ["大凶", "凶", "小凶"])
    good_count = sum(1 for r in [r1, r2, r3] if r["luck"] in ["大吉", "吉"])

    if bad_count >= 2:
        final_luck = "凶"
        final_desc = "三个结果里有两个以上不好，这事大概率成不了，别折腾了，及时止损"
    elif good_count >= 2:
        final_luck = "吉"
        final_desc = "三个结果里有两个以上好，这事能成，而且过程顺利，有人帮"
    else:
        final_luck = main["luck"]
        final_desc = f"最终结果是「{main['name']}」：{main['desc']}"

    return {
        "method": "小六壬",
        "r1": r1,
        "r2": r2,
        "r3": r3,
        "final_luck": final_luck,
        "final_desc": final_desc,
        "time": main["time"],
    }


def xiaoliuren_by_time():
    """小六壬：时间起卦"""
    now = datetime.datetime.now()
    return xiaoliuren_by_numbers(now.month, now.day, now.hour + 1)


# ==================== 六爻（简化版，铜钱摇卦）====================
LIUYAO_LUCK = {
    "世生应": "你主动，愿意付出，关系/事情能成，但是你要多费心",
    "应生世": "对方/外界主动帮你，有人托底，很容易成",
    "世克应": "你能掌控，但是要费力气，努力就能成",
    "应克世": "对方/外界压你，阻碍大，硬上容易吃亏",
    "世应比和": "双方平等，势均力敌，按部就班就能成",
}

def liuyao_by_coins():
    """六爻：模拟三枚铜钱摇六次，自动起卦
    返回：本卦、变卦、世应、动爻、吉凶判断
    """
    # 摇六次，每次三枚铜钱（标准：背为阳，字为阴）
    # 1个背=少阳(7)，2个背=少阴(8)，3个背=老阳(9，动)，0个背=老阴(6，动)
    lines = []
    for _ in range(6):
        coins = [secrets.randbelow(2) for _ in range(3)]  # 0=字(阴)，1=背(阳)
        cnt = sum(coins)  # 背的数量
        if cnt == 0:
            lines.append(6)  # 0背=老阴，动
        elif cnt == 1:
            lines.append(7)  # 1背=少阳
        elif cnt == 2:
            lines.append(8)  # 2背=少阴
        else:
            lines.append(9)  # 3背=老阳，动

    # lines从下往上，第0爻是初爻
    # 转成上下卦：下卦是初、二、三爻，上卦是四、五、上爻
    def get_trigram(l1, l2, l3):
        # 阳爻(7,9)=1，阴爻(6,8)=0，从下往上
        b = ""
        for l in [l3, l2, l1]:
            b += "1" if l in [7, 9] else "0"
        bin_map = {"111":1, "110":2, "101":3, "100":4, "011":5, "010":6, "001":7, "000":8}
        return bin_map[b]

    lower = get_trigram(lines[0], lines[1], lines[2])
    upper = get_trigram(lines[3], lines[4], lines[5])
    ben_name, ben_ci = HEXAGRAMS[(upper, lower)]

    # 动爻
    dong = [i+1 for i, l in enumerate(lines) if l in [6, 9]]

    # 变卦
    new_lines = []
    for l in lines:
        if l == 6:
            new_lines.append(7)
        elif l == 9:
            new_lines.append(8)
        else:
            new_lines.append(l)
    new_lower = get_trigram(new_lines[0], new_lines[1], new_lines[2])
    new_upper = get_trigram(new_lines[3], new_lines[4], new_lines[5])
    bian_name, bian_ci = HEXAGRAMS[(new_upper, new_lower)]

    # 世应位置（标准：世应永远隔两爻，按64卦世爻位置表）
    shi_pos = SHI_POS[(upper, lower)]  # 1-6，从下往上数
    shi_idx = shi_pos - 1
    ying_idx = (shi_idx + 3) % 6  # 世应隔三爻（索引差3）
    shi_el = TRIGRAMS[lower if shi_idx < 3 else upper]["element"]
    ying_el = TRIGRAMS[lower if ying_idx < 3 else upper]["element"]

    if ELEMENT_SHENG[shi_el] == ying_el:
        relation = "世生应"
    elif ELEMENT_SHENG[ying_el] == shi_el:
        relation = "应生世"
    elif ELEMENT_KE[shi_el] == ying_el:
        relation = "世克应"
    elif ELEMENT_KE[ying_el] == shi_el:
        relation = "应克世"
    else:
        relation = "世应比和"

    return {
        "method": "六爻",
        "ben_gua": ben_name,
        "ben_ci": ben_ci,
        "bian_gua": bian_name,
        "bian_ci": bian_ci,
        "dongyao": f"第{','.join(map(str, dong))}爻动" if dong else "无动爻",
        "relation": relation,
        "relation_desc": LIUYAO_LUCK[relation],
        "lines": lines,
    }
