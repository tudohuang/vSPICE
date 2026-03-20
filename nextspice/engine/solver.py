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

        for el in self.circuit.elements:
            extra_idx = self.extra_var_map.get(el)
            el.stamp(A, b, extra_idx=extra_idx, ctx=ctx)

        start_t = time.time()
        try:
            x = np.linalg.solve(A, b)
            # 工業級可信度指標：殘差檢查
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
            # 十倍頻：points 代表每十倍頻點數 (這裡簡化為總點數，若要完全貼合 SPICE 可再微調)
            freqs = np.logspace(np.log10(f_start), np.log10(f_stop), points)
        elif sweep_type == 'OCT':
            # 八倍頻：points 代表每八度音階 (Octave) 點數
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
            ctx = {'freq': f}
            
            for el in self.circuit.elements:
                extra_idx = self.extra_var_map.get(el)
                el.stamp(A_ac, b_ac, extra_idx=extra_idx, ctx=ctx)
            
            try:
                x_ac = np.linalg.solve(A_ac, b_ac)
                # 計算 AC 殘差 (||Ax - b||∞)
                residual = np.max(np.abs(np.dot(A_ac, x_ac) - b_ac))
                
                ac_results.append({
                    "freq": f,
                    "x": x_ac,
                    "status": "SUCCESS",
                    "residual": float(residual) # 儲存殘差以供診斷
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
        修復點 A.3：元件名稱比對忽略大小寫，確保魯棒性。
        """
        source_name = source_name.upper()
        target = next((el for el in self.circuit.elements if el.name.upper() == source_name), None)
        
        if not target:
            return [{"status": "ERROR", "msg": f"Source '{source_name}' not found for DC sweep"}]

        sweep_results = []
        original_val = getattr(target, 'value', 0.0) # 備份原值
        
        # 產生包含終點的掃描陣列
        v_points = np.arange(start_v, stop_v + (step_v * 0.1), step_v)
        
        for v in v_points:
            target.value = v
            res = self.solve_op()
            sweep_results.append({"v_in": v, "result": res})
            
        target.value = original_val # 恢復原值
        return sweep_results

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