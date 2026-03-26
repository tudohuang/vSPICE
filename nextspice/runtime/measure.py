import numpy as np

class MeasureEngine:
    """
    NextSPICE 數據萃取引擎 (v0.1)
    專門處理 .MEASURE 語法，包含線性內插與邊界條件防護。
    """
    def __init__(self, circuit, extra_var_map):
        self.circuit = circuit
        self.node_mgr = circuit.node_mgr
        self.extra_var_map = extra_var_map

    def _get_var_data(self, var_name, results):
        """從解向量歷史中，把指定變數 (如 V(OUT) 或 I(V1)) 的數據抽出來"""
        var_name = var_name.upper()
        y_data = []
        
        if var_name.startswith("V(") and var_name.endswith(")"):
            node = var_name[2:-1]
            if node == "0":
                return np.zeros(len(results))
            idx = self.node_mgr.mapping.get(node)
            if idx is None: return None
            idx -= 1
            for r in results:
                if r["status"] == "SUCCESS": y_data.append(r["x"][idx])
                
        elif var_name.startswith("I(") and var_name.endswith(")"):
            element_name = var_name[2:-1]
            target_el = next((el for el in self.circuit.elements if el.name == element_name), None)
            idx = self.extra_var_map.get(target_el)
            if idx is None: return None
            for r in results:
                if r["status"] == "SUCCESS": y_data.append(r["x"][idx])
        else:
            return None
            
        return np.array(y_data)

    def _find_crossings(self, x_data, y_data, val, edge_type):
        """核心演算法：線性內插尋找所有穿越點"""
        crossings = []
        for i in range(len(y_data) - 1):
            y1, y2 = y_data[i], y_data[i+1]
            x1, x2 = x_data[i], x_data[i+1]
            
            is_rise = (y1 < val <= y2)
            is_fall = (y1 > val >= y2)
            
            if (edge_type == 'RISE' and is_rise) or \
               (edge_type == 'FALL' and is_fall) or \
               (edge_type == 'CROSS' and (is_rise or is_fall)):
                
                # 🚀 內插公式： fraction = (目標值 - 起點值) / 總高度差
                if y2 == y1: continue
                fraction = (val - y1) / (y2 - y1)
                x_cross = x1 + fraction * (x2 - x1)
                crossings.append(x_cross)
                
        return crossings

    def _parse_trigger(self, args_list):
        """將 TRIG V(IN) VAL=2.5 RISE=1 解析成條件字典"""
        info = {"var": None, "val": 0.0, "edge": "CROSS", "count": 1}
        if not args_list: return info
        
        info["var"] = args_list[0]
        
        for arg in args_list[1:]:
            if "=" in arg:
                k, v = arg.split("=")
                k = k.upper()
                if k == "VAL": info["val"] = float(v)
                elif k == "RISE": info["edge"] = "RISE"; info["count"] = int(v)
                elif k == "FALL": info["edge"] = "FALL"; info["count"] = int(v)
                elif k == "CROSS": info["edge"] = "CROSS"; info["count"] = int(v)
        return info

    def evaluate_tran(self, measure_cmd, tran_results):
        """執行單條 .MEASURE TRAN 指令"""
        name = measure_cmd["name"]
        args = measure_cmd["raw_args"]
        
        # 建立時間軸
        x_data = np.array([r["time"] for r in tran_results if r["status"] == "SUCCESS"])
        
        try:
            # 切割 TRIG 與 TARG 條件
            trig_idx = args.index("TRIG")
            targ_idx = args.index("TARG")
            trig_args = args[trig_idx + 1 : targ_idx]
            targ_args = args[targ_idx + 1 :]
        except ValueError:
            return {"name": name, "value": "FAILED", "msg": "目前僅支援 TRIG ... TARG 雙點測量語法"}

        trig_info = self._parse_trigger(trig_args)
        targ_info = self._parse_trigger(targ_args)

        # 抽波形數據
        y_trig = self._get_var_data(trig_info["var"], tran_results)
        y_targ = self._get_var_data(targ_info["var"], tran_results)

        if y_trig is None or y_targ is None:
            return {"name": name, "value": "FAILED", "msg": "找不到指定的測量變數"}

        # 尋找所有穿越點
        trig_crossings = self._find_crossings(x_data, y_trig, trig_info["val"], trig_info["edge"])
        targ_crossings = self._find_crossings(x_data, y_targ, targ_info["val"], targ_info["edge"])

        # 確保要求的次數存在
        t1_idx = trig_info["count"] - 1
        t2_idx = targ_info["count"] - 1

        if t1_idx >= len(trig_crossings):
            return {"name": name, "value": "FAILED", "msg": f"TRIG 條件未能滿足 {trig_info['count']} 次"}
        if t2_idx >= len(targ_crossings):
            return {"name": name, "value": "FAILED", "msg": f"TARG 條件未能滿足 {targ_info['count']} 次"}

        # 計算時間差
        t1 = trig_crossings[t1_idx]
        t2 = targ_crossings[t2_idx]
        delay = t2 - t1

        return {"name": name, "value": delay, "msg": f"t1={t1:.3e}, t2={t2:.3e}"}