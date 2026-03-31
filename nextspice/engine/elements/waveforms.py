import re
import math
from nextspice.utils.unit_conv import UnitConverter as unit_conv

class BaseWaveform:
    """波形物件基底類別"""
    def eval(self, t):
        raise NotImplementedError("Subclasses must implement eval(t)")

class DCWaveform(BaseWaveform):
    """純直流波形 (Fallback 預設值)"""
    def __init__(self, value):
        self.value = float(value)
        
    def eval(self, t):
        return self.value

class SinWaveform(BaseWaveform):
    """正弦波 SIN(VO VA FREQ TD THETA)"""
    def __init__(self, vo, va, freq, td, theta):
        self.vo = float(vo)
        self.va = float(va)
        self.freq = float(freq)
        self.td = float(td)
        self.theta = float(theta)

    def eval(self, t):
        if t < self.td:
            return self.vo
        return self.vo + self.va * math.exp(-self.theta * (t - self.td)) * math.sin(2 * math.pi * self.freq * (t - self.td))

class PulseWaveform(BaseWaveform):
    """脈衝波 PULSE(V1 V2 TD TR TF PW PER)"""
    def __init__(self, v1, v2, td, tr, tf, pw, per):
        self.v1 = float(v1)
        self.v2 = float(v2)
        self.td = float(td)
        self.tr = float(tr)
        self.tf = float(tf)
        self.pw = float(pw)
        self.per = float(per)

    def eval(self, t):
        if t < self.td:
            return self.v1

        t_cycle = (t - self.td) % self.per if self.per > 0 else (t - self.td)

        if t_cycle < self.tr:
            return self.v1 + (self.v2 - self.v1) * (t_cycle / self.tr) if self.tr > 0 else self.v2
        elif t_cycle < self.tr + self.pw:
            return self.v2
        elif t_cycle < self.tr + self.pw + self.tf:
            return self.v2 - (self.v2 - self.v1) * ((t_cycle - self.tr - self.pw) / self.tf) if self.tf > 0 else self.v1
        else:
            return self.v1

class PwlWaveform(BaseWaveform):
    """分段線性波形 PWL(T1 V1 T2 V2 ...)"""
    def __init__(self, pts):
        # 預先算好並儲存座標對，eval 時完全不用再切陣列
        self.pts = pts
        
    def eval(self, t):
        if t <= self.pts[0][0]:
            return self.pts[0][1]
            
        if t >= self.pts[-1][0]:
            return self.pts[-1][1]
            
        for i in range(len(self.pts) - 1):
            t1, v1 = self.pts[i]
            t2, v2 = self.pts[i+1]
            
            if t1 <= t <= t2:
                if t2 == t1:
                    return v2
                return v1 + (v2 - v1) * (t - t1) / (t2 - t1)
                
        return self.pts[-1][1]

# =====================================================================
# 🛠️ 波形編譯器 (Factory) - 整個模擬只會在初始化時跑一次！
# =====================================================================

def _ensure_numeric(raw_args, wtype):
    """將字串陣列轉換為浮點數陣列，並透過 UnitConverter 展開 k, m, u 等單位"""
    numeric_args = []
    for x in raw_args:
        val = unit_conv.parse(x)
        if not isinstance(val, (int, float)):
            raise ValueError(f"[{wtype}] 遇到無法解析的非數值參數: '{x}'。請確認變數是否已在 Parser 階段完全展開。")
        numeric_args.append(float(val))
    return numeric_args

def compile_waveform(tran_str, dc_value):
    """
    將 SPICE 波形字串「編譯」為高效能的波形物件。
    """
    if not tran_str:
        return DCWaveform(dc_value)

    tran_upper = tran_str.upper()
    
    match = re.search(r'\((.*?)\)', tran_upper)
    if not match:
        return DCWaveform(dc_value)
        
    raw_args = match.group(1).replace(',', ' ').split()
    if not raw_args:
        return DCWaveform(dc_value)

    # === 根據波形前綴進行路由與編譯 ===
    if tran_upper.startswith("SIN"):
        args = _ensure_numeric(raw_args, "SIN")
        args += [0.0] * (5 - len(args))  # 自動補齊缺少的預設值
        return SinWaveform(*args[:5])
        
    elif tran_upper.startswith("PULSE"):
        args = _ensure_numeric(raw_args, "PULSE")
        args += [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0]  # 自動補齊
        return PulseWaveform(*args[:7])
        
    elif tran_upper.startswith("PWL"):
        args = _ensure_numeric(raw_args, "PWL")
        if len(args) % 2 != 0:
            raise ValueError(f"[PWL] 參數必須是成對的 (時間, 數值)，但目前解析出 {len(args)} 個參數: {raw_args}")
        if len(args) < 2:
            return DCWaveform(dc_value)
            
        pts = [(args[i], args[i+1]) for i in range(0, len(args)-1, 2)]
        return PwlWaveform(pts)

    return DCWaveform(dc_value)