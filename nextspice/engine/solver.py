import numpy as np
import time

class SolverResult:
    """
    封裝求解結果與深度診斷資訊。
    修復點 B.6: 統一 API 回傳格式，保證介面一致性，拒絕回傳 None。
    """
    def __init__(self, x=None, status="SUCCESS", error_msg="", 
                 residual=0.0, solve_time=0.0):
        self.x = x                # NumPy Array (解向量)
        self.status = status      # SUCCESS, SINGULAR, EMPTY, NUMERIC_FAILURE
        self.error_msg = error_msg
        self.residual = residual  # ||Ax - b||∞ (殘差)
        self.solve_time = solve_time

    def __repr__(self):
        res_str = f"{self.residual:.2e}" if self.residual is not None else "N/A"
        return (f"SolverResult(status={self.status}, res={res_str}, "
                f"time={self.solve_time*1000:.2f}ms)")

class Simulator:
    """
    NextSPICE 分析驅動引擎 (v0.2)
    職責：管理 MNA 拓撲映射、執行分析計畫、提供數值診斷。
    """
    def __init__(self, circuit):
        self.circuit = circuit
        self.node_mgr = circuit.node_mgr
        self.dim = 0
        self.extra_var_map = {}

    def _prepare_mna_structure(self):
        """
        計算矩陣維度並分配 Extra Variables (支路電流)。
        """
        node_count = self.node_mgr.num_unknowns
        
        curr_extra_idx = node_count
        self.extra_var_map = {}
        for el in self.circuit.elements:
            if el.extra_vars > 0:
                self.extra_var_map[el] = curr_extra_idx
                curr_extra_idx += el.extra_vars
        
        self.dim = curr_extra_idx
        return self.dim

    def solve_op(self, ctx=None):
        """
        執行直流工作點 (.OP) 分析。
        修復點 B.6：API 一致性，空矩陣回傳狀態碼。
        """
        dim = self._prepare_mna_structure()
        if dim == 0: 
            return SolverResult(status="EMPTY", error_msg="No unknown variables to solve.")

        A = np.zeros((dim, dim), dtype=np.float64)
        b = np.zeros(dim, dtype=np.float64)

        # 🚀 互感修復：確保 ctx 存在，並把變數地圖塞進去
        if ctx is None: 
            ctx = {'mode': 'op'}
        ctx['extra_map'] = self.extra_var_map

        for el in self.circuit.elements:
            extra_idx = self.extra_var_map.get(el)
            el.stamp(A, b, extra_idx=extra_idx, ctx=ctx)

        start_t = time.time()
        try:
            x = np.linalg.solve(A, b)
            residual = np.max(np.abs(np.dot(A, x) - b))
            
            return SolverResult(
                x=x, 
                residual=residual, 
                solve_time=time.time() - start_t
            )
        except np.linalg.LinAlgError as e:
            return SolverResult(
                status="SINGULAR", 
                error_msg=f"Matrix is singular or ill-conditioned: {str(e)}",
                solve_time=time.time() - start_t
            )
        except Exception as e:
            return SolverResult(
                status="NUMERIC_FAILURE", 
                error_msg=f"Unexpected solver error: {str(e)}",
                solve_time=time.time() - start_t
            )

    def solve_ac(self, f_start, f_stop, points, sweep_type='DEC'):
        """
        執行交流頻率掃描 (.AC)。
        修復點 B.3: 增加 AC 殘差診斷。
        修復點 B.4: 修正 OCT 掃描的真實語意 (每八度音階點數)。
        修復點 B.7: 嚴謹的 Exception 捕捉，不再吞噬錯誤。
        """
        dim = self._prepare_mna_structure()
        if dim == 0: return []

        # 建立頻率軸 (修正 OCT 語意)
        sweep_type = sweep_type.upper()
        if sweep_type == 'DEC':
            freqs = np.logspace(np.log10(f_start), np.log10(f_stop), points)
        elif sweep_type == 'OCT':
            octaves = np.log2(f_stop / f_start)
            total_points = max(2, int(octaves * points) + 1)
            freqs = np.logspace(np.log10(f_start), np.log10(f_stop), total_points)
        else:
            freqs = np.linspace(f_start, f_stop, points)

        ac_results = []
        for f in freqs:
            # 確保使用複數矩陣
            A_ac = np.zeros((dim, dim), dtype=np.complex128)
            b_ac = np.zeros(dim, dtype=np.complex128)
            
            # 🚀 互感修復：補上 'mode': 'ac' 以及 'extra_map'
            ctx = {'mode': 'ac', 'freq': f, 'extra_map': self.extra_var_map}
            
            for el in self.circuit.elements:
                extra_idx = self.extra_var_map.get(el)
                el.stamp(A_ac, b_ac, extra_idx=extra_idx, ctx=ctx)
            
            try:
                x_ac = np.linalg.solve(A_ac, b_ac)
                residual = np.max(np.abs(np.dot(A_ac, x_ac) - b_ac))
                
                ac_results.append({
                    "freq": f,
                    "x": x_ac,
                    "status": "SUCCESS",
                    "residual": float(residual)
                })
            except np.linalg.LinAlgError as e:
                ac_results.append({
                    "freq": f,
                    "x": None,
                    "status": "SINGULAR",
                    "error_msg": str(e)
                })
            except Exception as e:
                ac_results.append({
                    "freq": f,
                    "x": None,
                    "status": "FAILURE",
                    "error_msg": str(e)
                })
        
        return ac_results

    def solve_dc_sweep(self, source_name, start_v, stop_v, step_v):
        """
        執行 DC Sweep 分析。
        修復：正確判定目標元件使用的是 .dc_value 還是 .value
        """
        source_name = source_name.upper()
        target = next((el for el in self.circuit.elements if el.name.upper() == source_name), None)
        
        if not target:
            return [{"status": "ERROR", "msg": f"Source '{source_name}' not found for DC sweep"}]

        sweep_results = []
        
        # 備份原值 (優先找 dc_value，找不到再找 value)
        original_val = getattr(target, 'dc_value', getattr(target, 'value', 0.0))
        
        v_points = np.arange(start_v, stop_v + (step_v * 0.1), step_v)
        
        for v in v_points:
            # 根據元件屬性動態更新數值
            if hasattr(target, 'dc_value'):
                target.dc_value = v
            elif hasattr(target, 'value'):
                target.value = v
                
            res = self.solve_op() # solve_op 會自動注入 extra_map
            sweep_results.append({"v_in": v, "result": res})
            
        # 恢復原值
        if hasattr(target, 'dc_value'):
            target.dc_value = original_val
        elif hasattr(target, 'value'):
            target.value = original_val
            
        return sweep_results
        
    def solve_tran(self, tstep, tstop):
        """暫態分析 (.TRAN)"""
        dim = self._prepare_mna_structure()
        if dim == 0: return []

        results = []

        # ★★★ 修復 SH_TR03：TRAN 前的 DC OP 要用 t=0 的波形值作為 DC 基準 ★★★
        saved_dc = {}
        for el in self.circuit.elements:
            # 處理電壓源 (V)
            if hasattr(el, '_eval_tran_voltage') and el.tran:
                saved_dc[el] = el.dc_value
                el.dc_value = el._eval_tran_voltage(0.0)
            # 處理電流源 (I) - 順手防呆！
            elif hasattr(el, '_eval_tran_current') and el.tran:
                saved_dc[el] = el.dc_value
                el.dc_value = el._eval_tran_current(0.0)

        try:
            # --- Step 1: Initial Condition (t=0 的初始狀態) ---
            op_res = self.solve_op(ctx={'mode': 'op', 'extra_map': self.extra_var_map})
        finally:
            # ★★★ 安全還原：確保無論 OP 是否崩潰，都不會污染元件的原始定義 ★★★
            for el, val in saved_dc.items():
                el.dc_value = val

        if op_res.status != "SUCCESS":
            return [{"status": "ERROR", "msg": f"Initial OP failed: {op_res.error_msg}"}]

        x_prev = op_res.x
        results.append({"time": 0.0, "x": x_prev.copy(), "status": "SUCCESS"})
        # --- Step 2: 喚醒儲能元件記憶 (Seeding) ---
        # 鴨子型別：不問元件種類，只要有 update_history 就呼叫
        for el in self.circuit.elements:
            if hasattr(el, 'update_history'):
                el.update_history(x_prev, extra_idx=self.extra_var_map.get(el))

        # --- Step 3: 開始時間迴圈 (Time Marching) ---
        t_points = np.arange(tstep, tstop + (tstep * 0.1), tstep)
        
        for t in t_points:
            A = np.zeros((dim, dim), dtype=np.float64)
            b = np.zeros(dim, dtype=np.float64)
            
            ctx = {'mode': 'tran', 't': t, 'dt': tstep, 'extra_map': self.extra_var_map}
            
            for el in self.circuit.elements:
                extra_idx = self.extra_var_map.get(el)
                el.stamp(A, b, extra_idx=extra_idx, ctx=ctx)
                
            try:
                x_new = np.linalg.solve(A, b)
                results.append({"time": t, "x": x_new.copy(), "status": "SUCCESS"})
                
                # --- Step 4: 更新歷史 (為下個 dt 準備) ---
                for el in self.circuit.elements:
                    if hasattr(el, 'update_history'):
                        el.update_history(x_new, extra_idx=self.extra_var_map.get(el))
                        
            except np.linalg.LinAlgError as e:
                results.append({"time": t, "status": "SINGULAR", "msg": str(e)})
                break
            except Exception as e:
                results.append({"time": t, "status": "FAILURE", "msg": str(e)})
                break
                
        return results


    def get_full_report(self, solution_vec):
        """
        修復點 A.4: 補齊報告，同時輸出「節點電壓」與「支路電流」。
        """
        if solution_vec is None:
            return {}
            
        # 1. 取得節點電壓 (來自 circuit 的正規化方法)
        report = self.circuit.get_voltage_report(solution_vec)
        
        # 2. 補上 Extra Variables (例如電源的支路電流 I(V1))
        for el, idx in self.extra_var_map.items():
            if idx < len(solution_vec):
                report[f"I({el.name})"] = solution_vec[idx]
                
        return report