from fastapi import FastAPI, Request
from pydantic import BaseModel
from fastapi.responses import HTMLResponse
import uvicorn
import traceback

from nextspice.compiler.frontend import SpiceParser
from nextspice.runtime.circuit import Circuit
from nextspice.runtime.runner import SimulationRunner
from nextspice.compiler.formatter import SpiceFormatter
import json
app = FastAPI()

VERSION = "1.4.1"
SUPPORTED_ELEMENTS = {
    "R": "Resistor", "C": "Capacitor", "L": "Inductor",
    "V": "Voltage Source", "I": "Current Source", "D": "Diode",
    "E": "VCVS", "G": "VCCS", "H": "CCVS", "F": "CCCS",
    "K": "Mutual Inductance", "X": "Subcircuit Call","Q":"BJT"
}
SUPPORTED_ANALYSES = [".OP", ".TRAN", ".AC", ".DC", ".SENS"]
SUPPORTED_DIRECTIVES = [".MODEL", ".OPTIONS", ".PRINT", ".PROBE", ".MEAS", ".MEASURE", ".FOUR", ".STEP", ".SUBCKT", ".ENDS", ".PARAM", ".END"]
SUPPORTED_WAVEFORMS = ["SIN", "PULSE", "PWL"]

class NetlistRequest(BaseModel):
    netlist: str

@app.get("/", response_class=HTMLResponse)
async def get_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/version")
async def get_version():
    return {
        "version": VERSION,
        "engine": "NextSPICE",
        "elements": len(SUPPORTED_ELEMENTS),
        "analyses": SUPPORTED_ANALYSES,
    }

@app.get("/api/elements")
async def get_elements():
    return {
        "elements": [{"prefix": k, "name": v} for k, v in SUPPORTED_ELEMENTS.items()],
        "waveforms": SUPPORTED_WAVEFORMS,
    }

@app.post("/api/netlist-info")
async def get_netlist_info(request: NetlistRequest):
    raw = request.netlist.strip()
    try:
        parser = SpiceParser(content=raw)
        parsed = parser.compile()
        circ = parsed.get("circuit", {})
        elements = circ.get("elements", [])
        analyses = circ.get("analyses", [])
        subcircuits = circ.get("subcircuits", [])
        nodes = set()
        for el in elements:
            for k in ("n1", "n2", "n_pos", "n_neg", "n_out_pos", "n_out_neg", "n_ctrl_pos", "n_ctrl_neg"):
                v = el.get(k)
                if v is not None and str(v) != "0":
                    nodes.add(str(v))
        prefix_counts = {}
        for el in elements:
            p = el.get("name", "?")[0].upper()
            prefix_counts[p] = prefix_counts.get(p, 0) + 1
        return {
            "status": "ok",
            "nodes": len(nodes),
            "elements": len(elements),
            "analyses": [a.get("type", "?").upper() for a in analyses],
            "element_summary": prefix_counts,
            "subcircuits": len(subcircuits) if subcircuits else 0,
            "diagnostics": len(parsed.get("diagnostics", [])),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/simulate")
async def run_simulation(request: NetlistRequest):
    raw_netlist = request.netlist.strip()
    error_response = {"status": "error", "logs": [], "plots": [], "layout": {}, "op_results": {}}

    try:
        parser = SpiceParser(content=raw_netlist)
        parsed_data = parser.compile()

        has_error = False
        for d in parsed_data.get("diagnostics", []):
            error_response["logs"].append(f"[{d['severity']}] Line {d.get('line', '?')}: {d['message']}")
            if d['severity'] == "ERROR": has_error = True

        if has_error:
            return error_response

        circuit = Circuit(name="Web_Sim")
        build_res = circuit.build_from_json(parsed_data["circuit"])
        if not build_res.success:
            for err in build_res.errors:
                error_response["logs"].append(f"[BUILD ERROR] {err}")
            return error_response

        runner = SimulationRunner(circuit, parsed_data["circuit"])
        runner.response_data["logs"] = error_response["logs"]
        final_result = runner.run_all()
        with open("debug_dump.json", "w", encoding="utf-8") as f:
            json.dump(final_result, f, indent=4, ensure_ascii=False)
        return final_result

    except Exception as e:
        error_response["logs"].append(f"[ERR] API 崩潰: {str(e)}")
        traceback.print_exc()
        return error_response

@app.post("/api/format")
async def format_code(request: Request):
    data = await request.json()
    formatted_code = SpiceFormatter.format(data.get("code", ""))
    return {"code": formatted_code}