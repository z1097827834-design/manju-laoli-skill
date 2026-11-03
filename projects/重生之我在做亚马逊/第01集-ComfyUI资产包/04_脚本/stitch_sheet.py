#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四格板 / 九宫格 拼板脚本（纯标准库，无需 PIL）

为什么要拼：ComfyUI 的 SDXL 出 5.76:1 超宽画布会严重失真，
所以正确做法是「先出 4 张 / 9 张 16:9 单格，再拼成整板」。
本脚本只做 PNG 的等宽高拼合 + 白色分隔线 + 可选底部信息条（留给后期贴）。

用法：
  # 四格横排（角色板 / 道具板）
  python3 stitch_sheet.py --mode 4 --out 图01_陈默_四格板.png p1.png p2.png p3.png p4.png

  # 九宫格 3×3
  python3 stitch_sheet.py --mode 9 --out 图04_九宫格.png a1.png ... a9.png

  # 带底部信息条（高 64px，留给声纹与音色标签）
  python3 stitch_sheet.py --mode 4 --bar 64 --out out.png p1..p4
"""
import argparse, os, struct, sys, zlib

# ---------------- 极简 PNG 读写（只支持 8bit RGB / RGBA，无隔行） ----------------

def read_png(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} 不是 PNG")
    pos = 8
    w = h = bitd = ctype = None
    idat = b""
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, bitd, ctype, comp, filt, inter = struct.unpack(">IIBBBBB", body)
            if bitd != 8 or inter != 0 or ctype not in (2, 6):
                raise ValueError(f"{path}: 只支持 8bit 非隔行 RGB/RGBA（当前 bitd={bitd} ctype={ctype} interlace={inter}）")
        elif typ == b"IDAT":
            idat += body
        elif typ == b"IEND":
            break
        pos += 12 + ln
    raw = zlib.decompress(idat)
    ch = 3 if ctype == 2 else 4
    stride = w * ch
    out = bytearray(w * h * ch)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = raw[p]; p += 1
        line = bytearray(raw[p:p + stride]); p += stride
        if ft == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return w, h, ch, out


def write_png(path, w, h, ch, buf):
    ctype = 2 if ch == 3 else 6
    raw = bytearray()
    stride = w * ch
    for y in range(h):
        raw.append(0)
        raw += buf[y * stride:(y + 1) * stride]

    def chunk(typ, body):
        return (struct.pack(">I", len(body)) + typ + body
                + struct.pack(">I", zlib.crc32(typ + body) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


# ---------------- 缩放（最近邻，够用且不引入依赖） ----------------

def scale_to(w, h, ch, buf, tw, th):
    if (w, h) == (tw, th):
        return buf
    out = bytearray(tw * th * ch)
    for y in range(th):
        sy = min(h - 1, y * h // th)
        for x in range(tw):
            sx = min(w - 1, x * w // tw)
            si = (sy * w + sx) * ch
            di = (y * tw + x) * ch
            out[di:di + ch] = buf[si:si + ch]
    return out


# ---------------- 粘贴 ----------------

def blit(dst, dw, dh, ch, src, sw, sh, ox, oy):
    for y in range(sh):
        dy = oy + y
        if dy < 0 or dy >= dh:
            continue
        si = y * sw * ch
        di = (dy * dw + ox) * ch
        dst[di:di + sw * ch] = src[si:si + sw * ch]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--mode", type=int, choices=[1, 2, 4, 9], default=4,
                    help="1=单张 2=双列 4=四格横排 9=九宫格")
    ap.add_argument("--cell-w", type=int, default=688)
    ap.add_argument("--cell-h", type=int, default=384)
    ap.add_argument("--gap", type=int, default=6, help="格间白线宽度")
    ap.add_argument("--bar", type=int, default=0, help="底部信息条高度（0=不加）")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    need = a.mode
    if len(a.images) < need:
        sys.exit(f"mode={a.mode} 需要 {need} 张图，只给了 {len(a.images)} 张")

    cols, rows = {1: (1, 1), 2: (2, 1), 4: (4, 1), 9: (3, 3)}[a.mode]
    cw, ch_, gap = a.cell_w, a.cell_h, a.gap
    W = cols * cw + (cols + 1) * gap
    H = rows * ch_ + (rows + 1) * gap + a.bar

    canvas = bytearray(b"\xff" * (W * H * 3))  # 白底

    for idx, path in enumerate(a.images[:need]):
        w, h, c, buf = read_png(path)
        if c == 4:  # RGBA → RGB（丢弃 alpha，模板要求实底）
            rgb = bytearray(w * h * 3)
            for i in range(w * h):
                rgb[i * 3:i * 3 + 3] = buf[i * 4:i * 4 + 3]
            buf, c = rgb, 3
        buf = scale_to(w, h, 3, buf, cw, ch_)
        r, cc = divmod(idx, cols)
        ox = gap + cc * (cw + gap)
        oy = gap + r * (ch_ + gap)
        blit(canvas, W, H, 3, buf, cw, ch_, ox, oy)

    write_png(a.out, W, H, 3, canvas)
    print(f"✓ {a.out}  {W}×{H}  比例 {W/H:.3f}  ({cols}×{rows} 格)")


if __name__ == "__main__":
    main()
