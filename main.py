import argparse
import sys
import json
import os
import time

from nextspice.compiler.frontend import SpiceParser
from nextspice.runtime.circuit import Circuit
from nextspice.runtime.runner import SimulationRunner

def print_banner():
    print(r"""
             _____ _____ _____ _____ _____ 
    __   __ / ____|  __ \_   _/ ____|  ____|
    \ \ / /| (___ | |__) || || |     | |__   
     \ V /  \___ \|  ___/ | || |     |  __|  
      \ /   ____) | |    _| || |____ | |____ 
       V   |_____/|_|   |_____\_____|______|
                                v0.6 CLI Engine
    """)

def main():
    parser = argparse.ArgumentParser(description="NextSPICE Circuit Simulator CLI")
    parser.add_argument("netlist", help="要模擬的 SPICE 網表檔案路徑 (.cir, .sp)")
    parser.add_argument("-o", "--output", help="將前端繪圖用的 JSON 結果匯出到指定檔案", default=None)
    parser.add_argument("--dump-ast", action="store_true", help="只印出 Parser 編譯後的 JSON 藍圖並離開 (Debug 用)")
    
    args = parser.parse_args()

    if not os.path.exists(args.netlist):
        print(f"[ERROR] 找不到檔案: {args.netlist}")
        sys.exit(1)

    print_banner()
    print(f"[*] 讀取網表: {args.netlist} ...")

    start_time = time.time()

    # ==========================================
    # 階段 1：編譯器 (Compiler / Parser)
    # ==========================================
    spice_parser = SpiceParser(args.netlist)
    compiled_data = spice_parser.compile()
    
    blueprint = compiled_data.get("circuit", {})
    diagnostics = compiled_data.get("diagnostics", [])

    fatal_error = False
    for diag in diagnostics:
        severity = diag.get("severity", "INFO")
        line = diag.get("line", "?")
        msg = diag.get("message", "")
        if severity == "ERROR":
            print(f" [PARSE ERROR] Line {line}: {msg}")
            fatal_error = True
        else:
            print(f" [PARSE WARNING] Line {line}: {msg}")

    if fatal_error:
        print("\n[FATAL] 網表存在語法錯誤，模擬中止。")
        sys.exit(1)

    if args.dump_ast:
        print("\n[*] AST JSON 藍圖匯出:")
        print(json.dumps(blueprint, indent=2, default=str))
        sys.exit(0)

    # ==========================================
    # 階段 2：實體化電路模型 (Circuit Builder)
    # ==========================================
    print("[*] 建構電路模型...")
    circuit = Circuit()
    try:
        circuit.build_from_json(blueprint)
        print(f" └─ 成功: 節點數={circuit.node_mgr.num_unknowns}, 元件數={len(circuit.elements)}")
    except Exception as e:
        print(f"\n ❌ [BUILD ERROR] 電路建構失敗: {e}")
        sys.exit(1)

    # ==========================================
    # 階段 3：執行分析排程 (Simulation Runner)
    # ==========================================
    print("\n[*] 啟動模擬引擎...\n")
    runner = SimulationRunner(circuit, blueprint)
    response = runner.run_all()

    # ==========================================
    # 階段 4：結果展示
    # ==========================================
    print("================ 模擬日誌 ================")
    for log in response.get("logs", []):
        if "[ERR]" in log:
            print(f" {log}")
        elif "[WARN]" in log:
            print(f" {log}")
        elif "[OK]" in log:
            print(f" {log}")
        else:
            print(f"    {log}")
    print("==========================================")

    op_results = response.get("op_results", {})
    if op_results and not any("--- .OP Analysis ---" in l for l in response.get("logs", [])):
        print("\n測量與工作點數據 (.MEASURE / OP):")
        for k, v in op_results.items():
            print(f"    {k:<15}: {v:.6e}")

    elapsed = time.time() - start_time
    print(f"\n 總耗時: {elapsed*1000:.2f} ms")

    if response.get("status") != "success":
        print("[!] 模擬結束，發生錯誤。")
        sys.exit(1)
    else:
        print("[+] 模擬成功結束。")

    # ==========================================
    # 階段 5：匯出給前端或外部工具用的 JSON
    # ==========================================
    if args.output:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(response, f, indent=2)
            print(f"[+] 完整圖表數據已匯出至 {args.output}")
        except Exception as e:
            print(f" ❌ [IO ERROR] 無法儲存輸出檔案: {e}")

if __name__ == "__main__":
    main()