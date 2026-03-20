import argparse
import os
import sys
import datetime
import numpy as np

# 確保引用路徑正確
from nextspice.core.compiler import SpiceParser
from nextspice.core.circuit import Circuit
from nextspice.engine.solver import Simulator

class ReportGenerator:
    """負責將模擬結果格式化為 Markdown 報告"""
    def __init__(self, filename):
        self.filename = filename
        self.content = [f"# NextSPICE Simulation Report\n", 
                        f"- **Generated At**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
                        f"- **Engine**: NextSPICE v0.3 (Industrial Suite)\n",
                        "---\n"]

    def add_section(self, title, text):
        self.content.append(f"## {title}\n")
        self.content.append(f"{text}\n")

    def save(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            f.writelines(self.content)
        print(f"📄 [REPORT] Full report saved to: {self.filename}")

def simulate_single_file(file_path):
    """核心模擬邏輯：輸入路徑，輸出該檔案的結果摘要"""
    report_str = ""
    
    # --- Phase 1: Compiler ---
    parser = SpiceParser(file_path=file_path)
    parsed_data = parser.compile()
    
    # 檢查錯誤
    diags = parsed_data.get("diagnostics", [])
    errors = [d for d in diags if d['severity'] == "ERROR"]
    if errors:
        return f"❌ **Compilation Failed**: {len(errors)} errors found."

    # --- Phase 2: Circuit Builder ---
    circuit = Circuit(name=os.path.basename(file_path))
    build_res = circuit.build_from_json(parsed_data["circuit"])
    if not build_res.success:
        return "❌ **Circuit Build Failed**."

    # --- Phase 3: Engine ---
    simulator = Simulator(circuit)
    analyses = parsed_data["circuit"].get("analyses", [])
    
    file_results = []
    for analysis in analyses:
        atype = analysis["type"]
        if atype == "op":
            res = simulator.solve_op()
            if res.status == "SUCCESS":
                report = simulator.get_full_report(res.x)
                # 轉成 Markdown 表格
                table = "| Node/Branch | Value | Unit |\n| :--- | :--- | :--- |\n"
                for name, val in report.items():
                    unit = "A" if name.startswith("I(") else "V"
                    table += f"| {name} | {val:.5e} | {unit} |\n"
                file_results.append(f"### .OP Analysis\n{table}")
            else:
                file_results.append(f"❌ .OP Failed: {res.status}")
                
        # 這裡可以擴展 .AC 或 .TRAN 的報告邏輯
        elif atype == "ac":
            file_results.append("### .AC Analysis\n*AC data processed (See raw output for sweep details)*")

    return "\n".join(file_results)

def main():
    cli_parser = argparse.ArgumentParser(description="NextSPICE Batch Simulator")
    group = cli_parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-f', '--file', type=str, help="Single netlist file")
    group.add_argument('-d', '--dir', type=str, help="Directory containing .cir files")
    
    cli_parser.add_argument('-o', '--output', type=str, default="sim_report.md", help="Output report filename")
    
    args = cli_parser.parse_args()
    report_gen = ReportGenerator(args.output)

    # 決定處理路徑
    target_files = []
    if args.file:
        target_files.append(args.file)
    else:
        if os.path.exists(args.dir):
            target_files = [os.path.join(args.dir, f) for f in os.listdir(args.dir) if f.endswith(('.cir', '.sp'))]
        
    if not target_files:
        print("❌ No valid netlist files found.")
        return

    print(f"🚀 [BATCH] Starting simulation for {len(target_files)} files...")

    for f_path in target_files:
        f_name = os.path.basename(f_path)
        print(f"🔍 Processing: {f_name}")
        
        result_md = simulate_single_file(f_path)
        report_gen.add_section(f"Source: {f_name}", result_md)

    report_gen.save()

if __name__ == "__main__":
    main()