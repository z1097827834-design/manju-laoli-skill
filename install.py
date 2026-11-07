#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""漫剧老李 AIGC 创作全流程 Skill · 套装安装器（V7.4.26 多技能套装版）

为什么需要它
------------
本包是**多技能套装**：包根并列 1 个总控（`short-drama-director/`）+ 12 个子技能
（`sd-*-engine/`），**顶层没有 `SKILL.md`**。而各家 Agent 平台只认「技能目录的父目录」：

  · OpenClaw（工作区级）  ~/.openclaw/workspace/skills/<skill>/SKILL.md
  · OpenClaw（全局级）    ~/.openclaw/skills/<skill>/SKILL.md
  · .agents 通用格式      ~/.agents/skills/<skill>/SKILL.md

因此安装的动作 = **把 13 个技能目录整体同级拷进目标 skills 根**。这一步不能省、
也不能只拷总控：总控与子技能之间的跨模块引用一律写成「包根相对」路径
（`sd-asset-engine/references/xxx.md`），**子技能不同级，引用就全断**。

本脚本做三件事
--------------
1. **部署**：13 个目录同级落地（`--layout flat`，默认）；或压成单入口形态
   （`--layout single`，给「zip 根即 SKILL.md」的单技能导入平台用）。
2. **自检**：装完立刻在**安装副本上**跑包级自检与关键机检脚本 —— 拷坏、漏拷、
   跨模块引用断裂、脚本不可编译，当场报出来，不留给用户第一次使用时才发现。
3. **卸载 / 校验**：`--verify` 只体检不安装；`--uninstall` 只删本套装的 13 个目录，
   绝不碰同级的其它技能。

用法
----
    python3 install.py                          # 装到 ~/.openclaw/workspace/skills（默认）
    python3 install.py --target global          # 装到 ~/.openclaw/skills（全 agent 共享）
    python3 install.py --target agents          # 装到 ~/.agents/skills（通用 .agents 格式）
    python3 install.py --target claude          # 装到 ~/.claude/skills
    python3 install.py --dest /path/to/skills   # 自定义 skills 根
    python3 install.py --layout single --dest /path/out   # 单入口形态（zip 根即 SKILL.md）
    python3 install.py --dry-run                # 只打印计划，不动盘
    python3 install.py --verify                 # 只体检已安装副本
    python3 install.py --uninstall              # 卸载
    python3 install.py --force                  # 覆盖已存在的同名目录

可选依赖：`matplotlib` 仅 `generate_emotion_curve.py`（情绪曲线出图）需要，
缺失时该脚本会自己给出提示，**不影响其余链路**；本脚本只提示不强装。

退出码：0 成功（允许 WARN）· 1 有 FAIL · 2 用法 / 环境错误
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

VERSION = "7.4.26"                       # 与包内 frontmatter 对齐；不作为安装拦截条件
ROUTER = "short-drama-director"

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_ROOT = HERE

TARGETS = {
    # key           说明                                 相对 home 的 skills 根
    "openclaw": ("OpenClaw 工作区级（推荐 · agent 私有）", ".openclaw/workspace/skills"),
    "global":   ("OpenClaw 全局级（所有 agent 共享）",     ".openclaw/skills"),
    "agents":   (".agents 通用格式（多家 agent 共用）",    ".agents/skills"),
    "claude":   ("Claude Code 技能目录",                   ".claude/skills"),
}

IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "*.pyo", ".DS_Store", "Thumbs.db", ".git",
    ".pytest_cache", "_tmp", "*.tmp", "*.log",
)


# --------------------------------------------------------------------------- 工具
class C:
    G = "\033[32m"; R = "\033[31m"; Y = "\033[33m"; B = "\033[36m"; D = "\033[2m"; E = "\033[0m"

    @classmethod
    def _w(cls):
        return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

    @classmethod
    def c(cls, code, s):
        return f"{code}{s}{cls.E}" if cls._w() else s


RESULTS = []          # [(level, label, detail)]


def ok(label, detail=""):
    RESULTS.append(("PASS", label, detail))


def warn(label, detail=""):
    RESULTS.append(("WARN", label, detail))


def fail(label, detail=""):
    RESULTS.append(("FAIL", label, detail))


def section(title):
    print(f"\n{C.c(C.B, '=' * 64)}\n{C.c(C.B, title)}\n{C.c(C.B, '=' * 64)}")


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0


def dir_size(path):
    total = 0
    for root, _d, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


# --------------------------------------------------------------------- 套装发现
def discover(src=SRC_ROOT):
    """返回 (总控目录名, [12 个子技能目录名])；只认有 SKILL.md 的目录。"""
    if not os.path.isdir(os.path.join(src, ROUTER)):
        raise SystemExit(f"[x] 找不到总控目录 {ROUTER}/ —— 请把本脚本放在套装包根目录下运行")
    subs = sorted(
        d for d in os.listdir(src)
        if d.startswith("sd-") and d.endswith("-engine")
        and os.path.isfile(os.path.join(src, d, "SKILL.md"))
    )
    return ROUTER, subs


def frontmatter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    out = {}
    if not m:
        return out
    for line in m.group(1).splitlines():
        mm = re.match(r"^([A-Za-z_]+):\s*(.+?)\s*$", line)
        if mm:
            out[mm.group(1)] = mm.group(2).strip().strip('"').strip("'")
    return out


def check_source(src=SRC_ROOT):
    """安装前体检源包：结构 / frontmatter / 版本一致。"""
    section("① 源包体检")
    router, subs = discover(src)
    print(f"  源包路径 : {src}")
    print(f"  总控     : {router}")
    print(f"  子技能   : {len(subs)} 个 → {', '.join(s.split('-')[1] for s in subs)}")

    total_files = sum(
        sum(len(f) for _r, _d, f in os.walk(os.path.join(src, d)))
        for d in [router] + subs
    )
    print(f"  文件数   : {total_files}")
    print(f"  体积     : {human(sum(dir_size(os.path.join(src, d)) for d in [router] + subs))}")

    if len(subs) != 12:
        fail(f"子技能应为 12 个，实际 {len(subs)} 个", ", ".join(subs))
    else:
        ok("结构：1 总控 + 12 子技能齐全")

    versions, bad_fm = {}, []
    for d in [router] + subs:
        fm = frontmatter(open(os.path.join(src, d, "SKILL.md"), encoding="utf-8").read())
        if not fm.get("name") or not fm.get("description"):
            bad_fm.append(d)
            continue
        if fm.get("name") != d:
            warn(f"{d}/SKILL.md 的 frontmatter name 与目录名不一致",
                 f"name={fm.get('name')}（部分平台按 name 注册，建议对齐）")
        versions.setdefault(fm.get("version", "(无)"), []).append(d)

    if bad_fm:
        fail("frontmatter 缺 name / description 的技能", ", ".join(bad_fm))
    else:
        ok("frontmatter：13 份 SKILL.md 均含 name + description")

    if len(versions) == 1:
        v = next(iter(versions))
        ok(f"版本：13 份 SKILL.md 版本号一致（{v}）")
    else:
        fail("13 份 SKILL.md 版本号不一致",
             "; ".join(f"{v}: {len(vs)} 份" for v, vs in versions.items()))
    return router, subs


def check_refs(root, mods, skip_changelog=True, title="② 跨模块引用完整性", folded=None):
    """跨模块引用完整性：文档里写的 `<模块>/references/xxx.md` 必须真实存在。

    folded: single 形态下总控内容被上提到根，`short-drama-director/x` 应解析为 `x`。
    """
    section(title)
    pat = re.compile(
        r"((?:" + "|".join(re.escape(m) for m in sorted(mods, key=len, reverse=True)) +
        r")/(?:references|scripts)/[\w\-./]+?\.(?:md|py))"
    )
    missing, seen, scanned = {}, 0, 0
    for mod in mods:
        base = os.path.join(root, mod)
        for r, _d, files in os.walk(base):
            for fn in files:
                if not fn.endswith(".md"):
                    continue
                if skip_changelog and fn == "CHANGELOG.md":
                    continue       # 沿革文件里会提到已删/已改名文件，属历史记录
                p = os.path.join(r, fn)
                scanned += 1
                try:
                    text = open(p, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                for ref in set(pat.findall(text)):
                    seen += 1
                    probes = [ref]
                    if folded and ref.startswith(folded + "/"):
                        probes.append(ref[len(folded) + 1:])     # 总控内容已上提到根
                    if not any(os.path.exists(os.path.join(root, x)) for x in probes):
                        missing.setdefault(ref, os.path.relpath(p, root))
    print(f"  扫描 {scanned} 份 md · 解析 {seen} 处跨模块引用")
    if missing:
        for ref, where in list(missing.items())[:12]:
            fail(f"引用文件不存在：{ref}", f"出现于 {where}")
    else:
        ok("全部跨模块引用均可解析（子技能与总控同级部署生效）")
    return not missing


# ------------------------------------------------------------------------- 部署
def deploy(src, dest, mods, layout="flat", force=False, dry_run=False):
    section(f"③ 部署（layout={layout}）")
    print(f"  目标根 : {dest}")

    if layout == "flat":
        plan = [(os.path.join(src, m), os.path.join(dest, m)) for m in mods]
    elif layout == "single":
        # 单入口形态：SKILL.md 落在 dest 根，references/ scripts/ 同级上提，
        # 12 个子技能仍在 dest 下并列 —— 「zip 根即 SKILL.md」的平台可直接导入。
        plan = [(os.path.join(src, ROUTER, "references"), os.path.join(dest, "references")),
                (os.path.join(src, ROUTER, "scripts"), os.path.join(dest, "scripts"))]
        for fn in ("SKILL.md", "README.md", "LICENSE", "CHANGELOG.md"):
            p = os.path.join(src, ROUTER, fn)
            if os.path.exists(p):
                plan.append((p, os.path.join(dest, fn)))
        plan += [(os.path.join(src, m), os.path.join(dest, m)) for m in mods if m != ROUTER]
    else:
        raise SystemExit(f"[x] 未知 layout: {layout}")

    conflicts = [d for _s, d in plan if os.path.exists(d)]
    if conflicts and not force:
        print(C.c(C.R, f"\n  [x] 目标已存在 {len(conflicts)} 项，未覆盖："))
        for c in conflicts[:5]:
            print(f"      {c}")
        raise SystemExit("      加 --force 覆盖，或改用 --dest 指定别的目录 / --uninstall 先卸载")
    if (conflicts or os.path.isdir(dest)) and not dry_run:
        os.makedirs(dest, exist_ok=True)

    if dry_run:
        ok(f"dry-run：将落地 {len(plan)} 项（未写盘）")
        for s, d in plan[:3]:
            print(f"      {os.path.relpath(d, dest) if d.startswith(dest) else d}")
        return True

    written = 0
    for s, d in plan:
        if os.path.isdir(d) and force:
            shutil.rmtree(d)
        elif os.path.isfile(d) and force:
            os.remove(d)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        if os.path.isdir(s):
            shutil.copytree(s, d, ignore=IGNORE)
            written += sum(len(f) for _r, _d, f in os.walk(d))
        else:
            shutil.copy2(s, d)
            written += 1
    msg = f"已写入 {len(plan)} 项 · {written} 个文件 · {human(dir_size(dest))}"
    print("  " + C.c(C.G, "[PASS] " + msg))
    ok(msg)
    return True


# ------------------------------------------------------------------------- 体检
def run_script(path, args=None, timeout=300, cwd=None):
    """跑 python 脚本，返回 (rc, 合并输出)。"""
    cmd = [sys.executable, path] + (args or [])
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=cwd or os.path.dirname(os.path.dirname(path)))
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"超时（>{timeout}s）"
    except OSError as e:
        return 125, str(e)


def verify(root, mods, layout="flat", deep=True):
    """在**安装副本**上体检。返回 is_healthy。"""
    section(f"④ 安装副本自检（{root}）")

    if layout == "single":
        expected = [m for m in mods if m != ROUTER]
        root_skill = os.path.join(root, "SKILL.md")
        miss = [m for m in expected if not os.path.isfile(os.path.join(root, m, "SKILL.md"))]
        if not os.path.isfile(root_skill):
            miss.append("SKILL.md（根）")
        if miss:
            fail("single 形态缺件", ", ".join(miss))
            return False
        for sub in ("references", "scripts"):
            if not os.path.isdir(os.path.join(root, sub)):
                fail(f"single 形态缺 {sub}/（总控内容未上提）")
        fm = frontmatter(open(root_skill, encoding="utf-8").read())
        if fm.get("name") == ROUTER:
            ok(f"single 形态：根 SKILL.md（name={ROUTER}）+ {len(expected)} 个子技能同级 + 总控 references/scripts 已上提")
        else:
            fail("根 SKILL.md frontmatter 异常", f"name={fm.get('name')}")
        folded = ROUTER
    else:
        miss = [m for m in mods if not os.path.isfile(os.path.join(root, m, "SKILL.md"))]
        if miss:
            fail("缺失技能目录 / SKILL.md", ", ".join(miss))
            return False
        ok(f"{len(mods)} 个技能目录到位，SKILL.md 均在")
        folded = None

    # 跨模块引用（flat 走包根相对；single 走 dest 根）
    check_refs(root, sorted(mods), skip_changelog=True,
               title="④-1 跨模块引用完整性", folded=folded)

    # 关键脚本可运行性
    if not deep:
        warn("深度自检已跳过（--fast）")
        return not any(r[0] == "FAIL" for r in RESULTS)

    if layout == "single":
        warn("single（移植包）不做脚本级深度自检",
             "本形态把总控内容上提到了包根，包内 check_package.py 以「script 的上上级 = 包根」"
             "定位子技能，结构上不成立。请用 flat 安装做体检，或直接把 zip 传给你的人工智能平台。")
        return not any(r[0] == "FAIL" for r in RESULTS)

    d = os.path.join(root, "scripts") if layout == "single" else os.path.join(root, ROUTER, "scripts")
    cases = [
        ("validate_prompt.py --self-test", os.path.join(d, "validate_prompt.py"), ["--self-test"], "self-test PASSED"),
        ("audit_contract.py --self-test", os.path.join(d, "audit_contract.py"), ["--self-test"], "self-test PASSED"),
        ("gate_check.py --self-test", os.path.join(root, "sd-feed-engine", "scripts", "gate_check.py"), ["--self-test"], "self-test PASSED"),
        ("build_board_lite.py --self-test", os.path.join(d, "build_board_lite.py"), ["--self-test"], "self-test PASSED"),
        ("test_project_bundle.py", os.path.join(d, "test_project_bundle.py"), [], "OK"),
        ("test_validator_stability.py", os.path.join(d, "test_validator_stability.py"), [], "OK"),
        ("test_slice_stability.py", os.path.join(d, "test_slice_stability.py"), [], "OK"),
    ]
    for label, path, args, needle in cases:
        if not os.path.isfile(path):
            fail(f"{label}：脚本缺失", path)
            continue
        rc, out = run_script(path, args)
        tag = needle in out
        if rc == 0 and tag:
            ok(label)
        else:
            tail = " | ".join(out.strip().splitlines()[-3:])
            fail(label, f"rc={rc} · {tail[:300]}")

    # P2 / P4.5 门禁脚本存在性（这两个不在 self-test 覆盖内）
    for label, path in (
        ("check_asset_blocks.py（P2 资产门禁）", os.path.join(d, "check_asset_blocks.py")),
        ("check_p45.py（P4.5 预演故事板门禁）", os.path.join(root, "sd-storyboard-engine", "scripts", "check_p45.py")),
        ("slice_context.py（预算报账）", os.path.join(d, "slice_context.py")),
        ("style-lock-recommend.py（I 画风锁）", os.path.join(d, "style-lock-recommend.py")),
    ):
        (ok if os.path.isfile(path) else fail)(label)

    # 包级自检：在安装副本上跑（会校验 143 份 md 的规则一致性）
    cp = os.path.join(d, "check_package.py")
    if os.path.isfile(cp):
        rc, out = run_script(cp, [], timeout=600)
        last = [l for l in out.strip().splitlines() if l.strip()][-1:]
        if rc == 0:
            ok("check_package.py 包级自检（143 份 md 规则一致性）", last[0][:120] if last else "")
        else:
            fails = [l for l in out.splitlines() if l.startswith("[FAIL]")]
            fail("check_package.py 包级自检", f"{len(fails)} 项 FAIL · " + (fails[0][:200] if fails else ""))

    # 依赖提示（不阻断）
    try:
        import matplotlib  # noqa: F401
        ok("可选依赖 matplotlib 已装（情绪曲线可出图）")
    except ImportError:
        warn("可选依赖 matplotlib 未装 → /情绪曲线 出图不可用",
             f"{sys.executable} -m pip install --user matplotlib（或重跑安装器加 --with-deps）"
             "；其余链路不受影响")

    return not any(r[0] == "FAIL" for r in RESULTS)


# --------------------------------------------------------------------- 卸载
def uninstall(dest, mods):
    section(f"⑤ 卸载（{dest}）")
    if not os.path.isdir(dest):
        print("  目标目录不存在，无需卸载")
        return True
    removed, kept = [], []
    for m in mods:
        p = os.path.join(dest, m)
        if os.path.isdir(p):
            shutil.rmtree(p)
            removed.append(m)
    others = sorted(
        d for d in os.listdir(dest)
        if os.path.isdir(os.path.join(dest, d)) and d not in mods
    )
    # single 形态的散件
    for fn in ("SKILL.md", "references", "scripts", "CHANGELOG.md"):
        p = os.path.join(dest, fn)
        if fn == "CHANGELOG.md" and os.path.exists(p):
            os.remove(p); removed.append(fn)
    if removed:
        ok(f"已删除本套装 {len(removed)} 项")
    else:
        warn("目标目录里没有本套装的文件")
    if others:
        print(C.c(C.D, f"  保留同级其它技能（未触碰）：{', '.join(others)}"))
    return True


# --------------------------------------------------------------------- 报告
def report(dest=None, layout="flat"):
    section("⑥ 结果汇总")
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for lvl, label, detail in RESULTS:
        counts[lvl] += 1
        if lvl != "PASS" or os.environ.get("VERBOSE"):
            color = {"PASS": C.G, "WARN": C.Y, "FAIL": C.R}[lvl]
            print(f"  {C.c(color, f'[{lvl}]')} {label}" + (f"\n         {C.c(C.D, detail)}" if detail else ""))
    print(f"\n  合计：{counts['PASS']} PASS · {counts['WARN']} WARN · {counts['FAIL']} FAIL")

    if counts["FAIL"]:
        print(C.c(C.R, "\n  ✗ 安装未通过自检，请把上面 FAIL 项反馈给作者。"))
        return 1
    if dest:
        print(C.c(C.G, f"\n  ✓ 安装完成：{dest}"))
        print("    下一步 —— 对 AI 助手直接说需求即可（总控会自动路由）：")
        print('       「帮我做一集短剧，题材是重生复仇，Seedance 2.5，竖屏」')
        print("    平台侧确认：")
        print("       OpenClaw → openclaw skills list     （新技能自动热加载）")
        print("       清单/重载失败时 → openclaw gateway restart")
        if counts["WARN"]:
            print(C.c(C.Y, "    （WARN 不阻断使用，按需处理）"))
    return 0


# ------------------------------------------------------------------------- 主流程
def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="漫剧老李 AIGC 全流程 Skill 套装安装器（1 总控 + 12 子技能）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="目标目录与入口：\n" + "\n".join(
            f"  --target {k:<9} {v[0]}: ~/{v[1]}" for k, v in TARGETS.items()),
    )
    ap.add_argument("--target", choices=list(TARGETS), default="openclaw",
                    help="预置安装位置（默认 openclaw 工作区级）")
    ap.add_argument("--dest", help="自定义 skills 根目录（覆盖 --target）")
    ap.add_argument("--layout", choices=["flat", "single"], default="flat",
                    help="flat = 13 目录同级（默认）· single = zip 根即 SKILL.md")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的同名目录")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不写盘")
    ap.add_argument("--verify", action="store_true", help="只体检，不安装")
    ap.add_argument("--uninstall", action="store_true", help="卸载本套装")
    ap.add_argument("--fast", action="store_true", help="跳过脚本级深度自检")
    ap.add_argument("--with-deps", action="store_true",
                    help="顺带装可选依赖：matplotlib（情绪曲线出图）+ chineseize-matplotlib（无系统中文字体时的兜底）")
    ap.add_argument("--zip", dest="zip_path", metavar="PATH",
                    help="部署后额外打一个 zip（single 形态时 zip 根即 SKILL.md，可直接上传单入口平台）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果汇总")
    return ap.parse_args(argv)


def install_deps():
    """可选依赖：matplotlib（/情绪曲线 出图）+ 中文字体兜底包。失败不阻断安装。"""
    section("② 可选依赖")
    cmds = [
        ([sys.executable, "-m", "pip", "install", "--user", "--break-system-packages",
          "matplotlib", "chineseize-matplotlib"], "matplotlib + chineseize-matplotlib"),
    ]
    for cmd, label in cmds:
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except Exception as e:                                   # noqa: BLE001
            warn(f"{label} 安装失败（可手动装）", str(e))
            continue
        if p.returncode == 0:
            ok(f"{label} 已就绪")
        else:
            tail = " | ".join((p.stdout + p.stderr).strip().splitlines()[-3:])
            warn(f"{label} 未装上（不阻断使用）",
                 f"手动：{sys.executable} -m pip install --user matplotlib chineseize-matplotlib"
                 f" · {tail[:200]}")


def main(argv=None):
    a = parse_args(argv)
    router, subs = discover()
    mods = [router] + subs
    dest = os.path.abspath(os.path.expanduser(a.dest)) if a.dest else \
        os.path.join(os.path.expanduser("~"), TARGETS[a.target][1])

    if a.uninstall:
        uninstall(dest, mods)
        return report()

    if a.verify:
        if not os.path.isdir(dest):
            print(f"[x] 目录不存在：{dest}")
            return 2
        healthy = verify(dest, mods, layout=a.layout, deep=not a.fast)
        return report(dest if healthy else None)

    check_source()
    if a.with_deps and not a.dry_run:
        install_deps()
    if not deploy(SRC_ROOT, dest, mods, a.layout, a.force, a.dry_run):
        return 2
    if a.dry_run:
        return report()

    verify(dest, mods, layout=a.layout, deep=not a.fast)

    if a.zip_path:
        section("⑤ 打包 zip")
        zp = os.path.abspath(os.path.expanduser(a.zip_path))
        if not zp.lower().endswith(".zip"):
            zp += ".zip"
        os.makedirs(os.path.dirname(zp) or ".", exist_ok=True)
        import zipfile
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            if a.layout == "single":
                # 内容压平到 zip 根：根下直接是 SKILL.md
                for r, _d, fs in os.walk(dest):
                    for fn in fs:
                        full = os.path.join(r, fn)
                        z.write(full, os.path.relpath(full, dest))
            else:
                # 保留外层目录名，解压后得到 <name>/<13 个技能目录>
                outer = os.path.basename(dest.rstrip(os.sep))
                for r, _d, fs in os.walk(dest):
                    for fn in fs:
                        full = os.path.join(r, fn)
                        z.write(full, os.path.join(outer, os.path.relpath(full, dest)))
        ok(f"已打包：{zp}（{human(os.path.getsize(zp))}）",
           "single：zip 根即 SKILL.md，可直接上传单入口平台" if a.layout == "single"
           else "flat：解压后 13 个技能目录同级，整体放进 skills 根")

    if a.json:
        print(json.dumps(
            {"dest": dest, "layout": a.layout, "version": VERSION,
             "results": [{"level": l, "label": lb, "detail": d} for l, lb, d in RESULTS]},
            ensure_ascii=False, indent=2))
    return report(dest, a.layout)


if __name__ == "__main__":
    sys.exit(main())
