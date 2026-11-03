# 《重生之我在做亚马逊》第01集 · ComfyUI 操作手册

> 目标：用**本地 ComfyUI + Wan 2.1**，把这 18 张资产图变成第01集 100 秒成片。
> 全程不需要任何第三方插件，只用 ComfyUI 官方内置节点。

---

## 〇 · 先看这张图，搞清楚在哪一步

```
18 张资产图（现成）
      │
      ├─→【阶段A】补格子：把四格板/九宫格拆成单格，或直接当首帧用
      │
      ├─→【阶段B】Wan 2.1 I2V：单张首帧 → 5 秒动态片段（26 个片段）
      │
      ├─→【阶段C】截末帧：每个片段末帧 → 下一片段的 ImageToVideo 续写
      │
      ├─→【阶段D】补帧：16fps → 24fps（ffmpeg 一行）
      │
      └─→【阶段E】剪辑：26 段拼成 100 秒，裁掉每段末 1 秒定格
```

**你现在有**：阶段 A 之前的 18 张资产图 + 全部提示词。
**你缺的**：ComfyUI 环境 + Wan 2.1 模型权重 + 一段空闲的显卡时间。

---

## 一 · 环境准备（三件事，缺一不可）

### 1.1 装 ComfyUI

```bash
# 推荐 ComfyUI 0.3.x 以上（CreateVideo / SaveVideo 是较新节点）
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

启动：
```bash
python main.py --listen 127.0.0.1 --port 8188
```
浏览器打开 `http://127.0.0.1:8188` 能看到画布就成功了。

### 1.2 下载 Wan 2.1 模型（四个文件，缺一个就跑不起来）

| 文件 | 放哪 | 大小参考 | 作用 |
|---|---|:--:|---|
| `wan2.1_i2v_480p_14B_fp8_e4m3fn.safetensors` | `ComfyUI/models/diffusion_models/` | ~16 GB | 主模型 |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `ComfyUI/models/text_encoders/` | ~6.7 GB | 文本编码器 |
| `wan_2.1_vae.safetensors` | `ComfyUI/models/vae/` | ~250 MB | VAE |
| `clip_vision_h.safetensors` | `ComfyUI/models/clip_vision/` | ~1.2 GB | I2V 必需的图像编码器 |

> 显存 16 GB 以下跑不动 14B。**16 GB 显卡请换 `wan2.1_i2v_480p_14B_fp8` 并开 `--lowvram`**；8 GB 只能跑 1.3B 版本，画质会明显下降。

### 1.3 自检（先跑这一步，别急着出片）

```bash
cd 第01集-ComfyUI资产包/04_脚本
python3 run_comfy_batch.py --ping
```

正常输出长这样：
```
目标：http://127.0.0.1:8188
  ✓ 在线
    ComfyUI 版本 : 0.3.40
    Python       : 3.11.9
    显存总量/空闲: 24.0 GB / 21.3 GB
    可用节点数   : 428
    工作流所需节点: 全部存在 ✓
    UNETLoader.unet_name: ['wan2.1_i2v_480p_14B_fp8_e4m3fn.safetensors']
    CLIPLoader.clip_name: ['umt5_xxl_fp8_e4m3fn_scaled.safetensors']
    VAELoader.vae_name: ['wan_2.1_vae.safetensors']
    CLIPVisionLoader.clip_name: ['clip_vision_h.safetensors']
```

**看到 "缺 [...]" 或模型列表是空的，先回去补文件，不要往下走。**

---

## 二 · 阶段A · 资产图怎么进 ComfyUI

### 2.1 一键上传

```bash
python3 run_comfy_batch.py --upload-assets
```
18 张图会进 `ComfyUI/input/`，文件名保持不变（如 `图01_CHR-01_陈默_四格板.png`）。

### 2.2 手动上传（不想跑脚本）

浏览器里把图**直接拖进 ComfyUI 画布**，它会自动上传并生成一个 LoadImage 节点。

### 2.3 关键认知：四格板不是四张图

你手上的角色板是「**一张图里有四个格子**」。Wan 2.1 拿它当首帧会出问题——模型会把四格当成四个并列的人物，人物比例会崩。

**正确做法：先裁单格。**

| 用途 | 从哪张图裁 | 怎么裁 |
|---|---|---|
| 面部特写镜头 | 图1/图2/图8 的**第①格** | 按 25% 宽度裁最左一列 |
| 全身/半身镜头 | 第②③④格 | 同上 |
| 场景机位 | 图4/图7/图13/图14 的**某宫格** | 按 1/3 宽 × 1/3 高裁 |
| 道具特写 | 图5A/5B/5C/12A/12B/12C 的第①格 | 按 25% 宽度裁 |

裁图命令（ffmpeg，不用装 Python 库）：

```bash
# 四格板：裁第1格（最左 1/4）
ffmpeg -i 图01_CHR-01_陈默_四格板.png -vf "crop=iw/4:ih:0:0" 首帧_陈默_面部.png

# 四格板：裁第2格（正面全身）
ffmpeg -i 图01_CHR-01_陈默_四格板.png -vf "crop=iw/4:ih:iw/4:0" 首帧_陈默_正面.png

# 九宫格：裁第3格（第1行第3列）
ffmpeg -i 图13_SCN-04_车间_九宫格.png -vf "crop=iw/3:ih/3:iw*2/3:0" 首帧_车间_检测台.png

# 九宫格：裁第7格（第3行第1列）
ffmpeg -i 图13_SCN-04_车间_九宫格.png -vf "crop=iw/3:ih/3:0:ih*2/3" 首帧_车间_低机位.png
```

> **九宫格会带白分隔线**，裁的时候稍微往里收 3~5 像素，别把白线带进首帧：
> `crop=iw/3-8:ih/3-8:iw*2/3+4:4`

### 2.4 想自己出新的四格板？（可选）

`02_ComfyUI工作流/01_sdxl_manhua_t2i_ui.json` 是单格出图工作流。
**不要**直接让它出 5.76:1 的整板（会严重拉伸），正确流程是：

1. 用单格工作流出 **4 张 16:9**
2. 用拼板脚本合成整板：
```bash
cd 04_脚本
python3 stitch_sheet.py --mode 4 --out 图01_陈默_四格板.png p1.png p2.png p3.png p4.png
python3 stitch_sheet.py --mode 9 --bar 64 --out 图04_九宫格.png a1.png ... a9.png
```

---

## 三 · 阶段B · 跑 Wan 2.1 出片段

### 3.1 先跑一个片段验证（**强烈建议**）

```bash
python3 run_comfy_batch.py --run 8A --dry
```
这会只生成 JSON 载荷不出图，你先看一眼参数对不对。

确认无误，去掉 `--dry` 真跑：
```bash
python3 run_comfy_batch.py --run 8A
```

**一个 5 秒片段在 RTX 4090 上约 2~4 分钟**（30 步）。慢是正常的，Wan 14B 就是这个速度。

### 3.2 在 ComfyUI 界面里跑（替代方案）

不想用脚本，就手动拖工作流：

1. 把 `02_ComfyUI工作流/03_wan21_i2v_ui.json` **拖进 ComfyUI 画布**
2. 节点⑤ `LoadImage` 选你的首帧图
3. 节点⑦ 正向提示词：从 `03_提示词/ep01_wan21_prompts_zh.md` 复制对应镜头那一段
4. 节点⑧ 负向提示词：照抄手册里的负向
5. 节点⑭ 改输出文件名（如 `ep01/seg01_1A`）
6. 点 **Queue**
7. 想换随机种子就点 KSampler 的 `control_after_generate` 设为 `randomize`

### 3.3 参数速查表（工作流已预设，改之前先看这张）

| 参数 | 值 | 说明 |
|---|:--:|---|
| `length` | **81** | 帧数，81 = 5.06 秒 @16fps。**不要改成别的数**，Wan 按 4n+1 训练 |
| `width × height` | **1280 × 704** | 16:9。显存吃紧就降到 960×544 |
| `fps` | **16** | Wan 原生。24/30 靠后期补帧，不要在这里改 |
| `steps` | **30** | 20 也能出，30 更稳 |
| `cfg` | **6.0** | 1.0~8.0 合理区间；太高会过饱和 |
| `sampler` | **uni_pc** | Wan 官方推荐 |
| `scheduler` | **simple** | 同上 |
| `shift` | **8.0** | ModelSamplingSD3，Wan 的标配值 |

---

## 四 · 阶段C · 段缝怎么接（这是全集成败的关键）

### 4.1 三种接法，按场景选

| 情况 | 接法 | 具体操作 |
|---|---|---|
| **同一场景连续动作** | 末帧续写 | 上一片段末帧 → 存成 PNG → 当下一片段的 `start_image` |
| **换机位、同场景** | 重新指定首帧 | 直接用九宫格里另一格当首帧，不用末帧 |
| **换场** | 换首帧 + 换提示词 | 用新场景的资产图，提示词重写光照 |

### 4.2 末帧怎么截

**方法一：ComfyUI 里直接接 SaveImage**
把 `VAEDecode` 的输出再拉一条线到一个 `SaveImage` 节点，命名 `seg01_1A_last`。它存的是**第一批图**，不是最后一帧——所以还要加个 `ImageFromBatch` 节点取最后一帧：

```
VAEDecode → ImageFromBatch(batch_index=80, length=1) → SaveImage
```

**方法二：ffmpeg 从 mp4 截**（最简单）
```bash
ffmpeg -sseof -0.07 -i seg01_1A.mp4 -frames:v 1 -q:v 1 段1_1A_末帧.png
```
`-sseof -0.07` 表示从结尾往前 0.07 秒（16fps 下约等于最后一帧）。

### 4.3 ⚠️ 每段末 1 秒是定格，必须裁

本集的 D 锁是「① 末帧定格承接」，每段末镜的**最后 1 秒是静态定格**。
**剪辑时务必裁掉**，否则 10 段累计 10 秒死画面。

```bash
# 81 帧 @16fps = 5.06 秒，裁掉最后 1 秒 → 保留前 65 帧
ffmpeg -i seg01_1A.mp4 -vf "select='lt(n,65)',setpts=N/16/TB" -an seg01_1A_trim.mp4
```

> 段1 的 1A/1B 是铺垫镜，没有定格要求；**只有每段的最后一个片段末镜才需要裁**。

---

## 五 · 阶段D · 补帧（16fps → 24/30fps）

Wan 出的是 16fps，直接剪会卡顿。两种补法：

### 5.1 简单补帧（ffmpeg 光流法，够用）

```bash
ffmpeg -i input.mp4 -vf "minterpolate=fps=24:mi_mode=mci:mc_mode=aobmc:vsbmc=1" -c:v libx264 -crf 17 -pix_fmt yuv420p out_24fps.mp4
```

### 5.2 高质量补帧（RIFE，需要 ComfyUI 插件或独立工具）

如果你装了 `ComfyUI-Frame-Interpolation`（第三方插件），可以用它的 RIFE VFI 节点，两帧插一帧，效果比 ffmpeg 好很多。**但这属于可选插件，不是本包依赖。**

### 5.3 批量补帧

```bash
mkdir -p 补帧后
for f in ep01/*.mp4; do
  ffmpeg -i "$f" -vf "minterpolate=fps=24:mi_mode=mci:mc_mode=aobmc:vsbmc=1" \
         -c:v libx264 -crf 17 -pix_fmt yuv420p "补帧后/$(basename "$f")"
done
```

---

## 六 · 阶段E · 剪辑成 100 秒

### 6.1 26 个片段的顺序

按 `03_提示词/asset_manifest.json` 里的 clips 顺序，剪成 10 段：

```
段1  = 1A + 1B + 2A + 3A     （裁掉 3A 末 1 秒）
段2  = 2A + 2B               （裁掉 2B 末 1 秒）
段3  = 3A + 3B
段4  = 4A + 4B
段5  = 5A + 5B
段6  = 6A + 6B
段7  = 7A + 7B
段8  = 8A + 8B + 8C + 8D
段9  = 9A + 9B + 9C
段10 = 10A + 10B + 10C
```

### 6.2 ffmpeg 拼接（无损）

```bash
# 每段先写进一个列表文件
cat > seg1.txt <<EOF
file 'ep01/seg01_1A_trim.mp4'
file 'ep01/seg01_1B_trim.mp4'
file 'ep01/seg01_2A_trim.mp4'
file 'ep01/seg01_3A_trim.mp4'
EOF
ffmpeg -f concat -safe 0 -i seg1.txt -c copy ep01_seg1.mp4
```

然后 10 段再拼一次，得到 100 秒成片。

### 6.3 配音与 BGM

配音**不要**在 ComfyUI 里做。本集的 `CreateVideo` 节点留了 `audio` 输入口，如果你已经有音轨可以直接接进去；没有就走后期：

```bash
# 视频 + 独立音轨合并
ffmpeg -i ep01_full.mp4 -i ep01_voice.wav -c:v copy -c:a aac -shortest ep01_final.mp4
```

台词表见 `第01集-投喂稿.md` 各段的「台词」标注，开口顺序是：
段1 陈默 OS → 段2 陈默 → 段3 赵鹏 → 段4 陈默 OS → 段5 苏晚 → 段6 陈默 → 段7 陈默 OS → 段8 无 → 段9 陈默 → 段10 陈默。

---

## 七 · 常见问题（出问题先查这张）

| 现象 | 原因 | 解决 |
|---|---|---|
| `连不上 ComfyUI` | 没启动，或端口不是 8188 | 跑 `python main.py --port 8188`，再用 `--ping` 验 |
| `UNETLoader 找不到模型` | 文件名不对或放错目录 | `--ping` 看它读到的列表，按列表里的名字改 |
| 出图是全黑 / 全噪 | `start_image` 没接上 | 检查 WanImageToVideo 的 `start_image` 输入有没有连线 |
| 人物脸崩 / 变成四张脸 | 首帧用的是**四格板整板** | 先裁单格！见 2.3 |
| 视频只有 1 秒 | `length` 被人改过 | 改回 81，Wan 只认 4n+1 |
| 显存爆（OOM） | 14B + 1280×704 太高 | 降到 960×544，或启动加 `--lowvram` |
| 运动幅度太小 | Wan 对静态首帧很保守 | 提示词里明确写动作动词（"猛地抬头""一把抓起"），别写"保持不动" |
| 画面糊 / 抖动 | steps 太低 | 20 → 30 |
| 颜色过饱和 | cfg 太高 | 6.0 → 4.5 |
| 出来的动作方向反了 | 提示词缺左右/朝向 | 补上"从画面右侧伸进来""向左转头" |
| 末帧截图带进度条 | 截到 UI 了 | 用 ffmpeg 从 mp4 截，不要截屏 |

---

## 八 · 时间与算力估算

| 环节 | 数量 | 单件耗时（RTX 4090） | 合计 |
|---|:--:|:--:|:--:|
| 26 个片段生成 | 26 | 2~4 分钟 | **1~1.7 小时** |
| 补帧 16→24fps | 26 | 20~40 秒 | 10~17 分钟 |
| 剪辑拼接 | 2 轮 | — | 20 分钟 |
| **合计** | | | **约 2 小时** |

> RTX 3060 12G 大约慢 3~4 倍，一集约 6~8 小时。建议**先跑段1 和段8**（一个是开场、一个是爆点），验证画风和节奏，再批量跑剩下的。

---

## 九 · 本集的三条铁律（不遵守必翻车）

1. **首帧只能放单格，不能放整板。** 四格板/九宫格是给「看」和「选」的，不是给 Wan 当输入帧的。
2. **每段末 1 秒是定格，剪辑必须裁。** 10 段不裁 = 10 秒死画面。
3. **换场段不要用上一场的末帧当首帧。** 段4/6/7/9/10 都是换场，末帧只用来参考人物姿态，空间必须换新图。
