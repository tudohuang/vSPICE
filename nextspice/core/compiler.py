import re
import os
import datetime
from .unit_conv import UnitConverter

class SpiceParser:
    """
    NextSPICE Canonical Compiler (v0.3.1)
    修復：GND 前線正規化、解決 Aliasing 與 Missing Ground 誤判
    """
    def __init__(self, file_path=None, content=None):
        self.file_path = file_path or "memory_buffer.cir"
        self.raw_content = content
        self.diagnostics = []
        
        self.circuit = {
            "schema": "nextspice.circuit.v0.1",
            "metadata": {
                "source": os.path.basename(self.file_path),
                "compiled_at": "",
                "ground_node": "0"
            },
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

    def _normalize_to_canonical(self, raw_ast):
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
                    elif prefix in ['V', 'I']: self._parse_source(item, prefix)
                    elif prefix == 'E': self._parse_vcvs(item)
                    elif prefix == 'D': self._parse_diode(item)
                    elif prefix == 'X': self._parse_subckt_call(item) # 為 Boss 關卡預留
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
            "value": UnitConverter.parse(tk[3])
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
                spec["dc_value"] = UnitConverter.parse(tokens[i + 1])
                i += 2
            elif t == "AC" and i + 1 < len(tokens):
                spec["ac_magnitude"] = UnitConverter.parse(tokens[i + 1])
                if i + 2 < len(tokens):
                    try:
                        spec["ac_phase_deg"] = UnitConverter.parse(tokens[i + 2])
                        i += 3; continue
                    except: pass
                spec["ac_phase_deg"] = 0.0
                i += 2
            else:
                if spec["dc_value"] is None:
                    try:
                        spec["dc_value"] = UnitConverter.parse(tokens[i])
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
            "gain": UnitConverter.parse(tk[5])
        })

    def _parse_capacitor(self, item):
        tk = item["tokens"]
        if len(tk) < 4: raise ValueError("C requires 2 nodes and value")
        self.circuit["elements"].append({
            "type": "capacitor", "name": tk[0].upper(),
            "pins": {"p": self._norm_node(tk[1]), "n": self._norm_node(tk[2])},
            "value": UnitConverter.parse(tk[3])
        })

    def _parse_inductor(self, item):
        tk = item["tokens"]
        if len(tk) < 4: raise ValueError("L requires 2 nodes and value")
        self.circuit["elements"].append({
            "type": "inductor", "name": tk[0].upper(),
            "pins": {"p": self._norm_node(tk[1]), "n": self._norm_node(tk[2])},
            "value": UnitConverter.parse(tk[3])
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
        """讓包含子電路的 Boss 關卡不會因為找不到元件腳位而誤判沒接 GND"""
        tk = item["tokens"]
        if len(tk) < 3: raise ValueError("X requires nodes and subckt name")
        subname = tk[-1].upper()
        # 把中間的所有腳位都正規化
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
            "fstart": UnitConverter.parse(tk[3]), "fstop": UnitConverter.parse(tk[4])
        })

    def _parse_tran(self, item):
        tk = item["tokens"]
        if len(tk) < 3: raise ValueError(".TRAN requires tstep and tstop")
        self.circuit["analyses"].append({
            "type": "tran", "tstep": UnitConverter.parse(tk[1]), "tstop": UnitConverter.parse(tk[2])
        })

    def _parse_dc(self, item):
        tk = item["tokens"]
        if len(tk) < 5: raise ValueError(".DC requires source, start, stop, step")
        self.circuit["analyses"].append({
            "type": "dc", "source": tk[1].upper(), "start": UnitConverter.parse(tk[2]),
            "stop": UnitConverter.parse(tk[3]), "step": UnitConverter.parse(tk[4])
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