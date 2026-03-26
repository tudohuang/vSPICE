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
            if len(tk) < 3: raise ValueError(".MODEL requires name and type")
            circuit["models"].append({
                "name": tk[1].upper(), "type": tk[2].upper(),
                "raw_body": " ".join(tk[3:])
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
        elif cmd in ['.PRINT', '.PLOT']:
            if len(tk) < 3: raise ValueError(f"{cmd} requires analysis type and targets")
            circuit["outputs"].append({
                "directive": cmd[1:], "analysis": tk[1].upper(),
                "targets": [v.upper() for v in tk[2:]]
            })
        elif cmd in ['.MEAS', '.MEASURE']:
            if len(tk) < 4: raise ValueError(".MEASURE requires analysis, name, and expressions")
            circuit["metadata"]["measures"].append({
                "type": "measure", "analysis_type": tk[1].upper(),
                "name": tk[2].upper(), "raw_args": tk[3:]
            })
            
        elif cmd == '.SENS':
            # 語法範例: .SENS V(MID) V1
            if len(tk) < 2: 
                raise ValueError(".SENS requires at least one target variable")
            
            # 🚀 確保存進去的是一個乾淨的陣列，例如 ["V(MID)", "V1"]
            circuit["analyses"].append({
                "type": "sens",
                "targets": [v.upper() for v in tk[1:]] 
            })
        elif cmd == '.STEP':
            # 語法範例: .STEP PARAM R1 1k 10k 2k  或  .STEP R1 1k 10k 2k
            if len(tk) < 5: 
                raise ValueError(".STEP requires target, start, stop, step")
            
            # 判斷有沒有寫 "PARAM" 關鍵字
            if tk[1].upper() == 'PARAM':
                target = tk[2].upper()
                start_idx = 3
            else:
                target = tk[1].upper()
                start_idx = 2
            
            # 將步進設定存入 circuit，作為全域設定
            circuit["step_config"] = {
                "target": target,
                "start": eval_func(tk[start_idx]),
                "stop": eval_func(tk[start_idx+1]),
                "step": eval_func(tk[start_idx+2])
            }

        else:
            log_diag("INFO", f"Ignored directive: {cmd}")
    except Exception as e:
        log_diag("ERROR", f"Directive {cmd} parse error: {str(e)}")