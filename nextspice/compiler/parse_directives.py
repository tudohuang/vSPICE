def parse_directive(item, circuit, diagnostics, eval_func):
    tk = item["tokens"]
    ln = item["line_no"]
    cmd = tk[0].upper()
    
    def log_diag(sev, msg):
        diagnostics.append({"line": ln, "severity": sev, "message": msg})
        
    try:
        if cmd == '.TRAN':
            if len(tk) < 3: raise ValueError(".TRAN requires tstep and tstop")
            circuit["analyses"].append({
                "type": "tran", "tstep": eval_func(tk[1]), "tstop": eval_func(tk[2])
            })
        elif cmd == '.AC':
            if len(tk) < 5: raise ValueError(".AC requires sweep, points, fstart, fstop")
            circuit["analyses"].append({
                "type": "ac", "sweep": tk[1].upper(), "points": int(tk[2]),
                "fstart": eval_func(tk[3]), "fstop": eval_func(tk[4]) 
            })
        elif cmd == '.DC':
            if len(tk) < 5: raise ValueError(".DC requires source, start, stop, step")
            circuit["analyses"].append({
                "type": "dc", "source": tk[1].upper(), "start": eval_func(tk[2]),
                "stop": eval_func(tk[3]), "step": eval_func(tk[4]) 
            })
        elif cmd == '.OP':
            circuit["analyses"].append({"type": "op"})
        elif cmd == '.MODEL':
            import re
            if len(tk) < 3: raise ValueError(".MODEL requires name and type")
            model_name = tk[1].upper()
            # 有時候 type 和括號會黏在一起，例如 D(IS=...
            raw_type_str = tk[2].upper()
            model_type = raw_type_str.split('(')[0]
            
            # 把後面的所有 token 組合起來，拔掉括號，找出所有的 key=value
            param_str = " ".join(tk[2:]).upper()
            param_str = param_str[param_str.find(model_type)+len(model_type):].replace('(', ' ').replace(')', ' ')
            
            params = {}
            for match in re.finditer(r'([A-Z0-9_]+)\s*=\s*([^\s]+)', param_str):
                key, val_str = match.groups()
                try:
                    params[key] = eval_func(val_str) 
                except:
                    params[key] = val_str
                    
            circuit["models"].append({
                "name": model_name, "type": model_type, "params": params
            })
        elif cmd == '.OPTIONS':
            for token in tk[1:]:
                if '=' in token:
                    key, val = token.split('=', 1)
                    try:
                        circuit["options"][key.upper()] = eval_func(val)
                    except:
                        circuit["options"][key.upper()] = val.upper()
                else:
                    circuit["options"][token.upper()] = True
        elif cmd in ['.PRINT', '.PROBE']:
            if len(tk) >= 3:
                circuit["outputs"].append({
                    "type": cmd[1:],
                    "analysis_type": tk[1].lower(),
                    "targets": [t.upper() for t in tk[2:]]
                })
            else:
                diagnostics.append({"line": ln, "severity": "WARNING", "message": f"{cmd} requires analysis type and target variables"})
        elif cmd == '.SENS':
            if len(tk) < 2: 
                raise ValueError(".SENS requires at least one target variable")
            circuit["analyses"].append({
                "type": "sens",
                "targets": [v.upper() for v in tk[1:]] 
            })
        elif cmd == '.STEP':
            if len(tk) < 5: 
                raise ValueError(".STEP requires target, start, stop, step")
            if tk[1].upper() == 'PARAM':
                target = tk[2].upper()
                start_idx = 3
            else:
                target = tk[1].upper()
                start_idx = 2
            circuit["step_config"] = {
                "target": target,
                "start": eval_func(tk[start_idx]),
                "stop": eval_func(tk[start_idx+1]),
                "step": eval_func(tk[start_idx+2])
            }

# ==========================================
        # 🚀 .MEASURE 解析 (修復變數版)
        # ==========================================
        elif cmd in ['.MEASURE', '.MEAS']:
            # 把切碎的 token 重新組裝成一句話，這樣就不怕括號被切掉了
            # 例如 ['.MEASURE', 'TRAN', 'MAX_V', 'MAX', 'V', '(', 'OUT', ')']
            # 會變回 '.MEASURE TRAN MAX_V MAX V(OUT)'
            full_line_upper = "".join(tk) if len(tk) > 0 and '(' in tk[0] else " ".join(tk).upper()
            # 因為 join 可能會在括號前後多出空白，我們用 replace 修復它
            full_line_upper = full_line_upper.replace(" ( ", "(").replace(" )", ")").replace("( ", "(")

            # 重新用空白切開，確保 V(OUT) 黏在一起
            parts = full_line_upper.split()

            if len(parts) < 5:
                diagnostics.append({"line": ln, "severity": "WARN", "message": f"{cmd} 參數不足"})
            else:
                try:
                    m_data = {
                        "analysis_type": parts[1].lower(), 
                        "name": parts[2].upper()
                    }
                    
                    if "TRIG" in full_line_upper and "TARG" in full_line_upper:
                        import re
                        trig_match = re.search(r'TRIG\s+([^\s]+)\s+VAL=([0-9\.\-]+)\s+(RISE|FALL|CROSS)=([0-9]+)', full_line_upper)
                        targ_match = re.search(r'TARG\s+([^\s]+)\s+VAL=([0-9\.\-]+)\s+(RISE|FALL|CROSS)=([0-9]+)', full_line_upper)
                        if trig_match and targ_match:
                            m_data["trig_node"] = trig_match.group(1)
                            m_data["trig_val"] = float(trig_match.group(2))
                            m_data["trig_dir"] = trig_match.group(3)
                            m_data["trig_cross"] = int(trig_match.group(4))
                            
                            m_data["targ_node"] = targ_match.group(1)
                            m_data["targ_val"] = float(targ_match.group(2))
                            m_data["targ_dir"] = targ_match.group(3)
                            m_data["targ_cross"] = int(targ_match.group(4))
                    else:
                        m_data["operation"] = parts[3].upper()
                        m_data["target"] = parts[4].upper() 
                        
                    if "measures" not in circuit:
                        circuit["measures"] = []
                    circuit["measures"].append(m_data)
                except Exception as e:
                    diagnostics.append({"line": ln, "severity": "ERROR", "message": f"無法解析 .MEASURE: {str(e)}"})

        # ==========================================
        # 🚀 .FOUR 解析 (修復變數版)
        # ==========================================
        elif cmd == '.FOUR':
            # 一樣，把切碎的 token 重組成乾淨的字串再切一次
            full_line_upper = " ".join(tk).upper().replace(" ( ", "(").replace(" )", ")").replace("( ", "(")
            parts = full_line_upper.split()
            
            if len(parts) < 3:
                diagnostics.append({"line": ln, "severity": "WARN", "message": ".FOUR 指令參數不足"})
            else:
                try:
                    from nextspice.utils.unit_conv import UnitConverter as unit_conv
                    freq_val = float(unit_conv.parse(parts[1]))
                    
                    targets = [t.upper() for t in parts[2:]] 
                    
                    if "fourier" not in circuit:
                        circuit["fourier"] = []
                    circuit["fourier"].append({"freq": freq_val, "targets": targets})
                except Exception as e:
                    diagnostics.append({"line": ln, "severity": "ERROR", "message": f"無法解析 .FOUR 參數: {str(e)}"})


        else:
            log_diag("INFO", f"Ignored directive: {cmd}")
    except Exception as e:
        log_diag("ERROR", f"Directive {cmd} parse error: {str(e)}")