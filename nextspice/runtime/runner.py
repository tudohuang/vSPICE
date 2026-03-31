import numpy as np
import traceback
from .solver import Simulator, SimulatorOptions
from .measure import PostProcessor 
from nextspice.engine.analyses import build_analysis

class SimulationRunner:
    """
    NextSPICE 分析排程總管 (Dispatcher) v0.6
    全解耦架構：本身不包含任何數學或分析邏輯，完全交由 Analysis Pipeline 處理。
    """
    def __init__(self, circuit, circuit_json):
        self.circuit = circuit
        self.circuit_json = circuit_json
        
        # response_data 負責與前端 UI / Plotly 溝通
        self.response_data = {"status": "success", "logs": [], "plots": [], "layout": {}, "op_results": {}}
        
        # raw_data 是引擎內部的「純淨資料湖」
        self.raw_data = {"op": [], "tran": [], "ac": [], "dc": [], "sens": [], "tf": []} 
        
        # 🚀 1. 編譯 Analysis Pipeline (Factory Pattern)
        self.pipeline = []
        for cfg in self.circuit_json.get("analyses", []):
            try:
                self.pipeline.append(build_analysis(cfg))
            except Exception as e:
                self.log(f"[WARN] 忽略分析指令: {str(e)}")

    def log(self, msg):
        self.response_data["logs"].append(msg)

    def run_all(self):
        try:
            if not self.pipeline:
                self.log("[WARN] Pipeline 中沒有任何可執行的分析指令。")
                return self.response_data

            nodes_to_plot = [name for name in self.circuit.node_mgr.mapping.keys() if name != "0"]

            # ==========================================
            # STEP 掃描處理 (設定掃描變數與範圍)
            # ==========================================
            step_config = self.circuit_json.get("step_config")
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

            # ==========================================
            # 🧠 階段 1：Pipeline Orchestration (核心迴圈)
            # ==========================================
            for step_val in step_values:
                suffix = "" 
                if target_el is not None and step_val is not None:
                    if hasattr(target_el, 'value'): target_el.value = step_val
                    elif hasattr(target_el, 'dc_value'): target_el.dc_value = step_val
                    suffix = f" ({target_name}={step_val:.1e})"
                
                # 每個 Step 重新實體化 Simulator 確保數學引擎乾淨
                sim_opts = SimulatorOptions(self.circuit_json.get("options", {}))
                simulator = Simulator(self.circuit, options=sim_opts)

                for analysis in self.pipeline:
                    atype = analysis.atype
                    if step_val == step_values[0]: 
                        self.log(f"--- .{atype.upper()} Analysis ---")
                        
                    # 🚀 無腦調度：由各 Analysis Class 處理所有運算細節
                    res = analysis.run(simulator, self.circuit, step_suffix=suffix)
                    
                    if res["status"] == "SUCCESS":
                        self.raw_data[atype].append(res)
                        self.log(f"[OK] .{atype.upper()} 分析完成。")
                        
                        # 🍰 (選配) OP 的終端機報表印出
                        if atype == "op" and (step_val == step_values[0] or target_el is None):
                            for name, val in res["data"].items():
                                unit = "A" if name.startswith("I(") else "V"
                                self.log(f"{name:<10} | {val:>12.5e} {unit}")
                    else:
                        self.log(f"[ERR] .{atype.upper()} 失敗: {res.get('message', '未知錯誤')}")

            # 🌟 復原 STEP 掃描修改的元件數值現場
            if target_el is not None and orig_val is not None:
                if hasattr(target_el, 'value'): target_el.value = orig_val
                elif hasattr(target_el, 'dc_value'): target_el.dc_value = orig_val

            # ==========================================
            # 🔬 階段 2：後處理與前端繪圖 (Post-Processing)
            # ==========================================
            post_processor = PostProcessor(self.circuit_json, self.raw_data, self.log)
            measure_results = post_processor.run_all()
            if measure_results:
                self.response_data.setdefault("op_results", {}).update(measure_results)

            self._build_frontend_plots(nodes_to_plot)

        except Exception as e:
            self.log(f"[ERR] Runner 執行崩潰: {str(e)}")
            traceback.print_exc()

        return self.response_data

    def _build_frontend_plots(self, nodes_to_plot):
        """將 self.raw_data 轉換成前端 Plotly 專用的 JSON 格式"""
        
        # --- OP & SENS 表格報表 ---
        if self.raw_data["op"]:
            self.response_data.setdefault("op_results", {}).update(self.raw_data["op"][0]["data"])
        elif self.raw_data["sens"]:
            self.response_data.setdefault("op_results", {}).update(self.raw_data["sens"][0]["data"])

        # --- TRAN 波形 ---
        if self.raw_data["tran"]:
            self.response_data["layout"] = { "title": "Transient Response", "xaxis": "Time (s)", "yaxis": "Voltage (V) / Current (A)" }
            for run in self.raw_data["tran"]:
                data, suffix = run["data"], run["suffix"]
                if not data: continue
                t_vals = [d["time"] for d in data]
                
                # 過濾掉時間軸與子電路內部雜訊節點
                plot_keys = [k for k in data[0].keys() if k != "time" and "." not in k and "X" not in k.upper()]
                
                for key in plot_keys:
                    y_vals = [float(d.get(key, 0.0)) for d in data]
                    ls = "dash" if key.startswith("I(") else "solid"
                    self.response_data["plots"].append({"name": f"{key}{suffix}", "x": t_vals, "y": y_vals, "type": ls})
            
            self.response_data["tran_results"] = self.raw_data["tran"][0]["data"]

        # --- AC 波形 ---
        elif self.raw_data["ac"]:
            self.response_data["layout"] = {"title": "AC Frequency Response", "xaxis": "Frequency (Hz)", "yaxis": "Magnitude (dB)", "is_ac": True}
            for run in self.raw_data["ac"]:
                ac_res, suffix = run["data"], run["suffix"]
                freqs = [float(r["freq"]) for r in ac_res if r["status"] == "SUCCESS"]
                for node_name in nodes_to_plot:
                    if 'IN' in node_name.upper() or "." in node_name: continue
                    idx = self.circuit.node_mgr.mapping[node_name] - 1
                    v_cplx = [r["x"][idx] for r in ac_res if r["status"] == "SUCCESS"]
                    mags = [float(20 * np.log10(np.abs(v) + 1e-20)) for v in v_cplx]
                    self.response_data["plots"].append({"name": f"Mag V({node_name}){suffix}", "x": freqs, "y": mags, "type": "solid"})

        # --- DC 波形 ---
        elif self.raw_data["dc"]:
            src = self.raw_data["dc"][0].get("src", "Source")
            self.response_data["layout"] = {"title": f"DC Sweep ({src})", "xaxis": f"Source {src} (V)", "yaxis": "Voltage (V) / Current (A)"}
            
            for run in self.raw_data["dc"]:
                data, suffix = run["data"], run["suffix"]
                if not data: continue
                x_vals = [d["v_in"] for d in data]
                
                plot_keys = [k for k in data[0].keys() if k != "v_in" and "." not in k and not k.upper().startswith("X")]
                
                for key in plot_keys:
                    y_vals = [float(d.get(key, 0.0)) for d in data]
                    ls = "dash" if key.startswith("I(") else "solid"
                    self.response_data["plots"].append({"name": f"{key}{suffix}", "x": x_vals, "y": y_vals, "type": ls})