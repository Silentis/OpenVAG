import asyncio
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel
from serial.tools import list_ports

from studio.bridge import DiagnosticBridge
from studio.paths import BUNDLE_DIR, LOG_DIR

app = FastAPI(title="OpenVAG Studio")
bridge = DiagnosticBridge()


class ConnectReq(BaseModel):
    adapter: str = "mock"
    profile: str = "vag_2013"
    interface: str = "COM3"


class CodingReq(BaseModel):
    coding: str


class AdaptReq(BaseModel):
    value: str


@app.get("/")
async def index():
    return FileResponse(BUNDLE_DIR / "studio" / "static" / "index.html")


@app.get("/api/ports")
async def api_ports():
    ports = [{"device": p.device, "desc": p.description} for p in list_ports.comports()]
    return {"ports": ports}


@app.post("/api/connect")
async def api_connect(req: ConnectReq):
    try:
        return await bridge.connect(req.adapter, req.profile, req.interface)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/disconnect")
async def api_disconnect():
    await bridge.disconnect()
    return {"connected": False}


@app.get("/api/autoscan")
async def api_autoscan():
    try:
        return {"modules": await bridge.auto_scan()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/clear-all-dtcs")
async def api_clear_all():
    try:
        return await bridge.clear_all_dtcs()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/module/{addr}")
async def api_module(addr: str):
    try:
        return await bridge.open_module(addr)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/module/{addr}/dtcs")
async def api_get_dtcs(addr: str):
    return {"dtcs": await bridge.read_dtcs(addr)}


@app.delete("/api/module/{addr}/dtcs")
async def api_clear_dtcs(addr: str):
    return await bridge.clear_dtcs(addr)


@app.post("/api/module/{addr}/coding")
async def api_write_coding(addr: str, req: CodingReq):
    try:
        return await bridge.write_coding(addr, req.coding)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/module/{addr}/adaptation/{channel}")
async def api_read_adapt(addr: str, channel: str):
    try:
        return await bridge.read_adaptation(addr, channel)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/module/{addr}/adaptation/{channel}")
async def api_write_adapt(addr: str, channel: str, req: AdaptReq):
    try:
        return await bridge.write_adaptation(addr, channel, req.value)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/module/{addr}/output-test/{test_id}")
async def api_output_test(addr: str, test_id: str):
    try:
        return await bridge.run_output_test(addr, test_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/service/{action}")
async def api_service(action: str):
    try:
        return await bridge.run_service_function(action)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/backups")
async def api_backups():
    return {"backups": bridge.list_backups()}


@app.post("/api/export-log")
async def api_export_log():
    return bridge.export_session_log()


@app.get("/api/download-log/{filename}")
async def api_download_log(filename: str):
    return FileResponse(LOG_DIR / filename, filename=filename, media_type="application/jsonl")


@app.websocket("/ws/blocks/{addr}/{group}")
async def ws_blocks(websocket: WebSocket, addr: str, group: int):
    await websocket.accept()
    try:
        while True:
            data = await bridge.read_measuring_block(addr, group)
            await websocket.send_json(data)
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/trace")
async def ws_trace(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            entry = await bridge.trace_queue.get()
            await websocket.send_json(entry)
    except WebSocketDisconnect:
        pass