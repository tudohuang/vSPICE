from .base import BaseElement

class VCVS(BaseElement):
    """
    電壓控制電壓源 (E)
    方程式: V_out+ - V_out- - E * (V_in+ - V_in-) = 0
    引入 1 個額外變數 (輸出支路電流 I_out)
    """
    def __init__(self, name, np, nn, cp, cn, gain):
        super().__init__(name)
        self.n_out_p = np
        self.n_out_n = nn
        self.n_in_p = cp
        self.n_in_n = cn
        self.gain = float(gain)
        self.extra_vars = 1

    def stamp(self, A, b, extra_idx=None, ctx=None):
        # 1. KCL: I_out 離開 np，進入 nn
        if self.n_out_p > 0:
            A[self.n_out_p - 1, extra_idx] += 1.0
            A[extra_idx, self.n_out_p - 1] += 1.0
        if self.n_out_n > 0:
            A[self.n_out_n - 1, extra_idx] -= 1.0
            A[extra_idx, self.n_out_n - 1] -= 1.0
            
        # 2. 關係式: V_out - E * V_in = 0
        if self.n_in_p > 0: 
            A[extra_idx, self.n_in_p - 1] -= self.gain
        if self.n_in_n > 0: 
            A[extra_idx, self.n_in_n - 1] += self.gain


class VCCS(BaseElement):
    """
    電壓控制電流源 (G)
    方程式: I_out = G * (V_in+ - V_in-)
    不引入額外變數，直接作為導納 (Admittance) 蓋入矩陣
    """
    def __init__(self, name, np, nn, cp, cn, transconductance):
        super().__init__(name)
        self.np = np
        self.nn = nn
        self.cp = cp
        self.cn = cn
        self.g = float(transconductance)

    def stamp(self, A, b, extra_idx=None, ctx=None):
        # I 離開 np (I = G * V_cp - G * V_cn)
        if self.np > 0 and self.cp > 0: A[self.np - 1, self.cp - 1] += self.g
        if self.np > 0 and self.cn > 0: A[self.np - 1, self.cn - 1] -= self.g
        
        # I 進入 nn (-I = -G * V_cp + G * V_cn)
        if self.nn > 0 and self.cp > 0: A[self.nn - 1, self.cp - 1] -= self.g
        if self.nn > 0 and self.cn > 0: A[self.nn - 1, self.cn - 1] += self.g


class CCVS(BaseElement):
    """
    電流控制電壓源 (H)
    方程式: V_out+ - V_out- - Rm * I_ctrl = 0
    引入 1 個額外變數 (輸出支路電流 I_out)
    """
    def __init__(self, name, np, nn, ctrl_source, transresistance):
        super().__init__(name)
        self.np = np
        self.nn = nn
        self.ctrl_source = ctrl_source.upper() 
        self.rm = float(transresistance)
        self.extra_vars = 1

    def stamp(self, A, b, extra_idx=None, ctx=None):
        # 🚀 升級為強型別屬性存取
        ctrl_idx = ctx.extra_by_name.get(self.ctrl_source)
        if ctrl_idx is None:
            raise ValueError(f"[CCVS] 找不到控制電源 '{self.ctrl_source}'，請確認該電源存在於電路中。 ({self.name})")

        # 1. KCL: I_out 離開 np，進入 nn
        if self.np > 0:
            A[self.np - 1, extra_idx] += 1.0
            A[extra_idx, self.np - 1] += 1.0
        if self.nn > 0:
            A[self.nn - 1, extra_idx] -= 1.0
            A[extra_idx, self.nn - 1] -= 1.0
        
        # 2. 關係式: V_out - Rm * I_ctrl = 0
        A[extra_idx, ctrl_idx] -= self.rm


class CCCS(BaseElement):
    """
    電流控制電流源 (F)
    方程式: I_out = F * I_ctrl
    不引入額外變數，直接將控制電流按比例注入節點
    """
    def __init__(self, name, np, nn, ctrl_source, gain):
        super().__init__(name)
        self.np = np
        self.nn = nn
        self.ctrl_source = ctrl_source.upper()
        self.gain = float(gain)

    def stamp(self, A, b, extra_idx=None, ctx=None):
        # 🚀 升級為強型別屬性存取
        ctrl_idx = ctx.extra_by_name.get(self.ctrl_source)
        if ctrl_idx is None:
            raise ValueError(f"[CCCS] 找不到控制電源 '{self.ctrl_source}'，請確認該電源存在於電路中。 ({self.name})")
        
        # I_out 離開 np，進入 nn (依賴於 ctrl_idx 代表的電流)
        if self.np > 0: A[self.np - 1, ctrl_idx] += self.gain
        if self.nn > 0: A[self.nn - 1, ctrl_idx] -= self.gain