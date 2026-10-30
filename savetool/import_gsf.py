#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""原版营地存档 GD00.GSF ~ GD04.GSF -> 复刻版存档 save1.json ~ save5.json (只导入, 不导出)。

用法:
    python3 tools/saves/import_gsf.py <GDxx.GSF 或 含 GDxx.GSF 的目录> [--out <存档目录>] [--slot N] [--force] [--dry-run]

纯标准库 (Python 3.10+), 不依赖 Godot, 不依赖仓库里的其他文件。说明见 docs/存档互通.md。

格式 (docs/机制考证/养成与物品.md §7.1, 与 game/engine/camp/camp_scene.gd 的 import_gsf 逐字段对齐):
    0      int  进度值 = 营地编号 CAMPnn (复刻的 camp)
    4      int  殷剑平等级 (只用来显示, 游戏里的等级取自队伍记录)
    8      _strdate 9 字节, 17 _strtime 9 字节 (不读)
    26     0xF20 字节全局数据, 逐字节 XOR 0xA5:
      +0x00 下一场战斗关号 (复刻的 next_stage)    +0x08 金钱    +0x1c 剧情变量 128 个 int
      +0x21c 队伍记录 16 x 80 字节                +0x71c 公共行囊 512 个 int (-1 为空)
    队伍记录: +0 id +2 lv +4 exp +6 HP上限 +8 MP上限 +0xa 攻 咒 行 防 运 +0x14 五魂 x5 +0x1e 武器 护具 饰物
              +0x24 在队 (==1 才算) +0x26 五魂点 +0x28 物品 x10 +0x3c 技能 x10 (int16, -1 为空)

存档 JSON 里多一个可选字段 gsf_raw: 原文件前 26+0xF20 字节 (头 + 仍是 XOR 状态的全局数据, 即磁盘上的样子) 的 base64,
将来导出回原版格式时, 只改已知字段, 其余字节原样写回。

退出码: 0 成功 (含 --dry-run); 1 有文件读不了/没写成; 2 参数错误 (argparse); 3 有档位因已有存档被跳过 (加 --force 覆盖)。
"""
import argparse
import base64
import datetime
import json
import os
import re
import shutil
import struct
import sys

HEADER_SIZE = 26
BODY_SIZE = 0xF20
GSF_SIZE = HEADER_SIZE + BODY_SIZE
XOR_KEY = 0xA5
SLOTS = 5                      # GD00..GD04 -> save1..save5
# 内容包 tdj 的关卡数 (game/content/tdj/manifest.json stage_count): 进度值/下一关号超出它的档, 复刻读档会拒绝, 这里提前当「不是原版营地存档」处理
STAGE_LIMIT = 36
SLOT_KEYS = ("weapon", "armor", "accessory")
SPIRIT_NAMES = ("迅", "烈", "神", "魔", "魂")


class GsfError(Exception):
    """输入有问题 (文件读不了/格式不对): 消息是给玩家看的中文。"""


# ---------------------------------------------------------------- 解析

def xor_body(body):
    """全局数据逐字节 XOR 0xA5 (自反: 再做一次还原)。"""
    return bytes(b ^ XOR_KEY for b in body)


def parse_header(raw):
    """头 26 字节 -> {"camp_no", "level", "date", "time"} (date/time 只是原文, 导入不用)。"""
    if len(raw) < HEADER_SIZE:
        raise GsfError("文件太短 (%d 字节), 不是原版营地存档" % len(raw))
    camp_no, level = struct.unpack_from("<ii", raw, 0)
    date = raw[8:17].split(b"\0")[0].decode("ascii", "replace")
    time = raw[17:26].split(b"\0")[0].decode("ascii", "replace")
    return {"camp_no": camp_no, "level": level, "date": date, "time": time}


def parse_gsf(raw, name="存档"):
    """原版营地存档字节 -> 复刻版存档字段字典 (stage/next_stage/camp/gold/bag/game_data/party/seeded) + 附加信息。

    返回 {"state": {...}, "header": {...}, "warnings": [...]}。state 里的字段与 CampScene.import_gsf 填进 GameState 的一致。
    """
    if len(raw) < GSF_SIZE:
        raise GsfError("%s 太短 (%d 字节, 营地存档应有 %d 字节), 不是完整的原版营地存档" % (name, len(raw), GSF_SIZE))
    warnings = []
    if len(raw) > GSF_SIZE:
        warnings.append("%s 比标准长度多 %d 字节 (战阵存档 GAMEDATA.GCF 不是营地存档, 请用 import_gcf.py), 多出的部分已忽略" % (name, len(raw) - GSF_SIZE))
    raw = raw[:GSF_SIZE]
    head = parse_header(raw)
    d = xor_body(raw[HEADER_SIZE:])

    def s32(o):
        return struct.unpack_from("<i", d, o)[0]

    def s16(o):
        return struct.unpack_from("<h", d, o)[0]

    camp_no = head["camp_no"]
    next_stage = s32(0)
    gold = s32(8)
    if not (0 <= camp_no <= STAGE_LIMIT and 0 <= next_stage <= STAGE_LIMIT and gold >= 0):
        raise GsfError("%s 的进度值 (%d)、下一关 (%d) 或金钱 (%d) 超出合理范围, 不像原版营地存档 (文件损坏或选错了文件?)" % (name, camp_no, next_stage, gold))

    game_data = {}
    for i in range(128):
        v = s32(0x1C + 4 * i)
        if v != 0:
            game_data[str(i)] = v

    party = {}
    seeded = []
    for r in range(16):
        o = 0x21C + 80 * r
        if s16(o + 0x24) != 1:
            continue
        uid = s16(o)
        gear = {}
        for s, key in enumerate(SLOT_KEYS):
            v = s16(o + 0x1E + 2 * s)
            gear[key] = v if v >= 0 else None
        items = [v for v in (s16(o + 0x28 + 2 * k) for k in range(10)) if v >= 0]
        skills = [v for v in (s16(o + 0x3C + 2 * k) for k in range(10)) if v >= 0]
        spirit = {SPIRIT_NAMES[k]: s16(o + 0x14 + 2 * k) for k in range(5)}
        party[str(uid)] = {
            "lv": s16(o + 2), "exp": s16(o + 4), "hp_max": s16(o + 6), "mp_max": s16(o + 8),
            "stats": {"str": s16(o + 0xA), "int": s16(o + 0xC), "avg": s16(o + 0xE), "vit": s16(o + 0x10), "luk": s16(o + 0x12)},
            "gear": gear, "skills": skills, "spirit": spirit, "spirit_points": s16(o + 0x26), "items": items}
        if uid not in seeded:   # 与 GameState.seeded[uid] = true (字典, 重复 uid 不重复记)
            seeded.append(uid)

    bag = [v for v in (s32(0x71C + 4 * i) for i in range(512)) if v >= 0]
    if "0" not in party:
        warnings.append("%s 的队伍里没有殷剑平, 可能不是原版营地存档" % name)

    state = {"stage": camp_no, "next_stage": next_stage, "camp": camp_no, "gold": gold, "bag": bag,
             "game_data": game_data, "party": party, "seeded": seeded}
    return {"state": state, "header": head, "warnings": warnings}


def build_save(raw, mtime=None, name="存档"):
    """原版营地存档字节 -> 完整的复刻版存档字典 (可直接 json 写成 saveN.json), 另返回解析信息。

    字段怎么填 (对照 game/engine/core/game_saves.gd 的 _snapshot):
      stage     原版存档没有「上一关」: 取进度值 (营地号), 与复刻读不到 camp 字段时的缺省 (apply_dict: camp 缺省 = stage) 同义;
                存档位里显示的关名用它
      where     "camp" (营地存档)
      time      源文件的修改时间 (本地时区, YYYY-MM-DD HH:MM:SS); 不读原版头里的日期时间 (两位年份, 不可靠)
      content   [{"id": "tdj", "version": ""}]: 原版内容包, 版本未知 -> ContentCompat.check_save 当「不冲突」, 随内容包升级不会被拒。
                不在这里复刻 Content.signature() (要读本机已加载的包); 以后复刻自己再存档时会换成真实签名
      version   2 = SaveFile.VERSION (当前版本, 不触发迁移); 读档时 SaveFile.migrate 照常校验字段
      engine    不写 (读档不读它, 写了反而冒充某个引擎版本)
      gsf_raw   原文件字节 base64 (见文件头)
    """
    info = parse_gsf(raw, name)
    save = dict(info["state"])
    if mtime is None:
        mtime = datetime.datetime.now().timestamp()
    save["where"] = "camp"
    save["time"] = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
    save["content"] = [{"id": "tdj", "version": ""}]
    save["version"] = SAVE_VERSION
    save["gsf_raw"] = base64.b64encode(raw[:GSF_SIZE]).decode("ascii")
    info["save"] = save
    return info


SAVE_VERSION = 2   # SaveFile.VERSION (game/engine/core/save_file.gd); tools/tests/test_import_gsf.py 核对两边一致


# ---------------------------------------------------------------- 找输入 / 默认目录

def default_out_dir(platform=None, env=None):
    """玩家存档目录 (Godot 的 user://, 工程设了 custom_user_dir_name=SwordmanHD)。"""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    home = os.path.expanduser("~")
    if platform.startswith("win"):
        return os.path.join(env.get("APPDATA") or os.path.join(home, "AppData", "Roaming"), "SwordmanHD")
    if platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "SwordmanHD")
    return os.path.join(env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share"), "SwordmanHD")


def slot_of_name(name):
    """GD00.GSF ~ GD04.GSF (大小写不拘) -> 槽位 1~5; 其他名字 -> None。"""
    m = re.fullmatch(r"gd0([0-4])\.gsf", name.lower())
    return int(m.group(1)) + 1 if m else None


def find_inputs(path, slot=None):
    """输入路径 -> [(槽位 1~5, 文件路径)]。

    目录: 找里面的 GD00~GD04.GSF (大小写不拘), 按序号对应槽位; 给了 --slot 就只导那一个档位对应的文件。
    文件: --slot 缺省按文件名 GDxx 对应槽位, 名字不规范就放槽位 1。
    """
    if os.path.isdir(path):
        found = {}
        for f in sorted(os.listdir(path)):
            s = slot_of_name(f)
            if s is not None and os.path.isfile(os.path.join(path, f)):
                found.setdefault(s, os.path.join(path, f))
        if slot is not None:
            found = {s: p for s, p in found.items() if s == slot}
            if not found:
                raise GsfError("目录 %s 里没有槽位 %d 对应的 GD%02d.GSF" % (path, slot, slot - 1))
        if not found:
            raise GsfError("目录 %s 里没有 GD00.GSF ~ GD04.GSF (原版营地存档在原版游戏目录里)" % path)
        return sorted(found.items())
    if os.path.isfile(path):
        if os.path.basename(path).lower().endswith(".gcf"):
            raise GsfError("%s 是战阵存档 (GAMEDATA.GCF), 本工具只转营地存档 GD00.GSF ~ GD04.GSF; 战阵存档请用 import_gcf.py 或存档工具" % path)
        return [(slot or slot_of_name(os.path.basename(path)) or 1, path)]
    raise GsfError("找不到 %s (请给出 GDxx.GSF 文件, 或含有它们的目录)" % path)


def read_file(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as e:
        raise GsfError("读不了 %s: %s" % (path, e.strerror or e))


# ---------------------------------------------------------------- 写出 (覆盖保护 + 备份)

def slot_file(out_dir, slot):
    return os.path.join(out_dir, "save%d.json" % slot)


def slot_taken(target):
    """与游戏一致 (SaveFile.exists): 正式文件或它的 .bak 在, 就算这个档位有存档。"""
    return os.path.exists(target) or os.path.exists(target + ".bak")


def backup_path(target, now=None):
    """旧档备份名: <存档>.bak-YYYYMMDD-HHMMSS (同一秒已有则加 -2, -3 ...)。"""
    now = now or datetime.datetime.now()
    base = "%s.bak-%s" % (target, now.strftime("%Y%m%d-%H%M%S"))
    p, n = base, 1
    while os.path.exists(p):
        n += 1
        p = "%s-%d" % (base, n)
    return p


def write_atomic(target, text):
    tmp = target + ".tmp-import"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, target)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise GsfError("写不了 %s: %s" % (target, e.strerror or e))


def describe(info, save):
    p = save["party"]
    return "殷剑平 Lv %d, 金钱 %d 两, 队伍 %d 人, 行囊 %d 件, 进度: 营地 %d, 下一关 %d" % (
        info["header"]["level"], save["gold"], len(p), len(save["bag"]), save["camp"], save["next_stage"])


def import_files(inputs, out_dir, force=False, dry_run=False, now=None, out=print):
    """导入 inputs=[(槽位, 路径)] 到 out_dir。返回 {"written": [...], "skipped": [...], "failed": [...]} (槽位列表)。"""
    result = {"written": [], "skipped": [], "failed": []}
    for slot, src in inputs:
        name = os.path.basename(src)
        target = slot_file(out_dir, slot)
        try:
            raw = read_file(src)
            info = build_save(raw, os.path.getmtime(src), name)
        except GsfError as e:
            out("失败  %s: %s" % (name, e))
            result["failed"].append(slot)
            continue
        out("%s -> save%d.json: %s" % (name, slot, describe(info, info["save"])))
        for w in info["warnings"]:
            out("  注意: " + w)
        taken = slot_taken(target)
        if taken and not force:
            out("  跳过: 槽位 %d 已有存档 (%s), 加 --force 才会覆盖 (旧档会先备份)" % (slot, target))
            result["skipped"].append(slot)
            continue
        if dry_run:
            out("  (试运行, 不写文件%s)" % ("; 会覆盖已有存档并先备份" if taken else ""))
            result["written"].append(slot)
            continue
        try:
            os.makedirs(out_dir, exist_ok=True)
            if taken:
                old = target if os.path.exists(target) else target + ".bak"
                bak = backup_path(target, now)
                shutil.copy2(old, bak)
                out("  已备份旧档: " + bak)
            write_atomic(target, json.dumps(info["save"], ensure_ascii=False, separators=(",", ":")))
        except (GsfError, OSError) as e:
            out("失败  %s: %s" % (name, e if isinstance(e, GsfError) else "写不了 %s: %s" % (target, e.strerror or e)))
            result["failed"].append(slot)
            continue
        out("  已写入 " + target)
        result["written"].append(slot)
    return result


# ---------------------------------------------------------------- 命令行

def main(argv=None, out=print):
    ap = argparse.ArgumentParser(
        description="把原版营地存档 GD00.GSF ~ GD04.GSF 导入复刻版 (save1.json ~ save5.json)。说明见 docs/存档互通.md",
        epilog="退出码: 0 成功; 1 有文件读不了/没写成; 2 参数错误; 3 有档位因已有存档被跳过 (加 --force 覆盖)")
    ap.add_argument("path", help="原版营地存档 GDxx.GSF, 或含 GD00~GD04.GSF 的目录 (原版游戏目录)")
    ap.add_argument("--out", help="复刻版存档目录 (缺省: 本平台的玩家存档目录, 见 docs/存档互通.md)")
    ap.add_argument("--slot", type=int, choices=range(1, SLOTS + 1), metavar="N",
                    help="只导入/写入槽位 N (1~5 = save1.json~save5.json); 给文件时指定它放进哪个槽位, 给目录时只导入对应的 GD0(N-1).GSF")
    ap.add_argument("--force", action="store_true", help="覆盖已有存档 (旧档先备份成 saveN.json.bak-<时间戳>); 缺省不覆盖")
    ap.add_argument("--dry-run", action="store_true", help="只显示将要导入的内容, 不写任何文件")
    args = ap.parse_args(argv)
    try:
        inputs = find_inputs(args.path, args.slot)
    except GsfError as e:
        out("错误: %s" % e)
        return 1
    out_dir = args.out or default_out_dir()
    out("读到 %d 个原版营地存档; 复刻版存档目录: %s%s" % (len(inputs), out_dir, " (试运行)" if args.dry_run else ""))
    r = import_files(inputs, out_dir, args.force, args.dry_run, out=out)
    if args.dry_run:
        out("试运行结束, 没有写任何文件。")
    else:
        out("完成: 写入 %d 个, 跳过 %d 个, 失败 %d 个。" % (len(r["written"]), len(r["skipped"]), len(r["failed"])))
        if r["written"]:
            out("进游戏后在标题「前历再续」或营地「前历再续」读取。")
    if r["failed"] or (not r["written"] and not r["skipped"]):
        return 1
    return 3 if r["skipped"] else 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
