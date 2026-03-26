class SpiceFormatter:
    """
    NextSPICE 代碼美化器 (v0.2 - 修正 .END 排序問題)
    """
    @staticmethod
    def format(raw_text):
        if not raw_text.strip():
            return ""
            
        lines = raw_text.splitlines()
        formatted_lines = []
        
        # 1. 標題處理
        title = lines[0].strip()
        formatted_lines.append(title.upper() if not title.startswith('*') else title)
            
        elements = []
        directives = []
        
        for line in lines[1:]:
            s = line.strip()
            if not s or s.upper() == ".END": continue # 🚀 先無視 .END
            
            if s.startswith('*'):
                formatted_lines.append(s) # 註解直接放進去
            elif s.startswith('.'):
                directives.append(s.upper())
            else:
                tokens = s.split()
                if tokens:
                    tokens[0] = tokens[0].upper()
                    elements.append(tokens)

        # 2. 格式化元件
        if elements:
            formatted_lines.append("\n* --- Elements ---")
            for el in elements:
                name = f"{el[0]:<8}"
                # 處理節點對齊
                nodes = "".join([f"{n:<10}" for n in el[1:-1]])
                value = el[-1]
                formatted_lines.append(f"{name} {nodes} {value}")

        # 3. 格式化指令 (確保 .OP 在 .END 之前)
        if directives:
            formatted_lines.append("\n* --- Analysis ---")
            # 這裡可以照字母排，因為我們已經把 .END 拿掉了
            for d in sorted(directives):
                formatted_lines.append(d)

        # 4. 🚀 強制讓 .END 成為全劇終
        formatted_lines.append("\n.END")

        return "\n".join(formatted_lines)