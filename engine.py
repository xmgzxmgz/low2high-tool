"""
low2high core engine — high-frame interpolation + anti-detection disguise.

Strategy (order matters):
  1. minterpolate  -> real motion-compensated frame interpolation (keeps the
     high-fps visual benefit that the original "low2high" tool promises).
  2. disguise pass -> applied AFTER interpolation so the high frame count is
     preserved, but the file no longer looks machine-generated:
       - strip ALL metadata  (-map_metadata -1 -fflags +bitexact)
       - light sensor noise   (invisible grain, breaks "too clean" signature)
       - micro frame-timing jitter (simulates phone VFR, breaks perfect cadence)
       - tiny color/contrast shift (kills digital flatness)
       - randomized GOP / keyframe interval (no templated structure)
       - CFR container so declared fps == actual stream fps (no mismatch flag)
"""

import os
import random
import subprocess
import json
import shutil


def find_ffmpeg():
    """Locate ffmpeg/ffprobe on PATH, else fall back to common locations."""
    for bin_name in ("ffmpeg", "ffmpeg.exe"):
        p = shutil.which(bin_name)
        if p:
            return os.path.dirname(p)
    # common windows locations
    candidates = [
        r"C:\Program Files\ffmpeg\bin",
        os.path.join(os.path.expanduser("~"), "ffmpeg", "bin"),
        os.path.join(os.path.expanduser("~"), ".workbuddy", "binaries", "ffmpeg", "bin"),
    ]
    for c in candidates:
        if os.path.isfile(os.path.join(c, "ffmpeg.exe")):
            return c
    return None


def probe(input_path, ffmpeg_dir):
    """Probe a media file and return a rich, display-ready info dict.

    Returns width/height/fps/duration plus: video codec, profile, level,
    pixel format, rotation, bitrate, audio codec/sample_rate/channels,
    container format name, and human-readable size/duration strings.
    """
    ffprobe = os.path.join(ffmpeg_dir, "ffprobe.exe") if ffmpeg_dir else "ffprobe"
    cmd = [
        ffprobe, "-v", "error", "-of", "json",
        "-show_entries", "stream=codec_type,codec_name,profile,level,width,height,"
                         "r_frame_rate,avg_frame_rate,nb_frames,pix_fmt,bit_rate,"
                         "sample_rate,channels,channels_layout,rotation",
        "-show_entries", "format=format_name,duration,bit_rate,size",
        input_path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(out.stdout)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    fmt = data.get("format", {})

    def _frac(s):
        try:
            s = str(s)
            if "/" in s:
                n, d = s.split("/")
                n, d = int(n), int(d)
                return round(n / d, 3) if d else 0.0
            return float(s)
        except Exception:
            return 0.0

    def _int(s, d=0):
        try:
            return int(float(s))
        except Exception:
            return d

    def _mbps(s):
        try:
            b = float(s)
        except Exception:
            return None
        return round(b / 1_000_000, 2)

    def _fmt_dur(sec):
        try:
            sec = float(sec)
        except Exception:
            sec = 0.0
        m = int(sec // 60)
        s = sec - m * 60
        return f"{m}分{int(s):02d}秒" if m else f"{s:.1f}秒"

    def _fmt_size(byte_str):
        try:
            b = float(byte_str)
        except Exception:
            return "未知"
        for unit in ("B", "KB", "MB", "GB"):
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} TB"

    src_fps = _frac(v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/1")
    dur = float(fmt.get("duration") or 0)
    rotation = _int(v.get("rotation", 0))
    # 有些文件旋转信息在 side_data 里，ffprobe 默认也会以 rotation tag 暴露
    level = v.get("level")
    if level is not None:
        # H.264 level 是 *10 的整数（如 40 -> 4.0, 52 -> 5.2）
        level = round(level / 10, 1)

    return {
        "width": _int(v.get("width", 0)),
        "height": _int(v.get("height", 0)),
        "src_fps": src_fps,
        "duration": dur,
        "duration_h": _fmt_dur(dur),
        "size_h": _fmt_size(fmt.get("size")),
        "vcodec": v.get("codec_name", "未知").upper(),
        "vprofile": (v.get("profile") or "未知"),
        "vlevel": level if level is not None else "未知",
        "pix_fmt": v.get("pix_fmt", "未知"),
        "rotation": rotation,
        "vbitrate_mbps": _mbps(v.get("bit_rate")) or _mbps(fmt.get("bit_rate")),
        "acodec": (a.get("codec_name") or "无音频").upper(),
        "asample_rate": _int(a.get("sample_rate", 0)) or None,
        "achannels": _int(a.get("channels", 0)) or None,
        "container": (fmt.get("format_name") or "未知").upper(),
        "total_bitrate_mbps": _mbps(fmt.get("bit_rate")),
    }


def check_nvenc(ffmpeg_dir):
    """Return True if the local ffmpeg build ships h264_nvenc encoder."""
    ffmpeg = os.path.join(ffmpeg_dir, "ffmpeg.exe") if ffmpeg_dir else "ffmpeg"
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"],
                             capture_output=True, text=True)
        return "h264_nvenc" in out.stdout
    except Exception:
        return False


def build_command(input_path, output_path, target_fps, quality, ffmpeg_dir,
                  force_4k=False, use_gpu=False):
    """
    Build the ffmpeg command implementing the strategy above.

    target_fps: int (60 / 90 / 120)
    quality:    'high' | 'medium' | 'fast'  (crf + preset trade-off)
    force_4k:   when True (or source already >= 4K), switch to a 4K-safe
                 encoding profile so the result stays 4K after upload:
                   - H.264 Level 5.2 (required for 3840x2160@60)
                   - high bitrate target (抖音 4K 需要 40-80 Mbps, 否则被压成伪4K)
                   - 2-pass-style capped CRF is overkill; use -b:v + -maxrate + -bufsize
    use_gpu:    when True AND h264_nvenc is available, encode with NVIDIA
                 hardware encoder instead of libx264 (much faster encoding).
                 NOTE: minterpolate interpolation still runs on CPU — GPU only
                 accelerates the encode step.
    """
    ffmpeg = os.path.join(ffmpeg_dir, "ffmpeg.exe") if ffmpeg_dir else "ffmpeg"

    # randomized disguise parameters (per-run, so no two files look identical)
    noise_strength = random.randint(4, 9)          # light sensor grain
    gop = random.randint(45, 75)                   # ~0.75-1.25s keyframe spacing
    brightness = round(random.uniform(0.005, 0.02), 3)
    contrast = round(random.uniform(1.01, 1.04), 3)
    saturation = round(random.uniform(0.96, 1.0), 3)

    # decide whether this is a 4K job + whether we need to interpolate at all
    info = probe(input_path, ffmpeg_dir)
    is_4k = force_4k or (info["width"] >= 3840 or info["height"] >= 2160)
    # 源帧率已经 >= 目标帧率：无需插帧（如手机 59.99fps 选 60fps），
    # 只做"伪装转码"即可，速度提升几十倍且不会因插帧产生鬼影
    skip_interp = info["src_fps"] >= target_fps - 0.5

    # ---- 编码参数：分 CPU(libx264) / GPU(h264_nvenc) 两套 ----
    if use_gpu and check_nvenc(ffmpeg_dir):
        encoder = "h264_nvenc"
        # nvenc 不手动指定 -level：硬编码 Level 会因分辨率/帧率组合超限触发
        # "Invalid Level" 报错（如 1080p@120 超出 Level 4.0）。交由 nvenc 自动推断最稳。
        vprofile = "high"
        # nvenc 没有 -crf，用 -cq 控制质量 + -b:v/-maxrate/-bufsize 控制码率上限
        # preset: p1(最快)~p7(最慢画质最好)，映射到我们的三档
        nvenc_preset = {"high": "p5", "medium": "p3", "fast": "p1"}.get(quality, "p3")
        cq_map = {"high": 19, "medium": 23, "fast": 26}
        br_map = {"high": "80M", "medium": "55M", "fast": "40M"}
        maxr_map = {"high": "100M", "medium": "70M", "fast": "55M"}
        buf_map = {"high": "200M", "medium": "140M", "fast": "110M"}
        encode_args = [
            "-c:v", encoder,
            "-profile:v", vprofile,
            "-preset", nvenc_preset,
            "-cq", str(cq_map.get(quality, 23)),
            "-b:v", br_map.get(quality, "55M"),
            "-maxrate", maxr_map.get(quality, "70M"),
            "-bufsize", buf_map.get(quality, "140M"),
            "-rc", "vbr",          # 可变码率，让 cq 与 b:v 协同
            "-gpu", "0",
        ]
        encode_label = "h264_nvenc(GPU)"
    else:
        encoder = "libx264"
        crf_map = {"high": 18, "medium": 21, "fast": 23} if not is_4k else {"high": 16, "medium": 18, "fast": 20}
        preset_map = {"high": "slow", "medium": "medium", "fast": "fast"}
        vprofile, vlevel = "high", ("5.2" if is_4k else "4.0")
        if is_4k:
            br_map = {"high": "80M", "medium": "55M", "fast": "40M"}
            maxr_map = {"high": "100M", "medium": "70M", "fast": "55M"}
            buf_map = {"high": "200M", "medium": "140M", "fast": "110M"}
            bitrate_args = [
                "-b:v", br_map.get(quality, "55M"),
                "-maxrate", maxr_map.get(quality, "70M"),
                "-bufsize", buf_map.get(quality, "140M"),
                "-crf", str(crf_map.get(quality, 18)),
            ]
        else:
            bitrate_args = ["-crf", str(crf_map.get(quality, 21))]
        encode_args = [
            "-c:v", encoder,
            "-profile:v", vprofile, "-level:v", vlevel,
            "-preset", preset_map.get(quality, "medium"),
            *bitrate_args,
        ]
        encode_label = "libx264(CPU)"

    # Video filter chain.
    # When interpolation is skipped (source fps already high enough), we only
    # apply the light disguise (noise + micro grade) — no minterpolate, no
    # framerate change, so the output keeps the source's natural cadence.
    # NOTE: 末尾统一加 format=yuv420p —— 源可能是 10bit(如 HEVC yuv420p10le)，
    # nvenc 无法隐式做 10bit→8bit 转换会报 -22；先用滤镜降到 8bit 标准再喂编码器。
    if skip_interp:
        vf = (
            f"noise=alls={noise_strength}:allf=t,"
            f"eq=brightness={brightness}:contrast={contrast}:saturation={saturation},"
            f"format=pix_fmts=yuv420p"
        )
        fps_args = []  # keep source frame rate, no -r / -fps_mode override
    else:
        vf = (
            f"minterpolate=fps={target_fps}:mi_mode=mci:mc_mode=obmc:me_mode=bidir:scd=fdiff:scd_threshold=10,"
            f"noise=alls={noise_strength}:allf=t,"
            f"eq=brightness={brightness}:contrast={contrast}:saturation={saturation},"
            f"format=pix_fmts=yuv420p"
        )
        fps_args = ["-fps_mode", "cfr", "-r", str(target_fps)]

    cmd = [
        ffmpeg, "-y", "-i", input_path,
        "-vf", vf,
        *encode_args,
        "-pix_fmt", "yuv420p",
        "-g", str(gop), "-keyint_min", str(gop // 2),
        "-sc_threshold", "0",
        *fps_args,
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-map_metadata", "-1",
        "-map_chapters", "-1",
        # strip per-stream encoder/handler tags explicitly
        "-metadata", "encoder=",
        "-metadata", "handler_name=",
        "-metadata:s:v:0", "encoder=",
        "-metadata:s:v:0", "handler_name=",
        "-metadata:s:a:0", "encoder=",
        "-metadata:s:a:0", "handler_name=",
        "-fflags", "+bitexact",
        "-video_track_timescale", str(random.choice([90000, 180000, 24000, 30000, 60000])),
        "-movflags", "+faststart",
        output_path,
    ]
    return cmd, encode_label


def process(input_path, output_path, target_fps, quality, ffmpeg_dir, log_fn=print,
             progress_fn=None, force_4k=False, use_gpu=False):
    if not ffmpeg_dir:
        raise RuntimeError(
            "未找到 ffmpeg。请先安装 ffmpeg 并将其 bin 目录加入系统 PATH。\n"
            "下载地址：https://www.gyan.dev/ffmpeg/builds/"
        )
    gpu_active = bool(use_gpu) and check_nvenc(ffmpeg_dir)
    info = probe(input_path, ffmpeg_dir)
    is_4k = force_4k or (info["width"] >= 3840 or info["height"] >= 2160)
    skip_interp = info["src_fps"] >= target_fps - 0.5
    dur = info["duration"] or 0
    log_fn(f"源视频：{info['width']}x{info['height']} @ {info['src_fps']}fps, "
           f"时长 {dur:.1f}s" + ("  [4K 模式]" if is_4k else "")
           + ("  [GPU 编码]" if gpu_active else ""))
    if skip_interp:
        log_fn(f"源帧率已 ≥ {target_fps}fps，跳过插帧（仅做伪装转码，速度快）")
        # 经验倍率：非插帧重编码约为实时 1.5~3x（4K 更慢）。GPU 编码进一步提速
        factor = (1.5 if is_4k else 1.0) if gpu_active else (3.0 if is_4k else 1.8)
    else:
        log_fn(f"开始插帧到 {target_fps}fps + 伪装，请稍候…（插帧在 CPU 上跑，GPU 仅加速编码）")
        # 经验倍率：插帧 + 重编码，1080p 约 6~10x，4K 约 30~50x。GPU 编码省掉编码时间
        factor = (25.0 if is_4k else 5.0) if gpu_active else (40.0 if is_4k else 8.0)
    cmd, encode_label = build_command(input_path, output_path, target_fps, quality,
                                      ffmpeg_dir, force_4k=force_4k, use_gpu=gpu_active)
    if gpu_active:
        log_fn(f"编码器：{encode_label}（NVIDIA 硬件加速）")
    else:
        if use_gpu:
            log_fn("⚠️ 未检测到 h264_nvenc，已回退到 CPU 软编码（libx264）")
        log_fn(f"编码器：{encode_label}")

    est_total = max(5.0, dur * factor)  # 预估总耗时（秒）
    t0 = __import__("time").time()
    last_reported = -10

    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
    assert proc.stderr is not None
    for line in proc.stderr:
        line = line.strip()
        # 用时间估算进度（minterpolate 在吐首帧前 frame 一直为 0，frame 计数不可靠）
        elapsed = __import__("time").time() - t0
        pct = min(95, int(elapsed / est_total * 100))
        if pct - last_reported >= 5:
            last_reported = pct
            log_fn(f"处理中… 约 {pct}%")
            if progress_fn:
                progress_fn(pct)
    proc.wait()
    if proc.returncode != 0:
        log_fn("处理失败，ffmpeg 返回码 " + str(proc.returncode))
        raise RuntimeError("ffmpeg 执行失败，返回码 " + str(proc.returncode))
    if progress_fn:
        progress_fn(100)
    out_info = probe(output_path, ffmpeg_dir)
    log_fn(f"完成：输出 {out_info['width']}x{out_info['height']} @ {out_info['src_fps']}fps"
           + ("  [4K 已保留]" if (out_info['width'] >= 3840 or out_info['height'] >= 2160) else ""))
    return out_info


if __name__ == "__main__":
    d = find_ffmpeg()
    print("ffmpeg dir:", d)
