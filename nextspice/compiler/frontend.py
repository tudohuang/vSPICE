import os
import datetime
import copy
from .preprocess import preprocess, parse_to_raw_ast
from .param_eval import build_param_env, eval_val
from .parse_elements import parse_element
from .parse_directives import parse_directive
from .validator import validate_circuit

class SpiceParser:
    """
    NextSPICE Canonical Compiler (v0.5 - Subcircuit Supported)
    職責：協調解析，並將子電路 (Subcircuits) 展平成純平坦的元件清單。
    """
    def __init__(self, file_path=None, content=None):
        self.file_path = file_path or "memory_buffer.cir"
        self.raw_content = content
        self.diagnostics = []
        
        self.circuit = {
            "schema": "nextspice.circuit.v0.1",
            "name": "Untitled",
            "metadata": {
                "source": os.path.basename(self.file_path),
                "compiled_at": "",
                "ground_node": "0",
                "measures": [] 
            },
            "options": {},    
            "outputs": [],   
            "subckts": {},      
            "elements": [],     # 這裡最終只會剩下展平後的實體元件
            "models": [],
            "analyses": [],
            "params": {}
        }

    def _log_diag(self, ln, sev, msg):
        self.diagnostics.append({"line": ln, "severity": sev, "message": msg})

    def compile(self):
        self.circuit["metadata"]["compiled_at"] = datetime.datetime.now().isoformat()
        
        if self.raw_content is None:
            if not os.path.exists(self.file_path):
                self._log_diag(0, "ERROR", f"File not found: {self.file_path}")
                return {"circuit": self.circuit, "diagnostics": self.diagnostics}
            with open(self.file_path, 'r', encoding='utf-8') as f:
                raw_lines = f.readlines()
        else:
            raw_lines = self.raw_content.splitlines()

        # 標題處理
        for i, line in enumerate(raw_lines):
            stripped = line.strip()
            if stripped:
                if not stripped.startswith('*'):
                    self.circuit["name"] = stripped
                    raw_lines[i] = "* " + stripped
                else:
                    self.circuit["name"] = stripped[1:].strip()
                break

        # 1. 預處理與 AST
        preprocessed = preprocess(raw_lines)
        raw_ast = parse_to_raw_ast(preprocessed)

        # 2. 建立參數環境
        param_env = build_param_env(raw_ast)
        self.circuit["params"] = {k: v for k, v in param_env.items() if k not in dir(__import__('math'))}
        
        def _eval(val_str):
            return eval_val(val_str, param_env)

        # 3. 解析元件與指令 (支援 Scope 切換)
        active_target = self.circuit # 預設將元件加入主電路
        
        for item in raw_ast:
            if item["kind"] == "element":
                parse_element(item, active_target, self.diagnostics, _eval)
            
            elif item["kind"] == "directive":
                cmd = item["tokens"][0].upper()
                
                if cmd == '.SUBCKT':
                    if len(item["tokens"]) < 2:
                        self._log_diag(item["line_no"], "ERROR", ".SUBCKT missing name")
                        continue
                    sub_name = item["tokens"][1].upper()
                    # 抓取腳位並把 GND 統一轉成 0
                    sub_pins = ["0" if p.upper() in ["GND", "GROUND"] else p.upper() for p in item["tokens"][2:]]
                    self.circuit["subckts"][sub_name] = {"pins": sub_pins, "elements": []}
                    active_target = self.circuit["subckts"][sub_name]
                    
                # 🚀 攔截 .ENDS (切換 Scope 回主電路)
                elif cmd == '.ENDS':
                    active_target = self.circuit
                    
                elif cmd not in ['.PARAM', '.END']: 
                    # 一般指令只有在主電路 Scope 才會被解析
                    if active_target is self.circuit:
                        parse_directive(item, active_target, self.diagnostics, _eval)

        # 🚀 4. 暴力展平 (Macro Expansion)
        self._flatten_subckts()

        # 5. 驗證
        validate_circuit(self.circuit, self.diagnostics)
        
        return {
            "circuit": self.circuit,
            "diagnostics": self.diagnostics
        }

    def _flatten_subckts(self):
        """將所有 X 開頭的呼叫替換為實際元件，並自動產生 Prefix 避免名稱衝突"""
        flat_elements = []
        
        def expand(elements, prefix, node_map):
            for el in elements:
                if el.get("type") == "subckt_call":
                    sub_def = self.circuit["subckts"].get(el["subname"])
                    if not sub_def:
                        self._log_diag(0, "ERROR", f"Subcircuit '{el['subname']}' not found")
                        continue
                    
                    # 建立內外節點的映射表
                    new_node_map = {}
                    for i, pin in enumerate(sub_def["pins"]):
                        ext_node = el["pins"].get(f"p{i}")
                        # 處理巢狀：如果外面的節點已經是被 mapping 過的，就繼續往下傳遞
                        new_node_map[pin] = node_map.get(ext_node, ext_node)
                        
                    # 產生下一層的 Prefix (例如 X1.X2.)
                    new_prefix = f"{prefix}{el['name']}."
                    expand(sub_def["elements"], new_prefix, new_node_map)
                    
                else:
                    # 深拷貝元件，避免修改到原始藍圖
                    new_el = copy.deepcopy(el)
                    new_el["name"] = f"{prefix}{new_el['name']}"
                    
                    # 重新命名所有節點 (0 / 接地點永遠不變)
                    for pin_cat in ["pins", "ctrl_pins"]:
                        if pin_cat in new_el:
                            for k, v in new_el[pin_cat].items():
                                if v != "0": 
                                    new_el[pin_cat][k] = node_map.get(v, f"{prefix}{v}" if prefix else v)
                                    
                    # 重新命名交叉參照 (H, F 等受控源的控制對象也要加上 Prefix)
                    for ref_field in ["ctrl_source", "element1", "element2"]:
                        if ref_field in new_el:
                            new_el[ref_field] = f"{prefix}{new_el[ref_field]}"
                            
                    flat_elements.append(new_el)
                    
        # 啟動第一層遞迴展開
        expand(self.circuit["elements"], "", {})
        self.circuit["elements"] = flat_elements