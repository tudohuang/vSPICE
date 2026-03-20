from .elements import Resistor, VoltageSource, CurrentSource, Capacitor

class NodeManager:
    """
    職責：管理節點名稱與矩陣索引的對應。
    SPICE 標準：'0', 'GND', 'GROUND' 永遠映射到 0 (參考地)。
    """
    def __init__(self):
        # 修復點 4：維護雙向映射，避免 get_name() 的線性搜尋
        self.mapping = {"0": 0}
        self.rev_mapping = {0: "0"}
        self.count = 1  # 矩陣未知數索引從 1 開始

    def get_index(self, name):
        """將節點名稱轉為矩陣索引 (1-based)"""
        name = str(name).upper()
        if name in ["GND", "GROUND"]: 
            name = "0"
        
        if name not in self.mapping:
            self.mapping[name] = self.count
            self.rev_mapping[self.count] = name
            self.count += 1
        return self.mapping[name]

    def get_name(self, index):
        """修復點 4：透過 rev_mapping 達成 O(1) 查詢"""
        return self.rev_mapping.get(index, "UNKNOWN")

    @property
    def num_unknowns(self):
        """修復點 4: 傳回未知數數量 (不含地線)"""
        return self.count - 1

class BuildResult:
    """封裝電路構建結果與診斷資訊"""
    def __init__(self, success=True, errors=None, warnings=None, infos=None):
        self.success = success
        self.errors = errors or []
        self.warnings = warnings or []
        self.infos = infos or []

    def add_error(self, msg):
        self.success = False
        self.errors.append(msg)

    def __repr__(self):
        return (f"BuildResult(success={self.success}, errors={len(self.errors)}, "
                f"warnings={len(self.warnings)})")
class Circuit:
    """
    NextSPICE 電路容器 (v0.2)
    職責：實體化元件、管理 NodeManager、並收集構建階段的診斷。
    """
    def __init__(self, name="NextSPICE_Project"):
        self.name = name
        self.elements = []
        self.node_mgr = NodeManager()
        self.params = {}
        self.build_errors = []

    def add_element(self, element):
        self.elements.append(element)

    def build_from_json(self, circuit_json):
        """
        修復點 3 & 9：結構化構建邏輯與明確的支援範圍驗證。
        """
        self.build_errors = []
        self.params = circuit_json.get("params", {})
        
        for entry in circuit_json.get("elements", []):
            etype = entry.get("type", "").lower()
            ename = entry.get("name", "UNKNOWN")
            
            try:
                # 根據型別分發實體化
                if etype == "resistor":
                    p = self.node_mgr.get_index(entry["pins"]["p"])
                    n = self.node_mgr.get_index(entry["pins"]["n"])
                    val = entry.get("value", 1e-12)
                    self.add_element(Resistor(ename, p, n, val))

                elif etype == "voltage_source":
                    p = self.node_mgr.get_index(entry["pins"]["positive"])
                    n = self.node_mgr.get_index(entry["pins"]["negative"])
                    dc_val = entry.get("dc_value", 0.0)
                    
                    # 關鍵修復：把 AC 振幅與相位確實傳給元件！
                    self.add_element(VoltageSource(
                        ename, p, n, 
                        dc_value=dc_val,
                        ac_mag=entry.get("ac_magnitude"),
                        ac_phase=entry.get("ac_phase_deg"),
                        tran=entry.get("tran_waveform")
                    ))

                elif etype == "current_source":
                    p = self.node_mgr.get_index(entry["pins"]["positive"])
                    n = self.node_mgr.get_index(entry["pins"]["negative"])
                    dc_val = entry.get("dc_value", 0.0)
                    
                    # 電流源也要接通 AC 參數
                    self.add_element(CurrentSource(
                        ename, p, n, 
                        dc_value=dc_val,
                        ac_mag=entry.get("ac_magnitude"),
                        ac_phase=entry.get("ac_phase_deg"),
                        tran=entry.get("tran_waveform")
                    ))



                elif etype == "capacitor":
                    p = self.node_mgr.get_index(entry["pins"]["p"])
                    n = self.node_mgr.get_index(entry["pins"]["n"])
                    val = entry.get("value", 1e-12)
                    self.add_element(Capacitor(ename, p, n, val))

                # 修復點 9：明確攔截已 parse 但未實做的元件 (Inductor, Diode)
                elif etype in ["inductor", "diode", "mosfet"]:
                    raise NotImplementedError(f"Element type '{etype}' is documented but solver implementation is pending.")
                
                else:
                    raise ValueError(f"Unknown or unsupported element type: '{etype}'")

            except NotImplementedError as e:
                self.build_errors.append(f"STAMP_MISSING: {str(e)}")
            except KeyError as e:
                self.build_errors.append(f"PIN_ERROR: Element {ename} missing required pin {str(e)}")
            except Exception as e:
                self.build_errors.append(f"GENERIC_ERROR: Failed to instantiate {ename}: {str(e)}")

        success = len(self.build_errors) == 0
        return BuildResult(success=success, errors=self.build_errors)

    def get_voltage_report(self, solution_vec):
        """
        修復點 5：生成 Canonical 節點報告。
        """
        report = {}
        # 遍歷 NodeManager 的 rev_mapping 確保只列出有效節點
        for idx in range(self.node_mgr.count):
            name = self.node_mgr.get_name(idx)
            if idx == 0:
                report[name] = 0.0
            else:
                # 矩陣索引是 0-based (solution_vec)，而 NodeManager 是 1-based (idx)
                if idx - 1 < len(solution_vec):
                    report[name] = solution_vec[idx - 1]
        return report