#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""复刻版存档 save1.json ~ save5.json -> 原版营地存档 GD00.GSF ~ GD04.GSF (导入的反方向)。

用法:
    python3 tools/saves/export_gsf.py <saveN.json 或 含 saveN.json 的目录> [--out <原版游戏目录>] [--slot N] [--base GDxx.GSF] [--force] [--dry-run]

纯标准库 (Python 3.10+), 字段偏移与解码都复用同目录的 import_gsf.py (两个文件放在一起用)。说明见 docs/存档互通.md。

怎么写出 3898 字节: 先定「底板」, 再把复刻存档里已知的字段写在底板上:
    底板   --base 指定的原版 GDxx.GSF > 存档里的 gsf_raw (导入时留下的原文件字节) > 内置模板 (原版新游戏开局的状态)
    已知字段  进度值/下一关/金钱/128 个剧情变量/队伍 16 条记录 (在队角色的全部字段)/512 格行囊/头里的殷剑平等级和存档时间
    其余字节  (全局数据 +0x04 +0x0C +0x10 +0x14 +0x18 和末尾 4 字节, 以及不在队角色的记录) 照底板原样写回;
              +0x10/+0x14 是营地号的副本, 底板里它们与进度值相等时随新进度值一起改
队伍记录按 uid 对应底板里的记录: 底板里有就原地覆盖, 没有就放进第一个空记录; 底板里在队、复刻存档里不在队的人标成不在队 (其余字节保留)。

只导出营地存档 (where=camp); 战斗存档 GAMEDATA.GCF 不支持。
退出码: 0 成功 (含 --dry-run); 1 有文件读不了/没写成; 2 参数错误 (argparse); 3 有档位因目标已存在被跳过 (加 --force 覆盖)。
"""
import argparse
import base64
import binascii
import datetime
import json
import os
import re
import shutil
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import import_gsf as G  # noqa: E402

GsfError = G.GsfError

REC_BASE = 0x21C        # 队伍记录起点, 16 x 80 字节
REC_SIZE = 80
BAG_BASE = 0x71C        # 公共行囊 512 个 int32
BAG_SIZE = 512
VAR_BASE = 0x1C         # 剧情变量 128 个 int32
VAR_COUNT = 128
# 原版新游戏开局时全局数据里「没有逆清含义」的几个值 (见 tests/data/input_matrix/start.GSF): +0x04 +0x0C +0x10 +0x14 +0x18 和末尾 4 字节
TEMPLATE_UNKNOWN = {0x04: 18, 0x0C: 0, 0x10: -1, 0x14: 0, 0x18: 257}
TEMPLATE_TAIL = bytes.fromhex("f02f4c01")


# ---------------------------------------------------------------- 底板

def template_gsf():
    """内置模板: 原版新游戏开局的营地存档形状 (16 条空记录, 空行囊, 进度 0); 导出时已知字段会被存档内容覆盖。"""
    d = bytearray(G.BODY_SIZE)
    for o, v in TEMPLATE_UNKNOWN.items():
        struct.pack_into("<i", d, o, v)
    for r in range(16):
        struct.pack_into("<h", d, REC_BASE + REC_SIZE * r, -1)
    for i in range(BAG_SIZE):
        struct.pack_into("<i", d, BAG_BASE + 4 * i, -1)
    d[0xF1C:0xF20] = TEMPLATE_TAIL
    head = struct.pack("<ii", 0, 5) + b"01/01/26\0" + b"00:00:00\0"
    return head + G.xor_body(bytes(d))


def pick_base(save, base_raw=None):
    """底板字节和来源说明: --base 的文件 > 存档里的 gsf_raw > 内置模板。"""
    if base_raw is not None:
        if len(base_raw) < G.GSF_SIZE:
            raise GsfError("底板文件太短 (%d 字节, 应有 %d 字节), 不是原版营地存档" % (len(base_raw), G.GSF_SIZE))
        return base_raw[:G.GSF_SIZE], "指定的原版存档"
    raw = save.get("gsf_raw")
    if isinstance(raw, str) and raw:
        try:
            b = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            raise GsfError("存档里的 gsf_raw 不是有效的 base64 (存档损坏? 可以删掉这一项重试)")
        if len(b) != G.GSF_SIZE:
            raise GsfError("存档里的 gsf_raw 长度不对 (%d 字节, 应为 %d)" % (len(b), G.GSF_SIZE))
        return b, "存档里保留的原版字节 gsf_raw"
    return template_gsf(), "内置模板"


# ---------------------------------------------------------------- 编码

def _num(v, what, lo, hi):
    """JSON 里的数 (可能是 120.0) -> int, 超出 [lo, hi] 报给玩家看的错。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        raise GsfError("存档里的%s不是数字 (%r)" % (what, v))
    n = int(v)
    if not lo <= n <= hi:
        raise GsfError("存档里的%s (%d) 超出原版能存的范围 (%d ~ %d)" % (what, n, lo, hi))
    return n


def _i16(v, what):
    return _num(v, what, -32768, 32767)


def _i32(v, what):
    return _num(v, what, -2147483648, 2147483647)


def _put16(d, o, v, what):
    struct.pack_into("<h", d, o, _i16(v, what))


def _pad(values, n, fill, what, warnings):
    vals = [_i16(v, what) for v in values]
    if len(vals) > n:
        warnings.append("%s有 %d 个, 原版只有 %d 格, 多出的已丢弃" % (what, len(vals), n))
        vals = vals[:n]
    return vals + [fill] * (n - len(vals))


def _write_record(d, o, uid, p, who, warnings):
    """把复刻的一个角色 p 写进记录 o (字段齐全的 80 字节); 存档里没有的键保留底板里的字节。"""
    struct.pack_into("<h", d, o, uid)
    for key, off in (("lv", 2), ("exp", 4), ("hp_max", 6), ("mp_max", 8), ("spirit_points", 0x26)):
        if key in p:
            _put16(d, o + off, p[key], "%s的%s" % (who, key))
    st = p.get("stats")
    if isinstance(st, dict):
        for k, key in enumerate(("str", "int", "avg", "vit", "luk")):
            if key in st:
                _put16(d, o + 0xA + 2 * k, st[key], "%s的属性 %s" % (who, key))
    sp = p.get("spirit")
    if isinstance(sp, dict):
        for k, name in enumerate(G.SPIRIT_NAMES):
            if name in sp:
                _put16(d, o + 0x14 + 2 * k, sp[name], "%s的五魂 %s" % (who, name))
    gear = p.get("gear")
    if isinstance(gear, dict):
        for k, key in enumerate(G.SLOT_KEYS):
            if key in gear:
                _put16(d, o + 0x1E + 2 * k, -1 if gear[key] is None else gear[key], "%s的装备 %s" % (who, key))
    if isinstance(p.get("items"), list):
        struct.pack_into("<10h", d, o + 0x28, *_pad(p["items"], 10, -1, "%s的随身物品" % who, warnings))
    if isinstance(p.get("skills"), list):
        struct.pack_into("<10h", d, o + 0x3C, *_pad(p["skills"], 10, -1, "%s的技能" % who, warnings))
    struct.pack_into("<h", d, o + 0x24, 1)


def build_gsf(save, base_raw=None, now=None):
    """复刻版存档字典 -> (GSF 字节, 说明字典 {"base": 底板来源, "warnings": [...]})。出错抛 GsfError (中文)。"""
    if not isinstance(save, dict):
        raise GsfError("存档不是 JSON 对象")
    for k in ("gold", "bag", "game_data", "party"):
        if k not in save:
            raise GsfError("存档缺少必需字段 %s (存档损坏?)" % k)
    if save.get("where", "camp") != "camp":
        raise GsfError("只能导出营地存档 (where=camp), 这个存档的位置是 %r" % save.get("where"))
    warnings = []
    ids = [c.get("id") for c in save.get("content") or [] if isinstance(c, dict)]
    if any(i != "tdj" for i in ids):
        warnings.append("存档用了原版内容包 tdj 之外的内容包 (%s), 其中新增的角色/物品/技能在原版里不存在, 原版读档可能出问题" %
                        ", ".join(sorted({str(i) for i in ids if i != "tdj"})))
    base, base_name = pick_base(save, base_raw)
    base_body = G.xor_body(base[G.HEADER_SIZE:])
    base_head = G.parse_header(base)
    d = bytearray(base_body)

    stage = save.get("stage", 0)
    camp = _i32(save.get("camp", stage), "营地号")
    next_stage = _i32(save["next_stage"], "下一关")
    gold = _i32(save["gold"], "金钱")
    if not (0 <= camp <= G.STAGE_LIMIT and 0 <= next_stage <= G.STAGE_LIMIT and gold >= 0):
        raise GsfError("存档里的营地号 (%d)、下一关 (%d) 或金钱 (%d) 超出原版的合理范围" % (camp, next_stage, gold))
    struct.pack_into("<i", d, 0, next_stage)
    struct.pack_into("<i", d, 8, gold)
    for o in (0x10, 0x14):   # 营地号的副本: 底板里与它的进度值相等, 就跟着新进度值走
        if struct.unpack_from("<i", d, o)[0] == base_head["camp_no"]:
            struct.pack_into("<i", d, o, camp)

    # 剧情变量
    gd = save["game_data"]
    if not isinstance(gd, dict):
        raise GsfError("存档里的 game_data 不是字典")
    vars_ = [0] * VAR_COUNT
    dropped = 0
    for k, v in gd.items():
        try:
            i = int(k)
        except (TypeError, ValueError):
            i = -1
        if not 0 <= i < VAR_COUNT:
            dropped += 1
            continue
        vars_[i] = _i32(v, "剧情变量 %s" % k)
    if dropped:
        warnings.append("有 %d 个剧情变量的编号不在 0~%d, 原版没有这些变量, 已丢弃" % (dropped, VAR_COUNT - 1))
    struct.pack_into("<%di" % VAR_COUNT, d, VAR_BASE, *vars_)

    # 行囊
    bag = save["bag"]
    if not isinstance(bag, list):
        raise GsfError("存档里的 bag 不是数组")
    cells = [_i32(v, "行囊物品") for v in bag]
    if len(cells) > BAG_SIZE:
        warnings.append("行囊有 %d 件, 原版只有 %d 格, 多出的已丢弃" % (len(cells), BAG_SIZE))
        cells = cells[:BAG_SIZE]
    cells += [-1] * (BAG_SIZE - len(cells))
    struct.pack_into("<%di" % BAG_SIZE, d, BAG_BASE, *cells)

    # 队伍
    party = save["party"]
    if not isinstance(party, dict):
        raise GsfError("存档里的 party 不是字典")
    members = []
    for k, p in party.items():
        try:
            uid = int(k)
        except (TypeError, ValueError):
            raise GsfError("存档里的队伍编号 %r 不是整数" % k)
        if not isinstance(p, dict) or not 0 <= uid <= 32767:
            raise GsfError("存档里的队伍记录 %r 不对" % k)
        members.append((uid, p))
    if len(members) > 16:
        raise GsfError("队伍有 %d 人, 原版最多只记 16 人" % len(members))
    ids_in_party = {uid for uid, _ in members}
    rec = [REC_BASE + REC_SIZE * r for r in range(16)]
    uid_at = [struct.unpack_from("<h", d, o)[0] for o in rec]
    on_at = [struct.unpack_from("<h", d, o + 0x24)[0] for o in rec]
    for r in range(16):    # 底板里在队、现在不在队的人: 标成不在队, 其余字节保留
        if on_at[r] == 1 and uid_at[r] not in ids_in_party:
            struct.pack_into("<h", d, rec[r] + 0x24, 0)
            on_at[r] = 0
    used = set()
    for uid, p in members:
        slot = next((r for r in range(16) if uid_at[r] == uid and r not in used), None)
        if slot is None:   # 新成员: 先找空记录 (uid -1, 或整条全 0), 实在没有才占用不在队的旧记录
            free = [r for r in range(16) if on_at[r] != 1 and r not in used]
            slot = next((r for r in free if uid_at[r] == -1), None)
            if slot is None:
                slot = next((r for r in free if not any(d[rec[r]:rec[r] + REC_SIZE])), None)
            if slot is None and free:
                slot = free[0]
                warnings.append("原版的 16 条队伍记录里没有空位, 角色 %d 占用了不在队的角色 %d 的记录" % (uid, uid_at[slot]))
            if slot is None:
                raise GsfError("队伍记录放不下 (16 条都占着)")
        used.add(slot)
        uid_at[slot] = uid
        _write_record(d, rec[slot], uid, p, "角色 %d" % uid, warnings)

    # 头: 进度值 / 殷剑平等级 / 存档日期时间
    hero = party.get("0")
    level = _i32(hero["lv"], "殷剑平等级") if isinstance(hero, dict) and "lv" in hero else base_head["level"]
    when = now
    if when is None:
        try:
            when = datetime.datetime.strptime(str(save.get("time", "")), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            when = datetime.datetime.now()
    head = struct.pack("<ii", camp, level) + when.strftime("%m/%d/%y").encode("ascii").ljust(9, b"\0") + \
        when.strftime("%H:%M:%S").encode("ascii").ljust(9, b"\0")
    out = head + G.xor_body(bytes(d))
    if len(out) != G.GSF_SIZE:
        raise GsfError("内部错误: 生成的存档长度 %d 不对" % len(out))
    check_roundtrip(out, save, party)
    return out, {"base": base_name, "warnings": warnings}


def check_roundtrip(raw, save, party):
    """写出的字节读回来, 金钱/行囊/队伍必须和存档一致 (防止偏移写错把坏档交给玩家)。"""
    back = G.parse_gsf(raw)["state"]
    if back["gold"] != int(save["gold"]) or back["bag"] != [int(v) for v in save["bag"]][:BAG_SIZE]:
        raise GsfError("内部校验失败: 金钱或行囊读回来对不上, 没有写出文件")
    if sorted(back["party"], key=int) != sorted((str(int(k)) for k in party), key=int):
        raise GsfError("内部校验失败: 队伍读回来对不上, 没有写出文件")


# ---------------------------------------------------------------- 找输入 / 目标

def save_slot_of_name(name):
    m = re.fullmatch(r"save([1-5])\.json", name.lower())
    return int(m.group(1)) if m else None


def find_saves(path, slot=None):
    """输入路径 -> [(槽位 1~5, 文件路径)]; 规则与 import_gsf.find_inputs 对称。"""
    if os.path.isdir(path):
        found = {}
        for f in sorted(os.listdir(path)):
            s = save_slot_of_name(f)
            if s is not None and os.path.isfile(os.path.join(path, f)):
                found.setdefault(s, os.path.join(path, f))
        if slot is not None:
            found = {s: p for s, p in found.items() if s == slot}
            if not found:
                raise GsfError("目录 %s 里没有 save%d.json" % (path, slot))
        if not found:
            raise GsfError("目录 %s 里没有 save1.json ~ save5.json (复刻版存档目录, 见 docs/存档互通.md)" % path)
        return sorted(found.items())
    if os.path.isfile(path):
        return [(slot or save_slot_of_name(os.path.basename(path)) or 1, path)]
    raise GsfError("找不到 %s (请给出 saveN.json 文件, 或含有它们的目录)" % path)


def gsf_target(out_dir, slot):
    """槽位 1~5 -> 原版目录里的 GD00~GD04.GSF; 目录里已有同名文件 (大小写不拘) 就用它原来的拼写。"""
    want = "GD%02d.GSF" % (slot - 1)
    try:
        for f in os.listdir(out_dir):
            if f.lower() == want.lower():
                return os.path.join(out_dir, f)
    except OSError:
        pass
    return os.path.join(out_dir, want)


def read_save(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        raise GsfError("读不了 %s: %s" % (path, e.strerror or e))
    except ValueError:
        raise GsfError("%s 不是有效的 JSON (存档损坏?)" % path)
    if not isinstance(data, dict):
        raise GsfError("%s 不是复刻版存档" % path)
    return data


def write_atomic_bytes(target, data):
    tmp = target + ".tmp-export"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, target)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise GsfError("写不了 %s: %s" % (target, e.strerror or e))


def describe(save, raw):
    p = save["party"]
    return "殷剑平 Lv %d, 金钱 %d 两, 队伍 %d 人, 行囊 %d 件, 进度: 营地 %d, 下一关 %d" % (
        G.parse_header(raw)["level"], int(save["gold"]), len(p), len(save["bag"]), G.parse_header(raw)["camp_no"], int(save["next_stage"]))


def export_files(inputs, out_dir, force=False, dry_run=False, base_raw=None, now=None, out=print):
    """导出 inputs=[(槽位, 路径)] 到原版目录 out_dir。返回 {"written": [...], "skipped": [...], "failed": [...]} (槽位列表)。"""
    result = {"written": [], "skipped": [], "failed": []}
    for slot, src in inputs:
        name = os.path.basename(src)
        target = gsf_target(out_dir, slot)
        try:
            save = read_save(src)
            raw, info = build_gsf(save, base_raw, now)
        except GsfError as e:
            out("失败  %s: %s" % (name, e))
            result["failed"].append(slot)
            continue
        out("%s -> %s: %s (底板: %s)" % (name, os.path.basename(target), describe(save, raw), info["base"]))
        for w in info["warnings"]:
            out("  注意: " + w)
        taken = os.path.exists(target)
        if taken and not force:
            out("  跳过: %s 已存在, 加 --force 才会覆盖 (旧文件会先备份)" % target)
            result["skipped"].append(slot)
            continue
        if dry_run:
            out("  (试运行, 不写文件%s)" % ("; 会覆盖已有文件并先备份" if taken else ""))
            result["written"].append(slot)
            continue
        try:
            os.makedirs(out_dir, exist_ok=True)
            if taken:
                bak = G.backup_path(target, now)
                shutil.copy2(target, bak)
                out("  已备份旧文件: " + bak)
            write_atomic_bytes(target, raw)
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
        description="把复刻版存档 save1.json ~ save5.json 导出成原版营地存档 GD00.GSF ~ GD04.GSF。说明见 docs/存档互通.md",
        epilog="退出码: 0 成功; 1 有文件读不了/没写成; 2 参数错误; 3 有档位因目标已存在被跳过 (加 --force 覆盖)")
    ap.add_argument("path", help="复刻版存档 saveN.json, 或含 save1~5.json 的目录 (缺省存档目录: %s)" % G.default_out_dir())
    ap.add_argument("--out", required=True, help="原版游戏目录 (GDxx.GSF 写在这里)")
    ap.add_argument("--slot", type=int, choices=range(1, G.SLOTS + 1), metavar="N",
                    help="只导出槽位 N (1~5); 给文件时指定它写成 GD0(N-1).GSF")
    ap.add_argument("--base", help="用这个原版 GDxx.GSF 当底板 (缺省: 存档里的 gsf_raw, 没有就用内置模板)")
    ap.add_argument("--force", action="store_true", help="覆盖已有的 GDxx.GSF (旧文件先备份成 GDxx.GSF.bak-<时间戳>); 缺省不覆盖")
    ap.add_argument("--dry-run", action="store_true", help="只显示将要导出的内容, 不写任何文件")
    args = ap.parse_args(argv)
    try:
        inputs = find_saves(args.path, args.slot)
        base_raw = G.read_file(args.base) if args.base else None
    except GsfError as e:
        out("错误: %s" % e)
        return 1
    out("读到 %d 个复刻版存档; 原版目录: %s%s" % (len(inputs), args.out, " (试运行)" if args.dry_run else ""))
    r = export_files(inputs, args.out, args.force, args.dry_run, base_raw, out=out)
    if args.dry_run:
        out("试运行结束, 没有写任何文件。")
    else:
        out("完成: 写入 %d 个, 跳过 %d 个, 失败 %d 个。" % (len(r["written"]), len(r["skipped"]), len(r["failed"])))
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
