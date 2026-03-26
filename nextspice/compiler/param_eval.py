import math
import re
from nextspice.utils.unit_conv import UnitConverter

def build_param_env(raw_ast):
    param_env = {}
    for k in dir(math):
        if not k.startswith('_'): 
            param_env[k.upper()] = getattr(math, k)

    for item in raw_ast:
        if item["kind"] == "directive" and item["tokens"][0].upper() == ".PARAM":
            s = " ".join(item["tokens"][1:])
            pairs = re.findall(r'([A-Z0-9_]+)\s*=\s*([^\s]+)', s, re.I)
            for k, v in pairs:
                try:
                    param_env[k.upper()] = UnitConverter.parse(v)
                except:
                    param_env[k.upper()] = v
    return param_env

def eval_val(val_str, param_env):
    val_str = str(val_str)
    if val_str.startswith('{') and val_str.endswith('}'):
        expr = val_str[1:-1].upper()
        try:
            result = eval(expr, {"__builtins__": None}, param_env)
            return float(result)
        except Exception as e:
            raise ValueError(f"Failed to evaluate param '{expr}': {e}")
    return UnitConverter.parse(val_str)