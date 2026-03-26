import numpy as np
import traceback
import math
from .solver import Simulator

class SimulationRunner:
    """
    NextSPICE 分析排程總管 (Dispatcher)
    負責處理 .STEP 掃描、調度各項分析 (.OP, .TRAN, .AC 等)，並將結果打包成統一格式。
    這包邏輯獨立於 Web API，可供 CLI 或 Desktop App 直接呼叫。
    """
    def __init__(self, circuit, circuit_json):
        self.circuit = circuit
        self.circuit_json = circuit_json
        self.response_data = {"status": "success", "logs": [], "plots": [], "layout": {}, "op_results": {}}

    def log(self, msg):
        self.response_data["logs"].append(msg)

    def safe_num(self, val):
        try:
            v = float(val)
            return 0.0 if math.isnan(v) or math.isinf(v) else v
        except:
            return 0.0

    def run_all(self):
        try:
            analyses = self.circuit_json.get("analyses", [])
            step_config = self.circuit_json.get("step_config")

            if not analyses:
                self.log("[WARN] 找不到任何分析指令 (.OP, .TRAN, .AC, .DC, .SENS)")
                return self.response_data

            nodes_to_plot = [name for name in self.circuit.node_mgr.mapping.keys() if name != "0"]

            step_values = [None] 
            target_el = None
            orig_val = None

            if step_config:
                target_name = step_config["target"]
                target_el = next((e for e in self.circuit.elements if e.name.upper() == target_name), None)
                
                if target_el:
                    orig_val = getattr(target_el, 'value', getattr(target_el, 'dc_value', None))
                    start, stop, step_sz = step_config["start"], step_config["stop"], step_config["step"]
                    if step_sz == 0: step_sz = 1e-9
                    step_values = np.arange(start, stop + step_sz/2, step_sz).tolist()
                    self.log(f"[STEP] 掃描 {target_name}: {start} 到 {stop}，共 {len(step_values)} 步")
                else:
                    self.log(f"[ERR] .STEP 找不到元件 {target_name}，退回單次模擬。")

            # 🌟 外層終極大迴圈
            for step_val in step_values:
                suffix = "" 
                
                if target_el is not None and step_val is not None:
                    if hasattr(target_el, 'value'): target_el.value = self.safe_num(step_val)
                    elif hasattr(target_el, 'dc_value'): target_el.dc_value = self.safe_num(step_val)
                    suffix = f" ({target_name}={step_val:.1e})"
                
                simulator = Simulator(self.circuit)

                for analysis in analyses:
                    atype = analysis["type"]
                    
                    if atype == "op":
                        if step_val == step_values[0]: self.log("--- .OP Analysis ---")
                        res = simulator.solve_op()
                        if res.status == "SUCCESS":
                            report = {k: self.safe_num(v) for k, v in simulator.get_full_report(res.x).items()}
                            
                            # 🍰 功率報表
                            for el in self.circuit.elements:
                                if el.name.upper().startswith('R'):
                                    n1_idx = getattr(el, 'n1', -1)
                                    n2_idx = getattr(el, 'n2', -1)
                                    v1 = res.x[n1_idx] if 0 <= n1_idx < len(res.x) else 0.0
                                    v2 = res.x[n2_idx] if 0 <= n2_idx < len(res.x) else 0.0
                                    r_val = getattr(el, 'value', 1.0)
                                    if r_val != 0:
                                        report[f"P({el.name})"] = self.safe_num(((v1 - v2) ** 2) / r_val)
                                elif el.name.upper().startswith('V'):
                                    i_val = report.get(f"I({el.name})", 0.0)
                                    v_val = getattr(el, 'dc_value', getattr(el, 'value', 0.0))
                                    report[f"P({el.name})"] = self.safe_num(v_val * i_val)

                            if step_val == step_values[0] or target_el is None:
                                self.response_data["op_results"] = report
                                for name, val in report.items():
                                    unit = "W" if name.startswith("P(") else ("A" if name.startswith("I(") else "V")
                                    self.log(f"{name:<10} | {val:>12.5e} {unit}")

                    elif atype == "tran":
                        if step_val == step_values[0]: self.log(f"--- .TRAN Analysis (0 to {analysis['tstop']*1000} ms) ---")
                        tran_results = simulator.solve_tran(analysis['tstep'], analysis['tstop'])
                        times = [self.safe_num(r["time"]) for r in tran_results if r["status"] == "SUCCESS"]
                        
                        self.response_data["layout"] = {"title": "Transient Response", "xaxis": "Time (s)", "yaxis": "Voltage (V)"}
                        for node_name in nodes_to_plot:
                            idx = self.circuit.node_mgr.mapping[node_name] - 1
                            v_data = [self.safe_num(r["x"][idx]) for r in tran_results if r["status"] == "SUCCESS"]
                            ls = "dash" if "IN" in node_name.upper() else "solid"
                            self.response_data["plots"].append({"name": f"V({node_name}){suffix}", "x": times, "y": v_data, "type": ls})

                    elif atype == "ac":
                        if step_val == step_values[0]: self.log(f"--- .AC Analysis ---")
                        ac_results = simulator.solve_ac(analysis['fstart'], analysis['fstop'], analysis['points'], analysis['sweep'])
                        freqs = [self.safe_num(r["freq"]) for r in ac_results if r["status"] == "SUCCESS"]
                        
                        self.response_data["layout"] = {"title": "AC Frequency Response", "xaxis": "Frequency (Hz)", "yaxis": "Magnitude (dB)", "is_ac": True}
                        for node_name in nodes_to_plot:
                            if 'IN' in node_name.upper(): continue
                            idx = self.circuit.node_mgr.mapping[node_name] - 1
                            v_cplx = [r["x"][idx] for r in ac_results if r["status"] == "SUCCESS"]
                            mags = [self.safe_num(20 * np.log10(np.abs(v) + 1e-20)) for v in v_cplx]
                            self.response_data["plots"].append({"name": f"Mag V({node_name}){suffix}", "x": freqs, "y": mags, "type": "solid"})

                    elif atype == "dc":
                        src = analysis["source"]
                        start, stop, swp_step = analysis["start"], analysis["stop"], analysis["step"]
                        if step_val == step_values[0]: self.log(f"--- .DC Sweep ({src}: {start} to {stop}) ---")
                        
                        dc_results = simulator.solve_dc_sweep(src, start, stop, swp_step)
                        x_vals = [self.safe_num(r["v_in"]) for r in dc_results]
                        
                        self.response_data["layout"] = {"title": f"DC Sweep ({src})", "xaxis": f"Source {src} (V)", "yaxis": "Voltage (V)"}
                        for node_name in nodes_to_plot:
                            idx = self.circuit.node_mgr.mapping[node_name] - 1
                            y_vals = [self.safe_num(r["result"].x[idx]) for r in dc_results if r["result"].status == "SUCCESS"]
                            ls = "dash" if "IN" in node_name.upper() else "solid"
                            self.response_data["plots"].append({"name": f"V({node_name}){suffix}", "x": x_vals, "y": y_vals, "type": ls})

                    elif atype == "sens":
                        if step_val == step_values[0]: self.log("--- .SENS Sensitivity Analysis ---")
                        
                        parts = analysis.get("targets", []) if isinstance(analysis.get("targets", []), list) else str(analysis.get("targets", "")).split()
                        if not parts and "target" in analysis: parts = str(analysis["target"]).split()
                        if not parts and "out" in analysis:
                            parts.append(str(analysis["out"]))
                            if "src" in analysis: parts.append(str(analysis["src"]))

                        if not parts:
                            self.log("[ERR] .SENS 無法解析目標節點！")
                            continue
                        
                        out_node = parts[0].upper().replace("V(", "").replace("I(", "").replace(")", "").strip()
                        
                        in_src = None
                        if len(parts) > 1:
                            in_src = parts[1].strip().upper()
                        else:
                            v_sources = [el.name for el in self.circuit.elements if el.name.upper().startswith("V")]
                            in_src = v_sources[0] if v_sources else None

                        if not in_src:
                            self.log("[ERR] .SENS 找不到輸入電壓源作為基準。")
                            continue

                        components_to_test = [el.name for el in self.circuit.elements if el.name.upper().startswith("R") or el.name.upper().startswith("V")]
                        sens_data = simulator.solve_sens_perturbation(out_node, in_src, components_to_test)
                        
                        if not sens_data or sens_data.get("status") == "ERROR":
                            err_msg = sens_data.get("message") if sens_data else "未知錯誤"
                            self.log(f"[ERR] .SENS 崩潰：{err_msg}")
                            continue
                        
                        sens_report = {"Gain_Base(V/V)": self.safe_num(sens_data["base_gain"])}
                        for comp, vals in sens_data["sensitivities"].items():
                            if vals.get("status") == "SUCCESS":
                                sens_report[f"SENS_ABS({comp})"] = self.safe_num(vals["absolute"])
                                sens_report[f"SENS_NORM({comp})"] = self.safe_num(vals["normalized"])
                        
                        self.response_data["op_results"] = sens_report
                        if step_val == step_values[-1]: self.log(f"[OK] .SENS 掃描了 {len(components_to_test)} 個元件。")

            # 🌟 復原現場
            if target_el is not None and orig_val is not None:
                if hasattr(target_el, 'value'): target_el.value = orig_val
                elif hasattr(target_el, 'dc_value'): target_el.dc_value = orig_val

        except Exception as e:
            self.log(f"[ERR] Runner 執行崩潰: {str(e)}")
            traceback.print_exc()

        return self.response_data