# SPDX-License-Identifier: GPL-3.0-only
"""存档工具的逻辑层 (不依赖 tkinter, 可单独测试): 转一个存档文件、把转好的存档放进游戏的存档位。界面在 save_tool.py。

    convert_file   一个原版 GDxx.GSF 或复刻版 saveN.json -> 另一种格式, 写在源文件旁边的「转换后的存档」文件夹里 (不改源文件)
    place          把转好的存档放进游戏的存档位 (已有存档要先确认, 覆盖前自动备份)
    load_config    记住的原版游戏目录 (第一次放进原版时问一次)
两个方向的营地存档转换在 import_gsf.py (原版 -> 复刻) 和 export_gsf.py (复刻 -> 原版); 原版战阵存档 -> 复刻在 import_gcf.py。
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_gsf as X  # noqa: E402
import import_gsf as G  # noqa: E402

try:   # 战阵存档要用游戏引擎转, 只在游戏仓库里有; 独立的存档工具仓库不带它
    import import_gcf as C  # noqa: E402
except ImportError:
    C = None

GsfError = G.GsfError

TO_REPLICA = "to_replica"     # 原版 GDxx.GSF -> 复刻 saveN.json
TO_ORIGINAL = "to_original"   # 复刻 saveN.json -> 原版 GDxx.GSF
OUT_FOLDER = "转换后的存档"
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".swordman_save_tool.json")


class SlotTaken(GsfError):
    """目标存档位已有存档 (place 没给 overwrite 时抛出, 界面据此问玩家要不要替换)。"""

    def __init__(self, dst):
        super().__init__("存档位已有存档: %s" % dst)
        self.dst = dst


# ---------------------------------------------------------------- 转换

def summarize(save, level):
    """一行内容摘要: 殷剑平等级 · 金钱 · 队伍 · 营地。"""
    return "殷剑平 Lv %d · 金钱 %d · 队伍 %d 人 · 营地 %d" % (
        level, int(save["gold"]), len(save["party"]), int(save.get("camp", save.get("stage", 0))))


def _unique_path(folder, name, data):
    """folder/name; 已有同名文件时, 内容一样就沿用, 不一样加 (2)、(3) ... 不覆盖任何已有文件。"""
    stem, ext = os.path.splitext(name)
    path, n = os.path.join(folder, name), 1
    while os.path.exists(path):
        try:
            with open(path, "rb") as f:
                if f.read() == data:
                    return path
        except OSError:
            pass
        n += 1
        path = os.path.join(folder, "%s (%d)%s" % (stem, n, ext))
    return path


def _write(folder, name, data):
    try:
        os.makedirs(folder, exist_ok=True)
        path = _unique_path(folder, name, data)
        if not os.path.exists(path):
            X.write_atomic_bytes(path, data)
        return path
    except OSError as e:
        raise GsfError("写不了 %s: %s" % (folder, e.strerror or e))


def convert_file(path, out_dir=None, now=None, expect=None, run_engine_fn=None):
    """转一个存档文件。返回 {direction, kind_out, src, src_name, slot, out_path, summary, warnings}; 出错抛 GsfError (中文)。

    .GSF (原版营地存档) -> saveN.json; .json (复刻版存档) -> GD0x.GSF; .GCF (原版战阵存档) -> battle.json (要用游戏引擎转, 几秒到几十秒)。槽位取自文件名 (GD01 -> 2, save2 -> 2), 名字不规范时用 1。
    结果写进 out_dir (缺省: 源文件旁边的「转换后的存档」文件夹); 源文件不动。
    expect 给了 TO_REPLICA / TO_ORIGINAL 时, 文件类型不对就报错 (界面里每一页只收一种存档)。
    """
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    out_dir = out_dir or os.path.join(os.path.dirname(os.path.abspath(path)), OUT_FOLDER)
    if expect == TO_REPLICA and ext not in (".gsf", ".gcf"):
        raise GsfError("这一页只收原版存档 (GD00.GSF ~ GD04.GSF" + (" 或战阵存档 GAMEDATA.GCF)" if C else ")"))
    if expect == TO_ORIGINAL and ext != ".json":
        raise GsfError("这一页只收复刻版存档 (save1.json ~ save5.json)")
    if ext == ".gcf":
        if C is None:
            raise GsfError("战阵存档 (GAMEDATA.GCF) 要用游戏引擎转换, 这个版本不带; 请用 SwordmanHD 游戏仓库里的 tools/saves/import_gcf.py")
        raw = G.read_file(path)
        data, info = C.convert_bytes(raw, name, path, run_engine_fn)
        out_path = _write(out_dir, "battle.json", data)
        return {"direction": TO_REPLICA, "kind_out": "battle", "src": path, "src_name": name, "slot": None, "out_path": out_path,
                "summary": C.describe(info), "warnings": info["warnings"]}
    if ext == ".gsf":
        raw = G.read_file(path)
        info = G.build_save(raw, os.path.getmtime(path), name)
        save = info["save"]
        slot = G.slot_of_name(name) or 1
        out_path = _write(out_dir, "save%d.json" % slot, json.dumps(save, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        return {"direction": TO_REPLICA, "kind_out": "replica", "src": path, "src_name": name, "slot": slot, "out_path": out_path,
                "summary": summarize(save, info["header"]["level"]), "warnings": info["warnings"]}
    if ext == ".json":
        save = X.read_save(path)
        raw, info = X.build_gsf(save, now=now)
        slot = X.save_slot_of_name(name) or 1
        out_path = _write(out_dir, "GD%02d.GSF" % (slot - 1), raw)
        hero = (save.get("party") or {}).get("0") or {}
        return {"direction": TO_ORIGINAL, "kind_out": "original", "src": path, "src_name": name, "slot": slot, "out_path": out_path,
                "summary": summarize(save, int(hero.get("lv", 0))), "warnings": info["warnings"]}
    raise GsfError("看不懂 %s: 请拖原版存档 (GD00.GSF ~ GD04.GSF) 或复刻版存档 (save1.json ~ save5.json)" % name)


# ---------------------------------------------------------------- 放进游戏

def load_config(path=None):
    try:
        with open(path or CONFIG_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def remember(key, value, path=None):
    """记一项设置 (写不了就算了, 只是少一次记忆)。"""
    cfg = load_config(path)
    cfg[key] = value
    try:
        with open(path or CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
    except OSError:
        pass


def game_dir(kind_out, cfg=None):
    """转好的存档该放进哪个目录: 复刻版 = 游戏自己的存档目录 (自动); 原版 = 记住的原版游戏目录, 没记过返回 None。"""
    if kind_out in ("replica", "battle"):
        return G.default_out_dir()
    d = (cfg if cfg is not None else load_config()).get("original_dir")
    return d if d and os.path.isdir(d) else None


def target_path(kind_out, dst_dir, slot):
    if kind_out == "battle":
        return os.path.join(dst_dir, "battle.json")
    return G.slot_file(dst_dir, slot) if kind_out == "replica" else X.gsf_target(dst_dir, slot)


def is_taken(kind_out, dst_dir, slot):
    t = target_path(kind_out, dst_dir, slot)
    return G.slot_taken(t) if kind_out in ("replica", "battle") else os.path.exists(t)


def place(result, dst_dir, slot, overwrite=False, now=None):
    """把 convert_file 转好的存档放进 dst_dir 的槽位 slot (1~5; 战阵存档 battle.json 不分槽位, slot 忽略)。返回 {"dst", "backup"} (backup 是旧存档的备份路径或 None)。

    目标已有存档且没给 overwrite 就抛 SlotTaken; 覆盖前旧存档先备份成 <名>.bak-<时间戳>。
    """
    kind = result["kind_out"]
    dst = target_path(kind, dst_dir, slot)
    taken = is_taken(kind, dst_dir, slot)
    if taken and not overwrite:
        raise SlotTaken(dst)
    backup = None
    try:
        os.makedirs(dst_dir, exist_ok=True)
        if taken:
            old = dst if os.path.exists(dst) else dst + ".bak"
            backup = G.backup_path(dst, now)
            shutil.copy2(old, backup)
        tmp = dst + ".tmp-place"
        try:
            shutil.copyfile(result["out_path"], tmp)
            os.replace(tmp, dst)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    except OSError as e:
        raise GsfError("放不进 %s: %s" % (dst_dir, e.strerror or e))
    return {"dst": dst, "backup": backup}
