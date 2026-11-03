#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重生之我在做亚马逊 · 第01集 · ComfyUI 批量出片脚本
只依赖 Python 标准库 + requests（可选，无则用 urllib）

用法：
  # 0. 检查 ComfyUI 是否在线、看装了哪些模型
  python3 run_comfy_batch.py --ping

  # 1. 把 18 张资产图上传进 ComfyUI 的 input 目录
  python3 run_comfy_batch.py --upload-assets

  # 2. 查队列状态
  python3 run_comfy_batch.py --queue

  # 3. 跑单个片段（推荐先跑一个验证参数）
  python3 run_comfy_batch.py --run seg1 1A

  # 4. 跑整段
  python3 run_comfy_batch.py --run-seg 8

  # 5. 跑全集（26 个片段，注意显存与时间）
  python3 run_comfy_batch.py --run-all

参数默认指向 http://127.0.0.1:8188
注意：这不是"云端 API"，是打你自己本机的 ComfyUI，所以必须先在本机启动 ComfyUI。
"""

import argparse, json, os, sys, time, uuid, mimetypes, random

try:
    import urllib.request as urlreq
    import urllib.error as urlerr
except ImportError:
    sys.exit("需要 Python 3.7+")

HOST = os.environ.get("COMFY_HOST", "127.0.0.1:8188")
BASE = f"http://{HOST}"
PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSET_DIR = os.path.join(PKG, "01_资产图")
WF_DIR = os.path.join(PKG, "02_ComfyUI工作流")
MANIFEST = os.path.join(PKG, "03_提示词", "asset_manifest.json")

# ------------------------------------------------------------------ HTTP

def _req(path, data=None, method=None, headers=None, raw=False, timeout=120):
    url = BASE + path
    h = headers or {}
    body = data
    if isinstance(data, (dict, list)):
        body = json.dumps(data).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urlreq.Request(url, data=body, headers=h, method=method)
    try:
        with urlreq.urlopen(req, timeout=timeout) as r:
            buf = r.read()
            if raw:
                return buf
            try:
                return json.loads(buf.decode("utf-8"))
            except Exception:
                return buf
    except urlerr.HTTPError as e:
        msg = e.read().decode("utf-8", "ignore")[:800]
        raise RuntimeError(f"HTTP {e.code} @ {path}: {msg}")
    except urlerr.URLError as e:
        raise RuntimeError(f"连不上 ComfyUI ({BASE})：{e.reason}\n→ 先在本机启动 ComfyUI，确认 {BASE} 可访问")


# ------------------------------------------------------------------ 上传

def upload_image(path, name=None):
    """把本地图片上传进 ComfyUI input 目录"""
    name = name or os.path.basename(path)
    boundary = "----ComfyBatch" + uuid.uuid4().hex
    ctype = mimetypes.guess_type(name)[0] or "image/png"
    lines = []
    lines.append(f"--{boundary}\r\n".encode())
    lines.append(f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'.encode())
    lines.append(f"Content-Type: {ctype}\r\n\r\n".encode())
    lines.append(open(path, "rb").read())
    lines.append(f"\r\n--{boundary}\r\n".encode())
    lines.append(b'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n')
    lines.append(f"--{boundary}--\r\n".encode())
    body = b"".join(lines)
    out = _req("/upload/image", data=body, method="POST",
               headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return out


def cmd_upload_assets():
    files = sorted(f for f in os.listdir(ASSET_DIR) if f.lower().endswith(".png"))
    if not files:
        sys.exit(f"没找到资产图：{ASSET_DIR}")
    print(f"发现 {len(files)} 张资产图，开始上传到 {BASE} …\n")
    ok = 0
    for f in files:
        try:
            r = upload_image(os.path.join(ASSET_DIR, f))
            print(f"  ✓ {f}" + (f"  → {r.get('name')}" if isinstance(r, dict) else ""))
            ok += 1
        except Exception as e:
            print(f"  ✗ {f}  {e}")
    print(f"\n完成 {ok}/{len(files)}")
    print("提示：上传后文件名就是 LoadImage 节点里要填的名字。")


# ------------------------------------------------------------------ 出片

def load_manifest():
    return json.load(open(MANIFEST, encoding="utf-8"))


def build_prompt(seg, clip_id, first_frame, positive, negative,
                 prefix, seed=None, width=704, height=1280,
                 length=81, fps=16, steps=30, cfg=6.0):
    """
    直接构造 API 版 prompt（不依赖画布版 json，改动更可控）
    对应 03_wan21_i2v_ui.json 的结构
    """
    seed = seed if seed is not None else random.randint(0, 2**31 - 1)
    return {
        "1":  {"class_type": "UNETLoader",        "inputs": {"unet_name": "wan2.1_i2v_480p_14B_fp8_e4m3fn.safetensors", "weight_dtype": "default"}},
        "2":  {"class_type": "CLIPLoader",        "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "3":  {"class_type": "VAELoader",         "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "4":  {"class_type": "CLIPVisionLoader",  "inputs": {"clip_name": "clip_vision_h.safetensors"}},
        "5":  {"class_type": "LoadImage",         "inputs": {"image": first_frame, "upload": "image"}},
        "6":  {"class_type": "CLIPVisionEncode",  "inputs": {"clip_vision": ["4", 0], "image": ["5", 0], "crop": "none"}},
        "7":  {"class_type": "CLIPTextEncode",    "inputs": {"clip": ["2", 0], "text": positive}},
        "8":  {"class_type": "CLIPTextEncode",    "inputs": {"clip": ["2", 0], "text": negative}},
        "9":  {"class_type": "ModelSamplingSD3",  "inputs": {"model": ["1", 0], "shift": 8.0}},
        "10": {"class_type": "WanImageToVideo",   "inputs": {
                    "positive": ["7", 0], "negative": ["8", 0], "vae": ["3", 0],
                    "clip_vision_output": ["6", 0], "start_image": ["5", 0],
                    "width": width, "height": height, "length": length, "batch_size": 1}},
        "11": {"class_type": "KSampler",          "inputs": {
                    "model": ["9", 0], "positive": ["10", 0], "negative": ["10", 1],
                    "latent_image": ["10", 2], "seed": seed, "steps": steps, "cfg": cfg,
                    "sampler_name": "uni_pc", "scheduler": "simple", "denoise": 1.0}},
        "12": {"class_type": "VAEDecode",         "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "CreateVideo",       "inputs": {"images": ["12", 0], "fps": float(fps)}},
        "14": {"class_type": "SaveVideo",         "inputs": {"video": ["13", 0], "filename_prefix": prefix,
                                                             "format": "mp4", "codec": "h264"}},
    }


# 片段表：clip_id -> (段, 首帧文件名, 正向提示词, 负向提示词)
# 正向提示词与 03_提示词/ep01_wan21_prompts_zh.md 一一对应
CLIPS = {}


def _c(cid, seg, first, pos, neg="画面抖动, 手指畸形, 多余手指, 脸部漂移, 卡通, 3D渲染, 过曝, 高饱和, 文字, 水印, logo"):
    """键统一为「段号-镜号」，避免跨段重名（段1的2A 与 段2的2A 曾撞键）"""
    key = f"{seg}-{cid}"
    CLIPS[key] = dict(seg=seg, jing=cid, first=first, pos=pos, neg=neg)


_c("1A", 1, "图04_SCN-01_星辰办公室_九宫格.png",
   "固定机位大特写，一只男人的右手死死抠住白色哑光长桌的桌沿，指节泛白，指腹在漆面上压出浅凹痕。一滴汗从画面外落下，砸在手背旁边两厘米的桌面上，溅开一小片。桌面横着一条硬边的百叶窗光带，背景是虚化的牛皮纸箱一角。85mm 镜头，35 度俯角，浅景深，冷蓝灰调，低饱和，胶片颗粒。")
_c("1B", 1, "图04_SCN-01_星辰办公室_九宫格.png",
   "镜头极缓推近，男人的手在桌沿上松了一下又握紧，手背的一条血管凸起。桌面上斜横的光带缓慢移动，细小灰尘在光里浮动。冷蓝灰色调，硬边侧光，浅景深，胶片颗粒。")
_c("2A", 1, "图01_CHR-01_陈默_四格板.png",
   "29 岁中国男人的面部特写，他猛地抬起头，双眼猛地睁开，瞳孔一缩，睫毛颤了一下。额角一滴汗沿着太阳穴滑进鬓角。右后方硬边日光在他颧骨上切出一道亮边，鼻子左侧整片落在阴影里。85mm 镜头，平视略低于眼线，极缓推近，冷蓝灰调，皮肤有真实毛孔与细纹，不磨皮，胶片颗粒。")
_c("3A", 1, "图05A_PRP-01a_股权转让协议_四格板.png",
   "过肩中景，越过一个男人的右肩看向长桌对面。对面微胖的中年男人把三页订好的协议沿桌面推过来，食指在纸面轻敲两下。他嘴角提起，眼皮下压，眼角没有纹路。桌面漆面反着一条条平行光带，身后白板写满编号。50mm 镜头，略俯八度，固定机位带一点手持呼吸，冷蓝灰调，低饱和，胶片颗粒。")

_c("2A", 2, "段1_末帧.png",
   "过肩中景延续。男人的右手入画，掌心按在三页协议上把纸合成一叠，然后贴着桌面把它们推回对面半张桌的距离，手腕一转，钢带手表的表蒙在硬光里闪一下。对面的男人把手收回到桌沿。50mm 镜头，固定机位，冷蓝灰调，硬边侧光，胶片颗粒。")
_c("2B", 2, "段1_末帧.png",
   "镜头切到男人的中近景，平视略低。他从桌上抬起眼睛看向对面，喉结先动了一下，然后开口说话，嘴唇开合自然，说完嘴角收平，下颌绷紧。一道硬边光带横过他左脸颊，右脸落在阴影里。85mm 镜头，固定机位，冷蓝灰调，低饱和，胶片颗粒。")

_c("3A", 3, "图02_CHR-02_赵鹏_四格板.png",
   "微胖中年男人双手按在长桌上撑起身子，椅子向后滑开，随后一只手掌拍在桌面上，桌上那叠纸跳起两厘米，旁边的咖啡杯晃了一下没有倒。他身体前倾，脸逼近镜头。50mm 镜头，随他起身微微上摇，冷蓝灰调，低饱和，胶片颗粒。")
_c("3B", 3, "图01_CHR-01_陈默_四格板.png",
   "中近景，男人一句话没说，双手从脑后把工牌挂绳取下来，把工牌正面朝上放在白色桌面上，用两根手指推前一掌宽，然后站起身转身走向左侧玻璃门，背影渐远。35mm 镜头，机位 1.5 米，长桌形成一条硬水平线，冷蓝灰调，胶片颗粒。")

_c("4A", 4, "图09_SCN-03_写字楼雨夜外景_母版.png",
   "夜晚暴雨，男人抱着两片压扁的牛皮纸箱从写字楼旋转门里侧身退出来，门厅暖白光在他脚下湿地上铺出一片三角亮区，冷蓝城市光贴在玻璃和雨雾上。他走下三级台阶，在第二级停住。50mm 镜头，机位 1.6 米，绝对水平，严格中轴对称，雨丝只在暖光区可见，低饱和冷蓝灰，明显颗粒。")
_c("4B", 4, "段4_镜4A末帧.png",
   "侧面中近景，雨落在他头发上，顺着太阳穴流到下颌往下滴。他抬起下巴看向身后的高楼，雨幕里楼体只剩零星亮窗。他手臂收紧，怀里纸箱的胶带边翘起一角。85mm 镜头，平视，冷蓝灰调，浅景深，胶片颗粒。")

_c("5A", 5, "图07_SCN-02_深夜出租屋_九宫格.png",
   "台灯下的出租屋，男人站在斜靠墙面的白色磁板前，右手拿黑色马克笔，在白板顶上一笔一笔写下四个大字，写完下面那组箭头草图已经先画好了。台灯从右下方打出暖黄圆形光斑，房间四角接近全黑，窗框边一线冷光。35mm 镜头，机位 1.2 米，略俯十度，冷绿偏灰与 3000K 暖光对峙，胶片颗粒。")
_c("5B", 5, "图08_CHR-03_苏晚_四格板.png",
   "门被推开，二十七岁的女人背着帆布包走进来，走到折叠桌前，两根手指按在桌面上，把一枚黑色 U 盘推到一叠打印纸边停住，眼睛始终看着对面男人。台灯在她左边脸颊上打出暖光，右边落在暗处。50mm 镜头，平视固定，冷绿偏灰，胶片颗粒。")

_c("6A", 6, "图13_SCN-04_车间_九宫格.png",
   "东莞注塑厂，两米不锈钢检测台上放着一台白色挂颈无叶风扇样机。男人的右手握住数显卡尺，卡爪夹住样机出风口的一根栅条，拇指转动滚轮读数，左手把颈环按住不动。顶灯冷白光线直下，不锈钢台面边缘一道硬高光，侧门天光只落在身后的绿色环氧地坪上。50mm 镜头，机位 1.3 米，俯 25 度，冷白偏青，低饱和，胶片颗粒。")
_c("6B", 6, "段6_镜6A末帧.png",
   "中近景，男人把卡尺平放在不锈钢台面上，转头用两根手指指向身后钢料架上的同一块模具钢料，再转回来看住厂长。厂长举起的手停在半空不动。85mm 镜头，略俯，冷白偏青，浅景深，胶片颗粒。")

_c("7A", 7, "图12B_PRP-02b_FBA入仓箱_四格板.png",
   "折叠桌上，男人用拇指把最后一段透明胶带压平在纸箱封口上，抹掉一个气泡，然后把箱子搬起来放到桌边地上，那里已经码着两个同样封好的箱子。台灯从右下打出暖黄圆形光斑，桌面之外迅速压黑，窗框一线冷反射。35mm 镜头，机位 1.2 米，俯十度，低饱和，胶片颗粒。")
_c("7B", 7, "图07_SCN-02_深夜出租屋_九宫格.png",
   "侧向近景，一只男人的手从画面右侧伸进来，把笔记本电脑的盖子合上，盖面上贴着的黄粉两色便利贴被压平。屏幕的光从指节上退掉，房间重新只剩台灯的暖光。50mm 镜头，浅侧角，浅景深，胶片颗粒。")

_c("8A", 8, "图12C_PRP-02c_后台手机_四格板.png",
   "桌面特写，黑色直板手机平放在木桌上，桌边还有折好的打印纸。手机震了一下，机身贴着桌面挪了两毫米，屏幕从黑变白亮起，冷蓝白光从玻璃上溢出来，在木桌面上铺出一块硬边矩形。房间其余部分几乎全黑，只有画面右侧一线暖光。85mm 镜头，机位 0.9 米，焦点在手屏幕上，胶片颗粒。")
_c("8B", 8, "图01_CHR-01_陈默_四格板.png",
   "中近景，男人在椅子上仰头盯着天花板，听见声音后头猛地低下来，肩膀一弹，椅子向前一冲，右手一把抓起桌上的手机举到脸前。台灯还在他脑后镶出一道暖边，冷白屏幕光开始从下往上啃他的脸。35mm 镜头，与胸口齐平，胶片颗粒。")
_c("8C", 8, "段8_镜8B末帧.png",
   "面部特写，只有屏幕的冷光从下方斜打上来，在眉骨、鼻底和下唇切出硬阴影，眼窝里两点白色反光。他的瞳孔向下扫了两次，下颌松开，眼角挤出细纹，嘴角抬了半秒又收平。85mm 镜头，固定，冷蓝白，胶片颗粒。")
_c("8D", 8, "图12C_PRP-02c_后台手机_四格板.png",
   "俯拍特写，手机平放在木桌上，屏幕里的订单数字一格一格往上跳，每次跳一下屏幕就整块重绘一个节拍，数字不断替换。男人的指尖停在画面边缘的木桌上，一动不动。50mm 镜头，机位 0.7 米，俯视，胶片颗粒。")

_c("9A", 9, "图14_SCN-05_展会_九宫格.png",
   "展会现场，男人站在白色展位的高脚桌后，右手在身侧低低握着手机，眼睛从屏幕上抬起来望向远处走廊。展位顶部射灯在白色展板上打出两个硬边椭圆光斑，展馆高处的冷漫射光把走廊压成灰色，远处只有模糊的人影剪影。35mm 镜头，机位 1.6 米，平视，前景高脚桌虚化，低饱和偏青，胶片颗粒。")
_c("9B", 9, "图02_CHR-02_赵鹏_四格板.png",
   "长焦压缩的走廊，一个微胖中年男人双手抱着一只封好的牛皮纸箱朝镜头走来，走到距离展位四步的地方双脚停住，一只鞋在地毯上蹭了一下，下巴抬起来。两个人隔着走廊对视两秒，谁都不动，身后只有虚化的人影漂过。85mm 镜头，机位 1.6 米，浅景深，低饱和偏青，胶片颗粒。")
_c("9C", 9, "图12C_PRP-02c_后台手机_四格板.png",
   "双人中景，年轻男人把手里的手机转过来举到胸口高度，屏幕朝向对面的中年男人，然后微微调整角度让屏幕吃住射灯。中年男人的眼睛落到玻璃上，眉头拧紧，怀里的纸箱往下滑了一掌宽又被他颠回来。50mm 镜头，机位 1.5 米，略俯，低饱和偏青，胶片颗粒。")

_c("10A", 10, "图07_SCN-02_深夜出租屋_九宫格.png",
   "出租屋内，男人拉开椅子坐下，整个人沉进椅背，然后把手机屏幕朝下扣在桌上，用一根手指把它往远处推了一掌宽。台灯从右下打出暖黄圆形光斑，房间之外压到近黑，窗框一线冷反射。35mm 镜头，机位 1.3 米，俯十二度，胶片颗粒。")
_c("10B", 10, "图12C_PRP-02c_后台手机_四格板.png",
   "桌面近景，扣着的手机震了一下，机身离开桌面一毫米又落回去，屏幕的光从机身与桌面的缝里透出来，整块桌面被一块冷蓝白矩形照亮。手机再震一次后落平。85mm 镜头，机位 0.5 米，低角度浅景深，胶片颗粒。")
_c("10C", 10, "图01_CHR-01_陈默_四格板.png",
   "中近景，男人伸手把手机翻过来但没拿起来，转向自己，低头看屏幕。他的眼睛停止移动，下颌线绷紧，嘴角肌肉收紧，拇指悬在屏幕上空一厘米没有落下。台灯在画面外，他左脸留在阴影里。85mm 镜头，固定，冷蓝灰，胶片颗粒。")

# 键已按「段号-镜号」唯一


def submit(prompt):
    return _req("/prompt", data={"prompt": prompt, "client_id": uuid.uuid4().hex}, method="POST")


def wait(job_id, timeout=1800, interval=3):
    """轮询 /history 直到该任务完成"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            h = _req(f"/history/{job_id}")
            if isinstance(h, dict) and job_id in h:
                return h[job_id]
        except Exception:
            pass
        time.sleep(interval)
    return None


def run_clip(cid, dry=False, seed=None, width=704, height=1280,
             length=81, fps=16, steps=30, cfg=6.0):
    if cid not in CLIPS:
        print(f"  ✗ 没有这个片段：{cid}。可用：{', '.join(CLIPS)}")
        return False
    c = CLIPS[cid]
    prefix = f"ep01/seg{c['seg']:02d}_{c['jing']}"
    p = build_prompt(c["seg"], cid, c["first"], c["pos"], c["neg"], prefix,
                     seed=seed, width=width, height=height,
                     length=length, fps=fps, steps=steps, cfg=cfg)
    if dry:
        out = os.path.join(PKG, "04_脚本", f"_dry_seg{c['seg']}_{cid}.json")
        json.dump(p, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"  · [dry-run] 载荷已写出 {out}")
        return True
    r = submit(p)
    jid = r.get("prompt_id") if isinstance(r, dict) else None
    print(f"  → 已入队 {cid}  prompt_id={jid}  首帧={c['first']}")
    return jid


def cmd_run(cid, **kw):
    print(f"提交片段 {cid} …")
    jid = run_clip(cid, **kw)
    if jid and not kw.get("dry"):
        print("等待完成（Ctrl+C 可中断，任务仍在 ComfyUI 队列里继续）…")
        res = wait(jid)
        if res:
            outs = res.get("outputs", {})
            print("  ✓ 完成")
            for k, v in outs.items():
                for key in ("images", "videos", "gifs"):
                    for item in v.get(key, []):
                        print("    产出：", item.get("filename"))
        else:
            print("  ⚠ 超时未拿到结果，去 ComfyUI 界面看队列")


def cmd_run_seg(seg, **kw):
    ids = [k for k, v in CLIPS.items() if v["seg"] == seg]
    ids.sort(key=lambda k: (len(k.split("-")[1]), k.split("-")[1]))
    print(f"段{seg} 共 {len(ids)} 个片段：{ids}")
    for cid in ids:
        cmd_run(cid, **kw)


def cmd_run_all(**kw):
    segs = sorted({v["seg"] for v in CLIPS.values()})
    for s in segs:
        cmd_run_seg(s, **kw)


# ------------------------------------------------------------------ 诊断

def cmd_ping():
    print(f"目标：{BASE}")
    try:
        st = _req("/system_stats")
        sysinfo = st.get("system", {})
        print("  ✓ 在线")
        print(f"    ComfyUI 版本 : {sysinfo.get('comfyui_version', '?')}")
        print(f"    Python       : {sysinfo.get('python_version', '?')}")
        print(f"    显存总量/空闲: {sysinfo.get('vram_total', 0)/1e9:.1f} GB / {sysinfo.get('vram_free', 0)/1e9:.1f} GB")
    except Exception as e:
        print("  ✗", e)
        return
    try:
        oi = _req("/object_info")
        print(f"    可用节点数   : {len(oi)}")
        need = ["UNETLoader", "CLIPLoader", "VAELoader", "CLIPVisionLoader",
                "CLIPVisionEncode", "WanImageToVideo", "ModelSamplingSD3",
                "KSampler", "VAEDecode", "CreateVideo", "SaveVideo", "LoadImage"]
        miss = [n for n in need if n not in oi]
        print(f"    工作流所需节点: {'全部存在 ✓' if not miss else '缺 ' + str(miss)}")
        # 模型清单
        for k, label in [("UNETLoader", "unet_name"), ("CLIPLoader", "clip_name"),
                         ("VAELoader", "vae_name"), ("CLIPVisionLoader", "clip_name")]:
            if k in oi:
                opts = oi[k]["input"].get("required", {}).get(label, [[]])[0]
                print(f"    {k}.{label}: {opts[:6]}{' …' if len(opts) > 6 else ''}")
    except Exception as e:
        print("    （节点信息读取失败）", e)


def cmd_queue():
    q = _req("/queue")
    run = q.get("queue_running", [])
    pend = q.get("queue_pending", [])
    print(f"正在跑 {len(run)} 个，排队 {len(pend)} 个")
    for item in run[:5]:
        print("  running:", item[1] if len(item) > 1 else item)
    for item in pend[:10]:
        print("  pending:", item[1] if len(item) > 1 else item)


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description="重生之我在做亚马逊 · 第01集 ComfyUI 批量出片")
    ap.add_argument("--host", default=None, help="ComfyUI 地址，默认 127.0.0.1:8188")
    ap.add_argument("--ping", action="store_true", help="检查连接与模型")
    ap.add_argument("--queue", action="store_true", help="查看队列")
    ap.add_argument("--upload-assets", action="store_true", help="上传 18 张资产图到 input")
    ap.add_argument("--run", metavar="CLIP", help="跑单个片段，如 1A / 6B / 10C")
    ap.add_argument("--run-seg", type=int, metavar="N", help="跑某一整段，如 8")
    ap.add_argument("--run-all", action="store_true", help="跑全集 26 个片段")
    ap.add_argument("--dry", action="store_true", help="只生成 JSON 载荷不出图")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=704)
    ap.add_argument("--length", type=int, default=81)
    ap.add_argument("--fps", type=int, default=16)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--cfg", type=float, default=6.0)
    a = ap.parse_args()

    global HOST, BASE
    if a.host:
        HOST = a.host
        BASE = f"http://{HOST}"

    kw = dict(dry=a.dry, seed=a.seed, width=a.width, height=a.height,
              length=a.length, fps=a.fps, steps=a.steps, cfg=a.cfg)

    if a.ping:
        cmd_ping(); return
    if a.queue:
        cmd_queue(); return
    if a.upload_assets:
        cmd_upload_assets(); return
    if a.run:
        cmd_run(a.run, **kw); return
    if a.run_seg:
        cmd_run_seg(a.run_seg, **kw); return
    if a.run_all:
        cmd_run_all(**kw); return

    ap.print_help()


if __name__ == "__main__":
    main()
