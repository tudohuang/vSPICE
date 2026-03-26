import re
import os
import datetime
from nextspice.utils.unit_conv import UnitConverter

class SpiceParser:
    """
    NextSPICE Canonical Compiler (v0.3.1)
    修復：GND 前線正規化、解決 Aliasing 與 Missing Ground 誤判
    新增：K 元件 (Mutual Inductance) 支援
    """
    def __init__(self, file_path=None, content=None):
        self.file_path = file_path or "memory_buffer.cir"
        self.raw_content = content
        self.diagnostics = []
        
        self.circuit = {
            "schema": "nextspice.circuit.v0.1",
            "name": "Untitled", # 🚀 新增：網表標題
            "metadata": {
                "source": os.path.basename(self.file_path),
                "compiled_at": "",
                "ground_node": "0",
                "measures": [] 
            },
            "options": {},    
            "outputs": [],   
            "elements": [],
            "models": [],
            "analyses": [],
            "params": {}
        }

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

            for i, line in enumerate(raw_lines):
                stripped = line.strip()
                if stripped:
                    if not stripped.startswith('*'):
                        self.circuit["name"] = stripped
                        raw_lines[i] = "* " + stripped
                    else:
                        self.circuit["name"] = stripped[1:].strip()
                    break

            preprocessed = self._preprocess(raw_lines)
            raw_ast = self._parse_to_raw_ast(preprocessed)
            self._normalize_to_canonical(raw_ast)
            self._validate_circuit()
            
            return {
                "circuit": self.circuit,
                "diagnostics": self.diagnostics
            }

    def _preprocess(self, raw_lines):
        processed = []
        buffer = ""
        start_line = 0

        for i, line in enumerate(raw_lines, 1):
            line = line.strip()
            if not line or line.startswith('*'): continue
            
            line = re.split(r'[;$]', line)[0].strip()
            if not line: continue

            upper_line = line.upper()
            if upper_line.startswith('.END') and not upper_line.startswith('.ENDS'):
                if buffer: processed.append((start_line, buffer))
                processed.append((i, '.END'))
                break

            if line.startswith('+'):
                buffer += " " + line[1:].strip()
            else:
                if buffer: processed.append((start_line, buffer))
                buffer = line
                start_line = i
        else:
            if buffer: processed.append((start_line, buffer))

        return processed

    def _tokenize(self, content: str) -> list:
        # 把 {} 裡面的空白通通消除，確保它不會被 split 拆散
        content = re.sub(r'\{([^}]+)\}', lambda m: '{' + m.group(1).replace(' ', '') + '}', content)
        clean_line = content.replace('(', ' ( ').replace(')', ' ) ').replace(',', ' ')
        return [t.strip() for t in clean_line.split() if t.strip()]

    def _parse_to_raw_ast(self, lines):
        ast = []
        for line_no, content in lines:
            if content.upper() == '.END': continue
            tokens = self._tokenize(content)
            if not tokens: continue
            ast.append({
                "line_no": line_no,
                "raw": content,
                "tokens": tokens,
                "kind": "directive" if tokens[0].startswith('.') else "element"
            })
        return ast

    # ----------------------------------------------------------------
    # 核心修復：前線正規化攔截器
    # ----------------------------------------------------------------
    def _norm_node(self, node_str):
        """將所有 GND, GROUND 在解析瞬間就強制轉換為 0"""
        n = str(node_str).upper()
        return "0" if n in ["GND", "GROUND"] else n


    def _build_param_env(self, raw_ast):
        """第一遍掃描：建立參數變數環境"""
        self.param_env = {}
        import math
        # 將 math 函式庫裡的東西全部轉大寫存入 (例如 pi -> PI, sin -> SIN)
        for k in dir(math):
            if not k.startswith('_'): 
                self.param_env[k.upper()] = getattr(math, k)

        for item in raw_ast:
            if item["kind"] == "directive" and item["tokens"][0].upper() == ".PARAM":
                s = " ".join(item["tokens"][1:])
                pairs = re.findall(r'([A-Z0-9_]+)\s*=\s*([^\s]+)', s, re.I)
                for k, v in pairs:
                    try:
                        self.param_env[k.upper()] = UnitConverter.parse(v)
                    except:
                        self.param_env[k.upper()] = v

    def _eval_val(self, val_str):
        """運算大括號內的表達式，或進行單位轉換"""
        val_str = str(val_str)
        if val_str.startswith('{') and val_str.endswith('}'):
            expr = val_str[1:-1].upper() # 提取 {} 內的算式
            try:
                result = eval(expr, {"__builtins__": None}, self.param_env)
                return float(result)
            except Exception as e:
                raise ValueError(f"Failed to evaluate param expression '{expr}': {e}")
        return UnitConverter.parse(val_str)



    def _normalize_to_canonical(self, raw_ast):
        self._build_param_env(raw_ast)
        seen_elements = set()

        for item in raw_ast:
            tokens = item["tokens"]
            ln = item["line_no"]
            
            if item["kind"] == "element":
                name = tokens[0].upper()
                if name in seen_elements:
                    self._log_diag(ln, "ERROR", f"Duplicate element: {name}")
                seen_elements.add(name)

                prefix = name[0]
                try:
                    if prefix == 'R': self._parse_resistor(item)
                    elif prefix == 'C': self._parse_capacitor(item)
                    elif prefix == 'L': self._parse_inductor(item)
                    # 🚀 在這裡補上了 K 元件的攔截點！
                    elif prefix == 'K': self._parse_mutual_inductance(item)
                    elif prefix in ['V', 'I']: self._parse_source(item, prefix)
                    elif prefix == 'E': self._parse_vcvs(item)
                    elif prefix == 'G': self._parse_vccs(item)  # 新增
                    elif prefix == 'H': self._parse_ccvs(item)  # 新增
                    elif prefix == 'F': self._parse_cccs(item)  # 新增
                    elif prefix == 'D': self._parse_diode(item)
                    elif prefix == 'X': self._parse_subckt_call(item) 
                    else:
                        self._log_diag(ln, "WARNING", f"Unsupported prefix '{prefix}' for {name}")
                except Exception as e:
                    self._log_diag(ln, "ERROR", f"Element {name} parse error: {str(e)}")

            elif item["kind"] == "directive":
                cmd = tokens[0].upper()
                try:
                    if cmd == '.TRAN': self._parse_tran(item)
                    elif cmd == '.AC': self._parse_ac(item)
                    elif cmd == '.DC': self._parse_dc(item)
                    elif cmd == '.OP': self.circuit["analyses"].append({"type": "op"})
                    elif cmd == '.PARAM': self._parse_param(item)
                    elif cmd == '.MODEL': self._parse_model(item)
                    elif cmd == '.OPTIONS': self._parse_options(item)
                    elif cmd in ['.PRINT', '.PLOT']: self._parse_output(item)
                    elif cmd in ['.MEAS', '.MEASURE']: self._parse_measure(item)
                    else:
                        self._log_diag(ln, "INFO", f"Ignored directive: {cmd}")
                except Exception as e:
                    self._log_diag(ln, "ERROR", f"Directive {cmd} parse error: {str(e)}")

    # --- 3. Sub-Parsers (全部套用 _norm_node) ---

    def _parse_resistor(self, item):
        tk = item["tokens"]
        if len(tk) < 4: raise ValueError("R requires 2 nodes and value")
        self.circuit["elements"].append({
            "type": "resistor", "name": tk[0].upper(),
            "pins": {"p": self._norm_node(tk[1]), "n": self._norm_node(tk[2])},
            "value": self._eval_val(tk[3])  # 🚀 改用數學引擎
        })

    def _parse_source(self, item, prefix):
        tk = item["tokens"]
        if len(tk) < 3: raise ValueError(f"{prefix} source requires at least 2 nodes")
        
        spec, remainder = self._parse_source_spec(tk[3:])
        element = {
            "type": "voltage_source" if prefix == 'V' else "current_source",
            "name": tk[0].upper(),
            "pins": {
                "positive": self._norm_node(tk[1]),
                "negative": self._norm_node(tk[2])
            },
            **spec
        }
        if remainder:
            element["tran_waveform"] = " ".join(remainder)
        self.circuit["elements"].append(element)

    def _parse_source_spec(self, tokens):
        spec = {"dc_value": None, "ac_magnitude": None, "ac_phase_deg": 0.0}
        if not tokens: 
            spec["dc_value"] = 0.0
            return spec, []

        i = 0
        while i < len(tokens):
            t = tokens[i].upper()
            if t == "DC" and i + 1 < len(tokens):
                spec["dc_value"] = self._eval_val(tokens[i + 1]) # 🚀 改用數學引擎
                i += 2
            elif t == "AC" and i + 1 < len(tokens):
                spec["ac_magnitude"] = self._eval_val(tokens[i + 1]) # 🚀 改用數學引擎
                if i + 2 < len(tokens):
                    try:
                        spec["ac_phase_deg"] = self._eval_val(tokens[i + 2]) # 🚀 改用數學引擎
                        i += 3; continue
                    except: pass
                spec["ac_phase_deg"] = 0.0
                i += 2
            else:
                if spec["dc_value"] is None:
                    try:
                        spec["dc_value"] = self._eval_val(tokens[i]) # 🚀 改用數學引擎
                        i += 1; continue
                    except: pass
                break
        
        if spec["dc_value"] is None: spec["dc_value"] = 0.0
        return spec, tokens[i:]

    def _parse_vcvs(self, item):
        tk = item["tokens"]
        if len(tk) < 6: raise ValueError("VCVS (E) requires 4 nodes and gain")
        self.circuit["elements"].append({
            "type": "vcvs", "name": tk[0].upper(),
            "pins": {"p": self._norm_node(tk[1]), "n": self._norm_node(tk[2])},
            "ctrl_pins": {"cp": self._norm_node(tk[3]), "cn": self._norm_node(tk[4])},
            "gain": self._eval_val(tk[5]) # 🚀 改用數學引擎
        })

    def _parse_vccs(self, item): # G
        tk = item["tokens"]
        if len(tk) < 6: raise ValueError("VCCS (G) requires 4 nodes and transconductance")
        self.circuit["elements"].append({
            "type": "vccs", "name": tk[0].upper(),
            "pins": {"p": self._norm_node(tk[1]), "n": self._norm_node(tk[2])},
            "ctrl_pins": {"cp": self._norm_node(tk[3]), "cn": self._norm_node(tk[4])},
            "gain": self._eval_val(tk[5])
        })

    def _parse_ccvs(self, item): # H
        tk = item["tokens"]
        if len(tk) < 5: raise ValueError("CCVS (H) requires 2 nodes, ctrl source, and transresistance")
        self.circuit["elements"].append({
            "type": "ccvs", "name": tk[0].upper(),
            "pins": {"p": self._norm_node(tk[1]), "n": self._norm_node(tk[2])},
            "ctrl_source": tk[3].upper(),
            "gain": self._eval_val(tk[4])
        })

    def _parse_cccs(self, item): # F
        tk = item["tokens"]
        if len(tk) < 5: raise ValueError("CCCS (F) requires 2 nodes, ctrl source, and gain")
        self.circuit["elements"].append({
            "type": "cccs", "name": tk[0].upper(),
            "pins": {"p": self._norm_node(tk[1]), "n": self._norm_node(tk[2])},
            "ctrl_source": tk[3].upper(),
            "gain": self._eval_val(tk[4])
        })

    def _parse_capacitor(self, item):
        tk = item["tokens"]
        if len(tk) < 4: raise ValueError("C requires 2 nodes and value")
        self.circuit["elements"].append({
            "type": "capacitor", "name": tk[0].upper(),
            "pins": {"p": self._norm_node(tk[1]), "n": self._norm_node(tk[2])},
            "value": self._eval_val(tk[3]) # 🚀 改用數學引擎
        })

    def _parse_inductor(self, item):
        tk = item["tokens"]
        if len(tk) < 4: raise ValueError("L requires 2 nodes and value")
        self.circuit["elements"].append({
            "type": "inductor", "name": tk[0].upper(),
            "pins": {"p": self._norm_node(tk[1]), "n": self._norm_node(tk[2])},
            "value": self._eval_val(tk[3]) # 🚀 改用數學引擎
        })

    def _parse_mutual_inductance(self, item):
        tk = item["tokens"]
        if len(tk) < 4: raise ValueError("K requires 2 target inductors and a coupling coefficient")
        self.circuit["elements"].append({
            "type": "mutual_inductance", 
            "name": tk[0].upper(),
            "element1": tk[1].upper(),
            "element2": tk[2].upper(),
            "value": self._eval_val(tk[3]) # 🚀 改用數學引擎
        })

    def _parse_diode(self, item):
        tk = item["tokens"]
        if len(tk) < 4: raise ValueError("D requires A, K nodes and model")
        self.circuit["elements"].append({
            "type": "diode", "name": tk[0].upper(),
            "pins": {"a": self._norm_node(tk[1]), "k": self._norm_node(tk[2])},
            "model": tk[3].upper()
        })

    def _parse_subckt_call(self, item):
        tk = item["tokens"]
        if len(tk) < 3: raise ValueError("X requires nodes and subckt name")
        subname = tk[-1].upper()
        nodes = [self._norm_node(n) for n in tk[1:-1]]
        pins = {f"p{i}": n for i, n in enumerate(nodes)}
        self.circuit["elements"].append({
            "type": "subckt_call", "name": tk[0].upper(),
            "pins": pins, "subname": subname
        })

    def _parse_ac(self, item):
        tk = item["tokens"]
        if len(tk) < 5: raise ValueError(".AC requires sweep, points, fstart, fstop")
        self.circuit["analyses"].append({
            "type": "ac", "sweep": tk[1].upper(), "points": int(tk[2]),
            "fstart": self._eval_val(tk[3]), "fstop": self._eval_val(tk[4]) # 🚀 改用數學引擎
        })

    def _parse_tran(self, item):
        tk = item["tokens"]
        if len(tk) < 3: raise ValueError(".TRAN requires tstep and tstop")
        self.circuit["analyses"].append({
            "type": "tran", "tstep": self._eval_val(tk[1]), "tstop": self._eval_val(tk[2]) # 🚀 改用數學引擎
        })

    def _parse_dc(self, item):
        tk = item["tokens"]
        if len(tk) < 5: raise ValueError(".DC requires source, start, stop, step")
        self.circuit["analyses"].append({
            "type": "dc", "source": tk[1].upper(), "start": self._eval_val(tk[2]),
            "stop": self._eval_val(tk[3]), "step": self._eval_val(tk[4]) # 🚀 改用數學引擎
        })

    def _parse_param(self, item):
        s = " ".join(item["tokens"][1:])
        pairs = re.findall(r'([A-Z0-9_]+)\s*=\s*([^\s]+)', s, re.I)
        for k, v in pairs:
            self.circuit["params"][k.upper()] = v

    def _parse_model(self, item):
        tk = item["tokens"]
        if len(tk) < 3: raise ValueError(".MODEL requires name and type")
        self.circuit["models"].append({
            "name": tk[1].upper(), "type": tk[2].upper(),
            "raw_body": " ".join(tk[3:])
        })

    def _parse_options(self, item):
        tk = item["tokens"][1:]
        for token in tk:
            if '=' in token:
                key, val = token.split('=', 1)
                try:
                    # 嘗試將數值轉換，例如 1m 變成 0.001
                    self.circuit["options"][key.upper()] = self._eval_val(val)
                except:
                    # 如果不是數字（例如 METHOD=GEAR），就存字串
                    self.circuit["options"][key.upper()] = val.upper()
            else:
                # Boolean flag (例如 NODE)
                self.circuit["options"][token.upper()] = True

    def _parse_output(self, item):
        tk = item["tokens"]
        if len(tk) < 3: 
            self._log_diag(item["line_no"], "WARNING", f"{tk[0]} requires analysis type and targets")
            return
        self.circuit["outputs"].append({
            "directive": tk[0][1:].upper(),
            "analysis": tk[1].upper(),
            "targets": [v.upper() for v in tk[2:]]
        })

    def _parse_measure(self, item):
        tk = item["tokens"]
        if len(tk) < 4:
            self._log_diag(item["line_no"], "WARNING", ".MEASURE requires analysis, name, and expressions")
            return
        self.circuit["metadata"]["measures"].append({
            "type": "measure",
            "analysis_type": tk[1].upper(),
            "name": tk[2].upper(),
            "raw_args": tk[3:]
        })

    # --- 4. Diagnostics & Validation ---

    def _validate_circuit(self):
        """因為已經在前線做完 _norm_node，這裡可以直接乾淨俐落地抓 '0'"""
        node_counts = {}
        for el in self.circuit["elements"]:
            for n in el.get("pins", {}).values():
                node_counts[n] = node_counts.get(n, 0) + 1
            for n in el.get("ctrl_pins", {}).values():
                node_counts[n] = node_counts.get(n, 0) + 1
                
        if "0" not in node_counts:
            self._log_diag(0, "ERROR", "Missing ground connection (Node 0/GND)")
        
        for n, count in node_counts.items():
            if n != "0" and count < 2:
                self._log_diag(0, "WARNING", f"Floating node detected: {n}")

    def _log_diag(self, ln, sev, msg):
        self.diagnostics.append({"line": ln, "severity": sev, "message": msg})

    