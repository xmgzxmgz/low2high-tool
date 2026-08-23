"""
low2high web UI — local Flask server.

Run:  python app.py
Then open the printed http://127.0.0.1:5000 in your browser.

Pure local: no network upload, no login, no payment.
"""

import os
import threading
import uuid

from flask import Flask, render_template_string, request, jsonify, send_file
from werkzeug.utils import secure_filename

import engine

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2 GB

# per-job progress store
JOBS = {}

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
# 默认导出到用户下载目录
DEFAULT_OUTPUT = os.path.join(os.path.expanduser("~"), "Downloads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DEFAULT_OUTPUT, exist_ok=True)


def info_to_rows(info):
    """Turn a probe dict into a list of (label, value) rows for display."""
    rows = [
        ("分辨率", f"{info.get('width','?')} × {info.get('height','?')}"),
        ("帧率", f"{info.get('src_fps','?')} fps"),
        ("时长", info.get("duration_h", "未知")),
        ("文件大小", info.get("size_h", "未知")),
        ("视频编码", f"{info.get('vcodec','?')}  ({info.get('vprofile','?')} / Level {info.get('vlevel','?')})"),
        ("像素格式", info.get("pix_fmt", "未知")),
        ("视频码率", (f"{info.get('vbitrate_mbps')} Mbps" if info.get("vbitrate_mbps") else "未知")),
        ("旋转", (f"{info.get('rotation')}°" if info.get("rotation") else "无")),
        ("音频编码", info.get("acodec", "无")),
    ]
    if info.get("asample_rate"):
        rows.append(("音频采样率", f"{info.get('asample_rate')} Hz"))
    if info.get("achannels"):
        rows.append(("声道数", f"{info.get('achannels')}"))
    rows.append(("容器格式", info.get("container", "未知")))
    if info.get("total_bitrate_mbps"):
        rows.append(("总码率", f"{info.get('total_bitrate_mbps')} Mbps"))
    return rows


def build_info_html(info):
    rows = info_to_rows(info)
    trs = "".join(
        f"<tr><td class='k'>{k}</td><td class='v'>{v}</td></tr>" for k, v in rows
    )
    return f"<table class='itbl'>{trs}</table>"


PAGE = """
<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Low2High · 高帧视频处理器</title>
<style>
  :root { --bg:#0e1116; --card:#161b22; --acc:#2ea043; --txt:#e6edf3; --mut:#8b949e; --blue:#58a6ff; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:"Microsoft YaHei",system-ui,sans-serif;
         background:var(--bg); color:var(--txt); font-size:15px; line-height:1.5; }
  .wrap { max-width:780px; margin:0 auto; padding:24px 16px 48px; }
  h1 { font-size:21px; margin:0 0 4px; }
  .sub { color:var(--mut); font-size:13px; margin-bottom:18px; }
  .card { background:var(--card); border:1px solid #21262d; border-radius:12px;
          padding:18px; margin-bottom:14px; }
  label { display:block; font-size:13px; color:var(--mut); margin:14px 0 6px; }
  input[type=text] { width:100%; padding:10px; border-radius:8px;
         border:1px solid #30363d; background:#0d1117; color:var(--txt); font-size:14px; }
  .row { display:flex; gap:10px; align-items:stretch; }
  .row > div { flex:1; }
  .browse { flex:0 0 auto; padding:10px 14px; border-radius:8px; border:1px solid #30363d;
         background:#0d1117; color:var(--txt); cursor:pointer; font-size:13px; white-space:nowrap; }
  .browse:hover { border-color:var(--acc); }
  .fps-group button, .qual-group button {
     flex:1; padding:10px; border-radius:8px; border:1px solid #30363d;
     background:#0d1117; color:var(--txt); cursor:pointer; font-size:14px; }
  .fps-group button.active, .qual-group button.active {
     background:var(--acc); border-color:var(--acc); color:#fff; font-weight:bold; }
  .fps-group, .qual-group { display:flex; gap:8px; }
  .chk { display:flex; align-items:center; gap:8px; font-size:13px; color:var(--txt);
         cursor:pointer; margin:14px 0 2px; }
  .chk input { width:16px; height:16px; accent-color:var(--acc); }
  .drop { border:2px dashed #30363d; border-radius:10px; padding:24px; text-align:center;
          color:var(--mut); cursor:pointer; transition:.15s; }
  .drop.hover { border-color:var(--acc); color:var(--txt); }
  .btn { width:100%; padding:13px; border:0; border-radius:9px; background:var(--acc);
         color:#fff; font-size:15px; font-weight:bold; cursor:pointer; margin-top:14px; }
  .btn:disabled { opacity:.5; cursor:not-allowed; }
  .logbox { background:#0d1117; border-radius:8px; padding:12px; height:160px;
         overflow:auto; font-family:Consolas,monospace; font-size:12px;
         white-space:pre-wrap; color:#9da7b3; }
  .pbar { height:8px; background:#21262d; border-radius:4px; overflow:hidden; margin-top:10px; }
  .pbar > i { display:block; height:100%; width:0%; background:var(--acc); transition:width .4s; }
  .ok { color:var(--acc); }
  .bad { color:#f85149; }
  a.dl { color:var(--blue); text-decoration:none; }

  /* info table */
  .itbl { width:100%; border-collapse:collapse; font-size:13.5px; margin-top:6px; }
  .itbl td { padding:8px 10px; border-bottom:1px solid #21262d; }
  .itbl .k { color:var(--mut); width:38%; }
  .itbl .v { color:var(--txt); }
  .vwrap { display:flex; gap:14px; flex-wrap:wrap; }
  .vwrap video { width:100%; max-height:300px; background:#000; border-radius:8px; }
  .tag4k { display:inline-block; background:#1f6feb22; color:var(--blue);
           border:1px solid #1f6feb55; border-radius:6px; padding:1px 8px; font-size:12px; margin-left:6px; }
  .muted { color:var(--mut); font-size:13px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Low2High · 高帧视频处理器</h1>
  <div class="sub">本地运行 · 不上传 · 无需登录付费 · 插帧 + 防限流伪装</div>

  <div class="card">
    <div id="drop" class="drop">点击或拖拽视频到此处<br>（mp4 / mov / mkv / avi / webm）</div>
    <input id="file" type="file" accept="video/*" hidden>
    <div id="fname" style="font-size:13px;color:var(--mut);margin-top:8px;"></div>
  </div>

  <div class="card" id="srcCard" style="display:none">
    <label>原视频信息</label>
    <div class="vwrap">
      <div style="flex:1; min-width:260px;">
        <video id="srcVideo" controls preload="metadata"></video>
      </div>
      <div style="flex:1; min-width:260px;" id="srcInfo"><span class="muted">解析中…</span></div>
    </div>
  </div>

  <div class="card">
    <label>目标帧率</label>
    <div class="fps-group" id="fps">
      <button data-v="60" class="active">60 fps</button>
      <button data-v="90">90 fps</button>
      <button data-v="120">120 fps</button>
    </div>
    <label>画质</label>
    <div class="qual-group" id="qual">
      <button data-v="fast">快速</button>
      <button data-v="medium" class="active">均衡</button>
      <button data-v="high">高质量</button>
    </div>
    <label class="chk"><input id="f4k" type="checkbox"> 4K 模式（保真 4K + 高码率，骗过抖音 4K 审核）</label>
    <label class="chk"><input id="fgpu" type="checkbox" checked> GPU 加速（NVIDIA NVENC 硬件编码，比 CPU 软编码快数倍）</label>
    <label>输出目录（默认下载目录，可点击浏览修改）</label>
    <div class="row">
      <div><input id="outdir" type="text" value="{{ default_out }}"></div>
      <button class="browse" id="browse">浏览…</button>
    </div>
    <button id="run" class="btn">开始处理</button>
    <div class="pbar" id="pbar" style="display:none"><i id="pfill"></i></div>
  </div>

  <div class="card" id="outCard" style="display:none">
    <label>处理后信息</label>
    <div class="vwrap">
      <div style="flex:1; min-width:260px;">
        <video id="outVideo" controls preload="metadata"></video>
        <div style="margin-top:8px;"><a class="dl" id="dlLink" href="#">下载结果视频</a></div>
      </div>
      <div style="flex:1; min-width:260px;" id="outInfo"><span class="muted">等待处理完成…</span></div>
    </div>
  </div>

  <div class="card">
    <label>处理日志</label>
    <div id="log" class="logbox">就绪。</div>
    <div id="result"></div>
  </div>
</div>

<script>
let sel = { fps:60, qual:'medium', file:null };
const $=id=>document.getElementById(id);

$('fps').onclick=e=>{ if(e.target.dataset.v){ [...$('fps').children].forEach(b=>b.classList.remove('active'));
  e.target.classList.add('active'); sel.fps=+e.target.dataset.v; } };
$('qual').onclick=e=>{ if(e.target.dataset.v){ [...$('qual').children].forEach(b=>b.classList.remove('active'));
  e.target.classList.add('active'); sel.qual=e.target.dataset.v; } };

const drop=$('drop');
drop.onclick=()=>$('file').click();
$('file').onchange=e=>{ if(e.target.files[0]) setFile(e.target.files[0]); };
['dragover','dragenter'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add('hover');}));
['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('hover');}));
drop.ondrop=e=>{ if(e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]); };
function setFile(f){ sel.file=f; $('fname').textContent='已选择：'+f.name+' （'+(f.size/1048576).toFixed(1)+' MB）'; }

// 浏览按钮：用隐藏 file input 选目录（Chrome 支持 webkitdirectory）
$('browse').onclick=()=>{
  const d=document.createElement('input'); d.type='file'; d.webkitdirectory=true;
  d.onchange=()=>{ if(d.files[0]){ const p=d.files[0].webkitRelativePath.split('/')[0];
    if(window.showDirectoryPicker){ pickDir(); } else { alert('当前浏览器不支持选目录，请直接粘贴路径'); } } };
  d.click();
};
async function pickDir(){
  try{ const h=await window.showDirectoryPicker(); $('outdir').value=h.name ? (h.name) : $('outdir').value;
    alert('已选择目录：'+h.name+'\\n（如路径不完整，请直接手动粘贴完整路径）'); }
  catch(e){ /* 用户取消 */ }
}

// 日志：全量重绘，避免重复追加刷屏
let lastLogs=[];
function renderLogs(logs){
  if(JSON.stringify(logs)===JSON.stringify(lastLogs)) return;
  lastLogs=logs;
  $('log').textContent = logs.join('\\n');
  $('log').scrollTop = $('log').scrollHeight;
}

// 上传文件 -> 拿到 job 后先请求原视频信息并展示预览
$('run').onclick=async()=>{
  if(!sel.file){ alert('请先选择视频'); return; }
  lastLogs=[]; $('result').innerHTML='';
  $('srcCard').style.display='none'; $('outCard').style.display='none';
  $('run').disabled=true; $('pbar').style.display='block'; $('pfill').style.width='0%';
  renderLogs(['▶ 上传中…']);
  const fd=new FormData(); fd.append('file',sel.file);
  fd.append('fps',sel.fps); fd.append('qual',sel.qual); fd.append('outdir',$('outdir').value);
  fd.append('force4k', $('f4k').checked ? '1' : '0');
  fd.append('gpu', $('fgpu').checked ? '1' : '0');
  const r=await fetch('/process',{method:'POST',body:fd});
  const j=await r.json();
  if(j.error){ renderLogs(['❌ '+j.error]); $('pbar').style.display='none'; $('run').disabled=false; return; }
  showSrcInfo(j);
  poll(j.job);
};

function showSrcInfo(j){
  $('srcCard').style.display='block';
  $('srcVideo').src = '/preview/'+j.job+'?kind=src';
  $('srcInfo').innerHTML = j.src_info_html || '<span class="muted">无法解析信息</span>';
}

function poll(job){
  fetch('/status/'+job).then(r=>r.json()).then(j=>{
    renderLogs(j.logs||[]);
    if(j.progress) $('pfill').style.width=j.progress+'%';
    if(j.done){ $('pbar').style.display='none'; $('run').disabled=false;
      if(j.ok){ $('pfill').style.width='100%';
        showOutInfo(j);
        $('result').innerHTML='<p class="ok">✅ 处理完成</p>'; }
      else { $('result').innerHTML='<p class="bad">❌ 处理失败，请查看日志</p>'; } }
    else setTimeout(()=>poll(job),1000);
  });
}

function showOutInfo(j){
  $('outCard').style.display='block';
  $('outVideo').src = '/preview/'+j.job+'?kind=out';
  $('dlLink').href = '/download/'+j.job;
  $('outInfo').innerHTML = j.out_info_html || '<span class="muted">无法解析信息</span>';
}
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(PAGE, default_out=DEFAULT_OUTPUT)


@app.route("/process", methods=["POST"])
def process():
    f = request.files.get("file")
    if not f:
        return jsonify(error="未收到文件")
    try:
        fps = int(request.form.get("fps", 60))
    except ValueError:
        return jsonify(error="帧率参数错误")
    qual = request.form.get("qual", "medium")
    outdir = request.form.get("outdir", DEFAULT_OUTPUT).strip() or DEFAULT_OUTPUT
    force_4k = request.form.get("force4k", "0") in ("1", "true", "on")
    use_gpu = request.form.get("gpu", "0") in ("1", "true", "on")

    # 校验输出目录：不存在则尝试创建，失败回退到下载目录
    if not os.path.isdir(outdir):
        try:
            os.makedirs(outdir, exist_ok=True)
        except Exception:
            outdir = DEFAULT_OUTPUT
    if not os.access(outdir, os.W_OK):
        outdir = DEFAULT_OUTPUT

    job = uuid.uuid4().hex[:10]
    ext = os.path.splitext(secure_filename(f.filename))[1] or ".mp4"
    src = os.path.join(UPLOAD_FOLDER, job + ext)
    f.save(src)

    base = os.path.splitext(secure_filename(f.filename))[0] or "video"
    out_name = f"{base}_{fps}fps.mp4"
    out_path = os.path.join(outdir, out_name)
    # 防覆盖
    if os.path.exists(out_path):
        out_path = os.path.join(outdir, f"{base}_{fps}fps_{job}.mp4")

    # 解析原视频信息（上传后即可展示，无需等待处理）
    ff_dir = engine.find_ffmpeg()
    try:
        src_info = engine.probe(src, ff_dir)
    except Exception as e:
        src_info = {"error": str(e)}
    src_info_html = build_info_html(src_info) if "error" not in src_info else \
        f"<span class='muted'>解析失败：{src_info['error']}</span>"

    JOBS[job] = {"logs": ["▶ 已接收文件，准备处理…"], "done": False, "ok": False,
                 "output": out_path, "src": src, "progress": 0,
                 "src_info": src_info, "out_info": None}

    def worker():
        try:
            out_info = engine.process(src, out_path, fps, qual, ff_dir,
                           log_fn=lambda m: JOBS[job]["logs"].append(m),
                           progress_fn=lambda p: JOBS[job].__setitem__("progress", p),
                           force_4k=force_4k, use_gpu=use_gpu)
            JOBS[job]["out_info"] = out_info
            JOBS[job]["ok"] = True
            JOBS[job]["progress"] = 100
        except Exception as e:
            JOBS[job]["logs"].append(f"❌ 错误：{e}")
        finally:
            JOBS[job]["done"] = True

    threading.Thread(target=worker, daemon=True).start()
    return jsonify(job=job, src_info_html=src_info_html)


@app.route("/status/<job>")
def status(job):
    j = JOBS.get(job, {})
    out_info = j.get("out_info")
    out_info_html = build_info_html(out_info) if out_info else ""
    return jsonify(logs=j.get("logs", []), done=j.get("done", False),
                   ok=j.get("ok", False), output=j.get("output", ""),
                   progress=j.get("progress", 0),
                   out_info_html=out_info_html)


@app.route("/preview/<job>")
def preview(job):
    """Stream the source or the processed video for in-page preview.

    kind=src -> original uploaded file
    kind=out -> processed output file
    """
    j = JOBS.get(job, {})
    kind = request.args.get("kind", "src")
    p = j.get("src") if kind == "src" else j.get("output")
    if p and os.path.isfile(p):
        return send_file(p, mimetype="video/mp4", conditional=True)
    return "文件不存在", 404


@app.route("/download/<job>")
def download(job):
    j = JOBS.get(job, {})
    p = j.get("output")
    if p and os.path.isfile(p):
        return send_file(p, as_attachment=True)
    return "文件不存在", 404


if __name__ == "__main__":
    print("Low2High 已启动，请在浏览器打开： http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
