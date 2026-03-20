import re

class UnitConverter:
    """NextSPICE 工程單位轉換器：處理 p, n, u, m, k, MEG, G, T"""
    SUFFIXES = {
        'T': 1e12, 'G': 1e9, 'MEG': 1e6, 'K': 1e3,
        'MIL': 25.4e-6, 'M': 1e-3, 'U': 1e-6, 'N': 1e-9, 'P': 1e-12, 'F': 1e-15
    }

    @classmethod
    def parse(cls, val_str):
        if not val_str: return 0.0
        s = str(val_str).upper().strip()
        
        # 處理參數引用格式 {VAR}
        if s.startswith('{') and s.endswith('}'):
            return s
            
        # 移除物理後綴 (V, A, OHM...)
        s = re.sub(r'(V|A|OHM|S|SEC|HZ)$', '', s)
        
        match = re.match(r"^([-+]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:E[-+]?[0-9]+)?)([A-Z]*)", s)
        if not match: return s # 可能是變數名稱
            
        num = float(match.group(1))
        suffix = match.group(2)
        return num * cls.SUFFIXES[suffix] if suffix in cls.SUFFIXES else num