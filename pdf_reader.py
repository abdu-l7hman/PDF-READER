"""
PDF Reader — Split View (PDF left, Text+Audio right)
=====================================================
Requirements:
    pip install pypdf flask pydub

ffmpeg (optional, for gapless merge):
    Windows: winget install ffmpeg
    Mac:     brew install ffmpeg
    Linux:   sudo apt install ffmpeg

Usage:
    python pdf_reader.py
"""

import sys, os, io, base64, tempfile, threading, argparse, traceback
import urllib.parse, urllib.request
from pathlib import Path

try:
    from flask import Flask, request, jsonify
except ImportError:
    print("Missing: pip install flask"); sys.exit(1)

try:
    from pypdf import PdfReader
except ImportError:
    print("Missing: pip install pypdf"); sys.exit(1)

try:
    from pydub import AudioSegment
    PYDUB_OK = True
except ImportError:
    PYDUB_OK = False

app = Flask(__name__)

# ─── Google Translate TTS ──────────────────────────────────────────────────
GTTS_URL  = "https://translate.googleapis.com/translate_tts"
MAX_CHARS = 190

def tts_fetch(text: str, lang: str) -> bytes:
    params = urllib.parse.urlencode({"client":"gtx","ie":"UTF-8","tl":lang,"q":text})
    req = urllib.request.Request(f"{GTTS_URL}?{params}", headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()

def chunk_text(text: str, max_len=MAX_CHARS):
    words, chunks, cur, length = text.split(), [], [], 0
    for w in words:
        if length + len(w) + 1 > max_len:
            if cur: chunks.append(" ".join(cur))
            cur, length = [w], len(w)
        else:
            cur.append(w); length += len(w)+1
    if cur: chunks.append(" ".join(cur))
    return chunks

def build_merged_audio(text: str, lang: str) -> bytes:
    chunks = chunk_text(text)
    parts  = []
    for i, chunk in enumerate(chunks):
        print(f"  TTS {i+1}/{len(chunks)}: {chunk[:55]}...")
        try:
            parts.append(tts_fetch(chunk, lang))
        except Exception as e:
            print(f"  TTS error: {e}")
    if not parts:
        return b""
    if PYDUB_OK:
        try:
            combined = AudioSegment.empty()
            for p in parts:
                combined += AudioSegment.from_file(io.BytesIO(p), format="mp3")
            buf = io.BytesIO()
            combined.export(buf, format="mp3")
            print("  Merged with pydub OK")
            return buf.getvalue()
        except Exception as e:
            print(f"  pydub failed ({e}), raw concat fallback")
    print("  Using raw MP3 concat")
    return b"".join(parts)

# ─── PDF helpers ───────────────────────────────────────────────────────────
def extract_text(pdf_path: str, start: int, end) -> str:
    reader = PdfReader(pdf_path)
    total  = len(reader.pages)
    end    = min(int(end), total) if end else total
    start  = max(1, int(start))
    return "\n".join(p.extract_text() or "" for p in reader.pages[start-1:end])

# ─── Flask routes ──────────────────────────────────────────────────────────
UPLOAD_DIR = Path(tempfile.gettempdir()) / "pdf_reader_ui"
UPLOAD_DIR.mkdir(exist_ok=True)

@app.route("/")
def index():
    return HTML_PAGE

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f    = request.files["file"]
    dest = UPLOAD_DIR / f.filename
    f.save(dest)
    # Also return base64 of the PDF so the browser can render it
    pdf_b64 = base64.b64encode(dest.read_bytes()).decode()
    return jsonify({"path": str(dest), "name": f.filename, "pdf_b64": pdf_b64})

@app.route("/read", methods=["POST"])
def read():
    data  = request.json
    path  = data.get("path","")
    start = data.get("start", 1)
    end   = data.get("end", None)
    if not os.path.isfile(path):
        return jsonify({"error": f"File not found: {path}"}), 404
    text = extract_text(path, start, end)
    if not text.strip():
        return jsonify({"error": "No extractable text found (scanned PDF?)."}), 400
    return jsonify({"text": text})

@app.route("/audio", methods=["POST"])
def audio():
    data = request.json
    text = data.get("text","")
    lang = data.get("lang","en")
    if not text.strip():
        return jsonify({"error": "No text provided"}), 400
    try:
        mp3 = build_merged_audio(text, lang)
        if not mp3:
            return jsonify({"error": "Audio generation failed"}), 500
        return jsonify({"audio": base64.b64encode(mp3).decode()})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ─── HTML ──────────────────────────────────────────────────────────────────
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>PDF Reader</title>
<link href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,600;1,400&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/>
<style>
:root{
  --bg:#0e0f13;--surface:#16181f;--card:#1c1e27;--border:#2a2d3a;
  --accent:#f5a623;--accent2:#e8834a;--text:#d4cfc8;--muted:#6b6a72;
  --hi-bg:#f5a62340;--hi:#f5c040;--r:10px;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body{background:var(--bg);color:var(--text);font-family:'Lora',Georgia,serif;display:flex;flex-direction:column;}

/* ── Top bar ── */
.topbar{
  display:flex;align-items:center;gap:14px;padding:10px 18px;
  background:var(--card);border-bottom:1px solid var(--border);
  flex-shrink:0;flex-wrap:wrap;
}
.topbar h1{font-size:1.15rem;font-weight:600;color:#fff;white-space:nowrap}
.topbar h1 span{color:var(--accent)}
.upload-zone{
  border:1.5px dashed var(--border);border-radius:7px;
  padding:6px 14px;cursor:pointer;position:relative;
  transition:.2s;white-space:nowrap;
}
.upload-zone:hover{border-color:var(--accent);background:#f5a6230a}
.upload-zone input{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%}
.uz-label{color:var(--muted);font-size:.78rem;font-family:'JetBrains Mono',monospace}
.uz-name{color:var(--accent);font-size:.75rem;font-family:'JetBrains Mono',monospace;max-width:180px;overflow:hidden;text-overflow:ellipsis}
.field{display:flex;flex-direction:column;gap:3px}
.field label{font-family:'JetBrains Mono',monospace;font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
input[type=number],select{
  background:var(--surface);border:1px solid var(--border);border-radius:5px;
  color:var(--text);padding:5px 8px;font-family:'JetBrains Mono',monospace;font-size:.8rem;width:80px;
}
select{width:105px}
.btn{padding:7px 16px;border-radius:6px;border:none;cursor:pointer;
  font-family:'JetBrains Mono',monospace;font-size:.75rem;font-weight:600;transition:.15s;white-space:nowrap}
.btn-primary{background:var(--accent);color:#0e0f13}
.btn-primary:hover{background:var(--accent2)}
.btn-primary:disabled{opacity:.4;cursor:not-allowed}
.btn-ghost{background:transparent;border:1px solid var(--border);color:var(--muted)}
.btn-ghost:hover{border-color:var(--accent);color:var(--accent)}
.status-bar{
  font-family:'JetBrains Mono',monospace;font-size:.7rem;color:var(--muted);
  padding:5px 18px;background:var(--surface);border-bottom:1px solid var(--border);
  flex-shrink:0;min-height:24px;transition:color .2s;
}
.status-bar.loading{color:var(--accent)}
.status-bar.error{color:#e05c5c}
.status-bar.ok{color:#6bcb77}

/* ── Main split layout ── */
.main{display:flex;flex:1;overflow:hidden;min-height:0}

/* ── Left: PDF viewer ── */
.pdf-panel{
  width:50%;min-width:300px;flex-shrink:0;
  border-right:2px solid var(--border);
  display:flex;flex-direction:column;background:var(--surface);
}
.panel-title{
  font-family:'JetBrains Mono',monospace;font-size:.65rem;text-transform:uppercase;
  letter-spacing:.12em;color:var(--muted);padding:8px 14px;
  border-bottom:1px solid var(--border);background:var(--card);flex-shrink:0;
}
#pdfFrame{
  flex:1;width:100%;border:none;background:#525659;
}
.pdf-placeholder{
  flex:1;display:flex;align-items:center;justify-content:center;
  flex-direction:column;gap:10px;color:var(--muted);
}
.pdf-placeholder .icon{font-size:3rem;opacity:.3}
.pdf-placeholder p{font-size:.85rem;font-style:italic}

/* ── Right: text + audio ── */
.right-panel{
  flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0;
}

/* text area */
.text-panel{
  flex:1;overflow-y:auto;padding:20px 22px;
  line-height:1.9;font-size:1rem;word-break:break-word;
  scroll-behavior:smooth;
}
.text-panel::-webkit-scrollbar{width:4px}
.text-panel::-webkit-scrollbar-thumb{background:var(--border);border-radius:99px}
.text-empty{color:var(--muted);font-style:italic;font-size:.9rem;margin-top:40px;text-align:center}

.word{display:inline;border-radius:3px;transition:background .08s,color .08s;padding:0 1px}
.word.active{background:var(--hi-bg);color:var(--hi);font-weight:600}

/* audio dock */
.audio-dock{
  flex-shrink:0;border-top:1px solid var(--border);
  background:var(--card);padding:12px 18px;
}
.player-row{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
audio{flex:1;min-width:180px;height:34px;accent-color:var(--accent)}
.speed-group{display:flex;align-items:center;gap:6px}
.speed-label{font-family:'JetBrains Mono',monospace;font-size:.68rem;color:var(--muted)}
.prog{height:3px;background:var(--border);border-radius:99px;overflow:hidden;margin-top:8px}
.prog-fill{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));width:0%;transition:width .12s}

/* resizer */
.resizer{
  width:5px;background:var(--border);cursor:col-resize;flex-shrink:0;
  transition:background .15s;
}
.resizer:hover,.resizer.dragging{background:var(--accent)}
</style>
</head>
<body>

<!-- Top bar -->
<div class="topbar">
  <h1>PDF <span>Reader</span></h1>

  <div class="upload-zone">
    <input type="file" id="fileInput" accept=".pdf"/>
    <div class="uz-label">📂 Upload PDF</div>
    <div class="uz-name" id="fileName">No file selected</div>
  </div>

  <div class="field"><label>Start pg</label>
    <input type="number" id="startPage" value="1" min="1"/></div>
  <div class="field"><label>End pg</label>
    <input type="number" id="endPage" placeholder="last" min="1"/></div>
  <div class="field"><label>Lang</label>
    <select id="langSelect">
      <option value="en">English</option>
      <option value="ar">Arabic</option>
      <option value="fr">French</option>
      <option value="es">Spanish</option>
      <option value="de">German</option>
      <option value="zh">Chinese</option>
      <option value="ja">Japanese</option>
      <option value="ru">Russian</option>
      <option value="tr">Turkish</option>
      <option value="hi">Hindi</option>
    </select></div>

  <button class="btn btn-primary" id="loadBtn" onclick="loadPDF()">▶ Read</button>
  <button class="btn btn-ghost"   onclick="resetAll()">✕ Reset</button>
</div>

<!-- Status bar -->
<div class="status-bar" id="status">Ready — upload a PDF to begin.</div>

<!-- Main layout -->
<div class="main" id="mainLayout">

  <!-- Left: PDF viewer -->
  <div class="pdf-panel" id="pdfPanel">
    <div class="panel-title">📄 Original PDF</div>
    <div class="pdf-placeholder" id="pdfPlaceholder">
      <div class="icon">📄</div>
      <p>PDF will appear here after upload</p>
    </div>
    <iframe id="pdfFrame" style="display:none"></iframe>
  </div>

  <!-- Drag resizer -->
  <div class="resizer" id="resizer"></div>

  <!-- Right: text + audio -->
  <div class="right-panel">
    <div class="text-panel" id="textPanel">
      <div class="text-empty" id="textEmpty">Extracted text will appear here after loading.</div>
    </div>

    <div class="audio-dock" id="audioDock" style="display:none">
      <div class="player-row">
        <audio id="audioPlayer" controls></audio>
        <div class="speed-group">
          <span class="speed-label">Speed</span>
          <select onchange="document.getElementById('audioPlayer').playbackRate=+this.value" style="width:78px">
            <option value="0.75">0.75×</option>
            <option value="1" selected>1×</option>
            <option value="1.25">1.25×</option>
            <option value="1.5">1.5×</option>
            <option value="2">2×</option>
          </select>
        </div>
      </div>
      <div class="prog"><div class="prog-fill" id="progFill"></div></div>
    </div>
  </div>

</div>

<script>
// ── State ──────────────────────────────────────────────────────────────────
let uploadedPath = null, wordSpans = [], audioDur = 0, lastIdx = -1;

// ── Upload ─────────────────────────────────────────────────────────────────
document.getElementById('fileInput').addEventListener('change', async e => {
  const file = e.target.files[0];
  if (!file) return;
  document.getElementById('fileName').textContent = file.name;

  const fd = new FormData(); fd.append('file', file);
  setStatus('Uploading…','loading');
  try {
    const res  = await fetch('/upload',{method:'POST',body:fd});
    const data = await res.json();
    if (data.error){setStatus(data.error,'error');return;}
    uploadedPath = data.path;
    setStatus('Uploaded: ' + data.name + ' — click ▶ Read to begin.','ok');

    // Show PDF in left panel via data URI
    showPDF(data.pdf_b64);
  } catch(err){ setStatus('Upload failed: '+err.message,'error'); }
});

function showPDF(b64){
  const frame = document.getElementById('pdfFrame');
  const ph    = document.getElementById('pdfPlaceholder');
  frame.src   = 'data:application/pdf;base64,' + b64;
  frame.style.display = 'block';
  ph.style.display    = 'none';
}

// ── Load & process ─────────────────────────────────────────────────────────
async function loadPDF(){
  if (!uploadedPath){setStatus('Please upload a PDF first.','error');return;}
  const start = document.getElementById('startPage').value;
  const end   = document.getElementById('endPage').value || null;
  const lang  = document.getElementById('langSelect').value;
  document.getElementById('loadBtn').disabled = true;

  // 1. Extract text
  setStatus('Extracting text…','loading');
  let text;
  try {
    const res  = await fetch('/read',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({path:uploadedPath,start,end})});
    const data = await res.json();
    if(data.error){setStatus(data.error,'error');document.getElementById('loadBtn').disabled=false;return;}
    text = data.text;
  } catch(err){setStatus('Error: '+err.message,'error');document.getElementById('loadBtn').disabled=false;return;}

  renderText(text);

  // 2. Generate audio
  setStatus('Generating merged audio… ⏳','loading');
  try {
    const res  = await fetch('/audio',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text,lang})});
    const data = await res.json();
    if(!res.ok||data.error){setStatus(data.error||'Audio failed.','error');
      document.getElementById('loadBtn').disabled=false;return;}

    const binary = atob(data.audio);
    const bytes  = new Uint8Array(binary.length);
    for(let i=0;i<binary.length;i++) bytes[i]=binary.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([bytes],{type:'audio/mpeg'}));

    const player = document.getElementById('audioPlayer');
    player.src = url;
    player.onloadedmetadata = () => { audioDur = player.duration; };
    player.ontimeupdate = onTimeUpdate;
    document.getElementById('audioDock').style.display = 'block';
    setStatus('✓ Ready — press play to listen','ok');
  } catch(err){setStatus('Audio error: '+err.message,'error');}

  document.getElementById('loadBtn').disabled = false;
}

// ── Render words ───────────────────────────────────────────────────────────
function renderText(text){
  wordSpans = [];
  const panel = document.getElementById('textPanel');
  document.getElementById('textEmpty').style.display = 'none';
  // Clear old word spans but keep the empty hint
  panel.querySelectorAll('.word').forEach(el=>el.remove());
  panel.querySelectorAll('br,#textContent').forEach(el=>el.remove());

  const container = document.createElement('div');
  container.id = 'textContent';
  panel.appendChild(container);

  text.split(/(\s+)/).forEach(tok => {
    if(/^\s+$/.test(tok)){
      container.appendChild(document.createTextNode(tok));
    } else {
      const span = document.createElement('span');
      span.className = 'word';
      span.textContent = tok;
      container.appendChild(span);
      wordSpans.push(span);
    }
  });
}

// ── Word highlighting ──────────────────────────────────────────────────────
function onTimeUpdate(){
  const player = document.getElementById('audioPlayer');
  if(!audioDur||!wordSpans.length) return;
  const progress = player.currentTime / audioDur;
  const idx = Math.min(Math.floor(progress * wordSpans.length), wordSpans.length-1);
  if(idx===lastIdx) return;
  if(lastIdx>=0&&wordSpans[lastIdx]) wordSpans[lastIdx].classList.remove('active');
  wordSpans[idx].classList.add('active');
  wordSpans[idx].scrollIntoView({block:'nearest',behavior:'smooth'});
  lastIdx = idx;
  document.getElementById('progFill').style.width = (progress*100)+'%';
}

// ── Helpers ────────────────────────────────────────────────────────────────
function setStatus(msg,type=''){
  const el=document.getElementById('status');
  el.textContent=msg; el.className='status-bar '+type;
}

function resetAll(){
  uploadedPath=null; wordSpans=[]; lastIdx=-1; audioDur=0;
  document.getElementById('fileName').textContent='No file selected';
  document.getElementById('fileInput').value='';
  document.getElementById('pdfFrame').style.display='none';
  document.getElementById('pdfFrame').src='';
  document.getElementById('pdfPlaceholder').style.display='flex';
  document.getElementById('audioDock').style.display='none';
  document.getElementById('textEmpty').style.display='block';
  const tc=document.getElementById('textContent');
  if(tc) tc.remove();
  const p=document.getElementById('audioPlayer'); p.pause(); p.src='';
  document.getElementById('progFill').style.width='0%';
  setStatus('Ready — upload a PDF to begin.');
}

// ── Drag-to-resize splitter ────────────────────────────────────────────────
(function(){
  const resizer  = document.getElementById('resizer');
  const pdfPanel = document.getElementById('pdfPanel');
  const layout   = document.getElementById('mainLayout');
  let dragging = false, startX = 0, startW = 0;

  resizer.addEventListener('mousedown', e => {
    dragging = true; startX = e.clientX; startW = pdfPanel.offsetWidth;
    resizer.classList.add('dragging');
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';
  });
  document.addEventListener('mousemove', e => {
    if(!dragging) return;
    const delta = e.clientX - startX;
    const total = layout.offsetWidth;
    const newW  = Math.max(200, Math.min(total - 250, startW + delta));
    pdfPanel.style.width = newW + 'px';
  });
  document.addEventListener('mouseup', () => {
    dragging = false;
    resizer.classList.remove('dragging');
    document.body.style.userSelect = '';
    document.body.style.cursor = '';
  });
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    import webbrowser
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=5050, type=int)
    args = parser.parse_args()
    port = int(os.environ.get("PORT", args.port))
    url = f"http://127.0.0.1:{port}"
    print(f"\n📖 PDF Reader → {url}\n")
    from waitress import serve
    serve(app, host="0.0.0.0", port=port)