import numpy as np
import scipy.sparse
import scipy.sparse.linalg
import time

class SolverResult:
    def __init__(self, x=None, status="SUCCESS", error_msg="", 
                 residual=0.0, solve_time=0.0):
        self.x = x
        self.status = status
        self.error_msg = error_msg
        self.residual = residual
        self.solve_time = solve_time

    def __repr__(self):
        res_str = f"{self.residual:.2e}" if self.residual is not None else "N/A"
        return (f"SolverResult(status={self.status}, res={res_str}, "
                f"time={self.solve_time*1000:.2f}ms)")

class Simulator:
    """
    NextSPICE 分析驅動引擎 (v0.4 - 🚀 Sparse Matrix 極速版)
    """
    def __init__(self, circuit):
        self.circuit = circuit
        self.node_mgr = circuit.node_mgr
        self.dim = 0
        self.extra_var_map = {}
        self.extra_by_name = {}

    def _make_ctx(self, mode, freq=None, t=None, dt=None):
        return {
            'mode': mode,
            'freq': freq,
            't': t,
            'dt': dt,
            'extra_map': self.extra_var_map,
            'extra_by_name': self.extra_by_name
        }

    def _prepare_mna_structure(self):
        node_count = self.node_mgr.num_unknowns
        curr_extra_idx = node_count
        self.extra_var_map = {}
        for el in self.circuit.elements:
            if el.extra_vars > 0:
                self.extra_var_map[el] = curr_extra_idx
                curr_extra_idx += el.extra_vars
        
        self.dim = curr_extra_idx
        self.extra_by_name = {el.name.upper(): idx for el, idx in self.extra_var_map.items()}
        return self.dim

    def solve_op(self, ctx=None):
        dim = self._prepare_mna_structure()
        if dim == 0: 
            return SolverResult(status="EMPTY", error_msg="No unknown variables.")

        # 🚀 魔法 1：改用 LIL 稀疏矩陣 (最適合動態塞資料的格式)
        A = scipy.sparse.lil_matrix((dim, dim), dtype=np.float64)
        b = np.zeros(dim, dtype=np.float64)

        if ctx is None: 
            ctx = self._make_ctx(mode='op')

        for el in self.circuit.elements:
            extra_idx = self.extra_var_map.get(el)
            el.stamp(A, b, extra_idx=extra_idx, ctx=ctx)

        start_t = time.time()
        try:
            # 🚀 魔法 2：塞完資料後，壓縮成 CSR 格式 (解方程式最快的格式)
            A_csr = A.tocsr()
            # 🚀 魔法 3：呼叫 SciPy 的稀疏矩陣求解器
            x = scipy.sparse.linalg.spsolve(A_csr, b)
            
            # 稀疏矩陣的點積運算
            residual = np.max(np.abs(A_csr.dot(x) - b))
            
            return SolverResult(x=x, residual=residual, solve_time=time.time() - start_t)
        except Exception as e:
            return SolverResult(status="SINGULAR_OR_FAILURE", error_msg=str(e), solve_time=time.time() - start_t)

    def solve_ac(self, f_start, f_stop, points, sweep_type='DEC'):
        dim = self._prepare_mna_structure()
        if dim == 0: return []

        sweep_type = sweep_type.upper()
        if sweep_type == 'DEC': freqs = np.logspace(np.log10(f_start), np.log10(f_stop), points)
        elif sweep_type == 'OCT':
            octaves = np.log2(f_stop / f_start)
            freqs = np.logspace(np.log10(f_start), np.log10(f_stop), max(2, int(octaves * points) + 1))
        elif sweep_type == 'LIN': freqs = np.linspace(f_start, f_stop, points)
        else: return [{"status": "ERROR", "msg": f"Unsupported AC sweep: {sweep_type}"}]

        ac_results = []
        for f in freqs:
            # 🚀 交流分析也要換成支援複數的 LIL 矩陣
            A_ac = scipy.sparse.lil_matrix((dim, dim), dtype=np.complex128)
            b_ac = np.zeros(dim, dtype=np.complex128)
            
            ctx = self._make_ctx(mode='ac', freq=f)
            for el in self.circuit.elements:
                extra_idx = self.extra_var_map.get(el)
                el.stamp(A_ac, b_ac, extra_idx=extra_idx, ctx=ctx)
            
            try:
                A_csr = A_ac.tocsr() # 🚀 壓縮
                x_ac = scipy.sparse.linalg.spsolve(A_csr, b_ac) # 🚀 求解
                residual = np.max(np.abs(A_csr.dot(x_ac) - b_ac))
                ac_results.append({"freq": f, "x": x_ac, "status": "SUCCESS", "residual": float(residual)})
            except Exception as e:
                ac_results.append({"freq": f, "x": None, "status": "FAILURE", "error_msg": str(e)})
        
        return ac_results

    def solve_dc_sweep(self, source_name, start_v, stop_v, step_v):
        source_name = source_name.upper()
        target = next((el for el in self.circuit.elements if el.name.upper() == source_name), None)
        if not target: return [{"status": "ERROR", "msg": f"Source '{source_name}' not found"}]

        sweep_results = []
        original_val = getattr(target, 'dc_value', getattr(target, 'value', 0.0))
        v_points = np.arange(start_v, stop_v + (step_v * 0.1), step_v)
        
        try:
            for v in v_points:
                if hasattr(target, 'dc_value'): target.dc_value = v
                elif hasattr(target, 'value'): target.value = v
                res = self.solve_op() 
                sweep_results.append({"v_in": v, "result": res})
        finally:
            if hasattr(target, 'dc_value'): target.dc_value = original_val
            elif hasattr(target, 'value'): target.value = original_val
            
        return sweep_results
        
    def solve_tran(self, tstep, tstop):
        dim = self._prepare_mna_structure()
        if dim == 0: return []

        results = []
        saved_dc = {}
        for el in self.circuit.elements:
            if hasattr(el, '_eval_tran_voltage') and el.tran:
                saved_dc[el] = el.dc_value
                el.dc_value = el._eval_tran_voltage(0.0)
            elif hasattr(el, '_eval_tran_current') and el.tran:
                saved_dc[el] = el.dc_value
                el.dc_value = el._eval_tran_current(0.0)

        try:
            op_res = self.solve_op(ctx=self._make_ctx(mode='op'))
        finally:
            for el, val in saved_dc.items(): el.dc_value = val

        if op_res.status != "SUCCESS":
            return [{"status": "ERROR", "msg": f"Initial OP failed: {op_res.error_msg}"}]

        x_prev = op_res.x
        results.append({"time": 0.0, "x": x_prev.copy(), "status": "SUCCESS"})
        
        for el in self.circuit.elements:
            if hasattr(el, 'update_history'):
                el.update_history(x_prev, extra_idx=self.extra_var_map.get(el))

        t_points = np.arange(tstep, tstop + (tstep * 0.1), tstep)
        
        for t in t_points:
            # 🚀 暫態迴圈裡，每個時間步長都要開新的 LIL 矩陣
            A = scipy.sparse.lil_matrix((dim, dim), dtype=np.float64)
            b = np.zeros(dim, dtype=np.float64)
            
            ctx = self._make_ctx(mode='tran', t=t, dt=tstep)
            for el in self.circuit.elements:
                extra_idx = self.extra_var_map.get(el)
                el.stamp(A, b, extra_idx=extra_idx, ctx=ctx)
                
            try:
                A_csr = A.tocsr() # 🚀 壓縮
                x_new = scipy.sparse.linalg.spsolve(A_csr, b) # 🚀 求解
                results.append({"time": t, "x": x_new.copy(), "status": "SUCCESS"})
                
                for el in self.circuit.elements:
                    if hasattr(el, 'update_history'):
                        el.update_history(x_new, extra_idx=self.extra_var_map.get(el))
            except Exception as e:
                results.append({"time": t, "status": "FAILURE", "msg": str(e)})
                break
                
        return results

    def get_full_report(self, solution_vec):
        if solution_vec is None: return {}
        report = self.circuit.get_voltage_report(solution_vec)
        for el, idx in self.extra_var_map.items():
            if idx < len(solution_vec):
                report[f"I({el.name})"] = solution_vec[idx]
        return report
    def _get_element_by_name(self, name):
        """安全獲取元件，統一轉大寫比對"""
        name = str(name).upper().strip()
        return next((el for el in self.circuit.elements if el.name.upper() == name), None)

    def _resolve_voltage_index(self, node_name):
        """
        絕對安全的節點解析器
        回傳: index (供 op_res.x 使用), 或 -1 (代表接地), 或 None (找不到)
        """
        # 過濾 V() 括號並轉大寫
        clean_name = str(node_name).upper().replace("V(", "").replace(")", "").strip()
        
        if clean_name in ["0", "GND"]:
            return -1  # 接地節點電壓永遠為 0，不在未知數向量中

        idx = self.circuit.node_mgr.mapping.get(clean_name)
        if idx is None or idx == 0:
            return None
            
        return idx - 1

    def _get_param_value(self, el, attr_name=None):
        """智慧屬性提取器，支援動態命名"""
        if attr_name and hasattr(el, attr_name):
            return getattr(el, attr_name)
        # Fallback heuristic
        if hasattr(el, 'value'): return el.value
        if hasattr(el, 'dc_value'): return el.dc_value
        return None

    def _set_param_value(self, el, val, attr_name=None):
        """智慧屬性注入器"""
        if attr_name and hasattr(el, attr_name):
            setattr(el, attr_name, val)
        elif hasattr(el, 'value'):
            el.value = val
        elif hasattr(el, 'dc_value'):
            el.dc_value = val

    def measure_dc_gain(self, out_idx, in_src_name):
        """封裝單次 OP 與 Gain 計算，確保輸入擾動時分母也能動態更新"""
        # 強制清除 MNA 快取，確保微擾生效
        if hasattr(self, 'last_A'): self.last_A = None 
        
        op_res = self.solve_op()
        if op_res.status != "SUCCESS": 
            return None

        # 處理輸出電壓 (如果是接地則為 0)
        out_v = 0.0 if out_idx == -1 else op_res.x[out_idx]

        # 動態獲取當下的輸入電壓 (解決 Risk: Input perturbation)
        in_el = self._get_element_by_name(in_src_name)
        in_v = self._get_param_value(in_el)
        
        if in_v is None or in_v == 0:
            return None # 避免 Division by Zero

        return out_v / in_v

    def solve_sens_perturbation(self, out_node, in_src_name, targets, rel_step=1e-5, min_step=1e-12):
        """
        工業級微擾靈敏度分析 (Central Difference Edition)
        - 支援 tuple targets: [("R1", "value"), ("V1", "dc_value"), "R2"]
        """
        out_idx = self._resolve_voltage_index(out_node)
        if out_idx is None:
            return {"status": "ERROR", "message": f"Output node '{out_node}' is invalid or not found."}

        in_el = self._get_element_by_name(in_src_name)
        if not in_el:
            return {"status": "ERROR", "message": f"Input source '{in_src_name}' not found."}

        # 1. 基準測試 (Base Run)
        base_gain = self.measure_dc_gain(out_idx, in_src_name)
        if base_gain is None:
            return {"status": "ERROR", "message": "Failed to calculate base DC gain. OP may not converge or input is 0."}

        results = {}

        # 2. 開始中央差分微擾
        for target in targets:
            # 支援彈性 Target 格式：字串 "R1" 或 Tuple ("M1", "gm")
            if isinstance(target, tuple):
                el_name, attr_name = target
            else:
                el_name, attr_name = str(target), None

            el = self._get_element_by_name(el_name)
            if not el:
                results[el_name] = {"status": "ERROR", "message": "Element not found"}
                continue

            old_value = self._get_param_value(el, attr_name)
            if old_value is None:
                results[el_name] = {"status": "ERROR", "message": "Parameter unsupported"}
                continue

            # 防呆：動態計算步長，加上底線保護避免被浮點數誤差吃掉
            delta = max(abs(old_value) * rel_step, min_step)

            # --- Central Difference 核心 ---
            # 正向微擾 (+Delta)
            self._set_param_value(el, old_value + delta, attr_name)
            gain_plus = self.measure_dc_gain(out_idx, in_src_name)

            # 反向微擾 (-Delta)
            self._set_param_value(el, old_value - delta, attr_name)
            gain_minus = self.measure_dc_gain(out_idx, in_src_name)

            # 🚨 鐵律：立刻復原元件數值
            self._set_param_value(el, old_value, attr_name)
            if hasattr(self, 'last_A'): self.last_A = None

            if gain_plus is None or gain_minus is None:
                results[el_name] = {"status": "ERROR", "message": "OP failed during perturbation"}
                continue

            # 計算中央差分靈敏度
            sens = (gain_plus - gain_minus) / (2 * delta)
            norm_sens = (old_value / base_gain) * sens if base_gain != 0 else 0.0

            results[el_name] = {
                "status": "SUCCESS",
                "param_tested": attr_name or "default_value",
                "absolute": sens,
                "normalized": norm_sens
            }

        return {
            "status": "SUCCESS",
            "base_gain": base_gain,
            "sensitivities": results
        }