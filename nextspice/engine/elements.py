import numpy as np
import math
import cmath
import re
from nextspice.utils.unit_conv import UnitConverter as unit_conv

# --- 🚀 共用的波形計算核心 ---
def eval_source_waveform(tran_str, dc_value, t):
    """根據當下時間 t，計算時域波形的瞬間數值 (電壓或電流共用)"""
    if not tran_str:
        return dc_value

    tran_upper = tran_str.upper()
    
    match = re.search(r'\((.*?)\)', tran_upper)
    if not match:
        return dc_value
        
    raw_args = match.group(1).replace(',', ' ').split()
    args = [unit_conv.parse(x) for x in raw_args if x.strip()]

    # === 1. 正弦波 SIN(VO VA FREQ TD THETA) ===
    if tran_upper.startswith("SIN"):
        vo = args[0] if len(args) > 0 else 0.0       # DC 偏移量
        va = args[1] if len(args) > 1 else 0.0       # 振幅
        freq = args[2] if len(args) > 2 else 0.0     # 頻率
        td = args[3] if len(args) > 3 else 0.0       # 延遲時間
        theta = args[4] if len(args) > 4 else 0.0    # 阻尼系數
        
        if t < td:
            return vo
        else:
            return vo + va * math.exp(-theta * (t - td)) * math.sin(2 * math.pi * freq * (t - td))

    # === 2. 脈衝方波 PULSE(V1 V2 TD TR TF PW PER) ===
    elif tran_upper.startswith("PULSE"):
        v1 = args[0] if len(args) > 0 else 0.0       # 初始值
        v2 = args[1] if len(args) > 1 else 0.0       # 脈衝值
        td = args[2] if len(args) > 2 else 0.0       # 延遲時間
        tr = args[3] if len(args) > 3 else 0.0       # 上升時間
        tf = args[4] if len(args) > 4 else 0.0       # 下降時間
        pw = args[5] if len(args) > 5 else 1.0       # 脈衝寬度
        per = args[6] if len(args) > 6 else 1.0      # 週期

        if t < td:
            return v1

        t_cycle = (t - td) % per if per > 0 else (t - td)

        if t_cycle < tr:
            return v1 + (v2 - v1) * (t_cycle / tr) if tr > 0 else v2
        elif t_cycle < tr + pw:
            return v2
        elif t_cycle < tr + pw + tf:
            return v2 - (v2 - v1) * ((t_cycle - tr - pw) / tf) if tf > 0 else v1
        else:
            return v1

    # 🚀 === 3. 任意分段線性波形 PWL(T1 V1 T2 V2 T3 V3 ...) ===
    elif tran_upper.startswith("PWL"):
        # 至少要有兩個數字才構成一個座標點
        if len(args) < 2:
            return dc_value

        # 將一維陣列轉換為 (時間, 電壓/電流) 座標對陣列
        pts = [(args[i], args[i+1]) for i in range(0, len(args)-1, 2)]
        
        if not pts:
            return dc_value

        # 狀態 1：時間還沒到第一個點，保持第一個點的數值
        if t <= pts[0][0]:
            return pts[0][1]
            
        # 狀態 2：時間已經超過最後一個點，保持最後一個點的數值
        if t >= pts[-1][0]:
            return pts[-1][1]
            
        # 狀態 3：時間落在中間，尋找對應的區間進行「線性內插」
        for i in range(len(pts) - 1):
            t1, v1 = pts[i]
            t2, v2 = pts[i+1]
            
            if t1 <= t <= t2:
                # 防呆：如果兩個點時間一樣 (垂直線)，直接回傳後面的值避免除以零
                if t2 == t1:
                    return v2
                # 線性內插公式：V(t) = V1 + (V2 - V1) * (t - t1) / (t2 - t1)
                return v1 + (v2 - v1) * (t - t1) / (t2 - t1)

    return dc_value

# ==============================================================

class BaseElement:
    def __init__(self, name):
        self.name = name
        self.extra_vars = 0

    def stamp(self, A, b, extra_idx=None, ctx=None):
        raise NotImplementedError

class Resistor(BaseElement):
    def __init__(self, name, n1, n2, value):
        super().__init__(name)
        self.n1, self.n2 = n1, n2
        self.value = float(value)
        # 🚀 嚴格防呆：禁止 0 或負電阻 (除非未來引擎支援負阻抗)
        if self.value <= 0:
            raise ValueError(f"Resistor {self.name} has invalid value {self.value}. Value must be > 0.")

    def stamp(self, A, b, extra_idx=None, ctx=None):
        g = 1.0 / self.value # 🚀 移除了 1e-30 的掩耳盜鈴
        for i, j in [(self.n1, self.n1), (self.n2, self.n2)]:
            if i > 0 and j > 0: A[i-1, j-1] += g
        for i, j in [(self.n1, self.n2), (self.n2, self.n1)]:
            if i > 0 and j > 0: A[i-1, j-1] -= g

class Capacitor(BaseElement):
    def __init__(self, name, n1, n2, value):
        super().__init__(name)
        self.n1, self.n2 = n1, n2
        self.value = float(value)
        if self.value < 0:
            raise ValueError(f"Capacitor {self.name} cannot have a negative value.")
        self.v_prev = 0.0 

    def stamp(self, A, b, extra_idx=None, ctx=None):
        mode = ctx.get('mode', 'op') if ctx else 'op'
        
        if mode == 'ac':
            freq = ctx.get('freq', 1.0)
            omega = 2.0 * math.pi * freq
            y_c = complex(0, omega * self.value)
            for i, j in [(self.n1, self.n1), (self.n2, self.n2)]:
                if i > 0 and j > 0: A[i-1, j-1] += y_c
            for i, j in [(self.n1, self.n2), (self.n2, self.n1)]:
                if i > 0 and j > 0: A[i-1, j-1] -= y_c
                
        elif mode == 'tran':
            dt = ctx.get('dt', 1e-9) 
            g_eq = self.value / dt
            i_hist = g_eq * self.v_prev
            
            for i, j in [(self.n1, self.n1), (self.n2, self.n2)]:
                if i > 0 and j > 0: A[i-1, j-1] += g_eq
            for i, j in [(self.n1, self.n2), (self.n2, self.n1)]:
                if i > 0 and j > 0: A[i-1, j-1] -= g_eq
                
            if self.n1 > 0: b[self.n1-1] += i_hist
            if self.n2 > 0: b[self.n2-1] -= i_hist
            
        else:
            pass # DC open circuit

    def update_history(self, x, extra_idx=None):
        v_p = x[self.n1 - 1] if self.n1 > 0 else 0.0
        v_n = x[self.n2 - 1] if self.n2 > 0 else 0.0
        self.v_prev = v_p - v_n


class VoltageSource(BaseElement):
    def __init__(self, name, n1, n2, dc_value=0.0, ac_mag=None, ac_phase=0.0, tran=None):
        super().__init__(name)
        self.n1, self.n2 = n1, n2
        self.dc_value = float(dc_value) if dc_value is not None else 0.0
        self.ac_mag = float(ac_mag) if ac_mag is not None else 0.0
        self.ac_phase = float(ac_phase) if ac_phase is not None else 0.0
        self.tran = tran
        self.extra_vars = 1

    def _eval_tran_voltage(self, t):
        # 🚀 呼叫共用函數
        return eval_source_waveform(self.tran, self.dc_value, t)

    def stamp(self, A, b, extra_idx, ctx=None):
        if self.n1 > 0:
            A[self.n1-1, extra_idx] += 1.0
            A[extra_idx, self.n1-1] += 1.0
        if self.n2 > 0:
            A[self.n2-1, extra_idx] -= 1.0
            A[extra_idx, self.n2-1] -= 1.0
            
        mode = ctx.get('mode', 'op') if ctx else 'op'
            
        if mode == 'ac':
            phase_rad = math.radians(self.ac_phase)
            b[extra_idx] = self.ac_mag * cmath.exp(1j * phase_rad)
        elif mode == 'tran':
            t = ctx.get('t', 0.0)
            b[extra_idx] = self._eval_tran_voltage(t)
        else:
            b[extra_idx] = self.dc_value


class CurrentSource(BaseElement):
    def __init__(self, name, n1, n2, dc_value=0.0, ac_mag=None, ac_phase=0.0, tran=None):
        super().__init__(name)
        self.n1, self.n2 = n1, n2
        self.dc_value = float(dc_value) if dc_value is not None else 0.0
        self.ac_mag = float(ac_mag) if ac_mag is not None else 0.0
        self.ac_phase = float(ac_phase) if ac_phase is not None else 0.0
        self.tran = tran # 🚀 補齊 tran 屬性

    def _eval_tran_current(self, t):
        # 🚀 呼叫共用函數，電流源現在也有脈衝和正弦波能力了！
        return eval_source_waveform(self.tran, self.dc_value, t)

    def stamp(self, A, b, extra_idx=None, ctx=None):
        mode = ctx.get('mode', 'op') if ctx else 'op'
        
        # 🚀 統一介面契約：不再用 'freq' in ctx 當作判斷依據
        if mode == 'ac':
            phase_rad = math.radians(self.ac_phase)
            val = self.ac_mag * cmath.exp(1j * phase_rad)
        elif mode == 'tran':
            t = ctx.get('t', 0.0)
            val = self._eval_tran_current(t)
        else:
            val = self.dc_value

        if self.n1 > 0: b[self.n1-1] -= val
        if self.n2 > 0: b[self.n2-1] += val


class Inductor(BaseElement):
    def __init__(self, name, n1, n2, value):
        super().__init__(name)
        self.n1, self.n2 = n1, n2
        self.value = float(value)
        if self.value < 0:
            raise ValueError(f"Inductor {self.name} cannot have a negative value.")
        self.extra_vars = 1 
        self.i_prev = 0.0   

    def stamp(self, A, b, extra_idx, ctx=None):
        if self.n1 > 0:
            A[self.n1-1, extra_idx] += 1.0
            A[extra_idx, self.n1-1] += 1.0
        if self.n2 > 0:
            A[self.n2-1, extra_idx] -= 1.0
            A[extra_idx, self.n2-1] -= 1.0

        mode = ctx.get('mode', 'op') if ctx else 'op'

        if mode == 'ac':
            freq = ctx.get('freq', 1.0)
            omega = 2.0 * math.pi * freq
            A[extra_idx, extra_idx] -= complex(0, omega * self.value)

        elif mode == 'tran':
            dt = ctx.get('dt', 1e-9)
            r_eq = self.value / dt
            v_hist = -r_eq * self.i_prev
            A[extra_idx, extra_idx] -= r_eq
            b[extra_idx] += v_hist
        else:
            b[extra_idx] = 0.0

    def update_history(self, x, extra_idx=None):
        if extra_idx is not None:
            self.i_prev = x[extra_idx]


class MutualInductance(BaseElement):
    def __init__(self, name, l1_obj, l2_obj, k_value):
        super().__init__(name)
        self.l1_obj = l1_obj
        self.l2_obj = l2_obj
        self.k = float(k_value)
        if not (-1.0 <= self.k <= 1.0):
            raise ValueError(f"Coupling coefficient k for {self.name} must be between -1 and 1.")
        self.extra_vars = 0 
        self.M = self.k * math.sqrt(self.l1_obj.value * self.l2_obj.value)

    def stamp(self, A, b, extra_idx=None, ctx=None):
        extra_map = ctx.get('extra_map', {})
        idx1 = extra_map.get(self.l1_obj)
        idx2 = extra_map.get(self.l2_obj)

        if idx1 is None or idx2 is None:
            return

        mode = ctx.get('mode', 'op')

        if mode == 'ac':
            freq = ctx.get('freq', 1.0)
            omega = 2.0 * math.pi * freq
            zm = complex(0, omega * self.M)
            A[idx1, idx2] -= zm
            A[idx2, idx1] -= zm

        elif mode == 'tran':
            dt = ctx.get('dt', 1e-9)
            rm = self.M / dt
            A[idx1, idx2] -= rm
            A[idx2, idx1] -= rm
            b[idx1] += -rm * self.l2_obj.i_prev
            b[idx2] += -rm * self.l1_obj.i_prev
        else:
            pass


class VCVS(BaseElement):
    def __init__(self, name, np, nn, cp, cn, gain):
        super().__init__(name)
        self.n_out_p, self.n_out_n = np, nn
        self.n_in_p, self.n_in_n = cp, cn
        self.gain = float(gain)
        self.extra_vars = 1

    def stamp(self, A, b, extra_idx, ctx=None):
        if self.n_out_p > 0:
            A[self.n_out_p-1, extra_idx] += 1.0
            A[extra_idx, self.n_out_p-1] += 1.0
        if self.n_out_n > 0:
            A[self.n_out_n-1, extra_idx] -= 1.0
            A[extra_idx, self.n_out_n-1] -= 1.0
        if self.n_in_p > 0: A[extra_idx, self.n_in_p-1] -= self.gain
        if self.n_in_n > 0: A[extra_idx, self.n_in_n-1] += self.gain


class VCCS(BaseElement):
    def __init__(self, name, np, nn, cp, cn, transconductance):
        super().__init__(name)
        self.np, self.nn = np, nn
        self.cp, self.cn = cp, cn
        self.g = float(transconductance)

    def stamp(self, A, b, extra_idx=None, ctx=None):
        if self.np > 0 and self.cp > 0: A[self.np-1, self.cp-1] += self.g
        if self.np > 0 and self.cn > 0: A[self.np-1, self.cn-1] -= self.g
        if self.nn > 0 and self.cp > 0: A[self.nn-1, self.cp-1] -= self.g
        if self.nn > 0 and self.cn > 0: A[self.nn-1, self.cn-1] += self.g


class CCVS(BaseElement):
    def __init__(self, name, np, nn, ctrl_source, transresistance):
        super().__init__(name)
        self.np, self.nn = np, nn
        self.ctrl_source = ctrl_source.upper() 
        self.rm = float(transresistance)
        self.extra_vars = 1

    def stamp(self, A, b, extra_idx, ctx=None):
        ctrl_idx = ctx.get('extra_by_name', {}).get(self.ctrl_source)
        if ctrl_idx is None:
            raise ValueError(f"Controlling source '{self.ctrl_source}' not found for {self.name}")

        if self.np > 0:
            A[self.np-1, extra_idx] += 1.0
            A[extra_idx, self.np-1] += 1.0
        if self.nn > 0:
            A[self.nn-1, extra_idx] -= 1.0
            A[extra_idx, self.nn-1] -= 1.0
        
        A[extra_idx, ctrl_idx] -= self.rm


class CCCS(BaseElement):
    def __init__(self, name, np, nn, ctrl_source, gain):
        super().__init__(name)
        self.np, self.nn = np, nn
        self.ctrl_source = ctrl_source.upper()
        self.gain = float(gain)

    def stamp(self, A, b, extra_idx=None, ctx=None):
        ctrl_idx = ctx.get('extra_by_name', {}).get(self.ctrl_source)
        if ctrl_idx is None:
            raise ValueError(f"Controlling source '{self.ctrl_source}' not found for {self.name}")
        
        if self.np > 0: A[self.np-1, ctrl_idx] += self.gain
        if self.nn > 0: A[self.nn-1, ctrl_idx] -= self.gain