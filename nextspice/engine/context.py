class StateManager:
    """
    統一的狀態管理器 (State Manager) 2.0
    支援 Scope 命名空間，完美隔離不同分析 (TRAN, AC, SENS) 的狀態。
    """
    def __init__(self):
        self.data = {}

    def get(self, element, key, default=0.0, scope='default'):
        return self.data.get((id(element), scope, key), default)

    def set(self, element, key, value, scope='default'):
        self.data[(id(element), scope, key)] = value
        
    def clone(self):
        new_mgr = StateManager()
        new_mgr.data = self.data.copy()
        return new_mgr

class AnalysisContext:
    """
    強型別分析上下文 (Typed Analysis Context) 2.0
    加入生命週期管理 (Lifecycle) 與狀態隔離。
    """
    def __init__(
        self,
        mode="op",
        freq=1.0,
        t=0.0,
        dt=0.0,
        integration="trapezoidal",
        extra_map=None,
        extra_by_name=None,
        state_mgr=None,
    ):
        self.mode = mode
        self.freq = float(freq)
        self.t = float(t)
        self.dt = float(dt)
        self.integration = integration
        self.extra_map = extra_map if extra_map is not None else {}
        self.extra_by_name = extra_by_name if extra_by_name is not None else {}
        self.state_mgr = state_mgr if state_mgr is not None else StateManager()
        
        self.is_dc_op_valid = False