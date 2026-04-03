import math
from .base import BaseElement
from nextspice.utils.constants import GMIN_NONLINEAR

class MOSFET(BaseElement):
    """
    MOSFET (Level 1 Shichman-Hodges Model)
    支援 NMOS 與 PMOS，包含 Cutoff, Triode, Saturation 三大工作區。
    具備 Drain/Source 動態互換能力，並支援 AC 小訊號分析。
    """
    def __init__(self, name, nd, ng, ns, nb, model_type='NMOS', 
                 w=1e-6, l=1e-6, kp=50e-6, vto=0.8, lambda_val=0.0):
        super().__init__(name)
        self.nd, self.ng, self.ns, self.nb = nd, ng, ns, nb
        self.is_nonlinear = True
        
        # NMOS 為 1.0，PMOS 為 -1.0
        self.type_sign = 1.0 if model_type.upper() == 'NMOS' else -1.0
        
        self.w = float(w)
        self.l = float(l)
        self.kp = float(kp)         # 轉導參數 (u*Cox)
        # PMOS 的 VTO 通常輸入是負的，我們這裡統一轉成絕對值，靠 type_sign 處理方向
        self.vto = abs(float(vto))  
        self.lam = float(lambda_val)# 通道長度調變效應
        
        # 幾何轉導 beta = KP * (W/L)
        self.beta = self.kp * (self.w / self.l)

    def stamp_nonlinear(self, A, b, x_old, extra_idx=None, ctx=None):
        vd = x_old[self.nd - 1] if self.nd > 0 else 0.0
        vg = x_old[self.ng - 1] if self.ng > 0 else 0.0
        vs = x_old[self.ns - 1] if self.ns > 0 else 0.0
        
        # 考慮極性
        vds_raw = self.type_sign * (vd - vs)
        vgs_raw = self.type_sign * (vg - vs)

        # 🚀 防爆 Clamp 處理：強制將電壓限制在 ±100V 內，防止 float64 溢位！
        vds = max(-100.0, min(100.0, vds_raw))
        vgs = max(-100.0, min(100.0, vgs_raw))

        # 🚀 行使否決權：如果 NR 猜的電壓被我們強行截斷了，就舉報尚未收斂！
        is_clamped = abs(vds - vds_raw) > 1e-3 or abs(vgs - vgs_raw) > 1e-3
        ctx.state_mgr.set(self, 'clamped', is_clamped, scope='nr')

        # 如果 Vds < 0，代表 Drain 和 Source 物理上反轉了
        is_swapped = False
        if vds < 0:
            vds = -vds
            # 反轉後的 vgs 也要過一次防爆保護
            vgs = max(-100.0, min(100.0, self.type_sign * (vg - vd)))
            is_swapped = True

        vth = self.vto 
        vov = vgs - vth
        
        id_val = 0.0
        gm = 0.0
        gds = 0.0

        # --- 工作區間判定與物理公式計算 ---
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

        # 如果發生反轉，電流方向與轉導極性要倒過來
        if is_swapped:
            gm = -gm
            ieq = -ieq

        # 還原到真實電路極性
        ieq *= self.type_sign
       # gm *= self.type_sign

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

        # 🚀 存入狀態管理器，供 AC 分析重用，並提供給前端 GUI (OP Panel) 顯示
        ctx.state_mgr.set(self, 'gm', gm)
        ctx.state_mgr.set(self, 'gds', gds)
        ctx.state_mgr.set(self, 'id', id_val * self.type_sign * (-1 if is_swapped else 1))

    def stamp(self, A, b, extra_idx=None, ctx=None):
        # AC 分析：直接取用 DC OP 階段存起來的小訊號跨導
        if ctx.mode == 'ac':
            gm = ctx.state_mgr.get(self, 'gm', 0.0)
            gds = ctx.state_mgr.get(self, 'gds', 0.0)

            if gm == 0.0 and gds == 0.0:
                raise RuntimeError(f"[MOSFET] {self.name} AC 分析前未建立 DC 工作點！")

            D, G, S = self.nd - 1, self.ng - 1, self.ns - 1

            if self.nd > 0:
                A[D, D] += complex(gds, 0.0)
                if self.ns > 0: A[D, S] -= complex(gds + gm, 0.0)
                if self.ng > 0: A[D, G] += complex(gm, 0.0)

            if self.ns > 0:
                A[S, S] += complex(gds + gm, 0.0)
                if self.nd > 0: A[S, D] -= complex(gds, 0.0)
                if self.ng > 0: A[S, G] -= complex(gm, 0.0)