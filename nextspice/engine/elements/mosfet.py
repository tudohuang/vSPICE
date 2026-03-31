import math
from .base import BaseElement
from nextspice.utils.constants import GMIN_NONLINEAR

class MOSFET(BaseElement):
    """
    MOSFET (Level 1 Shichman-Hodges Model)
    支援 NMOS 與 PMOS，包含 Cutoff, Triode, Saturation 三大工作區。
    """
    def __init__(self, name, nd, ng, ns, nb, model_type='NMOS', 
                 w=1e-6, l=1e-6, kp=50e-6, vto=0.8, lambda_val=0.0):
        super().__init__(name)
        self.nd, self.ng, self.ns, self.nb = nd, ng, ns, nb
        self.is_nonlinear = True
        
        self.type_sign = 1.0 if model_type.upper() == 'NMOS' else -1.0
        
        self.w = float(w)
        self.l = float(l)
        self.kp = float(kp)         # 轉導參數 (u*Cox)
        self.vto = float(vto)       # 閾值電壓
        self.lam = float(lambda_val)# 通道長度調變效應
        
        # 幾何轉導 beta = KP * (W/L)
        self.beta = self.kp * (self.w / self.l)

    def stamp_nonlinear(self, A, b, x_old, extra_idx=None, ctx=None):
        vd = x_old[self.nd - 1] if self.nd > 0 else 0.0
        vg = x_old[self.ng - 1] if self.ng > 0 else 0.0
        vs = x_old[self.ns - 1] if self.ns > 0 else 0.0
        
        # 考慮 NMOS/PMOS 極性
        vds = self.type_sign * (vd - vs)
        vgs = self.type_sign * (vg - vs)
        
        # 如果 Vds < 0，代表 Drain 和 Source 物理上反轉了 (MOS 結構是對稱的)
        is_swapped = False
        if vds < 0:
            vds = -vds
            vgs = self.type_sign * (vg - vd)
            is_swapped = True

        vth = self.vto 
        vov = vgs - vth
        
        id_val = 0.0
        gm = 0.0
        gds = 0.0

        # --- 工作區間判定與數學計算 ---
        if vov <= 0:
            # 1. 截止區 (Cutoff)
            id_val, gm, gds = 0.0, 0.0, 0.0
        elif vds <= vov:
            # 2. 線性區 (Triode/Linear)
            id_val = self.beta * (vov * vds - 0.5 * vds**2) * (1.0 + self.lam * vds)
            gm = self.beta * vds * (1.0 + self.lam * vds)
            gds = self.beta * (vov - vds) * (1.0 + self.lam * vds) + self.lam * self.beta * (vov * vds - 0.5 * vds**2)
        else:
            # 3. 飽和區 (Saturation)
            id_val = 0.5 * self.beta * vov**2 * (1.0 + self.lam * vds)
            gm = self.beta * vov * (1.0 + self.lam * vds)
            gds = 0.5 * self.beta * vov**2 * self.lam

        gds += GMIN_NONLINEAR

        # 算出等效諾頓電流 (Equivalent Current)
        ieq = id_val - gm * vgs - gds * vds

        if is_swapped:
            gm = -gm
            ieq = -ieq

        ieq *= self.type_sign
        gm *= self.type_sign

        # --- 蓋章到 MNA 矩陣 ---
        D = self.nd - 1
        G = self.ng - 1
        S = self.ns - 1

        if self.nd > 0:
            A[D, D] += gds
            b[D] -= ieq
            if self.ns > 0: A[D, S] -= (gds + gm)
            if self.ng > 0: A[D, G] += gm

        if self.ns > 0:
            A[S, S] += (gds + gm)
            b[S] += ieq
            if self.nd > 0: A[S, D] -= gds
            if self.ng > 0: A[S, G] -= gm

        # 🚀 存入狀態管理器，供 AC 小訊號分析使用！
        ctx.state_mgr.set(self, 'gm', gm)
        ctx.state_mgr.set(self, 'gds', gds)

    def stamp(self, A, b, extra_idx=None, ctx=None):
        # AC 分析：直接取用 DC OP 階段存起來的小訊號跨導
        if ctx.mode == 'ac':
            gm = ctx.state_mgr.get(self, 'gm', 0.0)
            gds = ctx.state_mgr.get(self, 'gds', GMIN_NONLINEAR)

            D, G, S = self.nd - 1, self.ng - 1, self.ns - 1

            if self.nd > 0:
                A[D, D] += complex(gds, 0.0)
                if self.ns > 0: A[D, S] -= complex(gds + gm, 0.0)
                if self.ng > 0: A[D, G] += complex(gm, 0.0)

            if self.ns > 0:
                A[S, S] += complex(gds + gm, 0.0)
                if self.nd > 0: A[S, D] -= complex(gds, 0.0)
                if self.ng > 0: A[S, G] -= complex(gm, 0.0)