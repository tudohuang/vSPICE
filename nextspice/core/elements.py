import numpy as np
import math
import cmath

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

    def stamp(self, A, b, extra_idx=None, ctx=None):
        if ctx and 'freq' in ctx:
            omega = 2.0 * math.pi * ctx['freq']
            y_c = complex(0, omega * self.value)
            for i, j in [(self.n1, self.n1), (self.n2, self.n2)]:
                if i > 0 and j > 0: A[i-1, j-1] += y_c
            for i, j in [(self.n1, self.n2), (self.n2, self.n1)]:
                if i > 0 and j > 0: A[i-1, j-1] -= y_c

class VoltageSource(BaseElement):
    def __init__(self, name, n1, n2, dc_value=0.0, ac_mag=None, ac_phase=0.0, tran=None):
        super().__init__(name)
        self.n1, self.n2 = n1, n2
        self.dc_value = float(dc_value) if dc_value is not None else 0.0
        self.ac_mag = float(ac_mag) if ac_mag is not None else 0.0
        self.ac_phase = float(ac_phase) if ac_phase is not None else 0.0
        self.extra_vars = 1

    def stamp(self, A, b, extra_idx, ctx=None):
        if self.n1 > 0:
            A[self.n1-1, extra_idx] += 1.0
            A[extra_idx, self.n1-1] += 1.0
        if self.n2 > 0:
            A[self.n2-1, extra_idx] -= 1.0
            A[extra_idx, self.n2-1] -= 1.0
            
        # 判斷是注入 DC 還是 AC (相量)
        if ctx and 'freq' in ctx:
            phase_rad = math.radians(self.ac_phase)
            phasor = self.ac_mag * cmath.exp(1j * phase_rad)
            b[extra_idx] = phasor
        else:
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