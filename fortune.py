# -*- coding: utf-8 -*-
"""
运势核心排盘模块 (fortune.py)
=============================
基于 lunar_python (八字/黄历) 和 kerykeion v6 (西方占星) 成熟开源库。
所有函数返回 JSON 可序列化的 dict，方便传给前端和 AI 解读。

包含:
  - 八字排盘: 本命 / 大运 / 流年 / 流月 / 流日 / 十神 / 五行 / 神煞(十二长生)
  - 黄历: 宜忌 / 吉日吉时 / 冲煞 / 方位
  - 星盘: 本命 / 日返 / 次限 / 行运 / 比较盘 / 组合盘
  - 合婚数据: 八字合婚 + 星盘合盘综合

风格统一: 与塔罗/梅花/小六壬/六爻模块一致，数据结构化、大白话可读。
"""

import sys
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

# ==================== 库导入 ====================
from lunar_python import Solar, Lunar

# kerykeion v6 — 工厂模式
_KER_AVAILABLE = False
try:
    from kerykeion import AstrologicalSubjectFactory
    from kerykeion import CompositeSubjectFactory
    from kerykeion import SecondaryProgressionFactory
    from kerykeion import RelationshipScoreFactory
    from kerykeion import PlanetaryReturnFactory
    _KER_AVAILABLE = True
except Exception as _e:
    logging.warning(f"kerykeion 导入失败，星盘功能降级: {_e}")


# ==================== 国内主要城市经纬度 ====================
CITY_COORDS = {
    "北京": (39.9042, 116.4074), "上海": (31.2304, 121.4737),
    "广州": (23.1291, 113.2644), "深圳": (22.5431, 114.0579),
    "杭州": (30.2741, 120.1551), "成都": (30.5728, 104.0668),
    "重庆": (29.5630, 106.5516), "武汉": (30.5928, 114.3055),
    "西安": (34.3416, 108.9398), "南京": (32.0603, 118.7969),
    "天津": (39.3434, 117.3616), "苏州": (31.2989, 120.5853),
    "长沙": (28.2282, 112.9388), "郑州": (34.7466, 113.6254),
    "青岛": (36.0671, 120.3826), "大连": (38.9140, 121.6147),
    "厦门": (24.4798, 118.0894), "福州": (26.0745, 119.2965),
    "济南": (36.6512, 117.1201), "合肥": (31.8206, 117.2272),
    "南昌": (28.6820, 115.8579), "昆明": (25.0389, 102.7183),
    "贵阳": (26.6470, 106.6302), "南宁": (22.8170, 108.3669),
    "兰州": (36.0611, 103.8343), "太原": (37.8706, 112.5489),
    "石家庄": (38.0428, 114.5149), "哈尔滨": (45.8038, 126.5349),
    "长春": (43.8171, 125.3235), "沈阳": (41.8057, 123.4315),
    "呼和浩特": (40.8426, 111.7492), "银川": (38.4872, 106.2309),
    "西宁": (36.6171, 101.7782), "乌鲁木齐": (43.8256, 87.6168),
    "拉萨": (29.6520, 91.1721), "海口": (20.0440, 110.1989),
}

SIGN_MAP = {"Ari":"白羊","Tau":"金牛","Gem":"双子","Can":"巨蟹","Leo":"狮子","Vir":"处女",
            "Lib":"天秤","Sco":"天蝎","Sag":"射手","Cap":"摩羯","Aqu":"水瓶","Pis":"双鱼"}
PLANET_MAP = {"Sun":"太阳","Moon":"月亮","Mercury":"水星","Venus":"金星","Mars":"火星",
              "Jupiter":"木星","Saturn":"土星","Uranus":"天王星","Neptune":"海王星",
              "Pluto":"冥王星","Chiron":"凯龙星","True_North_Lunar_Node":"北交点"}
HOUSE_MAP = {"First_House":"一宫(命宫)","Second_House":"二宫(财帛)","Third_House":"三宫(兄弟)",
             "Fourth_House":"四宫(田宅)","Fifth_House":"五宫(子女)","Sixth_House":"六宫(奴仆)",
             "Seventh_House":"七宫(夫妻)","Eighth_House":"八宫(疾厄)","Ninth_House":"九宫(迁移)",
             "Tenth_House":"十宫(官禄)","Eleventh_House":"十一宫(福德)","Twelfth_House":"十二宫(玄秘)"}

ZHI_SHENGXIAO = {"子":"鼠","丑":"牛","寅":"虎","卯":"兔","辰":"龙","巳":"蛇",
                 "午":"马","未":"羊","申":"猴","酉":"鸡","戌":"狗","亥":"猪"}
SHENGXIAO_HELIU = {("鼠","牛"),("虎","猪"),("兔","狗"),("龙","鸡"),("蛇","猴"),("马","羊")}
SHENGXIAO_CHONG = {("鼠","马"),("牛","羊"),("虎","猴"),("兔","鸡"),("龙","狗"),("蛇","猪")}


def _get_city_coords(city: str = "", lat: float = 0, lng: float = 0) -> tuple:
    """根据城市名获取经纬度，不在字典里默认北京"""
    if lat and lng:
        return lat, lng
    if city and city in CITY_COORDS:
        return CITY_COORDS[city]
    return 39.9042, 116.4074


def _sf(v, default=0.0):
    try:
        return round(float(v), 2)
    except Exception:
        return default


# ==================== 八字内部工具 ====================

def _get_ec(by, bm, bd, bh, bmi, gender):
    """获取 (lunar, EightChar) 对象"""
    solar = Solar.fromYmdHms(by, bm, bd, bh, bmi, 0)
    lunar = solar.getLunar()
    return lunar, lunar.getEightChar()


def _count_wuxing(ec) -> Dict[str, int]:
    """统计四柱五行个数"""
    count = {"金": 0, "木": 0, "水": 0, "火": 0, "土": 0}
    for pillar in ["Year", "Month", "Day", "Time"]:
        wx = getattr(ec, f"get{pillar}WuXing")()
        for c in wx:
            if c in count:
                count[c] += 1
    return count


def _find_dayun_for_year(dayuns, target_year):
    """在大运列表中找到包含目标年份的大运对象"""
    for dy in dayuns:
        if dy.getStartYear() <= target_year <= dy.getEndYear():
            return dy
    return dayuns[0] if dayuns else None


# ==================== 八字排盘 ====================

def bazi_chart(birth_year: int, birth_month: int, birth_day: int,
               birth_hour: int, birth_minute: int, gender: int,
               city: str = "", lat: float = 0, lng: float = 0) -> Dict[str, Any]:
    """八字本命排盘
    Args:
        birth_year/month/day/hour/minute: 出生时间 (小时 0-23)
        gender: 1=男, 0=女
    Returns: 四柱、日主、十神、藏干、纳音、五行、十二长生、命宫身宫、旬空
    """
    try:
        lunar, ec = _get_ec(birth_year, birth_month, birth_day, birth_hour, birth_minute, gender)
        return {
            "type": "bazi_natal",
            "birth": f"{birth_year}-{birth_month:02d}-{birth_day:02d} {birth_hour:02d}:{birth_minute:02d}",
            "gender": "男" if gender == 1 else "女",
            "city": city,
            "lunar_date": f"{lunar.getYearInChinese()}年{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}",
            "four_pillars": {
                "year": {"ganzhi": ec.getYear(), "gan": ec.getYearGan(), "zhi": ec.getYearZhi(),
                         "wuxing": ec.getYearWuXing(), "nayin": ec.getYearNaYin()},
                "month": {"ganzhi": ec.getMonth(), "gan": ec.getMonthGan(), "zhi": ec.getMonthZhi(),
                          "wuxing": ec.getMonthWuXing(), "nayin": ec.getMonthNaYin()},
                "day":   {"ganzhi": ec.getDay(),   "gan": ec.getDayGan(),   "zhi": ec.getDayZhi(),
                          "wuxing": ec.getDayWuXing(),   "nayin": ec.getDayNaYin()},
                "time":  {"ganzhi": ec.getTime(),  "gan": ec.getTimeGan(),  "zhi": ec.getTimeZhi(),
                          "wuxing": ec.getTimeWuXing(),  "nayin": ec.getTimeNaYin()},
            },
            "day_master": ec.getDayGan(),
            "shishen_gan": {
                "year": ec.getYearShiShenGan(),
                "month": ec.getMonthShiShenGan(),
                "time": ec.getTimeShiShenGan(),
            },
            "shishen_zhi": {
                "year": ec.getYearShiShenZhi(),
                "month": ec.getMonthShiShenZhi(),
                "day": ec.getDayShiShenZhi(),
                "time": ec.getTimeShiShenZhi(),
            },
            "hide_gan": {
                "year": ec.getYearHideGan(), "month": ec.getMonthHideGan(),
                "day": ec.getDayHideGan(),   "time": ec.getTimeHideGan(),
            },
            "wuxing_count": _count_wuxing(ec),
            "di_shi": {  # 十二长生 (神煞替代)
                "year": ec.getYearDiShi(), "month": ec.getMonthDiShi(),
                "day": ec.getDayDiShi(),   "time": ec.getTimeDiShi(),
            },
            "special_palaces": {
                "ming_gong": ec.getMingGong(), "ming_gong_nayin": ec.getMingGongNaYin(),
                "shen_gong": ec.getShenGong(), "shen_gong_nayin": ec.getShenGongNaYin(),
                "tai_yuan": ec.getTaiYuan(),   "tai_yuan_nayin": ec.getTaiYuanNaYin(),
                "tai_xi": ec.getTaiXi(),       "tai_xi_nayin": ec.getTaiXiNaYin(),
            },
            "xunkong": {"year": ec.getYearXunKong(), "day": ec.getDayXunKong()},
        }
    except Exception as e:
        logging.exception("bazi_chart error")
        return {"error": f"八字排盘失败: {e}"}


def bazi_dayun(birth_year: int, birth_month: int, birth_day: int,
               birth_hour: int, birth_minute: int, gender: int) -> Dict[str, Any]:
    """大运表: 起运信息 + 10步大运"""
    try:
        _, ec = _get_ec(birth_year, birth_month, birth_day, birth_hour, birth_minute, gender)
        yun = ec.getYun(gender)
        dayuns = yun.getDaYun()
        dayun_list = []
        for dy in dayuns[:10]:
            gz = dy.getGanZhi()
            if not gz:  # 第一步可能为空(童限)
                continue
            dayun_list.append({
                "ganzhi": gz,
                "start_age": dy.getStartAge(),
                "end_age": dy.getEndAge(),
                "start_year": dy.getStartYear(),
                "end_year": dy.getEndYear(),
            })
        return {
            "type": "bazi_dayun",
            "start_year": yun.getStartYear(),
            "start_month": yun.getStartMonth(),
            "dayun_list": dayun_list,
        }
    except Exception as e:
        logging.exception("bazi_dayun error")
        return {"error": f"大运排盘失败: {e}"}


def bazi_liunian(birth_year: int, birth_month: int, birth_day: int,
                 birth_hour: int, birth_minute: int, gender: int,
                 start_year: int, end_year: int) -> Dict[str, Any]:
    """流年: 指定年份范围内的流年干支"""
    try:
        _, ec = _get_ec(birth_year, birth_month, birth_day, birth_hour, birth_minute, gender)
        yun = ec.getYun(gender)
        dayuns = yun.getDaYun()
        result = []
        for year in range(start_year, end_year + 1):
            dy = _find_dayun_for_year(dayuns, year)
            if not dy:
                continue
            for ln in dy.getLiuNian():
                if ln.getYear() == year:
                    result.append({"year": year, "ganzhi": ln.getGanZhi(),
                                   "dayun": dy.getGanZhi()})
                    break
        return {"type": "bazi_liunian", "range": f"{start_year}-{end_year}", "liunian_list": result}
    except Exception as e:
        logging.exception("bazi_liunian error")
        return {"error": f"流年排盘失败: {e}"}


def bazi_liuyue(birth_year: int, birth_month: int, birth_day: int,
                birth_hour: int, birth_minute: int, gender: int,
                year: int) -> Dict[str, Any]:
    """当年流月(12个月)"""
    try:
        _, ec = _get_ec(birth_year, birth_month, birth_day, birth_hour, birth_minute, gender)
        yun = ec.getYun(gender)
        dy = _find_dayun_for_year(yun.getDaYun(), year)
        if not dy:
            return {"error": "未找到对应大运"}
        result = []
        for ln in dy.getLiuNian():
            if ln.getYear() == year:
                for ly in ln.getLiuYue():
                    result.append({"ganzhi": ly.getGanZhi(), "month_cn": ly.getMonthInChinese()})
                break
        return {"type": "bazi_liuyue", "year": year, "liuyue_list": result}
    except Exception as e:
        logging.exception("bazi_liuyue error")
        return {"error": f"流月排盘失败: {e}"}


def bazi_liuri(birth_year: int, birth_month: int, birth_day: int,
               birth_hour: int, birth_minute: int, gender: int,
               year: int, month: int) -> Dict[str, Any]:
    """当月流日 (逐日干支)"""
    try:
        # 确定当月天数
        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)
        last_day = (next_month - timedelta(days=1)).day
        result = []
        for d in range(1, last_day + 1):
            l = Solar.fromYmdHms(year, month, d, 12, 0, 0).getLunar()
            result.append({"day": d, "ganzhi": l.getDayInGanZhi(),
                           "lunar_day": l.getDayInChinese()})
        return {"type": "bazi_liuri", "year_month": f"{year}-{month:02d}", "liuri_list": result}
    except Exception as e:
        logging.exception("bazi_liuri error")
        return {"error": f"流日排盘失败: {e}"}


def bazi_full(birth_info: Dict, target_type: str, target_params: Dict) -> Dict[str, Any]:
    """八字综合函数"""
    by, bm, bd = birth_info["year"], birth_info["month"], birth_info["day"]
    bh, bmi = birth_info["hour"], birth_info["minute"]
    gender = birth_info.get("gender", 1)
    city = birth_info.get("city", "")
    now = datetime.now()

    result = {"type": f"bazi_full_{target_type}"}
    result["natal"] = bazi_chart(by, bm, bd, bh, bmi, gender, city)
    result["dayun"] = bazi_dayun(by, bm, bd, bh, bmi, gender)

    if target_type == "day":
        result["liuri"] = bazi_liuri(by, bm, bd, bh, bmi, gender, now.year, now.month)
    elif target_type == "month":
        result["liuyue"] = bazi_liuyue(by, bm, bd, bh, bmi, gender, now.year)
        result["liuri"] = bazi_liuri(by, bm, bd, bh, bmi, gender, now.year, now.month)
    elif target_type == "year":
        result["liunian"] = bazi_liunian(by, bm, bd, bh, bmi, gender, now.year - 2, now.year + 2)
        result["liuyue"] = bazi_liuyue(by, bm, bd, bh, bmi, gender, now.year)
    elif target_type == "recent":
        result["liunian"] = bazi_liunian(by, bm, bd, bh, bmi, gender, now.year, now.year + 1)
        result["liuyue"] = bazi_liuyue(by, bm, bd, bh, bmi, gender, now.year)
    elif target_type == "custom":
        sy = target_params.get("start_year", now.year)
        ey = target_params.get("end_year", now.year + 1)
        result["liunian"] = bazi_liunian(by, bm, bd, bh, bmi, gender, sy, ey)
    else:
        result["liunian"] = bazi_liunian(by, bm, bd, bh, bmi, gender, now.year - 1, now.year + 3)
        result["liuyue"] = bazi_liuyue(by, bm, bd, bh, bmi, gender, now.year)
    return result


# ==================== 黄历 ====================

def almanac_day(year: int, month: int, day: int) -> Dict[str, Any]:
    """单日黄历"""
    try:
        lunar = Solar.fromYmdHms(year, month, day, 12, 0, 0).getLunar()
        return {
            "type": "almanac_day",
            "date": f"{year}-{month:02d}-{day:02d}",
            "lunar_date": f"{lunar.getYearInChinese()}年{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}",
            "ganzhi": {"year": lunar.getYearInGanZhi(), "month": lunar.getMonthInGanZhi(),
                       "day": lunar.getDayInGanZhi()},
            "yi": lunar.getDayYi(), "ji": lunar.getDayJi(),
            "ji_shen": lunar.getDayJiShen(), "xiong_sha": lunar.getDayXiongSha(),
            "chong": lunar.getDayChongDesc(), "sha": lunar.getDaySha(),
            "positions": {"xi": lunar.getDayPositionXi(), "cai": lunar.getDayPositionCai(),
                          "fu": lunar.getDayPositionFu(),
                          "yang_gui": lunar.getDayPositionYangGui(),
                          "yin_gui": lunar.getDayPositionYinGui()},
            "pengzu": f"{lunar.getPengZuGan()} {lunar.getPengZuZhi()}",
            "jieqi": lunar.getJieQi() or None,
            "zodiac": lunar.getYearShengXiao(),
        }
    except Exception as e:
        logging.exception("almanac_day error")
        return {"error": f"黄历查询失败: {e}"}


def almanac_range(start_date: str, end_date: str) -> Dict[str, Any]:
    """时间段黄历"""
    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d").date()
        ed = datetime.strptime(end_date, "%Y-%m-%d").date()
        days = []
        cur = sd
        while cur <= ed:
            info = almanac_day(cur.year, cur.month, cur.day)
            info["is_auspicious"] = len(info.get("yi", [])) >= 3
            days.append(info)
            cur += timedelta(days=1)
        return {"type": "almanac_range", "start": start_date, "end": end_date, "days": days}
    except Exception as e:
        logging.exception("almanac_range error")
        return {"error": f"时间段黄历失败: {e}"}


def auspicious_times(year: int, month: int, day: int) -> Dict[str, Any]:
    """当日十二时辰吉凶宜忌"""
    try:
        lunar = Solar.fromYmdHms(year, month, day, 12, 0, 0).getLunar()
        times = lunar.getTimes()
        time_list = []
        for t in times:
            time_list.append({
                "ganzhi": t.getGanZhi(),
                "tian_shen": t.getTianShen(),
                "tian_shen_luck": t.getTianShenLuck(),
                "chong": t.getChongDesc(),
                "yi": t.getYi(), "ji": t.getJi(),
                "position_xi": t.getPositionXiDesc(),
                "position_cai": t.getPositionCaiDesc(),
            })
        return {"type": "auspicious_times", "date": f"{year}-{month:02d}-{day:02d}", "times": time_list}
    except Exception as e:
        logging.exception("auspicious_times error")
        return {"error": f"吉时查询失败: {e}"}


def find_auspicious_days(start_date: str, end_date: str, activity: str) -> Dict[str, Any]:
    """在时间段内找适合做某事的吉日"""
    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d").date()
        ed = datetime.strptime(end_date, "%Y-%m-%d").date()
        good_days = []
        cur = sd
        while cur <= ed:
            info = almanac_day(cur.year, cur.month, cur.day)
            if activity in info.get("yi", []):
                good_days.append({
                    "date": info["date"], "lunar_date": info["lunar_date"],
                    "ganzhi_day": info["ganzhi"]["day"],
                    "yi": info["yi"], "chong": info["chong"],
                })
            cur += timedelta(days=1)
        return {"type": "find_auspicious_days", "activity": activity,
                "range": f"{start_date}~{end_date}",
                "count": len(good_days), "good_days": good_days}
    except Exception as e:
        logging.exception("find_auspicious_days error")
        return {"error": f"吉日查找失败: {e}"}


# ==================== 星盘 ====================

def _make_subj(bi: Dict):
    """用 kerykeion 创建 subject"""
    lat, lng = _get_city_coords(bi.get("city", ""), bi.get("lat", 0), bi.get("lng", 0))
    return AstrologicalSubjectFactory.from_birth_data(
        name=bi.get("name", "User"),
        year=bi["year"], month=bi["month"], day=bi["day"],
        hour=bi["hour"], minute=bi["minute"],
        city=bi.get("city", "Beijing"), nation="China",
        lat=lat, lng=lng, tz_str="Asia/Shanghai", online=False,
    )


def _extract_planets(subj) -> List[Dict]:
    """提取行星数据"""
    out = []
    for pk in ["sun","moon","mercury","venus","mars","jupiter","saturn",
               "uranus","neptune","pluto","chiron","true_north_lunar_node"]:
        p = getattr(subj, pk, None)
        if p is None:
            continue
        out.append({
            "name": PLANET_MAP.get(p.name, p.name),
            "sign": SIGN_MAP.get(p.sign, p.sign),
            "position": _sf(p.position),
            "house": HOUSE_MAP.get(p.house, p.house),
            "retrograde": bool(p.retrograde),
            "element": p.element, "quality": p.quality,
        })
    return out


def _get_angles(subj) -> Dict:
    """提取四轴"""
    return {
        "ascendant": {"sign": SIGN_MAP.get(subj.ascendant.sign, subj.ascendant.sign),
                      "position": _sf(subj.ascendant.position)},
        "mc": {"sign": SIGN_MAP.get(subj.medium_coeli.sign, subj.medium_coeli.sign),
               "position": _sf(subj.medium_coeli.position)},
        "descendant": {"sign": SIGN_MAP.get(subj.descendant.sign, subj.descendant.sign),
                       "position": _sf(subj.descendant.position)},
        "ic": {"sign": SIGN_MAP.get(subj.imum_coeli.sign, subj.imum_coeli.sign),
               "position": _sf(subj.imum_coeli.position)},
    }


def astrology_natal(birth_year: int, birth_month: int, birth_day: int,
                   birth_hour: int, birth_minute: int,
                   lat: float, lng: float, city: str = "") -> Dict[str, Any]:
    """本命盘"""
    if not _KER_AVAILABLE:
        return {"error": "kerykeion 不可用"}
    try:
        subj = _make_subj({"year":birth_year,"month":birth_month,"day":birth_day,
                           "hour":birth_hour,"minute":birth_minute,"city":city,"lat":lat,"lng":lng})
        return {"type": "astrology_natal",
                "birth": f"{birth_year}-{birth_month:02d}-{birth_day:02d} {birth_hour:02d}:{birth_minute:02d}",
                "city": city, "planets": _extract_planets(subj),
                **_get_angles(subj), "is_diurnal": subj.is_diurnal}
    except Exception as e:
        logging.exception("astrology_natal error")
        return {"error": f"本命盘失败: {e}"}


def astrology_solar_return(birth_info: Dict, year: int) -> Dict[str, Any]:
    """日返盘 (当年运势)"""
    if not _KER_AVAILABLE:
        return {"error": "kerykeion 不可用"}
    try:
        lat, lng = _get_city_coords(birth_info.get("city",""), birth_info.get("lat",0), birth_info.get("lng",0))
        subj = _make_subj(birth_info)
        pr = PlanetaryReturnFactory(subject=subj, city=birth_info.get("city","Beijing"),
                                     nation="China", lng=lng, lat=lat,
                                     tz_str="Asia/Shanghai", online=False)
        sr = pr.next_return_from_year(year=year, return_type="Solar")
        return {"type": "solar_return", "return_year": year,
                "planets": _extract_planets(sr), **_get_angles(sr)}
    except Exception as e:
        logging.exception("astrology_solar_return error")
        return {"error": f"日返盘失败: {e}"}


def astrology_secondary_progression(birth_info: Dict, target_date: str) -> Dict[str, Any]:
    """次限盘"""
    if not _KER_AVAILABLE:
        return {"error": "kerykeion 不可用"}
    try:
        dt = datetime.strptime(target_date, "%Y-%m-%d")
        subj = _make_subj(birth_info)
        prog = SecondaryProgressionFactory.compute(natal_subject=subj, target_year=dt.year)
        return {"type": "secondary_progression", "target_date": target_date,
                "planets": _extract_planets(prog), **_get_angles(prog)}
    except Exception as e:
        logging.exception("astrology_secondary_progression error")
        return {"error": f"次限盘失败: {e}"}


def astrology_synastry(birth_info_1: Dict, birth_info_2: Dict) -> Dict[str, Any]:
    """比较盘 (两人行星 + 关系评分)"""
    if not _KER_AVAILABLE:
        return {"error": "kerykeion 不可用"}
    try:
        s1 = _make_subj(birth_info_1)
        s2 = _make_subj(birth_info_2)
        rs_f = RelationshipScoreFactory(first_subject=s1, second_subject=s2)
        score = rs_f.get_relationship_score()
        aspects = []
        if hasattr(score, 'aspects'):
            for a in score.aspects[:15]:
                aspects.append({"p1": PLANET_MAP.get(a.p1_name, a.p1_name),
                                "p2": PLANET_MAP.get(a.p2_name, a.p2_name),
                                "aspect": a.aspect, "orbit": _sf(a.orbit)})
        return {"type": "synastry",
                "score": getattr(score, 'score_value', 0),
                "score_desc": getattr(score, 'score_description', ''),
                "is_destiny": getattr(score, 'is_destiny_sign', False),
                "key_aspects": aspects,
                "p1_planets": _extract_planets(s1),
                "p2_planets": _extract_planets(s2)}
    except Exception as e:
        logging.exception("astrology_synastry error")
        return {"error": f"比较盘失败: {e}"}


def astrology_composite(birth_info_1: Dict, birth_info_2: Dict) -> Dict[str, Any]:
    """组合盘"""
    if not _KER_AVAILABLE:
        return {"error": "kerykeion 不可用"}
    try:
        s1 = _make_subj(birth_info_1)
        s2 = _make_subj(birth_info_2)
        comp = CompositeSubjectFactory(first_subject=s1, second_subject=s2).get_midpoint_composite_subject_model()
        return {"type": "composite", "planets": _extract_planets(comp), **_get_angles(comp)}
    except Exception as e:
        logging.exception("astrology_composite error")
        return {"error": f"组合盘失败: {e}"}


def astrology_lunar_return(birth_info: Dict, target_date: str) -> Dict[str, Any]:
    """月返盘 (真实月返: 月亮回归到出生位置)"""
    if not _KER_AVAILABLE:
        return {"error": "kerykeion 不可用"}
    try:
        dt = datetime.strptime(target_date, "%Y-%m-%d")
        lat, lng = _get_city_coords(birth_info.get("city", ""), birth_info.get("lat", 0), birth_info.get("lng", 0))
        subj = _make_subj(birth_info)
        pr = PlanetaryReturnFactory(subject=subj, city=birth_info.get("city", "Beijing"),
                                     nation="China", lng=lng, lat=lat,
                                     tz_str="Asia/Shanghai", online=False)
        lr = pr.next_return_from_year(year=dt.year, return_type="Lunar")
        return {"type": "lunar_return", "return_date": target_date,
                "planets": _extract_planets(lr), **_get_angles(lr)}
    except Exception as e:
        logging.exception("astrology_lunar_return error")
        return {"error": f"月返盘失败: {e}"}


def astrology_transits(birth_info: Dict, target_date: str = "") -> Dict[str, Any]:
    """行运盘 (目标日期的现实天空星体位置,即过境天空盘)"""
    if not _KER_AVAILABLE:
        return {"error": "kerykeion 不可用"}
    try:
        if target_date:
            dt = datetime.strptime(target_date, "%Y-%m-%d")
        else:
            dt = datetime.now()
        lat, lng = _get_city_coords(birth_info.get("city", ""), birth_info.get("lat", 0), birth_info.get("lng", 0))
        # 以目标日期中午在出生地排一张"天空盘",代表当下过境星体
        sky = _make_subj({"year": dt.year, "month": dt.month, "day": dt.day,
                          "hour": 12, "minute": 0, "city": birth_info.get("city", "北京"),
                          "lat": lat, "lng": lng})
        natal = _make_subj(birth_info)
        return {"type": "transits", "target_date": dt.strftime("%Y-%m-%d"),
                "transit_sky": _extract_planets(sky),
                "natal_planets": _extract_planets(natal),
                **_get_angles(sky)}
    except Exception as e:
        logging.exception("astrology_transits error")
        return {"error": f"行运盘失败: {e}"}


def astrology_tertiary_progression(birth_info: Dict, target_date: str = "") -> Dict[str, Any]:
    """三限盘 (Tertiary Progression): 出生后每一天对应一个月。
    偏移天数 = (目标日期 - 出生日期).days / 12.0
    然后以 tertiary_date 作为出生日期(保持原出生时间/地点)排盘。"""
    if not _KER_AVAILABLE:
        return {"error": "kerykeion 不可用"}
    try:
        bd = date(birth_info["year"], birth_info["month"], birth_info["day"])
        if target_date:
            td = datetime.strptime(target_date, "%Y-%m-%d").date()
        else:
            td = datetime.now().date()
        days_diff = (td - bd).days
        offset = days_diff / 12.0
        tert = bd + timedelta(days=offset)
        subj = _make_subj({"year": tert.year, "month": tert.month, "day": tert.day,
                           "hour": birth_info["hour"], "minute": birth_info["minute"],
                           "city": birth_info.get("city", "北京"),
                           "lat": birth_info.get("lat", 0), "lng": birth_info.get("lng", 0)})
        return {"type": "tertiary_progression", "target_date": td.strftime("%Y-%m-%d"),
                "tertiary_chart_date": tert.strftime("%Y-%m-%d"),
                "planets": _extract_planets(subj), **_get_angles(subj)}
    except Exception as e:
        logging.exception("astrology_tertiary_progression error")
        return {"error": f"三限盘失败: {e}"}


def astrology_davison(birth_info_1: Dict, birth_info_2: Dict) -> Dict[str, Any]:
    """时空盘 (Davison): 两人出生数据的时间+空间中点,看关系最终走向/长期稳定性。"""
    if not _KER_AVAILABLE:
        return {"error": "kerykeion 不可用"}
    try:
        s1 = _make_subj(birth_info_1)
        s2 = _make_subj(birth_info_2)
        dav = CompositeSubjectFactory(first_subject=s1, second_subject=s2).get_davison_composite_subject_model()
        return {"type": "davison",
                "person_a": birth_info_1.get("name", "A"),
                "person_b": birth_info_2.get("name", "B"),
                "planets": _extract_planets(dav), **_get_angles(dav)}
    except Exception as e:
        logging.exception("astrology_davison error")
        return {"error": f"时空盘失败: {e}"}


def astrology_marx(birth_info_1: Dict, birth_info_2: Dict) -> Dict[str, Any]:
    """马盘 (马克思盘): 计算基础同时空盘(Davison 中点),
    但解读时分别从 A 和 B 的视角出发,看双方在关系里的真实心理。"""
    if not _KER_AVAILABLE:
        return {"error": "kerykeion 不可用"}
    try:
        dav = astrology_davison(birth_info_1, birth_info_2)
        if "error" in dav:
            return dav
        dav["type"] = "marx"
        dav["marx"] = True
        dav["note"] = ("马盘(基于Davison时间空间中点),解读时分别从双方视角出发: "
                       f"{birth_info_1.get('name','A')}对{birth_info_2.get('name','B')}的心理、"
                       f"{birth_info_2.get('name','B')}对{birth_info_1.get('name','A')}的心理。")
        return dav
    except Exception as e:
        logging.exception("astrology_marx error")
        return {"error": f"马盘失败: {e}"}


def astrology_full(birth_info: Dict, target_type: str, target_params: Dict,
                   other_birth_info: Optional[Dict] = None) -> Dict[str, Any]:
    """星盘综合函数"""
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d")
    result = {"type": f"astrology_full_{target_type}"}
    result["natal"] = astrology_natal(
        birth_info["year"], birth_info["month"], birth_info["day"],
        birth_info["hour"], birth_info["minute"],
        birth_info.get("lat", 0), birth_info.get("lng", 0), birth_info.get("city", ""))

    if target_type in ("year", "recent", "luck_change"):
        result["solar_return"] = astrology_solar_return(birth_info, now.year)
        result["progression"] = astrology_secondary_progression(birth_info, now_str)
    elif target_type in ("month", "day"):
        result["progression"] = astrology_secondary_progression(birth_info, now_str)

    if target_type in ("relationship", "find_love", "compatibility") and other_birth_info:
        result["synastry"] = astrology_synastry(birth_info, other_birth_info)
        result["composite"] = astrology_composite(birth_info, other_birth_info)
    return result


# ==================== 批量排盘 (改版新增) ====================

# 盘类型中文标签 (前端/AI 共用)
CHART_TYPE_LABELS = {
    "natal": "本命盘", "solar_return": "日返盘", "lunar_return": "月返盘",
    "secondary": "次限盘", "tertiary": "三限盘", "transits": "行运盘",
    "synastry": "比较盘", "composite": "组合盘", "davison": "时空盘", "marx": "马盘",
}
# 关系盘(需要第二人)
RELATION_CHARTS = {"synastry", "composite", "davison", "marx"}


def astrology_chart_multi(birth_info, chart_types, target_date=None, other_birth_info=None):
    """批量星盘排盘。chart_types 取 CHART_TYPE_LABELS 的 key。"""
    now = datetime.now()
    td = target_date or now.strftime("%Y-%m-%d")
    try:
        td_year = datetime.strptime(td, "%Y-%m-%d").year
    except Exception:
        td_year = now.year
    charts = {}
    labels = {}
    by, bm, bd = birth_info["year"], birth_info["month"], birth_info["day"]
    bh, bmi = birth_info["hour"], birth_info["minute"]
    lat, lng = birth_info.get("lat", 0), birth_info.get("lng", 0)
    city = birth_info.get("city", "")

    for ct in chart_types:
        labels[ct] = CHART_TYPE_LABELS.get(ct, ct)
        try:
            if ct == "natal":
                charts[ct] = astrology_natal(by, bm, bd, bh, bmi, lat, lng, city)
            elif ct == "solar_return":
                charts[ct] = astrology_solar_return(birth_info, td_year)
            elif ct == "lunar_return":
                charts[ct] = astrology_lunar_return(birth_info, td)
            elif ct == "secondary":
                charts[ct] = astrology_secondary_progression(birth_info, td)
            elif ct == "tertiary":
                charts[ct] = astrology_tertiary_progression(birth_info, td)
            elif ct == "transits":
                charts[ct] = astrology_transits(birth_info, td)
            elif ct in RELATION_CHARTS:
                if not other_birth_info:
                    charts[ct] = {"error": "%s需要第二人档案" % CHART_TYPE_LABELS.get(ct, ct)}
                    continue
                if ct == "synastry":
                    charts[ct] = astrology_synastry(birth_info, other_birth_info)
                elif ct == "composite":
                    charts[ct] = astrology_composite(birth_info, other_birth_info)
                elif ct == "davison":
                    charts[ct] = astrology_davison(birth_info, other_birth_info)
                elif ct == "marx":
                    charts[ct] = astrology_marx(birth_info, other_birth_info)
            else:
                charts[ct] = {"error": "未知盘类型: " + ct}
        except Exception as e:
            logging.exception("chart_multi %s error", ct)
            charts[ct] = {"error": "%s排盘失败: %s" % (CHART_TYPE_LABELS.get(ct, ct), e)}
    return {"type": "astrology_chart_multi", "target_date": td,
            "charts": charts, "labels": labels}


# 八字分析类型标签
BAZI_TYPE_LABELS = {
    "natal": "八字本命", "dayun": "大运", "liunian": "流年",
    "liuyue": "流月", "liuri": "流日", "shishen": "十神分析", "wuxing": "五行旺缺",
}


def bazi_analysis_multi(birth_info, analysis_types, target_params=None):
    """批量八字分析。analysis_types 取 BAZI_TYPE_LABELS 的 key。"""
    target_params = target_params or {}
    now = datetime.now()
    by, bm, bd = birth_info["year"], birth_info["month"], birth_info["day"]
    bh, bmi = birth_info["hour"], birth_info["minute"]
    gender = birth_info.get("gender", 1)
    city = birth_info.get("city", "")
    ty = int(target_params.get("year", now.year))
    tm = int(target_params.get("month", now.month))

    results = {}
    labels = {}
    for at in analysis_types:
        labels[at] = BAZI_TYPE_LABELS.get(at, at)
        try:
            if at == "natal":
                results[at] = bazi_chart(by, bm, bd, bh, bmi, gender, city)
            elif at == "dayun":
                results[at] = bazi_dayun(by, bm, bd, bh, bmi, gender)
            elif at == "liunian":
                results[at] = bazi_liunian(by, bm, bd, bh, bmi, gender, ty - 1, ty + 1)
            elif at == "liuyue":
                results[at] = bazi_liuyue(by, bm, bd, bh, bmi, gender, ty)
            elif at == "liuri":
                results[at] = bazi_liuri(by, bm, bd, bh, bmi, gender, ty, tm)
            elif at in ("shishen", "wuxing"):
                natal = bazi_chart(by, bm, bd, bh, bmi, gender, city)
                if at == "shishen":
                    results[at] = {"type": "bazi_shishen",
                                   "shishen_gan": natal.get("shishen_gan"),
                                   "shishen_zhi": natal.get("shishen_zhi"),
                                   "day_master": natal.get("day_master")}
                else:
                    results[at] = {"type": "bazi_wuxing",
                                   "wuxing_count": natal.get("wuxing_count"),
                                   "day_master": natal.get("day_master")}
            else:
                results[at] = {"error": "未知八字类型: " + at}
        except Exception as e:
            logging.exception("bazi_multi %s error", at)
            results[at] = {"error": "%s分析失败: %s" % (BAZI_TYPE_LABELS.get(at, at), e)}
    return {"type": "bazi_analysis_multi", "year": ty, "month": tm,
            "results": results, "labels": labels}


# ==================== 合婚 ====================

def compatibility_report(birth_info_1: Dict, birth_info_2: Dict) -> Dict[str, Any]:
    """合婚报告: 八字合婚 + 星盘合盘"""
    result = {"type": "compatibility_report"}
    try:
        _, ec1 = _get_ec(birth_info_1["year"],birth_info_1["month"],birth_info_1["day"],
                          birth_info_1["hour"],birth_info_1["minute"],birth_info_1.get("gender",1))
        _, ec2 = _get_ec(birth_info_2["year"],birth_info_2["month"],birth_info_2["day"],
                          birth_info_2["hour"],birth_info_2["minute"],birth_info_2.get("gender",0))
        sx1 = ZHI_SHENGXIAO.get(ec1.getYearZhi(), "?")
        sx2 = ZHI_SHENGXIAO.get(ec2.getYearZhi(), "?")
        pair = tuple(sorted([sx1, sx2]))
        if pair in SHENGXIAO_HELIU:
            sx_rel = "六合(上等婚配)"
        elif pair in SHENGXIAO_CHONG:
            sx_rel = "六冲(需多包容)"
        else:
            sx_rel = "中等(无冲无合)"
        result["bazi"] = {
            "p1": {"year_nayin": ec1.getYearNaYin(), "day_pillar": ec1.getDay(), "shengxiao": sx1,
                   "wuxing": _count_wuxing(ec1)},
            "p2": {"year_nayin": ec2.getYearNaYin(), "day_pillar": ec2.getDay(), "shengxiao": sx2,
                   "wuxing": _count_wuxing(ec2)},
            "shengxiao_relation": sx_rel,
        }
    except Exception as e:
        result["bazi"] = {"error": str(e)}

    try:
        result["astrology"] = {
            "synastry": astrology_synastry(birth_info_1, birth_info_2),
            "composite": astrology_composite(birth_info_1, birth_info_2),
        }
    except Exception as e:
        result["astrology"] = {"error": str(e)}
    return result


# ==================== 主入口 ====================

def get_fortune_data(birth_info: Dict, fortune_type: str,
                     fortune_params: Optional[Dict] = None,
                     other_birth_info: Optional[Dict] = None) -> Dict[str, Any]:
    """总入口: 返回八字+星盘+黄历完整排盘数据"""
    fortune_params = fortune_params or {}
    now = datetime.now()
    result = {"fortune_type": fortune_type, "birth_info": birth_info}
    result["bazi"] = bazi_full(birth_info, fortune_type, fortune_params)
    result["astrology"] = astrology_full(birth_info, fortune_type, fortune_params, other_birth_info)
    result["almanac"] = almanac_day(now.year, now.month, now.day)
    if fortune_type == "compatibility" and other_birth_info:
        result["compatibility"] = compatibility_report(birth_info, other_birth_info)
    result["data_summary"] = _make_summary(result, fortune_type)
    return result


def _make_summary(data: Dict, ftype: str) -> str:
    """大白话总结"""
    parts = []
    natal = data.get("bazi", {}).get("natal", {})
    if "day_master" in natal:
        parts.append(f"日主{natal['day_master']}")
        wx = natal.get("wuxing_count", {})
        weak = [k for k, v in wx.items() if v == 0]
        parts.append("五行缺" + "、".join(weak) if weak else f"五行{','.join(f'{k}{v}' for k,v in wx.items())}")
    astro = data.get("astrology", {}).get("natal", {})
    if "ascendant" in astro:
        parts.append(f"上升{astro['ascendant'].get('sign','?')}")
    alm = data.get("almanac", {})
    if "yi" in alm:
        parts.append(f"今日宜{'、'.join(alm['yi'][:3])}")
    hints = {"day":"今日运势","month":"本月运势","year":"今年运势","wealth":"财运分析",
             "career":"事业分析","relationship":"感情分析","health":"健康分析",
             "compatibility":"合婚合盘","luck_change":"运势转变期"}
    if ftype in hints:
        parts.insert(0, f"【{hints[ftype]}】")
    return "，".join(parts) + "。"


# ==================== 自测 ====================

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    print("=" * 60)
    print("fortune.py 自测: 1995-06-15 14:30 男 北京")
    print("=" * 60)

    bi = {"year":1995,"month":6,"day":15,"hour":14,"minute":30,
          "gender":1,"city":"北京","lat":39.9,"lng":116.4}
    bi2 = {"year":1992,"month":3,"day":20,"hour":10,"minute":0,
           "gender":0,"city":"上海","lat":31.2,"lng":121.5}

    passed, failed = [], []
    def test(name, fn, *args, **kw):
        try:
            r = fn(*args, **kw)
            if "error" in r and len(r) <= 2:
                failed.append(name); print(f"  [FAIL] {name}: {r.get('error','')[:70]}")
            else:
                passed.append(name); print(f"  [OK]   {name} → {list(r.keys())[:6]}")
        except Exception as e:
            failed.append(name); print(f"  [ERR]  {name}: {e}")

    print("\n--- 八字 ---")
    test("bazi_chart", bazi_chart, 1995,6,15,14,30,1,"北京")
    test("bazi_dayun", bazi_dayun, 1995,6,15,14,30,1)
    test("bazi_liunian", bazi_liunian, 1995,6,15,14,30,1, 2025, 2027)
    test("bazi_liuyue", bazi_liuyue, 1995,6,15,14,30,1, 2026)
    test("bazi_liuri", bazi_liuri, 1995,6,15,14,30,1, 2026, 10)
    test("bazi_full(year)", bazi_full, bi, "year", {})
    # 边界: 女命
    test("bazi_chart(女)", bazi_chart, 1995,6,15,14,30,0,"上海")
    # 边界: 闰年
    test("bazi_chart(闰年)", bazi_chart, 2024,2,29,8,0,1,"广州")
    # 边界: 子时
    test("bazi_chart(子时)", bazi_chart, 1995,6,15,0,30,1,"北京")

    print("\n--- 黄历 ---")
    test("almanac_day", almanac_day, 2026, 10, 3)
    test("auspicious_times", auspicious_times, 2026, 10, 3)
    test("find_auspicious_days", find_auspicious_days, "2026-10-01", "2026-10-15", "嫁娶")
    test("almanac_range", almanac_range, "2026-10-01", "2026-10-05")
    # 跨月
    test("almanac(跨月)", almanac_day, 2026, 1, 1)
    # 节气
    test("almanac(节气)", almanac_day, 2026, 6, 21)

    print("\n--- 星盘 ---")
    test("astrology_natal", astrology_natal, 1995,6,15,14,30, 39.9, 116.4, "北京")
    test("astrology_progression", astrology_secondary_progression, bi, "2026-10-03")
    test("astrology_synastry", astrology_synastry, bi, bi2)
    test("astrology_composite", astrology_composite, bi, bi2)
    test("astrology_solar_return", astrology_solar_return, bi, 2026)
    test("astrology_lunar_return", astrology_lunar_return, bi, "2026-10-03")

    print("\n--- 合婚 ---")
    test("compatibility_report", compatibility_report, bi, bi2)

    print("\n--- 主入口 ---")
    test("fortune(year)", get_fortune_data, bi, "year", {})
    test("fortune(compatibility)", get_fortune_data, bi, "compatibility", {}, bi2)
    test("fortune(day)", get_fortune_data, bi, "day", {})

    print("\n" + "=" * 60)
    print(f"自测结果: {len(passed)} 通过, {len(failed)} 失败")
    if failed:
        print("失败:", failed)
    print("=" * 60)
