import numpy as np
import math
import cmath
import re
from .unit_conv import UnitConverter as unit_conv
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

    def stamp(self, A, b, extra_idx=None, ctx=None):
        g = 1.0 / (self.value + 1e-30)
        for i, j in [(self.n1, self.n1), (self.n2, self.n2)]:
            if i > 0 and j > 0: A[i-1, j-1] += g
        for i, j in [(self.n1, self.n2), (self.n2, self.n1)]:
            if i > 0 and j > 0: A[i-1, j-1] -= g

class Capacitor(BaseElement):
    def __init__(self, name, n1, n2, value):
        super().__init__(name)
        self.n1, self.n2 = n1, n2
        self.value = float(value)
        # 新增：用來記憶上一個時間點的跨壓 (v_{n-1})
        self.v_prev = 0.0 

    def stamp(self, A, b, extra_idx=None, ctx=None):
        mode = ctx.get('mode', 'op') if ctx else 'op'
        
        if mode == 'ac':
            # --- AC 交流分析 (複數頻域) ---
            freq = ctx.get('freq', 1.0)
            omega = 2.0 * math.pi * freq
            y_c = complex(0, omega * self.value)
            for i, j in [(self.n1, self.n1), (self.n2, self.n2)]:
                if i > 0 and j > 0: A[i-1, j-1] += y_c
            for i, j in [(self.n1, self.n2), (self.n2, self.n1)]:
                if i > 0 and j > 0: A[i-1, j-1] -= y_c
                
        elif mode == 'tran':
            # --- TRAN 暫態分析 (Backward Euler 伴隨模型) ---
            dt = ctx.get('dt', 1e-9)  # 取得時間步長 Δt
            
            # 1. 算出等效電導 G_eq = C / Δt
            g_eq = self.value / dt
            
            # 2. 算出歷史等效電流源 I_hist = G_eq * v_{n-1}
            i_hist = g_eq * self.v_prev
            
            # 蓋章：把等效電導塞進 A 矩陣 (跟電阻一模一樣的蓋法)
            for i, j in [(self.n1, self.n1), (self.n2, self.n2)]:
                if i > 0 and j > 0: A[i-1, j-1] += g_eq
            for i, j in [(self.n1, self.n2), (self.n2, self.n1)]:
                if i > 0 and j > 0: A[i-1, j-1] -= g_eq
                
            # 蓋章：把歷史電流源塞進 b 向量 (RHS)
            if self.n1 > 0: b[self.n1-1] += i_hist
            if self.n2 > 0: b[self.n2-1] -= i_hist
            
        else:
            # --- OP / DC 分析 ---
            # 電容在 DC 下是斷路 (Open Circuit)，所以矩陣什麼都不用加
            pass

    def update_history(self, x, extra_idx=None):
        # 電容不需要 extra_idx，但必須接收它以符合統一介面 (Duck Typing)
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
        self.tran = tran  # 儲存波形字串，例如 "SIN(0 5 1k)" 或 "PULSE(0 5 1u 1n 1n 5u 10u)"
        self.extra_vars = 1

    def _eval_tran_voltage(self, t):
        """根據當下時間 t，計算時域波形的瞬間電壓"""
        if not self.tran:
            return self.dc_value  # 如果沒設定波形，就當純 DC 電池

        tran_upper = self.tran.upper()
        
        # 提取括號內的參數字串並用 UnitConverter 轉換
        match = re.search(r'\((.*?)\)', tran_upper)
        if not match:
            return self.dc_value
            
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
                # v(t) = VO + VA * e^(-theta*(t-td)) * sin(2*pi*f*(t-td))
                return vo + va * math.exp(-theta * (t - td)) * math.sin(2 * math.pi * freq * (t - td))

        # === 2. 脈衝方波 PULSE(V1 V2 TD TR TF PW PER) ===
        elif tran_upper.startswith("PULSE"):
            v1 = args[0] if len(args) > 0 else 0.0       # 初始值 (Low)
            v2 = args[1] if len(args) > 1 else 0.0       # 脈衝值 (High)
            td = args[2] if len(args) > 2 else 0.0       # 延遲時間
            tr = args[3] if len(args) > 3 else 0.0       # 上升時間 (Rise)
            tf = args[4] if len(args) > 4 else 0.0       # 下降時間 (Fall)
            pw = args[5] if len(args) > 5 else 1.0       # 脈衝寬度 (Width)
            per = args[6] if len(args) > 6 else 1.0      # 週期 (Period)

            if t < td:
                return v1

            # 透過取餘數 (Modulo)，算出在當前週期內的相對時間
            t_cycle = (t - td) % per if per > 0 else (t - td)

            if t_cycle < tr:
                # 處於上升沿 (斜率爬升)
                return v1 + (v2 - v1) * (t_cycle / tr) if tr > 0 else v2
            elif t_cycle < tr + pw:
                # 處於脈衝頂部 (High plateau)
                return v2
            elif t_cycle < tr + pw + tf:
                # 處於下降沿 (斜率下降)
                return v2 - (v2 - v1) * ((t_cycle - tr - pw) / tf) if tf > 0 else v1
            else:
                # 處於谷底 (Off phase)
                return v1

        return self.dc_value

    def stamp(self, A, b, extra_idx, ctx=None):
        if self.n1 > 0:
            A[self.n1-1, extra_idx] += 1.0
            A[extra_idx, self.n1-1] += 1.0
        if self.n2 > 0:
            A[self.n2-1, extra_idx] -= 1.0
            A[extra_idx, self.n2-1] -= 1.0
            
        # 從 Context 中取得當前分析模式，預設為 op
        mode = ctx.get('mode', 'op') if ctx else 'op'
            
        if mode == 'ac':
            # 交流分析：蓋上複數相量
            phase_rad = math.radians(self.ac_phase)
            phasor = self.ac_mag * cmath.exp(1j * phase_rad)
            b[extra_idx] = phasor
            
        elif mode == 'tran':
            # 暫態分析：從 context 拿當前時間 t，計算瞬間電壓並蓋上
            t = ctx.get('t', 0.0)
            b[extra_idx] = self._eval_tran_voltage(t)
            
        else:
            # OP 或 DC Sweep：蓋上純直流值
            b[extra_idx] = self.dc_value




class CurrentSource(BaseElement):
    def __init__(self, name, n1, n2, dc_value=0.0, ac_mag=None, ac_phase=0.0, tran=None):
        super().__init__(name)
        self.n1, self.n2 = n1, n2
        self.dc_value = float(dc_value) if dc_value is not None else 0.0
        self.ac_mag = float(ac_mag) if ac_mag is not None else 0.0
        self.ac_phase = float(ac_phase) if ac_phase is not None else 0.0

    def stamp(self, A, b, extra_idx=None, ctx=None):
        if ctx and 'freq' in ctx:
            phase_rad = math.radians(self.ac_phase)
            val = self.ac_mag * cmath.exp(1j * phase_rad)
        else:
            val = self.dc_value

        if self.n1 > 0: b[self.n1-1] -= val
        if self.n2 > 0: b[self.n2-1] += val

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


class Inductor(BaseElement):
    def __init__(self, name, n1, n2, value):
        super().__init__(name)
        self.n1, self.n2 = n1, n2
        self.value = float(value)
        # 關鍵 1：電感需要像電壓源一樣，拿一個額外變數來解電流
        self.extra_vars = 1 
        # 關鍵 2：記憶上一個時間點的電流 (i_{n-1})
        self.i_prev = 0.0   

    def stamp(self, A, b, extra_idx, ctx=None):
        # --- KCL / KVL 基礎拓撲 ---
        # 跟電壓源一樣，把「支路電流」注入到 n1 和 n2 節點
        if self.n1 > 0:
            A[self.n1-1, extra_idx] += 1.0
            A[extra_idx, self.n1-1] += 1.0
        if self.n2 > 0:
            A[self.n2-1, extra_idx] -= 1.0
            A[extra_idx, self.n2-1] -= 1.0

        mode = ctx.get('mode', 'op') if ctx else 'op'

        if mode == 'ac':
            # --- AC 交流分析 (阻抗 Z = jωL) ---
            freq = ctx.get('freq', 1.0)
            omega = 2.0 * math.pi * freq
            # 方程式: V1 - V2 - jωL * I = 0
            A[extra_idx, extra_idx] -= complex(0, omega * self.value)

        elif mode == 'tran':
            # --- TRAN 暫態分析 (Backward Euler 伴隨模型) ---
            dt = ctx.get('dt', 1e-9)
            
            # 1. 算出等效電阻 R_eq = L / Δt
            r_eq = self.value / dt
            
            # 2. 算出歷史等效電壓源 V_hist = -R_eq * i_{n-1}
            v_hist = -r_eq * self.i_prev
            
            # 方程式: V1 - V2 - R_eq * I_n = V_hist
            A[extra_idx, extra_idx] -= r_eq
            b[extra_idx] += v_hist

        else:
            b[extra_idx] = 0.0

    def update_history(self, x, extra_idx=None):
        # 電感必須依賴 extra_idx 來抓取自己流過的歷史電流
        if extra_idx is not None:
            self.i_prev = x[extra_idx]


class MutualInductance(BaseElement):
    def __init__(self, name, l1_obj, l2_obj, k_value):
        super().__init__(name)
        self.l1_obj = l1_obj
        self.l2_obj = l2_obj
        self.k = float(k_value)
        # 不增加額外變數，它寄生在 l1 和 l2 的 extra_idx 上
        self.extra_vars = 0 
        # 計算互感量 M = k * sqrt(L1 * L2)
        self.M = self.k * math.sqrt(self.l1_obj.value * self.l2_obj.value)

    def stamp(self, A, b, extra_idx=None, ctx=None):
        # 從 ctx 中取得 L1 和 L2 在矩陣中的變數索引
        extra_map = ctx.get('extra_map', {})
        idx1 = extra_map.get(self.l1_obj)
        idx2 = extra_map.get(self.l2_obj)

        # 如果找不到對應的電感，就無法計算互感
        if idx1 is None or idx2 is None:
            return

        mode = ctx.get('mode', 'op')

        if mode == 'ac':
            # --- AC 分析：非對角線阻抗 ---
            freq = ctx.get('freq', 1.0)
            omega = 2.0 * math.pi * freq
            zm = complex(0, omega * self.M)
            
            # 互相注入阻抗
            A[idx1, idx2] -= zm
            A[idx2, idx1] -= zm

        elif mode == 'tran':
            # --- TRAN 分析：交叉歷史電壓源 ---
            dt = ctx.get('dt', 1e-9)
            rm = self.M / dt
            
            # 1. 蓋入等效交叉電阻 (A 矩陣非對角線)
            A[idx1, idx2] -= rm
            A[idx2, idx1] -= rm
            
            # 2. 蓋入歷史干擾電壓源 (RHS 向量)
            # L1 受到 L2 上一步電流的干擾
            b[idx1] += -rm * self.l2_obj.i_prev
            # L2 受到 L1 上一步電流的干擾
            b[idx2] += -rm * self.l1_obj.i_prev

        else:
            # OP / DC：DC 狀態下互感沒有任何作用（di/dt = 0）
            pass


class VCCS(BaseElement):
    """壓控電流源 (G)"""
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
    """流控電壓源 (H)"""
    def __init__(self, name, np, nn, ctrl_source, transresistance):
        super().__init__(name)
        self.np, self.nn = np, nn
        self.ctrl_source = ctrl_source.upper() # 控制源名稱 (例如 V1)
        self.rm = float(transresistance)
        self.extra_vars = 1

    def stamp(self, A, b, extra_idx, ctx=None):
        # 從 ctx 取得控制電壓源的矩陣索引
        ctrl_idx = ctx.get('extra_by_name', {}).get(self.ctrl_source)
        if ctrl_idx is None:
            raise ValueError(f"Controlling source '{self.ctrl_source}' not found for {self.name}")

        if self.np > 0:
            A[self.np-1, extra_idx] += 1.0
            A[extra_idx, self.np-1] += 1.0
        if self.nn > 0:
            A[self.nn-1, extra_idx] -= 1.0
            A[extra_idx, self.nn-1] -= 1.0
        
        # 核心：流控關係 V_out = Rm * I_ctrl
        A[extra_idx, ctrl_idx] -= self.rm

class CCCS(BaseElement):
    """流控電流源 (F)"""
    def __init__(self, name, np, nn, ctrl_source, gain):
        super().__init__(name)
        self.np, self.nn = np, nn
        self.ctrl_source = ctrl_source.upper()
        self.gain = float(gain)

    def stamp(self, A, b, extra_idx=None, ctx=None):
        ctrl_idx = ctx.get('extra_by_name', {}).get(self.ctrl_source)
        if ctrl_idx is None:
            raise ValueError(f"Controlling source '{self.ctrl_source}' not found for {self.name}")
        
        # 注入電流 I_out = gain * I_ctrl
        if self.np > 0: A[self.np-1, ctrl_idx] += self.gain
        if self.nn > 0: A[self.nn-1, ctrl_idx] -= self.gain