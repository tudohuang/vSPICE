from .base import BaseAnalysis

class TRANAnalysis(BaseAnalysis):
    def run(self, simulator, circuit, step_suffix=""):
        tstep = self.config.get("tstep", 1e-6)
        tstop = self.config.get("tstop", 1e-3)
        
        tran_results = simulator.solve_tran(tstep, tstop)
        
        formatted_tran = []
        for step in tran_results:
            if step.get("status") != "SUCCESS": continue
            report = {"time": step["time"]}
            report.update({k: self.safe_num(v) for k, v in simulator.get_full_report(step["x"]).items()})
            formatted_tran.append(report)
            
        return {
            "status": "SUCCESS" if formatted_tran else "ERROR",
            "message": "TRAN solver failed" if not formatted_tran else "",
            "atype": self.atype,
            "suffix": step_suffix,
            "data": formatted_tran
        }