# Low2High · 高帧视频处理器（本地版）

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/platform-Windows-0078D6.svg" alt="Platform">
  <img src="https://img.shields.io/badge/ffmpeg-9.0.1-green.svg" alt="ffmpeg">
  <img src="https://img.shields.io/badge/GPU-NVENC-76b900.svg" alt="GPU">
</p>

把低帧视频（30/24fps）通过 **运动补偿插帧** 提升到 60/90/120fps，并叠加一层
**防限流伪装**，让输出看起来像手机原生拍摄，而不是机器批量生成的。

> 🔒 **纯本地运行 · 不上传 · 无需登录 · 无需付费**
> 所有处理都在你自己的电脑上完成，视频文件不会离开本机。

---

## ✨ 功能特性

- **运动补偿插帧**：基于 ffmpeg `minterpolate`（MCI + OBMC + 双向预测），把 30/60fps 提升到 60/90/120fps
- **防限流伪装**：清除机器指纹（元数据、编码器标签、规整 GOP、均匀帧时），叠加极轻传感器噪声与微幅色彩偏移，让视频"像手机拍的"
- **4K 保真模式**：切换 H.264 Level 5.2 + 高码率（40~80 Mbps），上传后仍是真 4K，骗过平台 4K 审核
- **GPU 加速（NVENC）**：有 N 卡时自动切换 `h264_nvenc` 硬件编码，比 CPU 软编码快 4~6 倍
- **完整信息展示**：上传后即刻显示原视频完整参数并可预览；处理完成后显示输出参数并可预览成片、对比
- **智能跳过插帧**：源帧率已 ≥ 目标帧率时只做伪装转码（速度快 10 倍、无鬼影）
- **可选输出目录**：默认 `~/Downloads`，可手动指定

---

## 🤔 为什么需要伪装

短视频平台现在的"伪原创"检测会识别机器生成视频的特征。直接 `minterpolate`
插帧的视频虽然帧数上去了，但有明显的机器指纹会被限流。本工具在 **保住高帧效果**
的同时，消除这些指纹：

| 机器指纹 | 伪装手段 |
|---|---|
| 编码器标签 `Lavf/ffmpeg` | `-map_metadata -1` + `-fflags +bitexact` 清除全部元数据 |
| 画面过于干净无传感器噪声 | 叠加极轻 sensor noise（肉眼不可见） |
| 色彩曲线"数字感" | 微幅亮度/对比/饱和偏移 |
| GOP 关键帧结构规整 | 每次随机 `-g` 间隔 |
| 帧时间绝对均匀 | 随机化容器 timescale，模拟自然 VFR |
| 帧率元数据与流不符 | `-fps_mode cfr` 让声明帧率 == 实际流帧率 |

---

## 🎬 4K 模式（保真 4K + 骗过平台 4K 审核）

需要保持 4K 画质时，勾选界面上的 **「4K 模式」**（源视频本身已是 4K 也会自动启用）。
它切换一组 4K 安全的编码参数：

| 参数 | 普通模式 | 4K 模式 |
|---|---|---|
| H.264 Level | 4.0（仅支持到 1080p） | **5.2**（4K60 合法等级） |
| 视频码率 | CRF 控制（4K 下会被压低） | **40~80 Mbps 目标 + CRF16~20 下限** |
| 分辨率 | 原样保留 | 原样保留（3840×2160 实测通过） |
| 音频 | AAC 128k/44.1k | AAC 192k/48k |

实测输出：`3840×2160 @ 60fps`，Level 5.2，视频码率 ~87 Mbps ——
分辨率真 4K、码率过门槛，不会被压成"伪 4K"。

> ⚠️ 4K 真插帧（源 30fps 提 60/120fps）非常吃 CPU。短片段尚可，长视频请在空闲时处理。

---

## 🚀 安装与运行

### 环境要求

- **Windows 10/11**（本工具内置 ffmpeg Windows 版，无需自行安装）
- **Python 3.10+**
- （可选）**NVIDIA 显卡 + 最新驱动**：用于 NVENC 硬件编码加速

### 步骤

```bash
# 1. 克隆仓库
git clone https://github.com/xmgzxmgz/low2high-tool.git
cd low2high-tool

# 2. 创建并激活虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate

# 3. 安装依赖
pip install flask

# 4. 启动
启动.bat          # 或直接： python app.py
```

启动后浏览器自动打开 **http://127.0.0.1:5000**。

> 仓库已内置 `ffmpeg_dist/`（ffmpeg 9.0.1 Windows essentials 版，含 `h264_nvenc`）。
> 程序启动时会自动在 `ffmpeg_dist` 与系统 `PATH` 中查找 ffmpeg/ffprobe。

---

## 🖥️ 使用流程

1. 打开网页，拖入视频（支持 mp4 / mov / mkv / avi / webm）
2. **上传后立即显示「原视频信息」**，左侧可预览原片
3. 选目标帧率（60 / 90 / 120）
4. 选画质（快速 / 均衡 / 高质量）
5. 需要 4K 就勾 **「4K 模式」**；有 N 卡就勾 **「GPU 加速（NVENC）」**
6. 点「开始处理」，处理完成后在「处理后信息」卡片预览成片、对比参数并下载

> 💡 **最佳实践**：如果你源视频本身已是 59~60fps（如手机拍摄），直接选 **60fps + 勾 4K模式 +
> 勾 GPU**，会跳过插帧、只做伪装转码——几秒出片、无鬼影、对平台展示无差异。
> 选 90/120fps 会触发真插帧（慢、可能鬼影），仅在确实需要更高展示帧率时使用。

> ⚠️ 上传平台时**直接选本地视频，不要加任何剪辑/滤镜/变速**，否则平台会重新编码丢掉高帧。

---

## ⚡ GPU 加速（NVENC）

有 **NVIDIA 显卡**（RTX 等，驱动装好）时，勾选 **「GPU 加速（NVENC）」** 即把视频编码从
CPU 软编码（`libx264`）切换到显卡硬件编码（`h264_nvenc`），编码速度提升 **4~6 倍**。

> ⚠️ **硬限制**：`minterpolate` 运动补偿插帧 **没有 GPU 实现，永远跑 CPU**。
> GPU 只加速"编码"这一步。选比源更高的帧率（如源 60fps 选 120fps 触发真插帧）时，
> 插帧仍在 CPU 上跑，GPU 仅加速后续编码。
> **最快方案 = 源 60fps 选 60fps（跳过插帧）+ 开 GPU 编码**，纯伪装转码，几秒搞定。

实测（RTX 5060 Ti / 驱动 610.88，4 秒 4K@60 片段，跳过插帧模式）：

| 编码方式 | 耗时 | 提速 |
|---|---|---|
| CPU（libx264） | 13.0 秒 | 基准 |
| **GPU（h264_nvenc）** | **2.5 秒** | **约 5.2 倍** |

输出均为 `3840×2160 @ 60fps`，4K 保留。无 N 卡或检测不到 `h264_nvenc` 时自动回退 CPU。

---

## 📊 性能参考

插帧是 CPU 密集型运算，越长越慢；GPU 仅加速编码段。

| 场景 | 耗时参考 |
|---|---|
| 纯伪装转码（源 60fps 选 60fps 跳过插帧，4K 片段） | CPU 约 13 秒 / **GPU 约 2.5 秒** |
| 真插帧（源 30fps 提 60fps，4K 片段） | CPU 插帧约 110 秒，长视频请在空闲时处理 |

---

## 🏗️ 技术架构

```
low2high-tool/
├── 启动.bat            # Windows 一键启动脚本
├── app.py              # Flask 本地 Web UI（上传 / 进度轮询 / 信息展示 / 预览）
├── engine.py           # ffmpeg 处理引擎（插帧 + 伪装 + 4K + GPU）
├── ffmpeg_dist/        # 内置 ffmpeg 9.0.1（Windows essentials 版，含 nvenc）
├── .gitignore
└── README.md
```

- **前端**：原生 HTML + CSS（深色主题）+ JavaScript 轮询 `/status` 获取进度与日志
- **后端**：Flask，单进程多线程；上传文件存 `uploads/`，输出落用户指定目录
- **引擎**：`engine.py` 封装 ffmpeg 命令构建与执行；`probe` 用 ffprobe 解析视频信息；
  `build_command` 根据帧率/画质/4K/GPU 动态拼装滤镜链与编码参数；
  `process` 用 `subprocess.Popen` 流式读取 stderr 估算进度
- **预览**：`/preview/<job>?kind=src|out` 本地流式返回视频（支持 Range 断点续播）

---

## ⚖️ 免责声明

本工具仅用于**个人学习、本地视频处理与平台规则研究**。请遵守所在平台的服务条款与
当地法律法规，不要用于批量搬运、侵权或欺诈等违规用途。因使用本工具产生的任何后果
由使用者自行承担。

---

## 📄 License

[MIT](LICENSE)
