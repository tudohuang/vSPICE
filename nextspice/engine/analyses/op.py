from .base import BaseAnalysis

class OPAnalysis(BaseAnalysis):
    def run(self, simulator, circuit, step_suffix=""):
        res = simulator.solve_op()
        if res.status != "SUCCESS":
            return {"status": "ERROR", "message": res.error_msg, "atype": self.atype}
            
        report = {k: self.safe_num(v) for k, v in simulator.get_full_report(res.x).items()}
        
        return {
            "status": "SUCCESS",
            "atype": self.atype,
            "suffix": step_suffix,
            "data": report
        }