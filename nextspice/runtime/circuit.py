from nextspice.engine.elements import (
    Resistor, Capacitor, Inductor, VoltageSource, CurrentSource,
    VCVS, VCCS, CCVS, CCCS, MutualInductance
)

class NodeManager:
    """管理節點字串與 MNA 矩陣整數索引的映射"""
    def __init__(self):
        self.mapping = {}
        self.num_unknowns = 0

    def add_node(self, node_str):
        if node_str == "0":
            return 0
        if node_str not in self.mapping:
            self.num_unknowns += 1
            self.mapping[node_str] = self.num_unknowns
        return self.mapping[node_str]

class BuildResult:
    def __init__(self, success=True, errors=None):
        self.success = success
        self.errors = errors or []

class Circuit:
    """
    NextSPICE Runtime Circuit Builder (v0.5 - Two-Pass 完美解析版)
    負責將 Parser 的 JSON 藍圖實體化為 Python 物件。
    """
    def __init__(self, name="Untitled"):
        self.name = name
        self.node_mgr = NodeManager()
        self.elements = []
        self._element_by_name = {} # 🚀 核心：用來 O(1) 查找已建立的元件
        self.analyses = []

    def _add_element(self, obj):
        """統一的元件註冊站"""
        self.elements.append(obj)
        self._element_by_name[obj.name] = obj

    def build_from_json(self, json_data):
        self.name = json_data.get("name", "Untitled")
        errors = []
        deferred_elements = [] # 🚀 存放需要 Pass 2 處理的相依元件

        # ==========================================
        # 🚀 Pass 1: 建立基礎獨立元件
        # ==========================================
        for el_data in json_data.get("elements", []):
            try:
                el_type = el_data.get("type")
                
                # 統一把 positive/negative 轉為標準的 p/n
                pins = el_data.get("pins", {})
                p_node = pins.get("p", pins.get("positive"))
                n_node = pins.get("n", pins.get("negative"))
                
                if p_node is not None: self.node_mgr.add_node(p_node)
                if n_node is not None: self.node_mgr.add_node(n_node)

                # 分發給各個專業的 Builder
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
                
                # 若是 K, H, F 元件，推遲到 Pass 2 處理
                elif el_type in ["mutual_inductance", "ccvs", "cccs"]:
                    deferred_elements.append(el_data)
                
                elif el_type == "subckt_call":
                    # 經過我們的 Macro Expansion，這裡理論上不該再看到子電路呼叫了
                    errors.append(f"Subcircuit {el_data['name']} was not flattened!")
                else:
                    errors.append(f"Unsupported element type: {el_type}")
                    
            except Exception as e:
                errors.append(f"Pass 1 Error building {el_data.get('name', 'Unknown')}: {str(e)}")

        # ==========================================
        # 🚀 Pass 2: 解析交叉參照 (Cross-Reference)
        # ==========================================
        for el_data in deferred_elements:
            try:
                el_type = el_data.get("type")
                if el_type == "mutual_inductance":
                    self._build_mutual(el_data)
                elif el_type in ["ccvs", "cccs"]:
                    pins = el_data.get("pins", {})
                    self._build_current_controlled(el_data, pins.get("p"), pins.get("n"), el_type)
            except Exception as e:
                errors.append(f"Pass 2 Error resolving {el_data.get('name')}: {str(e)}")

        return BuildResult(success=len(errors) == 0, errors=errors)

    # ---------------------------------------------------------
    # 🛠️ 拆分後的小型 Builder 函數
    # ---------------------------------------------------------
    def _build_resistor(self, data, p, n):
        self._add_element(Resistor(data["name"], self.node_mgr.mapping.get(p, 0), self.node_mgr.mapping.get(n, 0), data["value"]))

    def _build_capacitor(self, data, p, n):
        self._add_element(Capacitor(data["name"], self.node_mgr.mapping.get(p, 0), self.node_mgr.mapping.get(n, 0), data["value"]))

    def _build_inductor(self, data, p, n):
        self._add_element(Inductor(data["name"], self.node_mgr.mapping.get(p, 0), self.node_mgr.mapping.get(n, 0), data["value"]))

    def _build_vsource(self, data, p, n):
        self._add_element(VoltageSource(
            data["name"], self.node_mgr.mapping.get(p, 0), self.node_mgr.mapping.get(n, 0),
            dc_value=data.get("dc_value", 0.0), ac_mag=data.get("ac_magnitude", 0.0),
            ac_phase=data.get("ac_phase_deg", 0.0), tran=data.get("tran_waveform")
        ))

    def _build_isource(self, data, p, n):
        self._add_element(CurrentSource(
            data["name"], self.node_mgr.mapping.get(p, 0), self.node_mgr.mapping.get(n, 0),
            dc_value=data.get("dc_value", 0.0), ac_mag=data.get("ac_magnitude", 0.0),
            ac_phase=data.get("ac_phase_deg", 0.0), tran=data.get("tran_waveform")
        ))

    def _build_voltage_controlled(self, data, p, n, el_type):
        cp = data["ctrl_pins"]["cp"]
        cn = data["ctrl_pins"]["cn"]
        self.node_mgr.add_node(cp)
        self.node_mgr.add_node(cn)
        
        np_id = self.node_mgr.mapping.get(p, 0)
        nn_id = self.node_mgr.mapping.get(n, 0)
        cp_id = self.node_mgr.mapping.get(cp, 0)
        cn_id = self.node_mgr.mapping.get(cn, 0)
        
        if el_type == "vcvs":
            self._add_element(VCVS(data["name"], np_id, nn_id, cp_id, cn_id, data["gain"]))
        else:
            self._add_element(VCCS(data["name"], np_id, nn_id, cp_id, cn_id, data["gain"]))

    def _build_current_controlled(self, data, p, n, el_type):
        np_id = self.node_mgr.mapping.get(p, 0)
        nn_id = self.node_mgr.mapping.get(n, 0)
        ctrl_src_name = data["ctrl_source"]
        
        # 🚀 防呆驗證：確保依賴的控制源真的存在！
        if ctrl_src_name not in self._element_by_name:
            raise ValueError(f"Controlling source '{ctrl_src_name}' not found before being referenced.")
            
        if el_type == "ccvs":
            self._add_element(CCVS(data["name"], np_id, nn_id, ctrl_src_name, data["gain"]))
        else:
            self._add_element(CCCS(data["name"], np_id, nn_id, ctrl_src_name, data["gain"]))

    def _build_mutual(self, data):
        l1_name = data["element1"]
        l2_name = data["element2"]
        l1_obj = self._element_by_name.get(l1_name)
        l2_obj = self._element_by_name.get(l2_name)
        
        # 🚀 防呆驗證：確保這兩顆電感真的存在！
        if not l1_obj or not l2_obj:
            raise ValueError(f"Target inductors '{l1_name}' or '{l2_name}' not found for Mutual Inductance '{data['name']}'")
            
        self._add_element(MutualInductance(data["name"], l1_obj, l2_obj, data["value"]))

    def get_voltage_report(self, x):
        """將 MNA 解向量轉換回人類可讀的節點電壓"""
        report = {}
        for node_str, idx in self.node_mgr.mapping.items():
            if idx > 0 and idx - 1 < len(x):
                report[f"V({node_str})"] = x[idx - 1]
        return report