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
        if not model_name:
            return None

        model_key = self._normalize_name(model_name)
        model_data = self.models.get(model_key)
        if not model_data:
            return None

        model_type = str(model_data.get("type", "")).strip().upper()
        if model_type != expected_type.upper():
            return None

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

                if p_node is not None:
                    self.node_mgr.add_node(p_node)
                if n_node is not None:
                    self.node_mgr.add_node(n_node)

                # 🚀 預先註冊 BJT 節點
                if el_type == "bjt":
                    for nk in ["collector", "base", "emitter"]:
                        nd = el_data.get(nk)
                        if nd is not None:
                            self.node_mgr.add_node(nd)

                # 🚀 預先註冊 MOSFET 節點
                if el_type == "mosfet":
                    for nk in ["drain", "gate", "source", "bulk"]:
                        nd = el_data.get(nk)
                        if nd is not None:
                            self.node_mgr.add_node(nd)

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
                elif el_type in ["mutual_inductance", "ccvs", "cccs"]:
                    deferred_elements.append(el_data)
                elif el_type == "bjt":
                    self._build_bjt(el_data, warnings)
                elif el_type == "subckt_call":
                    errors.append(f"Subcircuit {el_data['name']} was not flattened!")
                elif el_type == "mosfet":
                    self._build_mosfet(el_data, warnings)
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
                    self._build_current_controlled(
                        el_data,
                        pins.get("p"),
                        pins.get("n"),
                        el_type
                    )
            except Exception as e:
                errors.append(f"Pass 2 Error resolving {el_data.get('name', 'Unknown')}: {str(e)}")

        return BuildResult(
            success=(len(errors) == 0),
            errors=errors,
            warnings=warnings
        )

    def _build_resistor(self, data, p, n):
        self._add_element(
            Resistor(
                data["name"],
                self.node_mgr.get_node_index(p),
                self.node_mgr.get_node_index(n),
                data["value"]
            )
        )

    def _build_capacitor(self, data, p, n):
        self._add_element(
            Capacitor(
                data["name"],
                self.node_mgr.get_node_index(p),
                self.node_mgr.get_node_index(n),
                data["value"]
            )
        )

    def _build_inductor(self, data, p, n):
        self._add_element(
            Inductor(
                data["name"],
                self.node_mgr.get_node_index(p),
                self.node_mgr.get_node_index(n),
                data["value"]
            )
        )

    def _build_vsource(self, data, p, n):
        self._add_element(
            VoltageSource(
                data["name"],
                self.node_mgr.get_node_index(p),
                self.node_mgr.get_node_index(n),
                dc_value=data.get("dc_value", 0.0),
                ac_mag=data.get("ac_magnitude", 0.0),
                ac_phase=data.get("ac_phase_deg", 0.0),
                tran=data.get("tran_waveform")
            )
        )

    def _build_isource(self, data, p, n):
        self._add_element(
            CurrentSource(
                data["name"],
                self.node_mgr.get_node_index(p),
                self.node_mgr.get_node_index(n),
                dc_value=data.get("dc_value", 0.0),
                ac_mag=data.get("ac_magnitude", 0.0),
                ac_phase=data.get("ac_phase_deg", 0.0),
                tran=data.get("tran_waveform")
            )
        )

    def _build_voltage_controlled(self, data, p, n, el_type):
        cp = data["ctrl_pins"]["cp"]
        cn = data["ctrl_pins"]["cn"]

        self.node_mgr.add_node(cp)
        self.node_mgr.add_node(cn)

        np_id = self.node_mgr.get_node_index(p)
        nn_id = self.node_mgr.get_node_index(n)
        cp_id = self.node_mgr.get_node_index(cp)
        cn_id = self.node_mgr.get_node_index(cn)

        if el_type == "vcvs":
            self._add_element(VCVS(data["name"], np_id, nn_id, cp_id, cn_id, data["gain"]))
        else:
            self._add_element(VCCS(data["name"], np_id, nn_id, cp_id, cn_id, data["gain"]))

    def _build_current_controlled(self, data, p, n, el_type):
        np_id = self.node_mgr.get_node_index(p)
        nn_id = self.node_mgr.get_node_index(n)
        ctrl_src_name = self._normalize_name(data["ctrl_source"])

        if ctrl_src_name not in self._element_by_name:
            raise ValueError(
                f"Controlling source '{ctrl_src_name}' not found before being referenced."
            )

        if el_type == "ccvs":
            self._add_element(CCVS(data["name"], np_id, nn_id, ctrl_src_name, data["gain"]))
        else:
            self._add_element(CCCS(data["name"], np_id, nn_id, ctrl_src_name, data["gain"]))

    def _build_mutual(self, data):
        l1_name = self._normalize_name(data["element1"])
        l2_name = self._normalize_name(data["element2"])

        l1_obj = self._element_by_name.get(l1_name)
        l2_obj = self._element_by_name.get(l2_name)

        if not l1_obj or not l2_obj:
            raise ValueError(
                f"Target inductors '{l1_name}' or '{l2_name}' not found for Mutual Inductance '{data['name']}'"
            )

        self._add_element(MutualInductance(data["name"], l1_obj, l2_obj, data["value"]))

    def _build_diode(self, data, p, n, warnings):
        is_sat = 1e-14
        n_factor = 1.0

        model_name = data.get("model")
        if model_name:
            params = self._get_model_params(model_name, "D")
            if params is not None:
                if "IS" in params:
                    is_sat = float(params["IS"])
                if "N" in params:
                    n_factor = float(params["N"])
            else:
                self._warn(
                    warnings,
                    f"[WARN] Diode {data['name']} references unknown or invalid model '{model_name}'. Using defaults."
                )

        self._add_element(
            Diode(
                data["name"],
                self.node_mgr.get_node_index(p),
                self.node_mgr.get_node_index(n),
                is_sat=is_sat,
                n=n_factor
            )
        )

    def _build_bjt(self, data, warnings):
        is_sat = 1e-14
        bf = 100.0
        br = 1.0
        temp = 300.15
        bjt_type = "NPN"

        model_name = data.get("model")
        if model_name:
            params = self._get_model_params(model_name, "Q")
            if params is not None:
                if "IS" in params:
                    is_sat = float(params["IS"])
                if "BF" in params:
                    bf = float(params["BF"])
                if "BR" in params:
                    br = float(params["BR"])
                if "TEMP" in params:
                    temp = float(params["TEMP"])

                if bf > br:
                    bjt_type = "NPN"
                else:
                    bjt_type = "PNP"
            else:
                self._warn(
                    warnings,
                    f"[WARN] BJT {data['name']} references unknown or invalid model '{model_name}'. Using defaults."
                )

        collector = data.get("collector")
        base = data.get("base")
        emitter = data.get("emitter")

        nc_idx = self.node_mgr.get_node_index(collector)
        nb_idx = self.node_mgr.get_node_index(base)
        ne_idx = self.node_mgr.get_node_index(emitter)

        self._add_element(
            BJT(
                data["name"],
                nc=nc_idx,
                nb=nb_idx,
                ne=ne_idx,
                bjt_type=bjt_type,
                is_sat=is_sat,
                bf=bf,
                br=br,
                temp=temp
            )
        )

    def _build_mosfet(self, data, warnings):
        nd = self.node_mgr.get_node_index(data.get("drain"))
        ng = self.node_mgr.get_node_index(data.get("gate"))
        ns = self.node_mgr.get_node_index(data.get("source"))
        nb = self.node_mgr.get_node_index(data.get("bulk"))

        model_name = data.get("model", "")
        m_type = 'NMOS'
        kp = 50e-6
        vto = 0.8
        lam = 0.0

        if model_name:
            params = self._get_model_params(model_name, "M")
            if params is not None:
                if 'NMOS' in str(params.get('TYPE', 'NMOS')).upper():
                    m_type = 'NMOS'
                elif 'PMOS' in str(params.get('TYPE', '')).upper():
                    m_type = 'PMOS'
                elif 'N' in model_name.upper():
                    m_type = 'NMOS'
                else:
                    m_type = 'PMOS'
                kp = float(params.get('KP', kp))
                vto = float(params.get('VTO', vto))
                lam = float(params.get('LAMBDA', lam))
            else:
                # Fallback: 從模型名稱推斷
                m_type = 'NMOS' if 'N' in model_name.upper() else 'PMOS'
                self._warn(warnings, f"[WARN] MOSFET {data['name']} references unknown model '{model_name}'. Using defaults.")

        self._add_element(
            MOSFET(
                data["name"], nd, ng, ns, nb,
                model_type=m_type,
                w=data.get("w", 1e-6),
                l=data.get("l", 1e-6),
                kp=kp,
                vto=vto,
                lambda_val=lam
            )
        )

    def get_voltage_report(self, x):
        """將 MNA 解向量轉換回人類可讀的節點電壓"""
        report = {}
        for node_str, idx in self.node_mgr.mapping.items():
            if idx > 0 and idx - 1 < len(x):
                report[f"V({node_str})"] = x[idx - 1]
        return report