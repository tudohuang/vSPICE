import numpy as np
import math
from scipy.interpolate import interp1d

class PostProcessor:
    """
    NextSPICE 高效能後處理引擎 (Vectorized Edition)
    專門處理 .MEASURE, .FOUR 等基於 raw_data 的數據分析。
    """
    def __init__(self, circuit_json, raw_data, log_callback):
        self.circuit_json = circuit_json
        self.raw_data = raw_data
        self.log = log_callback
        self.results = {}

    def run_all(self):
        """執行所有後處理分析"""
        self.evaluate_measures()
        self.evaluate_fourier()
        return self.results

    def safe_num(self, val):
        try:
            v = float(val)
            return 0.0 if math.isnan(v) or math.isinf(v) else v
        except:
            return 0.0

    # =================================================================
    # ⚡ 核心數值工具：NumPy 向量化跨越點偵測 (極速)
    # =================================================================
    def _find_crossings(self, t_arr, y_arr, target_val, edge_type="EITHER"):
        """使用 NumPy 矩陣運算，極速找出波形跨過 target_val 的所有精確時間點"""
        t = np.asarray(t_arr)
        y = np.asarray(y_arr)
        
        # 錯位陣列比較：y1 是前一點，y2 是後一點
        y1, y2 = y[:-1], y[1:]
        t1, t2 = t[:-1], t[1:]
        
        edge = edge_type.upper()
        if edge == "RISE":
            idx = np.where((y1 <= target_val) & (y2 > target_val))[0]
        elif edge == "FALL":
            idx = np.where((y1 >= target_val) & (y2 < target_val))[0]
        else:
            idx = np.where(((y1 <= target_val) & (y2 > target_val)) | 
                           ((y1 >= target_val) & (y2 < target_val)))[0]
                           
        if len(idx) == 0:
            return []
            
        # 向量化線性內插：t_cross = t1 + (val - y1) * (t2 - t1) / (y2 - y1)
        dy = y2[idx] - y1[idx]
        dy[dy == 0] = 1e-15  # 防止除以零
        t_cross = t1[idx] + (target_val - y1[idx]) * (t2[idx] - t1[idx]) / dy
        
        return t_cross.tolist()

    # =================================================================
    # 🎯 .MEASURE 分析路由
    # =================================================================
    def evaluate_measures(self):
        measures = self.circuit_json.get("measures", [])
        if not measures: return

        self.log("\n--- .MEASURE Results ---")
        
        for m in measures:
            try:
                atype = m.get("analysis_type", "tran").lower()
                name = m.get("name", "UNNAMED").upper()
                
                if atype != 'tran' or not self.raw_data.get("tran"):
                    continue
                    
                data = self.raw_data["tran"][0]["data"]
                if not data: continue
                
                t_vals = np.array([step["time"] for step in data])
                
                # 路由派發 (Dispatcher)
                if m.get("operation"):
                    self._eval_stat(name, m, data)
                elif m.get("find") and m.get("at") is not None:
                    self._eval_find_at(name, m, data, t_vals)
                elif m.get("trig_node") and m.get("targ_node"):
                    self._eval_targ_trig(name, m, data, t_vals)
                else:
                    self.log(f"[WARN] 測量 {name} 缺少必要參數或無法識別模式。")
                    
            except Exception as e:
                self.log(f"[ERR] 計算測量 {name} 失敗: {str(e)}")

    # --- 1. 基礎統計量 (MAX, MIN, PP, RMS, AVG) ---
    def _eval_stat(self, name, m, data):
        op = m.get("operation").upper()
        target = m.get("target", "").upper()
        
        # 🚀 大小寫免疫對照表
        actual_keys = {k.upper(): k for k in data[0].keys()}
        
        if target not in actual_keys:
            self.log(f"[WARN] 測量 {name} 找不到目標變數 {target}，可用變數: {list(data[0].keys())}")
            return
            
        real_target = actual_keys[target]
        vals = np.array([step[real_target] for step in data])
        res_val = 0.0
        
        if op == "MAX": res_val = np.max(vals)
        elif op == "MIN": res_val = np.min(vals)
        elif op == "PP": res_val = np.max(vals) - np.min(vals)
        elif op == "AVG": res_val = np.mean(vals)
        elif op == "RMS": res_val = np.sqrt(np.mean(vals**2))
        else:
            self.log(f"[WARN] 尚未支援的操作: {op}")
            return
            
        self._report(name, op, target, res_val)

    # --- 2. FIND 某變數 AT 特定時間 ---
    def _eval_find_at(self, name, m, data, t_vals):
        target = m["find"].upper()
        at_time = float(m["at"])
        
        actual_keys = {k.upper(): k for k in data[0].keys()}
        if target not in actual_keys:
            self.log(f"[WARN] 測量 {name} 找不到目標變數 {target}，可用變數: {list(data[0].keys())}")
            return
            
        real_target = actual_keys[target]
        y_vals = np.array([step[real_target] for step in data])
        
        # 利用 SciPy 快速一維內插
        interp_func = interp1d(t_vals, y_vals, kind='linear', fill_value="extrapolate")
        res_val = float(interp_func(at_time))
        
        self._report(name, f"FIND AT {at_time}", target, res_val)

    # --- 3. TRIG / TARG 事件測量 (傳輸延遲、上升時間) ---
    def _eval_targ_trig(self, name, m, data, t_vals):
        trig_node = m["trig_node"].upper()
        targ_node = m["targ_node"].upper()
        
        actual_keys = {k.upper(): k for k in data[0].keys()}
        if trig_node not in actual_keys or targ_node not in actual_keys:
            self.log(f"[WARN] 測量 {name} 找不到 TRIG 變數 {trig_node} 或 TARG 變數 {targ_node}。可用變數: {list(data[0].keys())}")
            return
            
        real_trig = actual_keys[trig_node]
        real_targ = actual_keys[targ_node]
        
        y_trig = np.array([step[real_trig] for step in data])
        y_targ = np.array([step[real_targ] for step in data])
        
        # 尋找所有觸發點
        trig_times = self._find_crossings(t_vals, y_trig, float(m.get("trig_val", 0.0)), m.get("trig_dir", "EITHER"))
        targ_times = self._find_crossings(t_vals, y_targ, float(m.get("targ_val", 0.0)), m.get("targ_dir", "EITHER"))
        
        if not trig_times or not targ_times:
            self.log(f"[WARN] {name}: 波形從未跨越指定的 TRIG 或 TARG 電壓值。")
            return
            
        # 根據指定的 cross 次數抓取時間 (預設為第 1 次，index 從 0 開始)
        idx_trig = int(m.get("trig_cross", 1)) - 1
        idx_targ = int(m.get("targ_cross", 1)) - 1
        
        if idx_trig >= len(trig_times) or idx_targ >= len(targ_times):
            self.log(f"[WARN] {name}: 指定的 cross 次數超出了實際發生的次數。")
            return
            
        t1, t2 = trig_times[idx_trig], targ_times[idx_targ]
        self._report(name, f"DELAY {trig_node}->{targ_node}", "", t2 - t1)

    def _report(self, name, op_desc, target, val):
        """格式化輸出 Helper"""
        msg = f"{name} ({op_desc}"
        if target: msg += f" of {target}"
        msg += f"): {val:.5e}"
        self.log(msg)
        self.results[f"MEAS: {name}"] = self.safe_num(val)


    # =================================================================
    # 🌊 .FOUR 傅立葉與 THD 分析 (優化版)
    # =================================================================
    def evaluate_fourier(self):
        fourier_cmds = self.circuit_json.get("fourier", [])
        if not fourier_cmds or not self.raw_data.get("tran"): return

        self.log("\n--- .FOUR Fourier Analysis ---")
        data = self.raw_data["tran"][0]["data"]
        t_vals = np.array([step["time"] for step in data])
        
        if len(t_vals) < 10:
            self.log("[ERR] 暫態資料點過少，無法執行傅立葉轉換。")
            return

        t_start, t_stop = t_vals[0], t_vals[-1]
        sim_time = t_stop - t_start
        num_points = max(len(t_vals), 4096)
        
        # 重採樣到均勻時間軸 (FFT 的剛性需求)
        t_uniform, dt = np.linspace(t_start, t_stop, num_points, retstep=True)
        
        # 🚀 大小寫免疫對照表
        actual_keys = {k.upper(): k for k in data[0].keys()}

        for cmd in fourier_cmds:
            fund_freq = float(cmd.get("freq", 1000.0))
            if 1.0 / sim_time > fund_freq:
                self.log(f"[WARN] 模擬總時間 {sim_time:.2e}s 太短，解析度不足以捕捉基頻 ({fund_freq}Hz)！")

            for target in cmd.get("targets", []):
                target_upper = target.upper()
                if target_upper not in actual_keys:
                    self.log(f"[WARN] .FOUR 找不到目標變數 {target}，可用變數: {list(data[0].keys())}")
                    continue

                real_target = actual_keys[target_upper]
                y_vals = np.array([step[real_target] for step in data])
                interp_func = interp1d(t_vals, y_vals, kind='cubic', fill_value="extrapolate")
                y_uniform = interp_func(t_uniform)

                # 執行實數 FFT
                fft_y = np.fft.rfft(y_uniform)
                fft_f = np.fft.rfftfreq(num_points, d=dt)
                
                # 計算振幅 (DC 分量特別除以 2)
                mag = np.abs(fft_y) * 2.0 / num_points
                mag[0] /= 2.0 
                
                self.log(f"\nFourier analysis for {real_target}:")
                self.log(f"  DC component = {mag[0]:.5e}")
                
                harmonics = []
                for i in range(1, 10):
                    target_f = fund_freq * i
                    idx = (np.abs(fft_f - target_f)).argmin()
                    
                    h_mag = mag[idx]
                    phase = np.angle(fft_y[idx], deg=True)
                    harmonics.append((h_mag, phase))
                    
                    norm_mag = h_mag / harmonics[0][0] if harmonics[0][0] != 0 else 0
                    self.log(f"  Harmonic {i:<2}: {target_f:<8.1f}Hz | Mag: {h_mag:.5e} | Norm: {norm_mag:.5f} | Phase: {phase:>7.2f}°")

                # 計算總諧波失真 (THD)
                v1 = harmonics[0][0]
                if v1 > 0:
                    sum_sq = np.sum([h[0]**2 for h in harmonics[1:]])
                    thd = (np.sqrt(sum_sq) / v1) * 100.0
                    self.log(f"  Total Harmonic Distortion (THD) = {thd:.4f} %")
                    self.results[f"THD({real_target})"] = self.safe_num(thd)
                else:
                    self.log("  [WARN] 基頻振幅過小，無法計算 THD。")