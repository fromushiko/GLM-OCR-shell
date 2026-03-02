import re

def fix_ocr_file(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    result_lines = []
    
    for i, line in enumerate(lines):
        line = line.strip()
        
        if not line:
            result_lines.append('')
            continue
        
        if line.startswith('--- 第') or line.startswith('## ') or line.startswith('# '):
            result_lines.append(line)
            continue
        
        if len(line) < 15:
            result_lines.append(line)
            continue
        
        if result_lines:
            last_line = result_lines[-1]
            if len(last_line) >= 15:
                a = line.replace(' ', '')
                b = last_line.replace(' ', '')
                if a == b or a in b or b in a:
                    continue
                
                len_diff = abs(len(a) - len(b))
                if len_diff <= 10:
                    matching = sum(1 for i in range(min(len(a), len(b))) if a[i] == b[i])
                    max_len = max(len(a), len(b))
                    sim = matching / max_len if max_len > 0 else 0
                    if sim > 0.92:
                        continue
        
        result_lines.append(line)
    
    content = '\n'.join(result_lines)
    content = re.sub(r'\n{3,}', '\n\n', content)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"修复完成: {output_file}")

if __name__ == "__main__":
    import sys
    input_file = sys.argv[1] if len(sys.argv) > 1 else r"d:\pdfTranser\jianti.md"
    output_file = sys.argv[2] if len(sys.argv) > 2 else r"d:\pdfTranser\output_fixed.md"
    fix_ocr_file(input_file, output_file)
