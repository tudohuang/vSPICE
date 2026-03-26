import re

def preprocess(raw_lines):
    processed = []
    buffer = ""
    start_line = 0
    for i, line in enumerate(raw_lines, 1):
        line = line.strip()
        if not line or line.startswith('*'): continue
        
        line = re.split(r'[;$]', line)[0].strip()
        if not line: continue

        upper_line = line.upper()
        if upper_line.startswith('.END') and not upper_line.startswith('.ENDS'):
            if buffer: processed.append((start_line, buffer))
            processed.append((i, '.END'))
            break

        if line.startswith('+'):
            buffer += " " + line[1:].strip()
        else:
            if buffer: processed.append((start_line, buffer))
            buffer = line
            start_line = i
    else:
        if buffer: processed.append((start_line, buffer))
    return processed

def tokenize(content: str) -> list:
    content = re.sub(r'\{([^}]+)\}', lambda m: '{' + m.group(1).replace(' ', '') + '}', content)
    clean_line = content.replace('(', ' ( ').replace(')', ' ) ').replace(',', ' ')
    return [t.strip() for t in clean_line.split() if t.strip()]

def parse_to_raw_ast(lines):
    ast = []
    for line_no, content in lines:
        if content.upper() == '.END': continue
        tokens = tokenize(content)
        if not tokens: continue
        ast.append({
            "line_no": line_no,
            "raw": content,
            "tokens": tokens,
            "kind": "directive" if tokens[0].startswith('.') else "element"
        })
    return ast