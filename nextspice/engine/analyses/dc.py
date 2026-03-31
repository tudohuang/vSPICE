from .base import BaseAnalysis

class DCSweepAnalysis(BaseAnalysis):
    def run(self, simulator, circuit, step_suffix=""):
        src = self.config.get("source")
        start = self.config.get("start", 0.0)
        stop = self.config.get("stop", 1.0)
        swp_step = self.config.get("step", 0.1)

        dc_results = simulator.solve_dc_sweep(src, start, stop, swp_step)

        formatted_dc = []
        for r in dc_results:
            if r["result"].status != "SUCCESS": 
                continue
            report = {"v_in": r["v_in"]}
            # 把矩陣解轉成人類看得懂的 V() 與 I()
            report.update({k: self.safe_num(v) for k, v in simulator.get_full_report(r["result"].x).items()})
            formatted_dc.append(report)

        return {
            "status": "SUCCESS" if formatted_dc else "ERROR",
            "message": "" if formatted_dc else "DC sweep failed to converge",
            "atype": self.atype,
            "suffix": step_suffix,
            "data": formatted_dc,
            "src": src  # 🚀 必須保留給前端畫 X 軸
        }