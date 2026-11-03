#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 ComfyUI 工作流 JSON（画布版 _ui / API 版）
只使用 ComfyUI 官方内置核心节点，避免第三方插件依赖。
"""
import json, os, copy

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "02_ComfyUI工作流")
OUT = os.path.abspath(OUT)
os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------------------- 工具

def ui_workflow(nodes, links, extra=None):
    """组装 ComfyUI 画布版工作流结构"""
    wf = {
        "last_node_id": max(n["id"] for n in nodes),
        "last_link_id": max(l[0] for l in links) if links else 0,
        "nodes": nodes,
        "links": links,
        "groups": [],
        "config": {},
        "extra": extra or {},
        "version": 0.4,
    }
    return wf


def node(nid, ntype, pos, size, inputs=None, outputs=None,
         widgets=None, title=None, color=None, bg=None):
    n = {
        "id": nid,
        "type": ntype,
        "pos": list(pos),
        "size": list(size),
        "flags": {},
        "order": nid,
        "mode": 0,
        "inputs": inputs or [],
        "outputs": outputs or [],
        "properties": {"Node name for S&R": ntype},
        "widgets_values": widgets or [],
    }
    if title:
        n["title"] = title
    if color:
        n["color"] = color
    if bg:
        n["bgcolor"] = bg
    return n


def inp(name, typ, link=None, shape=7):
    return {"name": name, "type": typ, "link": link, "shape": shape}

def outp(name, typ, links=None, slot_index=0):
    return {"name": name, "type": typ, "links": links or [], "slot_index": slot_index}

def link(lid, src, src_slot, dst, dst_slot, typ):
    return [lid, src, src_slot, dst, dst_slot, typ]


# ---------------------------------------------------------------- 工作流 01 · Wan 2.1 I2V

def build_wan_i2v():
    """
    Wan 2.1 图生视频（I2V）
    单张首帧 → 5s / 81帧 @16fps → mp4
    官方内置节点：UNETLoader / CLIPLoader / VAELoader
                  / LoadImage / CLIPVisionLoader / CLIPVisionEncode
                  / WanImageToVideo / ModelSamplingSD3
                  / KSampler / VAEDecode / CreateVideo / SaveVideo
    """
    N = {}
    L = []
    lid = [0]

    def newlink(*a):
        lid[0] += 1
        L.append(link(lid[0], *a))
        return lid[0]

    # --- 模型加载 ---
    n1 = node(1, "UNETLoader", (40, 120), (330, 82),
              outputs=[outp("MODEL", "MODEL")],
              widgets=["wan2.1_i2v_480p_14B_fp8_e4m3fn.safetensors", "default"],
              title="① Wan2.1 I2V 主模型（14B fp8）")
    n2 = node(2, "CLIPLoader", (40, 250), (330, 106),
              outputs=[outp("CLIP", "CLIP")],
              widgets=["umt5_xxl_fp8_e4m3fn_scaled.safetensors", "wan", "default"],
              title="② 文本编码器（umt5-xxl fp8）")
    n3 = node(3, "VAELoader", (40, 404), (330, 58),
              outputs=[outp("VAE", "VAE")],
              widgets=["wan_2.1_vae.safetensors"],
              title="③ VAE")
    n4 = node(4, "CLIPVisionLoader", (40, 510), (330, 58),
              outputs=[outp("CLIP_VISION", "CLIP_VISION")],
              widgets=["clip_vision_h.safetensors"],
              title="④ CLIP Vision（I2V 需要）")

    # --- 首帧图（改成你的资产图文件名） ---
    n5 = node(5, "LoadImage", (40, 616), (330, 314),
              outputs=[outp("IMAGE", "IMAGE"), outp("MASK", "MASK")],
              widgets=["图01_CHR-01_陈默_四格板.png", "image"],
              title="⑤ 首帧图 ⚠️ 每段换成对应资产/末帧截图")

    # --- CLIP Vision 编码 ---
    n6 = node(6, "CLIPVisionEncode", (420, 616), (300, 78),
              inputs=[inp("clip_vision", "CLIP_VISION"), inp("image", "IMAGE")],
              outputs=[outp("CLIP_VISION_OUTPUT", "CLIP_VISION_OUTPUT")],
              widgets=["none"],
              title="⑥ 图像视觉编码")

    # --- 正负提示词 ---
    n7 = node(7, "CLIPTextEncode", (420, 720), (400, 200),
              inputs=[inp("clip", "CLIP")],
              outputs=[outp("CONDITIONING", "CONDITIONING")],
              widgets=["""Cinematic live-action shot, cold blue-grey low-key lighting, low saturation, fine film grain, hard directional light, 16:9 widescreen. A 29-year-old Chinese man in a light grey-white cotton shirt with sleeves rolled to mid-forearm sits at a matte-white long meeting table in a dim open-plan office. He lifts his head slowly, his eyes open wide, a bead of sweat slides down his temple into his sideburn. Camera pushes in very slowly on an 85 mm lens, shallow depth of field, focus on his eyes. Natural subtle facial movement, controlled slow pacing, steady handheld breath, realistic skin texture, no digital gloss."""],
              title="⑦ 正向提示词（英文，描述运镜与动作）")
    n8 = node(8, "CLIPTextEncode", (420, 940), (400, 130),
              inputs=[inp("clip", "CLIP")],
              outputs=[outp("CONDITIONING", "CONDITIONING")],
              widgets=["still image, static, frozen frame, blurry, low quality, distorted face, extra fingers, warped hands, text overlay, watermark, logo, cartoon, anime, 3d render, oversaturated, HDR bloom"],
              title="⑧ 负向提示词")

    # --- 采样参数 ---
    n9 = node(9, "ModelSamplingSD3", (860, 120), (300, 58),
              inputs=[inp("model", "MODEL")],
              outputs=[outp("MODEL", "MODEL")],
              widgets=[8.0],
              title="⑨ Wan 推荐 shift=8.0")

    # --- I2V 条件 ---
    n10 = node(10, "WanImageToVideo", (860, 220), (300, 186),
               inputs=[inp("positive", "CONDITIONING"), inp("negative", "CONDITIONING"),
                       inp("vae", "VAE"), inp("clip_vision_output", "CLIP_VISION_OUTPUT"),
                       inp("start_image", "IMAGE")],
               outputs=[outp("positive", "CONDITIONING"), outp("negative", "CONDITIONING"),
                        outp("latent", "LATENT")],
               widgets=[81, 704, 1280, 1, 16],
               title="⑩ I2V 条件（81帧 / 704×1280 / 16fps）")

    # --- 采样 ---
    n11 = node(11, "KSampler", (1200, 120), (320, 262),
               inputs=[inp("model", "MODEL"), inp("positive", "CONDITIONING"),
                       inp("negative", "CONDITIONING"), inp("latent_image", "LATENT")],
               outputs=[outp("LATENT", "LATENT")],
               widgets=[42, "fixed", 30, 6.0, "uni_pc", "simple", 1.0],
               title="⑪ KSampler（steps30 / cfg6 / uni_pc）")

    # --- 解码 ---
    n12 = node(12, "VAEDecode", (1200, 420), (200, 46),
               inputs=[inp("samples", "LATENT"), inp("vae", "VAE")],
               outputs=[outp("IMAGE", "IMAGE")],
               title="⑫ VAE 解码")

    # --- 出片 ---
    n13 = node(13, "CreateVideo", (1200, 500), (300, 78),
               inputs=[inp("images", "IMAGE"), inp("audio", "AUDIO")],
               outputs=[outp("VIDEO", "VIDEO")],
               widgets=[16.0],
               title="⑬ 合成视频（16fps）")
    n14 = node(14, "SaveVideo", (1200, 610), (420, 400),
               inputs=[inp("video", "VIDEO")],
               widgets=["video/wan21_第01集_段01", "mp4", "h264"],
               title="⑭ 保存 mp4 ⚠️ 每段改文件名")

    # ---- 连线 ----
    l_model = newlink(1, 0, 9, 0, "MODEL")
    n1["outputs"][0]["links"] = [l_model]
    n9["inputs"][0]["link"] = l_model

    l_shift = newlink(9, 0, 11, 0, "MODEL")
    n9["outputs"][0]["links"] = [l_shift]
    n11["inputs"][0]["link"] = l_shift

    l_clip = newlink(2, 0, 7, 0, "CLIP")
    l_clip2 = newlink(2, 0, 8, 0, "CLIP")
    n2["outputs"][0]["links"] = [l_clip, l_clip2]
    n7["inputs"][0]["link"] = l_clip
    n8["inputs"][0]["link"] = l_clip2

    l_vae10 = newlink(3, 0, 10, 2, "VAE")
    l_vae12 = newlink(3, 0, 12, 1, "VAE")
    n3["outputs"][0]["links"] = [l_vae10, l_vae12]
    n10["inputs"][2]["link"] = l_vae10
    n12["inputs"][1]["link"] = l_vae12

    l_cv = newlink(4, 0, 6, 0, "CLIP_VISION")
    n4["outputs"][0]["links"] = [l_cv]
    n6["inputs"][0]["link"] = l_cv

    l_img6 = newlink(5, 0, 6, 1, "IMAGE")
    l_img10 = newlink(5, 0, 10, 4, "IMAGE")
    n5["outputs"][0]["links"] = [l_img6, l_img10]
    n6["inputs"][1]["link"] = l_img6
    n10["inputs"][4]["link"] = l_img10

    l_cvo = newlink(6, 0, 10, 3, "CLIP_VISION_OUTPUT")
    n6["outputs"][0]["links"] = [l_cvo]
    n10["inputs"][3]["link"] = l_cvo

    l_pos = newlink(7, 0, 10, 0, "CONDITIONING")
    n7["outputs"][0]["links"] = [l_pos]
    n10["inputs"][0]["link"] = l_pos

    l_neg = newlink(8, 0, 10, 1, "CONDITIONING")
    n8["outputs"][0]["links"] = [l_neg]
    n10["inputs"][1]["link"] = l_neg

    l_pos2 = newlink(10, 0, 11, 1, "CONDITIONING")
    l_neg2 = newlink(10, 1, 11, 2, "CONDITIONING")
    l_lat = newlink(10, 2, 11, 3, "LATENT")
    n10["outputs"][0]["links"] = [l_pos2]
    n10["outputs"][1]["links"] = [l_neg2]
    n10["outputs"][2]["links"] = [l_lat]
    n11["inputs"][1]["link"] = l_pos2
    n11["inputs"][2]["link"] = l_neg2
    n11["inputs"][3]["link"] = l_lat

    l_samp = newlink(11, 0, 12, 0, "LATENT")
    n11["outputs"][0]["links"] = [l_samp]
    n12["inputs"][0]["link"] = l_samp

    l_dec = newlink(12, 0, 13, 0, "IMAGE")
    n12["outputs"][0]["links"] = [l_dec]
    n13["inputs"][0]["link"] = l_dec
    n13["inputs"][1]["link"] = None

    l_vid = newlink(13, 0, 14, 0, "VIDEO")
    n13["outputs"][0]["links"] = [l_vid]
    n14["inputs"][0]["link"] = l_vid

    return ui_workflow([n1, n2, n3, n4, n5, n6, n7, n8, n9, n10, n11, n12, n13, n14], L,
                       extra={"ds": {"scale": 0.72, "offset": [0, 0]}})


# ---------------------------------------------------------------- 工作流 02 · SDXL 四格板

def build_sdxl_sheet():
    """
    SDXL 出角色四格板 / 场景九宫格 / 道具四格板
    5.76:1 超宽画布，所以先出 4 张 16:9 再拼 —— 这里给「单格出图」版本，
    拼板用 04_脚本/stitch_sheet.py 完成（比让 SDXL 一次吐四格稳得多）
    """
    N, L = [], []
    lid = [0]
    def newlink(*a):
        lid[0] += 1
        L.append(link(lid[0], *a)); return lid[0]

    n1 = node(1, "CheckpointLoaderSimple", (40, 120), (330, 98),
              outputs=[outp("MODEL", "MODEL"), outp("CLIP", "CLIP"), outp("VAE", "VAE")],
              widgets=["illustriousXL_v01.safetensors"],
              title="① 大模型（Illustrious / SDXL 系）")
    n2 = node(2, "CLIPTextEncode", (420, 120), (420, 180),
              inputs=[inp("clip", "CLIP")],
              outputs=[outp("CONDITIONING", "CONDITIONING")],
              widgets=["live-action photographic character sheet, single panel, 16:9, a 29-year-old Chinese man, natural skin texture with visible pores, cinematic low-key cold blue-grey grade, hard directional side light, fine film grain, realistic 6.5-7.5 head proportions, neutral light-grey seamless background"],
              title="② 正向提示词（单格 · 英文）")
    n3 = node(3, "CLIPTextEncode", (420, 330), (420, 110),
              inputs=[inp("clip", "CLIP")],
              outputs=[outp("CONDITIONING", "CONDITIONING")],
              widgets=["anime, cartoon, 3d render, illustration, glossy plastic skin, watermark, text, logo, extra limbs, deformed face, low quality"],
              title="③ 负向提示词")
    n4 = node(4, "EmptyLatentImage", (420, 470), (330, 106),
              outputs=[outp("LATENT", "LATENT")],
              widgets=[1376, 768, 1],
              title="④ 画布 1376×768（16:9）")
    n5 = node(5, "KSampler", (880, 120), (320, 262),
              inputs=[inp("model", "MODEL"), inp("positive", "CONDITIONING"),
                      inp("negative", "CONDITIONING"), inp("latent_image", "LATENT")],
              outputs=[outp("LATENT", "LATENT")],
              widgets=[20261103, "fixed", 28, 5.5, "dpmpp_2m", "karras", 1.0],
              title="⑤ KSampler（28步 / cfg5.5）")
    n6 = node(6, "VAEDecode", (880, 420), (200, 46),
              inputs=[inp("samples", "LATENT"), inp("vae", "VAE")],
              outputs=[outp("IMAGE", "IMAGE")])
    n7 = node(7, "SaveImage", (880, 500), (420, 420),
              inputs=[inp("images", "IMAGE")],
              widgets=["图01_陈默_面板1_面部特写"],
              title="⑥ 保存单格 ⚠️ 命名规则见说明")

    l1 = newlink(1, 0, 5, 0, "MODEL"); n1["outputs"][0]["links"] = [l1]; n5["inputs"][0]["link"] = l1
    l2 = newlink(1, 1, 2, 0, "CLIP"); l3 = newlink(1, 1, 3, 0, "CLIP")
    n1["outputs"][1]["links"] = [l2, l3]
    n2["inputs"][0]["link"] = l2; n3["inputs"][0]["link"] = l3
    l4 = newlink(1, 2, 6, 1, "VAE"); n1["outputs"][2]["links"] = [l4]; n6["inputs"][1]["link"] = l4
    l5 = newlink(2, 0, 5, 1, "CONDITIONING"); n2["outputs"][0]["links"] = [l5]; n5["inputs"][1]["link"] = l5
    l6 = newlink(3, 0, 5, 2, "CONDITIONING"); n3["outputs"][0]["links"] = [l6]; n5["inputs"][2]["link"] = l6
    l7 = newlink(4, 0, 5, 3, "LATENT"); n4["outputs"][0]["links"] = [l7]; n5["inputs"][3]["link"] = l7
    l8 = newlink(5, 0, 6, 0, "LATENT"); n5["outputs"][0]["links"] = [l8]; n6["inputs"][0]["link"] = l8
    l9 = newlink(6, 0, 7, 0, "IMAGE"); n6["outputs"][0]["links"] = [l9]; n7["inputs"][0]["link"] = l9

    return ui_workflow([n1, n2, n3, n4, n5, n6, n7], L,
                       extra={"ds": {"scale": 0.8, "offset": [0, 0]}})


# ---------------------------------------------------------------- 写盘

def to_api(wf):
    """画布版 → API 版（prompt 格式）"""
    api = {}
    for n in wf["nodes"]:
        e = {"class_type": n["type"], "inputs": {}, "_meta": {"title": n.get("title", n["type"])}}
        # widget 值
        wv = n.get("widgets_values") or []
        t = n["type"]
        if t == "UNETLoader":
            e["inputs"] = {"unet_name": wv[0], "weight_dtype": wv[1]}
        elif t == "CLIPLoader":
            e["inputs"] = {"clip_name": wv[0], "type": wv[1], "device": wv[2]}
        elif t == "VAELoader":
            e["inputs"] = {"vae_name": wv[0]}
        elif t == "CLIPVisionLoader":
            e["inputs"] = {"clip_name": wv[0]}
        elif t == "LoadImage":
            e["inputs"] = {"image": wv[0], "upload": "image"}
        elif t == "CLIPTextEncode":
            e["inputs"] = {"text": wv[0]}
        elif t == "ModelSamplingSD3":
            e["inputs"] = {"shift": wv[0]}
        elif t == "WanImageToVideo":
            e["inputs"].update({"width": wv[2], "height": wv[3], "length": wv[0],
                                "batch_size": wv[1] if isinstance(wv[1], int) else 1})
        elif t == "KSampler":
            e["inputs"].update({"seed": wv[0], "steps": wv[2], "cfg": wv[3],
                                "sampler_name": wv[4], "scheduler": wv[5], "denoise": wv[6]})
        elif t == "CreateVideo":
            e["inputs"] = {"fps": wv[0]}
        elif t == "SaveVideo":
            e["inputs"] = {"filename_prefix": wv[0], "format": wv[1], "codec": wv[2]}
        elif t == "SaveImage":
            e["inputs"] = {"filename_prefix": wv[0]}
        elif t == "EmptyLatentImage":
            e["inputs"] = {"width": wv[0], "height": wv[1], "batch_size": wv[2]}
        elif t == "CLIPVisionEncode":
            e["inputs"] = {"crop": wv[0]}
        api[str(n["id"])] = e
    # 连线
    for l in wf["links"]:
        _, src, src_slot, dst, dst_slot, typ = l
        src_n = next(n for n in wf["nodes"] if n["id"] == src)
        dst_n = next(n for n in wf["nodes"] if n["id"] == dst)
        name = dst_n["inputs"][dst_slot]["name"]
        api[str(dst)]["inputs"][name] = [str(src), src_slot]
    return api


def main():
    files = {}
    wan = build_wan_i2v()
    files["03_wan21_i2v_ui.json"] = wan
    files["03_wan21_i2v_api.json"] = to_api(wan)

    sdxl = build_sdxl_sheet()
    files["01_sdxl_manhua_t2i_ui.json"] = sdxl
    files["01_sdxl_manhua_t2i_api.json"] = to_api(sdxl)

    for fn, data in files.items():
        p = os.path.join(OUT, fn)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("写出", p, os.path.getsize(p), "bytes")


if __name__ == "__main__":
    main()
