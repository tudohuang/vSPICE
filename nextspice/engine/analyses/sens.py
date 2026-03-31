from .base import BaseAnalysis

class SENSAnalysis(BaseAnalysis):
    def run(self, simulator, circuit, step_suffix=""):
        parts = self.config.get("targets", []) if isinstance(self.config.get("targets", []), list) else str(self.config.get("targets", "")).split()
        if not parts and "target" in self.config: parts = str(self.config["target"]).split()
        if not parts and "out" in self.config:
            parts.append(str(self.config["out"]))
            if "src" in self.config: parts.append(str(self.config["src"]))

        if not parts:
            return {"status": "ERROR", "message": "無法解析目標節點！", "atype": self.atype}

        out_node = parts[0].upper().replace("V(", "").replace("I(", "").replace(")", "").strip()
        in_src = parts[1].strip().upper() if len(parts) > 1 else None
        
        if not in_src:
            v_sources = [el.name for el in circuit.elements if el.name.upper().startswith("V") and not el.name.upper().startswith("VM")]
            in_src = v_sources[0] if v_sources else None

        if not in_src:
            return {"status": "ERROR", "message": "找不到輸入電壓源作為基準。", "atype": self.atype}

        # 掃描 R 與 V 元件
        components_to_test = [el.name for el in circuit.elements if el.name.upper().startswith("R") or (el.name.upper().startswith("V") and not el.name.upper().startswith("VM"))]
        sens_data = simulator.solve_sens_perturbation(out_node, in_src, components_to_test)

        if not sens_data or sens_data.get("status") == "ERROR":
            err_msg = sens_data.get("message") if sens_data else "未知錯誤"
            return {"status": "ERROR", "message": err_msg, "atype": self.atype}

        sens_report = {"Gain_Base(V/V)": self.safe_num(sens_data["base_gain"])}
        for comp, vals in sens_data["sensitivities"].items():
            if vals.get("status") == "SUCCESS":
                sens_report[f"SENS_ABS({comp})"] = self.safe_num(vals["absolute"])
                sens_report[f"SENS_NORM({comp})"] = self.safe_num(vals["normalized"])

        return {
            "status": "SUCCESS",
            "atype": self.atype,
            "suffix": step_suffix,
            "data": sens_report
        }