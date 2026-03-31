# nextspice/engine/elements/base.py
class BaseElement:
    def __init__(self, name):
        self.name = name
        self.extra_vars = 0
        self.is_nonlinear = False

    def requires_extra(self):
        """🚀 讓 Simulator 在 Build 階段能提早檢查，避免 Stamp 時炸掉"""
        return self.extra_vars > 0

    def stamp(self, A, b, extra_idx=None, ctx=None):
        raise NotImplementedError

    def stamp_nonlinear(self, A, b, x_old, extra_idx=None, ctx=None):
        if self.is_nonlinear: raise NotImplementedError

    def update_history(self, x, extra_idx=None, ctx=None):
        pass

class BaseAnalysis:
    """所有分析指令的基底類別 (Strategy Pattern)"""
    def __init__(self, name):
        self.name = name
        
    def run(self, simulator):
        """執行分析並回傳標準化的結果字典或物件"""
        raise NotImplementedError("Subclasses must implement run()")