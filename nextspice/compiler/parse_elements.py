def norm_node(node_str):
    n = str(node_str).upper()
    return "0" if n in ["GND", "GROUND"] else n

def parse_source_spec(tokens, eval_func):
    spec = {"dc_value": None, "ac_magnitude": None, "ac_phase_deg": 0.0}
    if not tokens: 
        spec["dc_value"] = 0.0
        return spec, []

    i = 0
    while i < len(tokens):
        t = tokens[i].upper()
        if t == "DC" and i + 1 < len(tokens):
            spec["dc_value"] = eval_func(tokens[i + 1]); i += 2
        elif t == "AC" and i + 1 < len(tokens):
            spec["ac_magnitude"] = eval_func(tokens[i + 1]) 
            if i + 2 < len(tokens):
                try: spec["ac_phase_deg"] = eval_func(tokens[i + 2]); i += 3; continue
                except: pass
            spec["ac_phase_deg"] = 0.0; i += 2
        else:
            if spec["dc_value"] is None:
                try: spec["dc_value"] = eval_func(tokens[i]); i += 1; continue
                except: pass
            break
    
    if spec["dc_value"] is None: spec["dc_value"] = 0.0
    return spec, tokens[i:]

def parse_element(item, circuit, diagnostics, eval_func):
    tk = item["tokens"]
    ln = item["line_no"]
    name = tk[0].upper()
    
    if name.startswith('VM'):
        prefix = 'VM'
    elif name.startswith('AM'):
        prefix = 'AM'
    else:
        prefix = name[0]

    def log_err(msg): diagnostics.append({"line": ln, "severity": "ERROR", "message": msg})

    try:
        if prefix == 'R':
            if len(tk) < 4: raise ValueError("R requires 2 nodes and value")
            circuit["elements"].append({
                "type": "resistor", "name": name,
                "pins": {"p": norm_node(tk[1]), "n": norm_node(tk[2])},
                "value": eval_func(tk[3]) 
            })
        elif prefix == 'C':
            if len(tk) < 4: raise ValueError("C requires 2 nodes and value")
            circuit["elements"].append({
                "type": "capacitor", "name": name,
                "pins": {"p": norm_node(tk[1]), "n": norm_node(tk[2])},
                "value": eval_func(tk[3])
            })
        elif prefix == 'L':
            if len(tk) < 4: raise ValueError("L requires 2 nodes and value")
            circuit["elements"].append({
                "type": "inductor", "name": name,
                "pins": {"p": norm_node(tk[1]), "n": norm_node(tk[2])},
                "value": eval_func(tk[3])
            })
        elif prefix == 'K':
            if len(tk) < 4: raise ValueError("K requires 2 target inductors and a coupling coefficient")
            circuit["elements"].append({
                "type": "mutual_inductance", "name": name,
                "element1": tk[1].upper(), "element2": tk[2].upper(),
                "value": eval_func(tk[3])
            })
        elif prefix in ['V', 'I']:
            if len(tk) < 3: raise ValueError(f"{prefix} source requires at least 2 nodes")
            spec, remainder = parse_source_spec(tk[3:], eval_func)
            element = {
                "type": "voltage_source" if prefix == 'V' else "current_source",
                "name": name,
                "pins": {"positive": norm_node(tk[1]), "negative": norm_node(tk[2])},
                **spec
            }
            if remainder: element["tran_waveform"] = " ".join(remainder)
            circuit["elements"].append(element)
        elif prefix == 'E':
            if len(tk) < 6: raise ValueError("VCVS (E) requires 4 nodes and gain")
            circuit["elements"].append({
                "type": "vcvs", "name": name,
                "pins": {"p": norm_node(tk[1]), "n": norm_node(tk[2])},
                "ctrl_pins": {"cp": norm_node(tk[3]), "cn": norm_node(tk[4])},
                "gain": eval_func(tk[5])
            })
        elif prefix == 'G':
            if len(tk) < 6: raise ValueError("VCCS (G) requires 4 nodes and transconductance")
            circuit["elements"].append({
                "type": "vccs", "name": name,
                "pins": {"p": norm_node(tk[1]), "n": norm_node(tk[2])},
                "ctrl_pins": {"cp": norm_node(tk[3]), "cn": norm_node(tk[4])},
                "gain": eval_func(tk[5])
            })
        elif prefix == 'H':
            if len(tk) < 5: raise ValueError("CCVS (H) requires 2 nodes, ctrl source, and transresistance")
            circuit["elements"].append({
                "type": "ccvs", "name": name,
                "pins": {"p": norm_node(tk[1]), "n": norm_node(tk[2])},
                "ctrl_source": tk[3].upper(), "gain": eval_func(tk[4])
            })
        elif prefix == 'F':
            if len(tk) < 5: raise ValueError("CCCS (F) requires 2 nodes, ctrl source, and gain")
            circuit["elements"].append({
                "type": "cccs", "name": name,
                "pins": {"p": norm_node(tk[1]), "n": norm_node(tk[2])},
                "ctrl_source": tk[3].upper(), "gain": eval_func(tk[4])
            })
        elif prefix == 'D':
            if len(tk) < 4: raise ValueError("D requires p, n nodes and model")
            circuit["elements"].append({
                "type": "diode", "name": name,
                "pins": {"p": norm_node(tk[1]), "n": norm_node(tk[2])},
                "model": tk[3].upper()
            })
        elif prefix == 'X':
            if len(tk) < 3: raise ValueError("X requires nodes and subckt name")
            subname = tk[-1].upper()
            nodes = [norm_node(n) for n in tk[1:-1]]
            pins = {f"p{i}": n for i, n in enumerate(nodes)}
            circuit["elements"].append({
                "type": "subckt_call", "name": name,
                "pins": pins, "subname": subname
            })
        elif prefix == 'Q':
            if len(tk) < 5: raise ValueError("BJT requires C, B, E nodes and model")
            circuit["elements"].append({
                "type": "bjt", "name": name,
                "collector": norm_node(tk[1]),
                "base": norm_node(tk[2]),
                "emitter": norm_node(tk[3]),
                "model": tk[4].upper()
            })

        elif prefix == 'M':
            if len(tk) < 6: raise ValueError("MOSFET (M) requires D, G, S, B nodes and model")
            
            params = {}
            for token in tk[6:]:
                if '=' in token:
                    k, v = token.split('=', 1)
                    params[k.lower()] = eval_func(v)
                    
            circuit["elements"].append({
                "type": "mosfet",
                "name": name,
                "drain": norm_node(tk[1]),
                "gate": norm_node(tk[2]),
                "source": norm_node(tk[3]),
                "bulk": norm_node(tk[4]),
                "model": tk[5].upper(),
                "w": params.get('w', 1e-6),
                "l": params.get('l', 1e-6)
            })


        else:
            diagnostics.append({"line": ln, "severity": "WARNING", "message": f"Unsupported prefix '{prefix}' for {name}"})
    except Exception as e:
        log_err(f"Element {name} parse error: {str(e)}")