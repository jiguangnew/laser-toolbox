from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
import importlib.util
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

BASE = Path(__file__).resolve().parent
PROCESSOR = BASE / "auto_tab.py"
if not PROCESSOR.exists():
    PROCESSOR = BASE.parent / "auto_tab.py"
VENDOR = BASE / "vendor"
if VENDOR.exists():
    sys.path.insert(0, str(VENDOR))
RUNS = BASE / "outputs" / "runs"
RUNS.mkdir(parents=True, exist_ok=True)
MAX_BYTES = 25 * 1024 * 1024

app = FastAPI(title="���⹤������Ͽڲ��԰�", docs_url=None, redoc_url=None)


def missing_runtime_packages():
    return [name for name in ("ezdxf", "matplotlib") if importlib.util.find_spec(name) is None]


@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health():
    missing = missing_runtime_packages()
    return {"ok": not missing and PROCESSOR.exists(), "processor": PROCESSOR.exists(), "missing": missing}


@app.post("/api/process")
async def process(file: UploadFile = File(...), thickness: int = Form(...)):
    missing = missing_runtime_packages()
    if missing:
        raise HTTPException(503, "�Ͽ���������δ��װ��" + ", ".join(missing) + "�������� start.bat ��ɰ�װ")
    if thickness not in (3, 5):
        raise HTTPException(400, "Ŀǰֻ֧�� 3mm �� 5mm ���")
    original_name = Path(file.filename or "drawing.dxf").name
    if Path(original_name).suffix.lower() != ".dxf":
        raise HTTPException(400, "��ǰ���԰�ֻ���� DXF��AI/CDR ���ȵ��� DXF")
    payload = await file.read(MAX_BYTES + 1)
    if not payload:
        raise HTTPException(400, "�ļ�Ϊ��")
    if len(payload) > MAX_BYTES:
        raise HTTPException(413, "�ļ����� 25MB������ѹ������")

    run_id = uuid.uuid4().hex[:12]
    folder = RUNS / run_id
    folder.mkdir(parents=True, exist_ok=False)
    source = folder / "source_original.dxf"
    output = folder / "result_test_only.dxf"
    source.write_bytes(payload)
    cmd = [sys.executable, str(PROCESSOR), str(source), "--thickness", str(thickness), "--out", str(output)]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(VENDOR) + os.pathsep + env.get("PYTHONPATH", "")
    env["MPLBACKEND"] = "Agg"
    try:
        result = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=180, env=env)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "�������� 180 �룬��ֹͣ��ԭʼ�ļ�����")

    (folder / "run.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    artifacts = []
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.name not in {"source_original.dxf", "run.log"}:
            artifacts.append({"name": path.name, "url": f"/api/file/{run_id}/{path.name}"})
    if result.returncode != 0:
        return {"ok": False, "run_id": run_id, "exit_code": result.returncode,
                "log": (result.stdout + "\n" + result.stderr)[-12000:], "artifacts": artifacts,
                "message": "����δͨ��������ֻ������ϼ�¼��δ�Ķ�ԭͼ��"}
    return {"ok": True, "run_id": run_id, "exit_code": 0,
            "log": (result.stdout + "\n" + result.stderr)[-12000:], "artifacts": artifacts,
            "message": "������ɡ����Ⱥ˶Ը���ͼ�ͱ��棻���԰����������������С�"}


@app.get("/api/file/{run_id}/{name}")
def get_file(run_id: str, name: str):
    if not re.fullmatch(r"[a-f0-9]{12}", run_id):
        raise HTTPException(404, "�ļ�������")
    if name not in {"result_test_only.dxf", "result_test_only_review.png"} and not re.fullmatch(r"result_test_only_review_detail_\d+\.png", name):
        raise HTTPException(404, "�ļ�������")
    path = RUNS / run_id / name
    if not path.is_file():
        raise HTTPException(404, "�ļ�������")
    return FileResponse(path, filename=name)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8765, reload=False)

