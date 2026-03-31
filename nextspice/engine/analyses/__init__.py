from .base import BaseAnalysis
from .op import OPAnalysis
from .tran import TRANAnalysis
from .ac import ACAnalysis
from .dc import DCSweepAnalysis  
from .sens import SENSAnalysis 

# 建立分析指令註冊表 (Registry)
ANALYSIS_REGISTRY = {
    "op": OPAnalysis,
    "tran": TRANAnalysis,
    "ac": ACAnalysis,
    "dc": DCSweepAnalysis,        
    "sens": SENSAnalysis,       
}

def build_analysis(config):
    """Factory Method: 根據 JSON 設定實體化對應的 Analysis 物件"""
    atype = config.get("type", "").lower()
    cls = ANALYSIS_REGISTRY.get(atype)
    if not cls:
        raise ValueError(f"尚未支援或未知的分析類型: {atype}")
    return cls(config)