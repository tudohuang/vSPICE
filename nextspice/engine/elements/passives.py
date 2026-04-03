import math
from .base import BaseElement
# 🚀 使用精準的分類常數與絕對路徑
from nextspice.utils.constants import GMIN_DC_PULLDOWN, GMIN_BRANCH_PATCH, DEFAULT_DT

class Resistor(BaseElement):
    """
    理想電阻器 (R)
    方程式: I = V / R (蓋入節點導納矩陣)
    """
    def __init__(self, name, n1, n2, value):
        super().__init__(name)
        self.n1, self.n2 = n1, n2
        self.value = float(value)
        
        if self.value <= 0:
            raise ValueError(f"[Resistor] {self.name} 的阻值必須大於 0，目前為 {self.value}")

    def stamp(self, A, b, extra_idx=None, ctx=None):
        g = 1.0 / self.value 
        if self.n1 > 0: A[self.n1 - 1, self.n1 - 1] += g
        if self.n2 > 0: A[self.n2 - 1, self.n2 - 1] += g
        if self.n1 > 0 and self.n2 > 0:
            A[self.n1 - 1, self.n2 - 1] -= g
            A[self.n2 - 1, self.n1 - 1] -= g


class Capacitor(BaseElement):
    """
    理想電容器 (C)
    DC/OP: 視為開路 (加上 GMIN_DC_PULLDOWN 避免節點浮接)
    AC: 複數導納 Y = jωC
    TRAN: Companion Model (Norton 等效)
    """
    def __init__(self, name, n1, n2, value):
        super().__init__(name)
        self.n1, self.n2 = n1, n2
        self.value = float(value)
        
        # 🚀 乾淨！不再自己記住歷史狀態
        if self.value <= 0:
            raise ValueError(f"[Capacitor] {self.name} 的電容值必須大於 0，目前為 {self.value}")

    def stamp(self, A, b, extra_idx=None, ctx=None):
        if ctx.mode in ('dc', 'op'):
            # DC OP 視為開路，補上極小電導防止浮接節點導致矩陣無法求解
            if self.n1 > 0: A[self.n1 - 1, self.n1 - 1] += GMIN_DC_PULLDOWN
            if self.n2 > 0: A[self.n2 - 1, self.n2 - 1] += GMIN_DC_PULLDOWN
            if self.n1 > 0 and self.n2 > 0:
                A[self.n1 - 1, self.n2 - 1] -= GMIN_DC_PULLDOWN
                A[self.n2 - 1, self.n1 - 1] -= GMIN_DC_PULLDOWN
                
        elif ctx.mode == 'ac':
            omega = 2.0 * math.pi * ctx.freq
            y_c = complex(0, omega * self.value)
            if self.n1 > 0: A[self.n1 - 1, self.n1 - 1] += y_c
            if self.n2 > 0: A[self.n2 - 1, self.n2 - 1] += y_c
            if self.n1 > 0 and self.n2 > 0:
                A[self.n1 - 1, self.n2 - 1] -= y_c
                A[self.n2 - 1, self.n1 - 1] -= y_c
                
        elif ctx.mode == 'tran':
            # 🚀 從狀態管理器撈資料
            v_prev = ctx.state_mgr.get(self, 'v_prev', 0.0)
            i_prev = ctx.state_mgr.get(self, 'i_prev', 0.0)
            
            if ctx.integration == 'gear2':
                v_prev2 = ctx.state_mgr.get(self, 'v_prev2', 0.0)
                g_eq = 1.5 * self.value / ctx.dt
                i_hist = self.value / ctx.dt * (2.0 * v_prev - 0.5 * v_prev2)
            elif ctx.integration == 'trapezoidal':
                g_eq = 2.0 * self.value / ctx.dt
                i_hist = g_eq * v_prev + i_prev
            else:
                g_eq = self.value / ctx.dt
                i_hist = g_eq * v_prev

            if self.n1 > 0:
                A[self.n1 - 1, self.n1 - 1] += g_eq
                b[self.n1 - 1] += i_hist
            if self.n2 > 0:
                A[self.n2 - 1, self.n2 - 1] += g_eq
                b[self.n2 - 1] -= i_hist
            if self.n1 > 0 and self.n2 > 0:
                A[self.n1 - 1, self.n2 - 1] -= g_eq
                A[self.n2 - 1, self.n1 - 1] -= g_eq

    def update_history(self, x, extra_idx=None, ctx=None):
        v_p = x[self.n1 - 1] if self.n1 > 0 else 0.0
        v_n = x[self.n2 - 1] if self.n2 > 0 else 0.0
        v_now = v_p - v_n
        
        # 🚀 先把現在的 v_prev 存成 v_prev2 (給 Gear2 用)
        v_prev = ctx.state_mgr.get(self, 'v_prev', 0.0)
        ctx.state_mgr.set(self, 'v_prev2', v_prev)
        
        if ctx.integration == 'trapezoidal' and ctx.dt:
            g_eq = 2.0 * self.value / ctx.dt
            i_prev = ctx.state_mgr.get(self, 'i_prev', 0.0)
            i_now = g_eq * (v_now - v_prev) - i_prev
            ctx.state_mgr.set(self, 'i_prev', i_now)
            
        ctx.state_mgr.set(self, 'v_prev', v_now)

    def init_history(self, x_op, extra_idx=None, ctx=None):
        """核心修復 REG-TR01: 從 OP 狀態正確初始化歷史"""
        v_p = x_op[self.n1 - 1] if self.n1 > 0 else 0.0
        v_n = x_op[self.n2 - 1] if self.n2 > 0 else 0.0
        v_op = v_p - v_n
        ctx.state_mgr.set(self, 'v_prev', v_op)
        ctx.state_mgr.set(self, 'v_prev2', v_op)  # 給 Gear2 備用
        ctx.state_mgr.set(self, 'i_prev', 0.0)    # DC 穩態電容無電流
        ctx.state_mgr.set(self, 'i_prev2', 0.0)


class Inductor(BaseElement):
    """
    理想電感器 (L)
    引入 1 個額外變數 (支路電流 I_L)
    DC/OP: 視為短路
    TRAN: Companion Model (Thevenin 等效)
    """
    def __init__(self, name, n1, n2, value):
        super().__init__(name)
        self.n1, self.n2 = n1, n2
        self.value = float(value)
        self.extra_vars = 1
        
        # 🚀 移除 self.i_prev, self.v_prev
        if self.value <= 0:
            raise ValueError(f"[Inductor] {self.name} 的電感值必須大於 0")

    def stamp(self, A, b, extra_idx=None, ctx=None):
        if extra_idx is None:
            raise ValueError(f"[{self.name}] 致命錯誤：未分配到 extra_idx")
            
        idx = extra_idx
        
        if ctx.mode in ('dc', 'op'):
            if self.n1 > 0:
                A[self.n1 - 1, idx] += 1.0
                A[idx, self.n1 - 1] += 1.0
            if self.n2 > 0:
                A[self.n2 - 1, idx] -= 1.0
                A[idx, self.n2 - 1] -= 1.0
            b[idx] += 0.0
            A[idx, idx] -= GMIN_BRANCH_PATCH
            
        elif ctx.mode == 'ac':
            omega = 2.0 * math.pi * ctx.freq
            z_l = complex(0, omega * self.value)
            if self.n1 > 0:
                A[self.n1 - 1, idx] += 1.0
                A[idx, self.n1 - 1] += 1.0
            if self.n2 > 0:
                A[self.n2 - 1, idx] -= 1.0
                A[idx, self.n2 - 1] -= 1.0
            A[idx, idx] -= z_l
            
        elif ctx.mode == 'tran':
            i_prev = ctx.state_mgr.get(self, 'i_prev', 0.0)
            v_prev = ctx.state_mgr.get(self, 'v_prev', 0.0)
            
            if ctx.integration == 'gear2':
                i_prev2 = ctx.state_mgr.get(self, 'i_prev2', 0.0)
                r_eq = 1.5 * self.value / ctx.dt
                v_hist = self.value / ctx.dt * (2.0 * i_prev - 0.5 * i_prev2)
            elif ctx.integration == 'trapezoidal':
                r_eq = 2.0 * self.value / ctx.dt
                v_hist = r_eq * i_prev + v_prev
            else:
                r_eq = self.value / ctx.dt
                v_hist = r_eq * i_prev

            if self.n1 > 0:
                A[self.n1 - 1, idx] += 1.0
                A[idx, self.n1 - 1] += 1.0
            if self.n2 > 0:
                A[self.n2 - 1, idx] -= 1.0
                A[idx, self.n2 - 1] -= 1.0
            A[idx, idx] -= r_eq
            b[idx] -= v_hist

    def update_history(self, x, extra_idx=None, ctx=None):
        i_now = x[extra_idx] if extra_idx is not None else 0.0
        v_p = x[self.n1 - 1] if self.n1 > 0 else 0.0
        v_n = x[self.n2 - 1] if self.n2 > 0 else 0.0
        v_now = v_p - v_n
        
        i_prev = ctx.state_mgr.get(self, 'i_prev', 0.0)
        ctx.state_mgr.set(self, 'i_prev2', i_prev) 
        
        if ctx.integration == 'trapezoidal' and ctx.dt:
            ctx.state_mgr.set(self, 'v_prev', v_now)
            
        ctx.state_mgr.set(self, 'i_prev', i_now)

    def init_history(self, x_op, extra_idx=None, ctx=None):
        """核心修復 REG-TR01: 從 OP 狀態正確初始化歷史"""
        i_op = x_op[extra_idx] if extra_idx is not None else 0.0
        ctx.state_mgr.set(self, 'i_prev', i_op)
        ctx.state_mgr.set(self, 'i_prev2', i_op)
        ctx.state_mgr.set(self, 'v_prev', 0.0)    # DC 穩態電感無跨壓


class MutualInductance(BaseElement):
    """
    互感器 (K)
    透過修改所屬兩個電感的轉移阻抗達成耦合
    """
    def __init__(self, name, l1_obj, l2_obj, k_value):
        super().__init__(name)
        self.l1_obj, self.l2_obj = l1_obj, l2_obj
        self.k = float(k_value)
        if not (-1.0 <= self.k <= 1.0):
            raise ValueError(f"[MutualInductance] {self.name} 的 k 必須介於 -1 到 1")
        self.M = self.k * math.sqrt(self.l1_obj.value * self.l2_obj.value)

    def stamp(self, A, b, extra_idx=None, ctx=None):
        idx1 = ctx.extra_map.get(self.l1_obj)
        idx2 = ctx.extra_map.get(self.l2_obj)
        if idx1 is None or idx2 is None: return

        if ctx.mode == 'ac':
            omega = 2.0 * math.pi * ctx.freq
            zm = complex(0, omega * self.M)
            A[idx1, idx2] -= zm
            A[idx2, idx1] -= zm
        elif ctx.mode == 'tran':
            rm = self.M / ctx.dt
            A[idx1, idx2] -= rm
            A[idx2, idx1] -= rm
            
            # 🚀 互感電流相依性：直接從 state_mgr 讀取兩個目標電感的歷史狀態
            l1_i_prev = ctx.state_mgr.get(self.l1_obj, 'i_prev', 0.0)
            l2_i_prev = ctx.state_mgr.get(self.l2_obj, 'i_prev', 0.0)
            
            b[idx1] -= rm * l2_i_prev
            b[idx2] -= rm * l1_i_prev