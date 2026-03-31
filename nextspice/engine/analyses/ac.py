from .base import BaseAnalysis

class ACAnalysis(BaseAnalysis):
    def run(self, simulator, circuit, step_suffix=""):
        fstart = self.config.get("fstart", 1.0)
        fstop = self.config.get("fstop", 1e6)
        points = self.config.get("points", 10)
        sweep = self.config.get("sweep", "DEC")
        
        ac_results = simulator.solve_ac(fstart, fstop, points, sweep)
        
        # 檢查是否有任何成功的點
        has_error = any(r.get("status") == "ERROR" for r in ac_results)
        success_count = sum(1 for r in ac_results if r.get("status") == "SUCCESS")
        
        if success_count == 0:
            err_msg = ac_results[0].get("msg", "AC analysis failed") if ac_results else "No AC results"
            return {
                "status": "ERROR",
                "message": err_msg,
                "atype": self.atype,
                "suffix": step_suffix,
                "data": ac_results,
            }
        
        return {
            "status": "SUCCESS",
            "atype": self.atype,
            "suffix": step_suffix,
            "data": ac_results,
            "sweep": sweep
        }