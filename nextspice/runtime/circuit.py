from nextspice.engine.elements import (
    Resistor, Capacitor, Inductor, VoltageSource, CurrentSource,
    VCVS, VCCS, CCVS, CCCS, MutualInductance, Diode, BJT, MOSFET
)

class NodeManager:
    """管理節點字串與 MNA 矩陣整數索引的映射"""
    def __init__(self):
        self.mapping = {}
        self.num_unknowns = 0

    def normalize_node(self, node_str):
        if node_str is None:
            return "0"
        node = str(node_str).strip().upper()
        if node in ["0", "GND"]:
            return "0"
        return node

    def add_node(self, node_str):
        node = self.normalize_node(node_str)
        if node == "0":
            return 0
        if node not in self.mapping:
            self.num_unknowns += 1
            self.mapping[node] = self.num_unknowns
        return self.mapping[node]

    def get_node_index(self, node_str):
        node = self.normalize_node(node_str)
        if node == "0":
            return 0
        return self.mapping.get(node, 0)

class BuildResult:
    def __init__(self, success=True, errors=None, warnings=None):
        self.success = success
        self.errors = errors or []
        self.warnings = warnings or []

class Circuit:
    """
    NextSPICE Runtime Circuit Builder
    負責將 Parser 的 JSON 藍圖實體化為 Python 物件。
    """
    def __init__(self, name="Untitled"):
        self.name = name
        self.node_mgr = NodeManager()
        self.elements = []
        self._element_by_name = {}
        self.analyses = []
        self.models = {}

    def _normalize_name(self, name):
        return str(name).strip().upper()

    def _add_element(self, obj):
        """統一的元件註冊站"""
        self.elements.append(obj)
        self._element_by_name[self._normalize_name(obj.name)] = obj

    def _warn(self, warnings, msg):
        warnings.append(msg)

    def _load_models(self, json_data):
        raw_models = json_data.get("models", {})
        models = {}
        if isinstance(raw_models, list):
            for m in raw_models:
                if isinstance(m, dict) and "name" in m:
                    models[self._normalize_name(m["name"])] = m
                elif isinstance(m, dict):
                    for k, v in m.items():
                        models[self._normalize_name(k)] = v
        elif isinstance(raw_models, dict):
            for k, v in raw_models.items():
                models[self._normalize_name(k)] = v
        return models

    def _get_model_params(self, model_name, expected_type):
        if not model_name: return None
        model_key = self._normalize_name(model_name)
        model_data = self.models.get(model_key)
        if not model_data: return None
        model_type = str(model_data.get("type", "")).strip().upper()
        if model_type != expected_type.upper(): return None
        params = model_data.get("params", model_data)
        return {self._normalize_name(k): v for k, v in params.items()}

    def build_from_json(self, json_data):
        self.name = json_data.get("name", "Untitled")
        self.models = self._load_models(json_data)

        errors = []
        warnings = []
        deferred_elements = []

        for el_data in json_data.get("elements", []):
            try:
                el_type = el_data.get("type")
                pins = el_data.get("pins", {})
                p_node = pins.get("p", pins.get("positive"))
                n_node = pins.get("n", pins.get("negative"))

                if p_node is not None: self.node_mgr.add_node(p_node)
                if n_node is not None: self.node_mgr.add_node(n_node)

                # 預先註冊多腳位元件節點
                if el_type == "bjt":
                    for nk in ["collector", "base", "emitter"]:
                        nd = el_data.get(nk)
                        if nd is not None: self.node_mgr.add_node(nd)
                if el_type == "mosfet":
                    # 支援舊版頂層屬性與新版 pins 字典
                    for nk in ["drain", "gate", "source", "bulk"]:
                        nd = pins.get(nk[0]) or el_data.get(nk)
                        if nd is not None: self.node_mgr.add_node(nd)

                # 乾淨的派發中心
                if el_type == "resistor":
                    self._build_resistor(el_data, p_node, n_node)
                elif el_type == "capacitor":
                    self._build_capacitor(el_data, p_node, n_node)
                elif el_type == "inductor":
                    self._build_inductor(el_data, p_node, n_node)
                elif el_type == "voltage_source":
                    self._build_vsource(el_data, p_node, n_node)
                elif el_type == "current_source":
                    self._build_isource(el_data, p_node, n_node)
                elif el_type in ["vcvs", "vccs"]:
                    self._build_voltage_controlled(el_data, p_node, n_node, el_type)
                elif el_type == "diode":
                    self._build_diode(el_data, p_node, n_node, warnings)
                elif el_type == "bjt":
                    self._build_bjt(el_data, warnings)
                elif el_type == "mosfet":
                    self._build_mosfet(el_data, warnings)
                elif el_type in ["mutual_inductance", "ccvs", "cccs"]:
                    deferred_elements.append(el_data)
                elif el_type == "subckt_call":
                    errors.append(f"Subcircuit {el_data['name']} was not flattened!")
                else:
                    errors.append(f"Unsupported element type: {el_type}")

            except Exception as e:
                errors.append(f"Pass 1 Error building {el_data.get('name', 'Unknown')}: {str(e)}")

        for el_data in deferred_elements:
            try:
                el_type = el_data.get("type")
                if el_type == "mutual_inductance":
                    self._build_mutual(el_data)
                elif el_type in ["ccvs", "cccs"]:
                    pins = el_data.get("pins", {})
                    self._build_current_controlled(el_data, pins.get("p"), pins.get("n"), el_type)
            except Exception as e:
                errors.append(f"Pass 2 Error resolving {el_data.get('name', 'Unknown')}: {str(e)}")

        return BuildResult(success=(len(errors) == 0), errors=errors, warnings=warnings)

    def _build_resistor(self, data, p, n):
        self._add_element(Resistor(data["name"], self.node_mgr.get_node_index(p), self.node_mgr.get_node_index(n), data["value"]))

    def _build_capacitor(self, data, p, n):
        self._add_element(Capacitor(data["name"], self.node_mgr.get_node_index(p), self.node_mgr.get_node_index(n), data["value"]))

    def _build_inductor(self, data, p, n):
        self._add_element(Inductor(data["name"], self.node_mgr.get_node_index(p), self.node_mgr.get_node_index(n), data["value"]))

    def _build_vsource(self, data, p, n):
        self._add_element(VoltageSource(
            data["name"], self.node_mgr.get_node_index(p), self.node_mgr.get_node_index(n),
            dc_value=data.get("dc_value", 0.0), ac_mag=data.get("ac_magnitude", 0.0),
            ac_phase=data.get("ac_phase_deg", 0.0), tran=data.get("tran_waveform")
        ))

    def _build_isource(self, data, p, n):
        self._add_element(CurrentSource(
            data["name"], self.node_mgr.get_node_index(p), self.node_mgr.get_node_index(n),
            dc_value=data.get("dc_value", 0.0), ac_mag=data.get("ac_magnitude", 0.0),
            ac_phase=data.get("ac_phase_deg", 0.0), tran=data.get("tran_waveform")
        ))

    def _build_voltage_controlled(self, data, p, n, el_type):
        cp, cn = data["ctrl_pins"]["cp"], data["ctrl_pins"]["cn"]
        self.node_mgr.add_node(cp)
        self.node_mgr.add_node(cn)
        np_id, nn_id = self.node_mgr.get_node_index(p), self.node_mgr.get_node_index(n)
        cp_id, cn_id = self.node_mgr.get_node_index(cp), self.node_mgr.get_node_index(cn)
        if el_type == "vcvs":
            self._add_element(VCVS(data["name"], np_id, nn_id, cp_id, cn_id, data["gain"]))
        else:
            self._add_element(VCCS(data["name"], np_id, nn_id, cp_id, cn_id, data["gain"]))

    def _build_current_controlled(self, data, p, n, el_type):
        np_id, nn_id = self.node_mgr.get_node_index(p), self.node_mgr.get_node_index(n)
        ctrl_src_name = self._normalize_name(data["ctrl_source"])
        if ctrl_src_name not in self._element_by_name:
            raise ValueError(f"Controlling source '{ctrl_src_name}' not found.")
        if el_type == "ccvs":
            self._add_element(CCVS(data["name"], np_id, nn_id, ctrl_src_name, data["gain"]))
        else:
            self._add_element(CCCS(data["name"], np_id, nn_id, ctrl_src_name, data["gain"]))

    def _build_mutual(self, data):
        l1_obj = self._element_by_name.get(self._normalize_name(data["element1"]))
        l2_obj = self._element_by_name.get(self._normalize_name(data["element2"]))
        if not l1_obj or not l2_obj:
            raise ValueError(f"Target inductors not found for Mutual Inductance '{data['name']}'")
        self._add_element(MutualInductance(data["name"], l1_obj, l2_obj, data["value"]))

    def _build_diode(self, data, p, n, warnings):
        is_sat, n_factor = 1e-14, 1.0
        params = self._get_model_params(data.get("model"), "D")
        if params:
            is_sat = float(params.get("IS", is_sat))
            n_factor = float(params.get("N", n_factor))
        self._add_element(Diode(data["name"], self.node_mgr.get_node_index(p), self.node_mgr.get_node_index(n), is_sat=is_sat, n=n_factor))

    def _build_bjt(self, data, warnings):
        is_sat, bf, br, temp, bjt_type = 1e-14, 100.0, 1.0, 300.15, "NPN"
        params = self._get_model_params(data.get("model"), "Q")
        if params:
            is_sat = float(params.get("IS", is_sat))
            bf = float(params.get("BF", bf))
            br = float(params.get("BR", br))
            temp = float(params.get("TEMP", temp))
            bjt_type = "NPN" if bf > br else "PNP"
            
        nc_idx = self.node_mgr.get_node_index(data.get("collector"))
        nb_idx = self.node_mgr.get_node_index(data.get("base"))
        ne_idx = self.node_mgr.get_node_index(data.get("emitter"))
        self._add_element(BJT(data["name"], nc=nc_idx, nb=nb_idx, ne=ne_idx, bjt_type=bjt_type, is_sat=is_sat, bf=bf, br=br, temp=temp))

    def _build_mosfet(self, data, warnings):
        # 🚀 無敵防呆版 MOSFET 腳位解析
        pins = data.get("pins", {})
        d_node = pins.get("d") or data.get("drain")
        g_node = pins.get("g") or data.get("gate")
        s_node = pins.get("s") or data.get("source")
        b_node = pins.get("b") or data.get("bulk")

        nd = self.node_mgr.get_node_index(d_node)
        ng = self.node_mgr.get_node_index(g_node)
        ns = self.node_mgr.get_node_index(s_node)
        nb = self.node_mgr.get_node_index(b_node)

        model_name = data.get("model", "")
        m_type, kp, vto, lam = 'NMOS', 50e-6, 0.8, 0.0

        params = self._get_model_params(model_name, "M")
        if params:
            m_type = 'NMOS' if 'N' in str(params.get('TYPE', 'NMOS')).upper() else 'PMOS'
            kp = float(params.get('KP', kp))
            vto = float(params.get('VTO', vto))
            lam = float(params.get('LAMBDA', lam))
        else:
            m_type = 'NMOS' if 'N' in model_name.upper() else 'PMOS'

        self._add_element(MOSFET(
            data["name"], nd, ng, ns, nb,
            model_type=m_type, w=data.get("w", 1e-6), l=data.get("l", 1e-6),
            kp=kp, vto=vto, lambda_val=lam
        ))

    def get_voltage_report(self, x):
        report = {}
        for node_str, idx in self.node_mgr.mapping.items():
            if idx > 0 and idx - 1 < len(x):
                report[f"V({node_str})"] = x[idx - 1]
        return report