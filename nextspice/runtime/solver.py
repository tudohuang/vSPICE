import numpy as np
import scipy.sparse
import scipy.sparse.linalg
import time
import math
from nextspice.engine.context import AnalysisContext, StateManager

class SolverResult:
    def __init__(self, x=None, status="SUCCESS", error_msg="",
                 residual=0.0, solve_time=0.0, method_used=""):
        self.x = x
        self.status = status
        self.error_msg = error_msg
        self.residual = residual
        self.solve_time = solve_time
        self.method_used = method_used

    def __repr__(self):
        res_str = f"{self.residual:.2e}" if self.residual is not None else "N/A"
        m = f", method={self.method_used}" if self.method_used else ""
        return (f"SolverResult(status={self.status}, res={res_str}, "
                f"time={self.solve_time*1000:.2f}ms{m})")

# ── 線性求解器工廠 ──
ITERATIVE_SOLVERS = {
    'gmres': scipy.sparse.linalg.gmres,
    'bicgstab': scipy.sparse.linalg.bicgstab,
    'cgs': scipy.sparse.linalg.cgs,
    'lgmres': scipy.sparse.linalg.lgmres,
}

def linear_solve(A_csr, b, method='spsolve', tol=1e-10, maxiter=1000, precond=True):
    method = method.lower()
    if method == 'spsolve' or method == 'lu':
        return scipy.sparse.linalg.spsolve(A_csr, b), 'spsolve'

    solver_fn = ITERATIVE_SOLVERS.get(method)
    if solver_fn is None:
        return scipy.sparse.linalg.spsolve(A_csr, b), 'spsolve'

    M = None
    if precond:
        try:
            ilu = scipy.sparse.linalg.spilu(A_csr.tocsc(), drop_tol=1e-4)
            M = scipy.sparse.linalg.LinearOperator(A_csr.shape, ilu.solve)
        except Exception:
            M = None

    x, info = solver_fn(A_csr, b, tol=tol, maxiter=maxiter, M=M)
    if info != 0:
        x = scipy.sparse.linalg.spsolve(A_csr, b)
        return x, f'{method}→spsolve'
    return x, method


class SimulatorOptions:
    def __init__(self, options_dict=None):
        opts = options_dict or {}
        self.reltol = float(opts.get('RELTOL', 1e-3))
        self.abstol = float(opts.get('ABSTOL', 1e-6))
        self.itl1 = int(opts.get('ITL1', 100))      
        self.itl4 = int(opts.get('ITL4', 100))       
        self.gmin = float(opts.get('GMIN', 1e-12))   
        self.solver = str(opts.get('SOLVER', 'spsolve')).lower()
        self.method = str(opts.get('METHOD', 'TRAP')).upper()
        self.damping = str(opts.get('DAMPING', 'AUTO')).upper()  
        self.srcsteps = int(opts.get('SRCSTEPS', 0))  


class Simulator:
    def __init__(self, circuit, options=None):
        self.circuit = circuit
        self.node_mgr = circuit.node_mgr
        self.dim = 0
        self.extra_var_map = {}
        self.extra_by_name = {}
        self.opts = options if isinstance(options, SimulatorOptions) else SimulatorOptions(options)
        
        # 🚀 生命周期管理：存放最後一次成功的 OP 狀態
        self.last_op_state = None  

    # 🚀 使用者設定值 → 內部統一名稱的對照表
    _INTEGRATION_MAP = {
        'trap': 'trapezoidal', 'trapezoidal': 'trapezoidal',
        'be': 'be', 'euler': 'be',
        'gear2': 'gear2', 'gear': 'gear2',
    }

    def _make_ctx(self, mode, freq=1.0, t=0.0, dt=0.0, state_mgr=None):
        """🚀 必修修正 1：全面換裝強型別 AnalysisContext"""
        raw_method = self.opts.method.lower()
        integration = self._INTEGRATION_MAP.get(raw_method, 'trapezoidal')
        return AnalysisContext(
            mode=mode,
            freq=freq,
            t=t,
            dt=dt,
            integration=integration,
            extra_map=self.extra_var_map,
            extra_by_name=self.extra_by_name,
            state_mgr=state_mgr
        )

    def _prepare_mna_structure(self):
        """🚀 必修修正 2：使用 requires_extra 進行 Build-time 檢查"""
        node_count = self.node_mgr.num_unknowns
        curr_extra_idx = node_count
        self.extra_var_map = {}
        for el in self.circuit.elements:
            if getattr(el, 'requires_extra', lambda: el.extra_vars > 0)():
                self.extra_var_map[el] = curr_extra_idx
                curr_extra_idx += el.extra_vars
        
        self.dim = curr_extra_idx
        self.extra_by_name = {el.name.upper(): idx for el, idx in self.extra_var_map.items()}
        return self.dim

    def _stamp_system(self, A, b, ctx, x_guess=None):
        """🚀 必修修正 3：對齊 Nonlinear 參數簽名與 Ctx 傳遞"""
        for el in self.circuit.elements:
            extra_idx = self.extra_var_map.get(el)
            if getattr(el, 'is_nonlinear', False):
                # 正確順序：A, b, x_old, extra_idx, ctx
                el.stamp_nonlinear(A, b, x_guess, extra_idx=extra_idx, ctx=ctx)
            else:
                el.stamp(A, b, extra_idx=extra_idx, ctx=ctx)

    def _linear_solve(self, A, b):
        A_csr = A.tocsr()
        x, method_used = linear_solve(A_csr, b, method=self.opts.solver)
        return x, A_csr, method_used

    def _nr_loop(self, dim, ctx, max_iters, reltol, abstol, x_init=None, damping='AUTO'):
        """通用 Newton-Raphson 迴圈，傳遞 Context"""
        x_guess = x_init if x_init is not None else np.zeros(dim, dtype=np.float64)
        prev_norm = float('inf')
        method_used = ''

        for i in range(max_iters):
            A = scipy.sparse.lil_matrix((dim, dim), dtype=np.float64)
            b = np.zeros(dim, dtype=np.float64)
            self._stamp_system(A, b, ctx, x_guess)

            try:
                x_new, A_csr, method_used = self._linear_solve(A, b)
            except Exception as e:
                return None, A_csr if 'A_csr' in locals() else None, str(e), method_used

            diff = x_new - x_guess
            diff_norm = np.linalg.norm(diff)

            if damping == 'ON' or (damping == 'AUTO' and diff_norm > prev_norm * 2):
                alpha = min(1.0, prev_norm / (diff_norm + 1e-30))
                alpha = max(alpha, 0.1)  
                x_new = x_guess + alpha * diff

            prev_norm = diff_norm

            conv_diff = np.abs(x_new - x_guess)
            tolerance = reltol * np.maximum(np.abs(x_new), np.abs(x_guess)) + abstol
            if np.all(conv_diff <= tolerance):
                residual = np.max(np.abs(A_csr.dot(x_new) - b))
                return x_new, residual, None, method_used

            x_guess = x_new

        return None, None, f"NR failed to converge after {max_iters} iterations", method_used

    def solve_op(self, ctx=None, max_iters=None, reltol=None, abstol=None):
        dim = self._prepare_mna_structure()
        if dim == 0:
            return SolverResult(status="EMPTY", error_msg="No unknown variables.")

        if ctx is None:
            ctx = self._make_ctx(mode='op')
            
        max_iters = max_iters or self.opts.itl1
        reltol = reltol or self.opts.reltol
        abstol = abstol or self.opts.abstol
        start_t = time.time()

        x, residual, err, method_used = self._nr_loop(
            dim, ctx, max_iters, reltol, abstol, damping=self.opts.damping)

        if x is not None:
            # 🚀 生命週期管理：將收斂的狀態保存下來
            ctx.is_dc_op_valid = True
            self.last_op_state = ctx.state_mgr.clone()
            return SolverResult(x=x, residual=residual,
                                solve_time=time.time() - start_t, method_used=method_used)

        # 第二輪：Source Stepping 
        src_steps = self.opts.srcsteps if self.opts.srcsteps > 0 else 10
        saved_sources = {}
        for el in self.circuit.elements:
            if hasattr(el, 'dc_value'):
                saved_sources[el] = el.dc_value
            elif hasattr(el, 'value') and el.name.upper().startswith(('V', 'I')):
                saved_sources[el] = el.value

        x_guess = np.zeros(dim, dtype=np.float64)
        src_success = False

        try:
            for step in range(1, src_steps + 1):
                scale = step / src_steps
                for el, orig in saved_sources.items():
                    if hasattr(el, 'dc_value'): el.dc_value = orig * scale
                    elif hasattr(el, 'value'): el.value = orig * scale

                x_step, res_step, err_step, m = self._nr_loop(
                    dim, ctx, max_iters, reltol, abstol, x_init=x_guess, damping='ON')

                if x_step is not None:
                    x_guess = x_step
                    method_used = f'srcstep({step}/{src_steps})+{m}'
                    if step == src_steps: src_success = True
                else: break
        finally:
            for el, orig in saved_sources.items():
                if hasattr(el, 'dc_value'): el.dc_value = orig
                elif hasattr(el, 'value'): el.value = orig

        if src_success:
            ctx.is_dc_op_valid = True
            self.last_op_state = ctx.state_mgr.clone()
            return SolverResult(x=x_guess, residual=res_step,
                                solve_time=time.time() - start_t, method_used=method_used)

        return SolverResult(status="NON_CONVERGENCE", error_msg=f"OP failed. Last err: {err}", solve_time=time.time() - start_t)

    def solve_ac(self, f_start, f_stop, points, sweep_type='DEC'):
        dim = self._prepare_mna_structure()
        if dim == 0: return []

        # 🚀 必修修正 4：AC 必須 Reuse OP State
        if not self.last_op_state:
            op_res = self.solve_op()
            if op_res.status != "SUCCESS":
                return [{"status": "ERROR", "msg": "DC OP failed, AC aborted."}]

        sweep_type = sweep_type.upper()
        if sweep_type == 'DEC':
            decades = math.log10(f_stop / f_start)
            freqs = np.logspace(np.log10(f_start), np.log10(f_stop), int(round(points * decades)) + 1)
        elif sweep_type == 'LIN':
            freqs = np.linspace(f_start, f_stop, points)
        else: return [{"status": "ERROR", "msg": f"Unsupported AC sweep: {sweep_type}"}]

        ac_results = []
        for f in freqs:
            A_ac = scipy.sparse.lil_matrix((dim, dim), dtype=np.complex128)
            b_ac = np.zeros(dim, dtype=np.complex128)
            
            # 🚀 借用 OP 階段算好的非線性跨導
            ctx = self._make_ctx(mode='ac', freq=f, state_mgr=self.last_op_state.clone())
            
            for el in self.circuit.elements:
                el.stamp(A_ac, b_ac, extra_idx=self.extra_var_map.get(el), ctx=ctx)
                
            try:
                A_csr = A_ac.tocsr()
                x_ac = scipy.sparse.linalg.spsolve(A_csr, b_ac)
                ac_results.append({"freq": f, "x": x_ac, "status": "SUCCESS"})
            except Exception as e:
                ac_results.append({"freq": f, "x": None, "status": "FAILURE", "error_msg": str(e)})
        return ac_results

    def solve_tran(self, tstep, tstop, max_iters=None, reltol=None, abstol=None):
        """
        🚀 必修修正 5：具備動態 Rollback 與 State Clone 能力的強大 TRAN 引擎
        """
        dim = self._prepare_mna_structure()
        if dim == 0: return []

        max_iters = max_iters or self.opts.itl4
        reltol = reltol or self.opts.reltol
        abstol = abstol or self.opts.abstol
        integration = self.opts.method 

        results = []
        saved_dc = {}

        # 準備初始 DC 狀態
        for el in self.circuit.elements:
            if hasattr(el, 'waveform'):
                saved_dc[el] = el.dc_value
                el.dc_value = el.waveform.eval(0.0)

        op_res = self.solve_op()
        for el, val in saved_dc.items(): el.dc_value = val

        if op_res.status != "SUCCESS":
            return [{"status": "ERROR", "msg": f"Initial OP failed: {op_res.error_msg}"}]

        x_prev = op_res.x
        results.append({"time": 0.0, "x": x_prev.copy(), "status": "SUCCESS"})

        # 🚀 繼承 OP 狀態開始進行 TRAN
        ctx = self._make_ctx('tran', dt=tstep, state_mgr=self.last_op_state.clone())
        base_integration = ctx.integration  # 已正規化的積分方法名稱
        
        # 通知元件記錄初始歷史
        for el in self.circuit.elements:
            if hasattr(el, 'update_history'):
                el.update_history(x_prev, extra_idx=self.extra_var_map.get(el), ctx=ctx)

        t = tstep
        first_step = True
        current_dt = tstep

        while t <= tstop + 1e-12:
            ctx.t = t
            ctx.dt = current_dt
            
            # Gear-2 第一步退化為 Backward Euler
            ctx.integration = 'be' if (base_integration == 'gear2' and first_step) else base_integration
            
            # 💥 核心：備份這一步的 State！如果 NR 爆炸可以無痛還原
            state_backup = ctx.state_mgr.clone()
            
            x_guess = x_prev.copy()
            x_new, residual, err, m = self._nr_loop(dim, ctx, max_iters, reltol, abstol, x_init=x_guess, damping=self.opts.damping)

            if err is None:
                # 收斂成功！寫入歷史狀態
                for el in self.circuit.elements:
                    if hasattr(el, 'update_history'):
                        el.update_history(x_new, extra_idx=self.extra_var_map.get(el), ctx=ctx)

                results.append({"time": t, "status": "SUCCESS", "x": x_new.copy()})
                x_prev = x_new
                first_step = False
                
                # 收斂良好，嘗試恢復原始 timestep
                if current_dt < tstep:
                    current_dt = min(current_dt * 2.0, tstep)
                
                t += current_dt
            else:
                # 💥 NR 失敗，時步切半，State 回溯！
                ctx.state_mgr = state_backup
                current_dt /= 2.0
                
                if current_dt < 1e-15:
                    results.append({"time": t, "status": "FAILURE", "msg": f"TRAN NR failed. Timestep too small."})
                    break
                    
                # 時間 t 不推進，重新嘗試這一步

        return results

    # =======================================================
    # 以下為 .DC, .SENS, .TF 分析，完整保留並對齊 Ctx 架構
    # =======================================================

    def solve_dc_sweep(self, source_name, start_v, stop_v, step_v):
        dim = self._prepare_mna_structure()
        if dim == 0: return []

        source_name = source_name.upper()
        target = next((el for el in self.circuit.elements if el.name.upper() == source_name), None)
        if not target: return [{"status": "ERROR", "msg": f"Source '{source_name}' not found"}]

        sweep_results = []
        original_val = getattr(target, 'dc_value', getattr(target, 'value', 0.0))
        v_points = np.arange(start_v, stop_v + (step_v * 0.1), step_v)
        
        ctx = self._make_ctx('op')
        x_guess = np.zeros(dim, dtype=np.float64)
        
        try:
            for v in v_points:
                if hasattr(target, 'dc_value'): target.dc_value = v
                elif hasattr(target, 'value'): target.value = v
                
                x_new, res, err, m = self._nr_loop(dim, ctx, self.opts.itl1, self.opts.reltol, self.opts.abstol, x_init=x_guess)
                if err is None:
                    x_guess = x_new
                    # 🐞 關鍵修復：明確指定 x=... 和 status=...
                    sweep_results.append({"v_in": v, "result": SolverResult(x=x_new.copy(), status="SUCCESS")})
                else:
                    sweep_results.append({"v_in": v, "result": SolverResult(status="ERROR")})
        finally:
            if hasattr(target, 'dc_value'): target.dc_value = original_val
            elif hasattr(target, 'value'): target.value = original_val
            
        return sweep_results

    def get_full_report(self, solution_vec):
        if solution_vec is None: return {}
        # 取得所有節點電壓
        report = self.circuit.get_voltage_report(solution_vec)
        
        # 取得所有獨立支路電流
        for el, idx in self.extra_var_map.items():
            if idx < len(solution_vec):
                report[f"I({el.name})"] = solution_vec[idx]
                
        # 🌟 LED 亮度裝飾數據
        for el in self.circuit.elements:
            if el.name.upper().startswith('LED') and hasattr(el, 'n1') and hasattr(el, 'n2'):
                vp = solution_vec[el.n1 - 1] if el.n1 > 0 else 0.0
                vn = solution_vec[el.n2 - 1] if el.n2 > 0 else 0.0
                report[f"LUM({el.name})_%"] = el.get_brightness_percent(vp, vn)
                
        return report


    def _get_element_by_name(self, name):
        name = str(name).upper().strip()
        return next((el for el in self.circuit.elements if el.name.upper() == name), None)

    def _resolve_voltage_index(self, node_name):
        clean_name = str(node_name).upper().replace("V(", "").replace(")", "").strip()
        if clean_name in ["0", "GND"]: return -1 
        idx = self.circuit.node_mgr.mapping.get(clean_name)
        if idx is None or idx == 0: return None
        return idx - 1

    def _get_param_value(self, el, attr_name=None):
        if attr_name and hasattr(el, attr_name): return getattr(el, attr_name)
        if hasattr(el, 'value'): return el.value
        if hasattr(el, 'dc_value'): return el.dc_value
        return None

    def _set_param_value(self, el, val, attr_name=None):
        if attr_name and hasattr(el, attr_name): setattr(el, attr_name, val)
        elif hasattr(el, 'value'): el.value = val
        elif hasattr(el, 'dc_value'): el.dc_value = val

    def measure_dc_gain(self, out_idx, in_src_name):
        op_res = self.solve_op()
        if op_res.status != "SUCCESS": return None
        out_v = 0.0 if out_idx == -1 else op_res.x[out_idx]
        in_el = self._get_element_by_name(in_src_name)
        in_v = self._get_param_value(in_el)
        if in_v is None or in_v == 0: return None 
        return out_v / in_v

    def solve_sens_perturbation(self, out_node, in_src_name, targets, rel_step=1e-5, min_step=1e-12):
        out_idx = self._resolve_voltage_index(out_node)
        if out_idx is None: return {"status": "ERROR"}
        in_el = self._get_element_by_name(in_src_name)
        if not in_el: return {"status": "ERROR"}

        base_gain = self.measure_dc_gain(out_idx, in_src_name)
        if base_gain is None: return {"status": "ERROR"}

        results = {}
        for target in targets:
            if isinstance(target, tuple): el_name, attr_name = target
            else: el_name, attr_name = str(target), None

            el = self._get_element_by_name(el_name)
            if not el: continue
            old_value = self._get_param_value(el, attr_name)
            if old_value is None: continue

            delta = max(abs(old_value) * rel_step, min_step)

            self._set_param_value(el, old_value + delta, attr_name)
            gain_plus = self.measure_dc_gain(out_idx, in_src_name)

            self._set_param_value(el, old_value - delta, attr_name)
            gain_minus = self.measure_dc_gain(out_idx, in_src_name)

            self._set_param_value(el, old_value, attr_name)

            if gain_plus is None or gain_minus is None: continue

            sens = (gain_plus - gain_minus) / (2 * delta)
            norm_sens = (old_value / base_gain) * sens if base_gain != 0 else 0.0

            results[el_name] = {"status": "SUCCESS", "absolute": sens, "normalized": norm_sens}

        return {"status": "SUCCESS", "base_gain": base_gain, "sensitivities": results}

    def solve_tf(self, out_node_str, in_src_name):
        """🚀 完美對齊：利用 Reuse OP State 與新 Stamp 簽名的 TF 分析"""
        out_node = out_node_str.upper().replace("V(", "").replace(")", "").strip()
        in_src_name = in_src_name.upper()

        op_res = self.solve_op()
        if op_res.status != "SUCCESS":
            return {"status": "ERROR", "message": "DC OP failed"}

        out_idx = self.circuit.node_mgr.mapping.get(out_node, 0) - 1
        in_src = self._get_element_by_name(in_src_name)
        if not in_src: return {"status": "ERROR"}
            
        in_src_idx = self.extra_var_map.get(in_src)

        n = self.dim
        A = np.zeros((n, n))
        b_zero = np.zeros(n)
        
        # 🚀 關鍵：使用 OP State 提取 Jacobian 矩陣
        ctx = self._make_ctx('op', state_mgr=self.last_op_state.clone())
        
        for el in self.circuit.elements:
            idx = self.extra_var_map.get(el)
            if getattr(el, 'is_nonlinear', False):
                el.stamp_nonlinear(A, b_zero, op_res.x, extra_idx=idx, ctx=ctx)
            else:
                el.stamp(A, b_zero, extra_idx=idx, ctx=ctx)

        b_gain = np.zeros(n)
        if in_src.name.upper().startswith('V'):
            b_gain[in_src_idx] += 1.0  
        elif in_src.name.upper().startswith('I'):
            if in_src.n1 > 0: b_gain[in_src.n1 - 1] -= 1.0
            if in_src.n2 > 0: b_gain[in_src.n2 - 1] += 1.0

        try:
            x_gain = np.linalg.solve(A, b_gain)
            gain = x_gain[out_idx] if out_idx >= 0 else 0.0
            if in_src.name.upper().startswith('V'):
                i_in = x_gain[in_src_idx]
                rin = 1.0 / abs(i_in) if abs(i_in) > 1e-15 else float('inf')
            else:
                v_in = (x_gain[in_src.n1-1] if in_src.n1 > 0 else 0) - (x_gain[in_src.n2-1] if in_src.n2 > 0 else 0)
                rin = abs(v_in) / 1.0
        except Exception as e:
            return {"status": "ERROR", "message": str(e)}

        b_rout = np.zeros(n)
        if out_idx >= 0: b_rout[out_idx] -= 1.0  
            
        try:
            x_rout = np.linalg.solve(A, b_rout)
            rout = abs(x_rout[out_idx]) if out_idx >= 0 else 0.0
        except:
            rout = float('inf')

        return {"status": "SUCCESS", "gain": gain, "rin": rin, "rout": rout}