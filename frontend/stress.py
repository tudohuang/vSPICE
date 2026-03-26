import time
import sys
# 🚀 匯入你剛打造好的工業級 NextSPICE 核心
from nextspice.compiler.frontend import SpiceParser
from nextspice.runtime.circuit import Circuit
from nextspice.runtime.solver import Simulator

# === ⚙️ 燒機設定區 ===
# 警告：10000 個節點代表底層要解 10000 x 10000 的浮點數矩陣 (佔用約 800MB 記憶體)
# 如果你的電腦記憶體不夠，可以先從 2000 開始測！
N_STAGES = 10000  
TIME_STEPS = 50  # 暫態分析的時間步數 (每次都要重解一次矩陣)

def generate_rc_ladder(n):
    print(f"🔨 正在生成 {n} 級 RC 傳輸線網表...")
    lines = [f"{n}-Stage RC Ladder Stress Test"]
    # 輸入端給一個超快的脈衝波
    lines.append("V1 IN 0 PULSE(0 5 1n 0.1n 0.1n 5n 10n)")
    
    # 瘋狂串接電阻和電容
    for i in range(n):
        prev_node = "IN" if i == 0 else f"N{i}"
        curr_node = f"N{i+1}"
        lines.append(f"R{i+1} {prev_node} {curr_node} 1k")
        lines.append(f"C{i+1} {curr_node} 0 1p")
        
    # TRAN 分析設定 (總共算 TIME_STEPS 次)
    lines.append(f".TRAN 0.2n {0.2 * TIME_STEPS}n")
    lines.append(".END")
    
    return "\n".join(lines)

def run_stress_test():
    netlist = generate_rc_ladder(N_STAGES)
    
    print("\n" + "="*40)
    print("🚀 燒機測試開始 (NextSPICE 核心直連)")
    print("="*40)

    # --- 1. 編譯期 (Compiler) ---
    t_comp_start = time.perf_counter()
    parser = SpiceParser(content=netlist)
    parsed_data = parser.compile()
    t_comp_end = time.perf_counter()
    
    if parsed_data["diagnostics"]:
        print("❌ 編譯器發現錯誤！")
        return

    print(f"✅ 編譯完成 (Compiler) : {t_comp_end - t_comp_start:.4f} 秒")

    # --- 2. 建構期 (Builder) ---
    t_build_start = time.perf_counter()
    circuit = Circuit(name=parsed_data["circuit"]["name"])
    build_res = circuit.build_from_json(parsed_data["circuit"])
    t_build_end = time.perf_counter()

    if not build_res.success:
        print("❌ 電路建構失敗！")
        return

    print(f"✅ 建構完成 (Builder)  : {t_build_end - t_build_start:.4f} 秒")
    print(f"   📊 總節點數: {circuit.node_mgr.num_unknowns}")
    print(f"   📊 總元件數: {len(circuit.elements)}")

    # --- 3. 求解期 (Solver) ---
    t_solve_start = time.perf_counter()
    simulator = Simulator(circuit)
    
    analysis = parsed_data["circuit"]["analyses"][0]
    tran_results = simulator.solve_tran(analysis["tstep"], analysis["tstop"])
    t_solve_end = time.perf_counter()

    success_steps = len([r for r in tran_results if r["status"] == "SUCCESS"])
    
    print(f"🔥 模擬完成 (Solver)   : {t_solve_end - t_solve_start:.4f} 秒")
    print(f"   📊 成功步數: {success_steps} / {len(tran_results)}")
    print("="*40)
    print(f"🏆 總耗時: {(t_comp_end - t_comp_start) + (t_build_end - t_build_start) + (t_solve_end - t_solve_start):.4f} 秒")
    print("="*40)

if __name__ == "__main__":
    run_stress_test()