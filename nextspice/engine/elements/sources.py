from .base import BaseElement
from .waveforms import compile_waveform
import math
import cmath

class VoltageSource(BaseElement):
    def __init__(self, name, n1, n2, dc_value=0.0, ac_mag=None, ac_phase=0.0, tran=None):
        super().__init__(name)
        self.n1, self.n2 = n1, n2
        self.dc_value = float(dc_value) if dc_value is not None else 0.0
        self.ac_mag = float(ac_mag) if ac_mag is not None else 0.0
        self.ac_phase = float(ac_phase) if ac_phase is not None else 0.0
        self.extra_vars = 1
        
        # 🚀 統一：預編譯波形
        self.waveform = compile_waveform(tran, self.dc_value)

    def stamp(self, A, b, extra_idx=None, ctx=None):
        if self.n1 > 0:
            A[self.n1-1, extra_idx] += 1.0
            A[extra_idx, self.n1-1] += 1.0
        if self.n2 > 0:
            A[self.n2-1, extra_idx] -= 1.0
            A[extra_idx, self.n2-1] -= 1.0
            
        # ❗ 致命 Bug 修復：全部改為 += (Superposition)
        if ctx.mode == 'ac':
            phase_rad = math.radians(self.ac_phase)
            b[extra_idx] += self.ac_mag * cmath.exp(1j * phase_rad)
        elif ctx.mode == 'tran':
            b[extra_idx] += self.waveform.eval(ctx.t)
        else:
            b[extra_idx] += self.dc_value

class CurrentSource(BaseElement):
    def __init__(self, name, n1, n2, dc_value=0.0, ac_mag=None, ac_phase=0.0, tran=None):
        super().__init__(name)
        self.n1, self.n2 = n1, n2
        self.dc_value = float(dc_value) if dc_value is not None else 0.0
        self.ac_mag = float(ac_mag) if ac_mag is not None else 0.0
        self.ac_phase = float(ac_phase) if ac_phase is not None else 0.0
        
        # 🚀 統一：預編譯波形
        self.waveform = compile_waveform(tran, self.dc_value)

    def stamp(self, A, b, extra_idx=None, ctx=None):
        # 🚀 統一：強型別 Context + Waveform Eval
        if ctx.mode == 'ac':
            phase_rad = math.radians(self.ac_phase)
            val = self.ac_mag * cmath.exp(1j * phase_rad)
        elif ctx.mode == 'tran':
            val = self.waveform.eval(ctx.t)
        else:
            val = self.dc_value

        # MNA 節點電流注入本來就是 += 和 -=
        if self.n1 > 0: b[self.n1-1] -= val
        if self.n2 > 0: b[self.n2-1] += val

