import math

class BaseAnalysis:
    """分析指令的抽象基底類別 (Strategy Pattern)"""
    def __init__(self, config):
        self.config = config
        self.atype = config.get("type", "unknown").lower()

    def run(self, simulator, circuit, step_suffix=""):
        """
        執行分析並回傳標準化結果字典:
        { "status": "SUCCESS", "atype": "...", "suffix": "...", "data": ... }
        """
        raise NotImplementedError("Subclasses must implement run()")

    def safe_num(self, val):
        """共用的浮點數安全轉換器"""
        try:
            v = float(val)
            return 0.0 if math.isnan(v) or math.isinf(v) else v
        except:
            return 0.0