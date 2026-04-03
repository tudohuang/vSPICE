import json
import argparse
import sys
try:
    import matplotlib.pyplot as plt
except ImportError:
    print("❌ [ERROR] 找不到 matplotlib！請先執行: pip install matplotlib")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="vSPICE CLI 繪圖器 (Matplotlib)")
    parser.add_argument("data_file", help="vSPICE 匯出的 JSON 結果檔路徑 (例如 results.json)")
    args = parser.parse_args()

    # 1. 讀取 JSON 數據
    try:
        with open(args.data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ [ERROR] 無法讀取檔案 {args.data_file}: {e}")
        sys.exit(1)

    plots = data.get("plots", [])
    if not plots:
        print("⚠️ [WARNING] JSON 檔案中沒有找到任何繪圖數據 (plots 為空)。")
        sys.exit(0)

    layout = data.get("layout", {})
    is_ac = layout.get("is_ac", False)

    # 2. 設定 Matplotlib 畫布
    # 使用深色背景看起來更像專業儀器 (選配)
    plt.style.use('dark_background') 
    fig, ax = plt.subplots(figsize=(10, 6))
    
    ax.set_title(layout.get("title", "vSPICE Waveform Viewer"), fontsize=14, fontweight='bold')
    ax.set_xlabel(layout.get("xaxis", "X-axis"), fontsize=12)
    ax.set_ylabel(layout.get("yaxis", "Y-axis"), fontsize=12)
    
    # 開啟格線
    ax.grid(True, which="major", color="#444444", linestyle='-', alpha=0.8)
    if is_ac:
        ax.grid(True, which="minor", color="#333333", linestyle=':', alpha=0.5)

    # 3. 繪製所有波形
    for p in plots:
        x_vals = p.get("x", [])
        y_vals = p.get("y", [])
        name = p.get("name", "Unknown")
        
        # 根據我們之前定義的 type 決定實線或虛線 (電流通常是 dash)
        ls = "--" if p.get("type") == "dash" else "-"
        
        # AC 分析的 X 軸必須是 Log 座標
        if is_ac:
            ax.semilogx(x_vals, y_vals, label=name, linestyle=ls, linewidth=2)
        else:
            ax.plot(x_vals, y_vals, label=name, linestyle=ls, linewidth=2)

    # 4. 顯示圖例與繪製
    ax.legend(loc="upper right", framealpha=0.7)
    plt.tight_layout()
    
    print(f"[*] 成功載入 {len(plots)} 條波形，正在開啟繪圖視窗...")
    plt.show()

if __name__ == "__main__":
    main()