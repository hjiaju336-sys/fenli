import sys

with open('D:/project/规则怪谈/fenli/mvp/static/_debug_js.js', encoding='utf-8') as f:
    js = f.read()

curly = 0
square = 0
paren = 0
in_string = False
string_char = ''
skip_next = False

for i, ch in enumerate(js):
    if skip_next:
        skip_next = False
        continue

    if in_string:
        if ch == '\\':
            skip_next = True
            continue
        if ch == string_char:
            in_string = False
    else:
        if ch in ['"', "'", '`']:
            in_string = True
            string_char = ch
        elif ch == '{':
            curly += 1
        elif ch == '}':
            curly -= 1
            if curly < 0:
                line = js[:i].count('\n') + 1
                print(f'Extra }} at position {i}, line ~{line}')
        elif ch == '[':
            square += 1
        elif ch == ']':
            square -= 1
            if square < 0:
                line = js[:i].count('\n') + 1
                print(f'Extra ] at position {i}, line ~{line}')
        elif ch == '(':
            paren += 1
        elif ch == ')':
            paren -= 1
            if paren < 0:
                line = js[:i].count('\n') + 1
                print(f'Extra ) at position {i}, line ~{line}')

total_lines = js.count('\n') + 1
print(f"Curly:  {curly} (should be 0)")
print(f"Square: {square} (should be 0)")
print(f"Paren:  {paren} (should be 0)")
print(f"Lines:  {total_lines}")
