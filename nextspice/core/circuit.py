from .elements import Resistor, VoltageSource, CurrentSource, Capacitor, Inductor, MutualInductance,VCVS, VCCS, CCVS, CCCS
from .unit_conv import UnitConverter
class NodeManager:
    """
    職責：管理節點名稱與矩陣索引的對應。
    SPICE 標準：'0', 'GND', 'GROUND' 永遠映射到 0 (參考地)。
    """
    def __init__(self):
        self.mapping = {"0": 0}
        self.rev_mapping = {0: "0"}
        self.count = 1  

    def get_index(self, name):
        name = str(name).upper()
        if name in ["GND", "GROUND"]: 
            name = "0"
        
        if name not in self.mapping:
            self.mapping[name] = self.count
            self.rev_mapping[self.count] = name
            self.count += 1
        return self.mapping[name]

    def get_name(self, index):
        return self.rev_mapping.get(index, "UNKNOWN")

    @property
    def num_unknowns(self):
        return self.count - 1

class BuildResult:
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
    def __init__(self, name="NextSPICE_Project"):
        self.name = name
        self.elements = []
        self.node_mgr = NodeManager()
        self.params = {}
        self.build_errors = []

    def add_element(self, element):
        self.elements.append(element)

    def build_from_json(self, circuit_json):
        self.build_errors = []
        self.params = circuit_json.get("params", {})
        
        for entry in circuit_json.get("elements", []):
            etype = entry.get("type", "").lower()
            ename = entry.get("name", "UNKNOWN")
            
            try:
                if etype == "resistor":
                    p = self.node_mgr.get_index(entry["pins"]["p"])
                    n = self.node_mgr.get_index(entry["pins"]["n"])
                    val = entry.get("value", 1e-12)
                    self.add_element(Resistor(ename, p, n, val))

                elif etype == "capacitor":
                    p = self.node_mgr.get_index(entry["pins"]["p"])
                    n = self.node_mgr.get_index(entry["pins"]["n"])
                    val = entry.get("value", 1e-12)
                    self.add_element(Capacitor(ename, p, n, val))

                elif etype == "inductor":
                    p = self.node_mgr.get_index(entry["pins"]["p"])
                    n = self.node_mgr.get_index(entry["pins"]["n"])
                    val = entry.get("value", 1e-9)
                    self.add_element(Inductor(ename, p, n, val))

                elif etype == "voltage_source":
                    p = self.node_mgr.get_index(entry["pins"]["positive"])
                    n = self.node_mgr.get_index(entry["pins"]["negative"])
                    
                    dc_val = entry.get("dc_value", 0.0)
                    tran_wave = entry.get("tran_waveform")
                    
                    # 🛡️ 智慧波形重組：修復 UnitConverter 沒報錯造成的錯位
                    if isinstance(dc_val, str):
                        try:
                            dc_val = float(dc_val)
                        except ValueError:
                            # 轉數字失敗，代表它是 "PULSE" 或 "SIN"！
                            # 把字串拼回 tran_waveform，並把 dc_value 歸零
                            tran_wave = f"{dc_val} {tran_wave or ''}".strip()
                            dc_val = 0.0

                    self.add_element(VoltageSource(
                        ename, p, n, 
                        dc_value=dc_val,
                        ac_mag=entry.get("ac_magnitude"),
                        ac_phase=entry.get("ac_phase_deg"),
                        tran=tran_wave
                    ))

                elif etype == "current_source":
                    p = self.node_mgr.get_index(entry["pins"]["positive"])
                    n = self.node_mgr.get_index(entry["pins"]["negative"])
                    
                    dc_val = entry.get("dc_value", 0.0)
                    tran_wave = entry.get("tran_waveform")
                    
                    # 🛡️ 電流源也套用一樣的防呆保護
                    if isinstance(dc_val, str):
                        try:
                            dc_val = float(dc_val)
                        except ValueError:
                            tran_wave = f"{dc_val} {tran_wave or ''}".strip()
                            dc_val = 0.0
                    
                    self.add_element(CurrentSource(
                        ename, p, n, 
                        dc_value=dc_val,
                        ac_mag=entry.get("ac_magnitude"),
                        ac_phase=entry.get("ac_phase_deg"),
                        tran=tran_wave
                    ))
                elif etype == "mutual_inductance":
                    # 必須從已經建好的 elements 裡面找出 L1 和 L2 的物件實體
                    l1_name = entry["element1"].upper()
                    l2_name = entry["element2"].upper()
                    l1_obj = next((e for e in self.elements if e.name == l1_name and isinstance(e, Inductor)), None)
                    l2_obj = next((e for e in self.elements if e.name == l2_name and isinstance(e, Inductor)), None)
                    
                    if not l1_obj or not l2_obj:
                        self.build_errors.append(f"Mutual Inductance {ename} cannot find target inductors {l1_name} or {l2_name}")
                    else:
                        self.add_element(MutualInductance(ename, l1_obj, l2_obj, entry["value"]))                
                elif etype == "vcvs":
                    p = self.node_mgr.get_index(entry["pins"]["p"])
                    n = self.node_mgr.get_index(entry["pins"]["n"])
                    cp = self.node_mgr.get_index(entry["ctrl_pins"]["cp"])
                    cn = self.node_mgr.get_index(entry["ctrl_pins"]["cn"])
                    self.add_element(VCVS(ename, p, n, cp, cn, entry["gain"]))

                elif etype == "vccs":
                    p = self.node_mgr.get_index(entry["pins"]["p"])
                    n = self.node_mgr.get_index(entry["pins"]["n"])
                    cp = self.node_mgr.get_index(entry["ctrl_pins"]["cp"])
                    cn = self.node_mgr.get_index(entry["ctrl_pins"]["cn"])
                    self.add_element(VCCS(ename, p, n, cp, cn, entry["gain"]))

                elif etype in ["ccvs", "cccs"]:
                    p = self.node_mgr.get_index(entry["pins"]["p"])
                    n = self.node_mgr.get_index(entry["pins"]["n"])
                    ctrl_src = entry["ctrl_source"]
                    gain = entry["gain"]
                    if etype == "ccvs":
                        self.add_element(CCVS(ename, p, n, ctrl_src, gain))
                    else:
                        self.add_element(CCCS(ename, p, n, ctrl_src, gain))



                elif etype in ["diode", "mosfet"]:
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
        report = {}
        for idx in range(self.node_mgr.count):
            name = self.node_mgr.get_name(idx)
            if idx == 0:
                report[name] = 0.0
            else:
                if idx - 1 < len(solution_vec):
                    report[name] = solution_vec[idx - 1]
        return report