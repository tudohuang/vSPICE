from fastapi import FastAPI, Request
from pydantic import BaseModel
from fastapi.responses import HTMLResponse
import uvicorn
import traceback

# 🚀 引入重構後的 NextSPICE 架構
from nextspice.compiler.frontend import SpiceParser
from nextspice.runtime.circuit import Circuit
from nextspice.runtime.runner import SimulationRunner # 引入大總管！
from nextspice.compiler.formatter import SpiceFormatter

app = FastAPI()

class NetlistRequest(BaseModel):
    netlist: str

@app.get("/", response_class=HTMLResponse)
async def get_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/simulate")
async def run_simulation(request: NetlistRequest):
    raw_netlist = request.netlist.strip()
    
    # 預設的回傳格式與錯誤容器
    error_response = {"status": "error", "logs": [], "plots": [], "layout": {}, "op_results": {}}

    try:
        # --- Phase 1: Compile ---
        parser = SpiceParser(content=raw_netlist)
        parsed_data = parser.compile()
        
        has_error = False
        for d in parsed_data.get("diagnostics", []):
            error_response["logs"].append(f"[{d['severity']}] Line {d.get('line', '?')}: {d['message']}")
            if d['severity'] == "ERROR": has_error = True
            
        if has_error:
            return error_response

        # --- Phase 2: Build ---
        circuit = Circuit(name="Web_Sim")
        build_res = circuit.build_from_json(parsed_data["circuit"])
        if not build_res.success:
            for err in build_res.errors: 
                error_response["logs"].append(f"[BUILD ERROR] {err}")
            return error_response

        # --- Phase 3 & 4: Dispatch & Solve (交給 Runner 處理) ---
        runner = SimulationRunner(circuit, parsed_data["circuit"])
        
        # 為了保留前面的 compile logs，我們把它預先塞進 runner 的 log 裡面
        runner.response_data["logs"] = error_response["logs"] 
        
        # 🚀 啟動大總管，直接回傳執行結果！
        return runner.run_all()

    except Exception as e:
        error_response["logs"].append(f"[ERR] API 崩潰: {str(e)}")
        traceback.print_exc()
        return error_response

@app.post("/api/format")
async def format_code(request: Request):
    data = await request.json()
    formatted_code = SpiceFormatter.format(data.get("code", ""))
    return {"code": formatted_code}