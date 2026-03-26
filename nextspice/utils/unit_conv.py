import re

class UnitConverter:
    """
    NextSPICE 工業級單位轉換器 (v0.5 - Strict Match)
    嚴格遵守 SPICE 標準：
    - 允許科學記號 (e.g., 1.5e-3)
    - 允許嚴格的乘數後綴 (e.g., K, MEG, U)
    - 允許搭配標準物理單位 (e.g., 1kOHM, 10uF, 5V)
    - 拒絕任何未知的垃圾字元 (e.g., 1X, 123ABC)
    """

    # 🚀 SPICE 標準乘數白名單 (區分 MEG 和 M)
    MULTIPLIERS = {
        'T': 1e12,      # Tera
        'G': 1e9,       # Giga
        'MEG': 1e6,     # Mega (SPICE 專屬，避免跟 Milli 搞混)
        'K': 1e3,       # Kilo
        'MIL': 25.4e-6, # Mils (標準 SPICE 單位)
        'M': 1e-3,      # Milli
        'U': 1e-6,      # Micro
        'N': 1e-9,      # Nano
        'P': 1e-12,     # Pico
        'F': 1e-15      # Femto
    }

    # 🚀 允許的安全物理單位 (讓 1kOHM 這種寫法能合法通過)
    # 如果使用者沒寫單位 (例如只寫 1k)，也是合法的
    ALLOWED_UNITS = {'V', 'A', 'OHM', 'F', 'H', 'S', 'C', 'SEC', 'M'}

    # 嚴格正則表達式：
    # Group 1: 數值部分 (支援 +- 符號、小數點、e/E 科學記號)
    # Group 2: 剩餘的所有後綴字串
    _REGEX = re.compile(r'^([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)(.*)$')

    @classmethod
    def parse(cls, val_str):
        if val_str is None:
            return 0.0
            
        val_str = str(val_str).strip().upper()
        
        # 如果是純大括號 {} 包起來的，代表是 .PARAM 變數，不該在這裡處理
        if val_str.startswith('{') and val_str.endswith('}'):
            raise ValueError(f"Expression '{val_str}' should be evaluated by param_eval before unit conversion.")

        match = cls._REGEX.match(val_str)
        if not match:
            raise ValueError(f"Invalid numeric format: '{val_str}'")

        num_part = match.group(1)
        suffix_part = match.group(2).strip()
        value = float(num_part)

        # 如果沒有後綴，直接回傳純數字
        if not suffix_part:
            return value

        multiplier_val = 1.0
        
        # 1. 先攔截 3 個字母的乘數 (MEG, MIL)
        if suffix_part.startswith('MEG'):
            multiplier_val = cls.MULTIPLIERS['MEG']
            suffix_part = suffix_part[3:]
        elif suffix_part.startswith('MIL'):
            multiplier_val = cls.MULTIPLIERS['MIL']
            suffix_part = suffix_part[3:]
            
        # 2. 再攔截單字母的乘數 (T, G, K, M, U, N, P, F)
        elif suffix_part[0] in cls.MULTIPLIERS:
            multiplier_val = cls.MULTIPLIERS[suffix_part[0]]
            suffix_part = suffix_part[1:]

        # 3. 如果拔掉乘數後，還有剩下的字元，它必須是合法的物理單位
        if suffix_part and suffix_part not in cls.ALLOWED_UNITS:
            raise ValueError(
                f"Invalid suffix or garbage character '{suffix_part}' found in '{val_str}'. "
                f"Valid multipliers are: {list(cls.MULTIPLIERS.keys())}"
            )

        return value * multiplier_val

    @classmethod
    def is_valid(cls, val_str):
        """提供給 Validator 測試用的安全檢查"""
        try:
            cls.parse(val_str)
            return True
        except ValueError:
            return False