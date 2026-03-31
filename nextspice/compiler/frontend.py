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
        """將所有 X 開呼叫替換為實際元件，處理地節點保護與模型作用域"""
        flat_elements = []
        global_models = list(self.circuit.get("models", []))
        
        def expand(elements, prefix, node_map, subckt_models=None):
            # 🚀 處理模型展平：如果子電路內有定義模型，將其改名後加入全域
            if subckt_models:
                for m_name, m_def in subckt_models.items():
                    new_m = copy.deepcopy(m_def)
                    # 讓模型名稱也帶上 Prefix，例如 XQ1.DMOD
                    new_m_name = f"{prefix}{m_name}"
                    # 這裡要確保存入全域模型清單 (格式需符合你的 Circuit 結構)
                    if "name" not in new_m: new_m["name"] = new_m_name
                    else: new_m["name"] = new_m_name
                    global_models.append(new_m)

            for el in elements:
                if el.get("type") == "subckt_call":
                    sub_def = self.circuit["subckts"].get(el["subname"])
                    if not sub_def:
                        self._log_diag(0, "ERROR", f"Subcircuit '{el['subname']}' not found")
                        continue
                    
                    new_node_map = {}
                    for i, pin in enumerate(sub_def["pins"]):
                        # 抓取呼叫時傳入的外部節點名稱
                        ext_node = el["pins"].get(f"p{i}")
                        # 處理巢狀節點映射
                        new_node_map[pin] = node_map.get(ext_node, ext_node)
                    
                    new_prefix = f"{prefix}{el['name']}."
                    # 遞迴展開，傳入該子電路內部的模型
                    expand(sub_def["elements"], new_prefix, new_node_map, sub_def.get("models", {}))
                    
                else:
                    new_el = copy.deepcopy(el)
                    new_el["name"] = f"{prefix}{new_el['name']}"
                    
                    # 🚀 重新命名模型參考
                    if "model" in new_el:
                        # 優先指向子電路內部的改名模型
                        new_el["model"] = f"{prefix}{new_el['model']}"
                    
                    # 🚀 重新命名節點 (加入 GND 保護)
                    for pin_cat in ["pins", "ctrl_pins"]:
                        if pin_cat in new_el:
                            for k, v in new_el[pin_cat].items():
                                # 🛡️ 關鍵修正：如果 v 是 '0'，絕對不能加前綴！
                                if str(v) == "0":
                                    new_el[pin_cat][k] = "0"
                                else:
                                    # 先看 mapping (對外腳位)，沒有的話才視為內部節點加前綴
                                    new_el[pin_cat][k] = node_map.get(v, f"{prefix}{v}" if prefix else v)
                                    
                    for ref_field in ["ctrl_source", "element1", "element2"]:
                        if ref_field in new_el:
                            new_el[ref_field] = f"{prefix}{new_el[ref_field]}"
                            
                    flat_elements.append(new_el)
                    
        # 啟動展開
        expand(self.circuit["elements"], "", {})
        self.circuit["elements"] = flat_elements
        self.circuit["models"] = global_models # 更新回展平後的模型清單