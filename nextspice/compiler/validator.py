def validate_circuit(circuit, diagnostics):
    def log_diag(ln, sev, msg):
        diagnostics.append({"line": ln, "severity": sev, "message": msg})

    node_counts = {}
    for el in circuit["elements"]:
        for n in el.get("pins", {}).values():
            node_counts[n] = node_counts.get(n, 0) + 1
        for n in el.get("ctrl_pins", {}).values():
            node_counts[n] = node_counts.get(n, 0) + 1
            
    if "0" not in node_counts:
        log_diag(0, "ERROR", "Missing ground connection (Node 0/GND)")
    
    for n, count in node_counts.items():
        if n != "0" and count < 2:
            log_diag(0, "WARNING", f"Floating node detected: {n}")