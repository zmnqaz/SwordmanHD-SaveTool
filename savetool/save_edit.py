# SPDX-License-Identifier: GPL-3.0-only
"""存档修改器的逻辑层 (不依赖 tkinter, 可单独测试): 改复刻版 saveN.json 的金钱、公共行囊、队员属性 / 装备 / 技能 / 随身物品。界面在 save_edit_ui.py。

    load / save    读存档 (校验是复刻版存档); 保存前把旧文件备份成 <存档>.bak-时间戳, 再原子写, 写不进去时原文件不动
    set_gold, bag_add / bag_remove / bag_set_count, set_field, set_gear, set_slots    各项修改; 越界一律抛 EditError (中文提示, 带范围), 不静默截断
只动被改的字段, 存档里其它内容 (剧情变量 game_data、content、gsf_raw ...) 原样保留。范围取游戏规则 (等级上限 99、属性上限 500、
每人随身 10 格、技能 10 格、行囊 512 格) 与原版存档能存的值 (int16 / int32) 中更严的, 所以改完的存档仍能用 export_gsf.py 转回原版格式。
传 names (save_names.Names) 时额外检查物品 / 技能编号存在、装备类型与「谁能装」; 没有名字表时只查数值范围。
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import import_gsf as G  # noqa: E402
from save_names import GEAR_TYPE  # noqa: E402

GOLD_MAX = 2147483647     # 引擎没有金钱上限, 存档里是 int32
BAG_SLOTS = 512           # 公共行囊格数
SLOTS = 10                # 每人随身物品 / 技能的格数
STAT_KEYS = ("str", "int", "avg", "vit", "luk")
SPIRIT_KEYS = ("迅", "烈", "神", "魔", "魂")
# 数值字段范围: 等级上限 99 (游戏规则); 其余是原版存档的 int16 (HP/MP 游戏里是 u16, 但正常满级约 3500, 到不了 32767)
FIELD_NAMES = {"lv": "等级", "exp": "经验", "hp_max": "HP 上限", "mp_max": "MP 上限", "spirit_points": "五魂点"}
FIELD_LIMITS = {"lv": (1, 99), "exp": (0, 32767), "hp_max": (1, 32767), "mp_max": (0, 32767), "spirit_points": (0, 32767)}
STAT_LIMIT = (0, 500)     # 游戏的属性上限
SPIRIT_LIMIT = (0, 32767)
ID_LIMIT = (0, 32767)


class EditError(ValueError):
    """修改被拒绝 (越界、编号不存在、存档读写失败 ...), 文字直接给玩家看。"""


def check_int(v, what, lo, hi):
    """界面传来的字符串 / JSON 里的 9.0 -> int, 非整数或越界抛 EditError。"""
    if isinstance(v, bool) or v is None:
        raise EditError("%s 要填整数 (得到 %r)" % (what, v))
    if isinstance(v, str):
        try:
            v = int(v.strip())
        except ValueError:
            raise EditError("%s 要填整数 (得到 %r)" % (what, v))
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")) or v != int(v):
            raise EditError("%s 要填整数 (得到 %r)" % (what, v))
        v = int(v)
    if not isinstance(v, int):
        raise EditError("%s 要填整数 (得到 %r)" % (what, v))
    if not lo <= v <= hi:
        raise EditError("%s 应在 %d ~ %d 之间 (填了 %d)" % (what, lo, hi, v))
    return v


# ---------------------------------------------------------------- 存档位置

def default_save_dir(platform=None, env=None, home=None):
    """复刻版存档目录 (游戏的 user://): Windows %APPDATA%\\SwordmanHD, macOS ~/Library/Application Support/SwordmanHD, Linux ~/.local/share/SwordmanHD。"""
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    home = os.path.expanduser("~") if home is None else home
    if platform.startswith("win"):
        return os.path.join(env.get("APPDATA") or os.path.join(home, "AppData", "Roaming"), "SwordmanHD")
    if platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "SwordmanHD")
    return os.path.join(env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share"), "SwordmanHD")


def existing_saves(folder):
    """文件夹里的 save1.json ~ save5.json [(存档位, 路径)], 按存档位排序; 没有这个文件夹返回空。"""
    out = []
    for i in range(1, 6):
        p = os.path.join(folder, "save%d.json" % i)
        if os.path.isfile(p):
            out.append((i, p))
    return out


# ---------------------------------------------------------------- 读写

def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        raise EditError("读不了 %s: %s" % (path, getattr(e, "strerror", None) or e))
    if not isinstance(d, dict) or not all(k in d for k in ("gold", "bag", "party")):
        raise EditError("%s 不像复刻版存档 (需要 gold / bag / party)" % os.path.basename(path))
    if not isinstance(d["bag"], list) or not isinstance(d["party"], dict):
        raise EditError("%s 的 bag 或 party 格式不对" % os.path.basename(path))
    return d


def save(path, d, now=None):
    """写回 path; 已有文件先备份, 返回备份路径 (原来没有文件则返回 None)。"""
    bak = None
    if os.path.exists(path):
        bak = G.backup_path(path, now)
        try:
            shutil.copy2(path, bak)
        except OSError as e:
            raise EditError("备份不了 %s: %s" % (path, e.strerror or e))
    try:
        G.write_atomic(path, json.dumps(d, ensure_ascii=False, separators=(",", ":")))
    except G.GsfError as e:
        raise EditError(str(e))
    return bak


# ---------------------------------------------------------------- 金钱 / 行囊

def set_gold(d, v):
    d["gold"] = check_int(v, "金钱", 0, GOLD_MAX)


def bag_counts(d):
    """行囊里每种物品的数量 [(编号, 数量)], 按第一次出现的顺序。"""
    counts = {}
    for i in d["bag"]:
        counts[int(i)] = counts.get(int(i), 0) + 1
    return list(counts.items())


def _item_id(names, v):
    i = check_int(v, "物品编号", *ID_LIMIT)
    if names is not None and names.available and i not in names.items:
        raise EditError("物品表里没有编号 %d" % i)
    return i


def bag_add(d, item, count, names=None):
    i = _item_id(names, item)
    n = check_int(count, "数量", 1, BAG_SLOTS)
    if len(d["bag"]) + n > BAG_SLOTS:
        raise EditError("行囊最多 %d 件, 现在 %d 件, 再加 %d 件放不下" % (BAG_SLOTS, len(d["bag"]), n))
    d["bag"].extend([i] * n)


def bag_remove(d, item, count):
    i = check_int(item, "物品编号", *ID_LIMIT)
    n = check_int(count, "数量", 1, BAG_SLOTS)
    have = sum(1 for x in d["bag"] if int(x) == i)
    if n > have:
        raise EditError("行囊里只有 %d 件这个物品, 删不了 %d 件" % (have, n))
    out, left = [], n
    for x in d["bag"]:
        if int(x) == i and left:
            left -= 1
        else:
            out.append(x)
    d["bag"][:] = out


def bag_set_count(d, item, count, names=None):
    i = _item_id(names, item)
    n = check_int(count, "数量", 0, BAG_SLOTS)
    have = sum(1 for x in d["bag"] if int(x) == i)
    if n > have:
        bag_add(d, i, n - have, names)
    elif n < have:
        bag_remove(d, i, have - n)


# ---------------------------------------------------------------- 队员

def members(d):
    """[(编号 int, 记录 dict)] 按编号排序。"""
    return sorted(((int(k), v) for k, v in d["party"].items()), key=lambda t: t[0])


def _member(d, uid):
    p = d["party"].get(str(int(uid)))
    if not isinstance(p, dict):
        raise EditError("存档里没有 %s 号队员" % uid)
    return p


def set_field(d, uid, field, v):
    """field: lv / exp / hp_max / mp_max / spirit_points, 或 stat:<str|int|avg|vit|luk>、spirit:<迅|烈|神|魔|魂>。"""
    p = _member(d, uid)
    if field in FIELD_LIMITS:
        p[field] = check_int(v, FIELD_NAMES[field], *FIELD_LIMITS[field])
    elif field.startswith("stat:") and field[5:] in STAT_KEYS:
        p.setdefault("stats", {})[field[5:]] = check_int(v, "属性 " + field[5:], *STAT_LIMIT)
    elif field.startswith("spirit:") and field[7:] in SPIRIT_KEYS:
        p.setdefault("spirit", {})[field[7:]] = check_int(v, "五魂 " + field[7:], *SPIRIT_LIMIT)
    else:
        raise EditError("没有这个字段: %s" % field)


def set_gear(d, uid, slot, item, names=None):
    """装备栏 weapon / armor / accessory; item 为 None 表示空。有名字表时检查物品类型对应栏位、且这个人能装。"""
    if slot not in GEAR_TYPE:
        raise EditError("没有这个装备栏: %s" % slot)
    p = _member(d, uid)
    if item is None:
        value = None
    else:
        value = check_int(item, "装备编号", *ID_LIMIT)
        if names is not None and names.available:
            row = names.items.get(value)
            if row is None:
                raise EditError("物品表里没有编号 %d" % value)
            if row.get("type") != GEAR_TYPE[slot]:
                raise EditError("%s 不能放进 %s 栏" % (row["name"], slot))
            if int(uid) not in row.get("equip_units", []):
                raise EditError("%s 这个人装不了" % row["name"])
    p.setdefault("gear", {})[slot] = value


def set_slots(d, uid, key, values, names=None):
    """随身物品 (items) 或技能 (skills), 最多 10 格, 编号须存在。"""
    if key not in ("items", "skills"):
        raise EditError("没有这个列表: %s" % key)
    p = _member(d, uid)
    if len(values) > SLOTS:
        raise EditError("%s最多 %d 格 (填了 %d 个)" % ("随身物品" if key == "items" else "技能", SLOTS, len(values)))
    out = []
    for v in values:
        i = check_int(v, "编号", *ID_LIMIT)
        if names is not None and names.available:
            table = names.items if key == "items" else names.skills
            if i not in table:
                raise EditError("%s表里没有编号 %d" % ("物品" if key == "items" else "技能", i))
        out.append(i)
    p[key] = out
