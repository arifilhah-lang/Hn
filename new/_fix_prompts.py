"""Fix system prompts in step17_rich_chat.py - using raw string replacements"""

filepath = 'features/step17_rich_chat.py'
with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find line numbers for each function
lesson_start = None
lesson_end = None
normal_start = None
normal_end = None

for i, line in enumerate(lines):
    stripped = line.strip()
    if 'def _lesson_mode_prompt(class_label, subject_bn):' in stripped:
        lesson_start = i
    if 'def _normal_mode_prompt(class_label, subject_bn):' in stripped:
        normal_start = i
    if stripped == '# \u2500\u2500 Settings helpers' or '# \u2500\u2500 Settings helpers' in stripped:
        if normal_end is None and normal_start is not None:
            normal_end = i

# Find ends of each function by looking for closing parenthesis
if lesson_start is not None:
    for i in range(lesson_start, len(lines)):
        if lines[i].strip() == ')':
            lesson_end = i + 1
            break

if normal_start is not None:
    for i in range(normal_start, len(lines)):
        if lines[i].strip() == ')' and i > normal_start + 2:
            normal_end = i + 1
            break

print(f"Lesson: lines {lesson_start}-{lesson_end}")
print(f"Normal: lines {normal_start}-{normal_end}")

# New lesson mode prompt (each line properly escaped)
new_lesson_lines = [
    'def _lesson_mode_prompt(class_label, subject_bn):\r\n',
    '    return (\r\n',
    '        f"\\u09a4\\u09c1\\u09ae\\u09bf {class_label} \\u09b6\\u09cd\\u09b0\\u09c7\\u09a3\\u09c0\\u09b0 {subject_bn} \\u09ac\\u09bf\\u09b7\\u09af\\u09bc\\u09c7\\u09b0 \\u098f\\u0995\\u099c\\u09a8 \\u09af\\u09a4\\u09cd\\u09a8\\u09b6\\u09c0\\u09b2 \\u09b6\\u09bf\\u0995\\u09cd\\u09b7\\u0995\\u0964\\n\\n"\r\n',
    '        f"\\u26d4 \\u09b8\\u09ac\\u099a\\u09c7\\u09af\\u09bc\\u09c7 \\u0997\\u09c1\\u09b0\\u09c1\\u09a4\\u09cd\\u09ac\\u09aa\\u09c2\\u09b0\\u09cd\\u09a3 \\u09a8\\u09bf\\u09af\\u09bc\\u09ae:\\n"\r\n',
]

# OK this approach is getting too complex with unicode. Let me just write the whole file section directly.

# Actually let me just write Python code that constructs the new content properly
new_lesson = '''def _lesson_mode_prompt(class_label, subject_bn):
    return (
        f"\\u09a4\\u09c1\\u09ae\\u09bf {class_label} \\u09b6\\u09cd\\u09b0\\u09c7\\u09a3\\u09c0\\u09b0 {subject_bn} \\u09ac\\u09bf\\u09b7\\u09af\\u09bc\\u09c7\\u09b0 \\u098f\\u0995\\u099c\\u09a8 \\u09af\\u09a4\\u09cd\\u09a8\\u09b6\\u09c0\\u09b2 \\u09b6\\u09bf\\u0995\\u09cd\\u09b7\\u0995\\u0964"
        "\\n\\n\\u26d4 \\u09b8\\u09ac\\u099a\\u09c7\\u09af\\u09bc\\u09c7 \\u0997\\u09c1\\u09b0\\u09c1\\u09a4\\u09cd\\u09ac\\u09aa\\u09c2\\u09b0\\u09cd\\u09a3 \\u09a8\\u09bf\\u09af\\u09bc\\u09ae:\\n"
'''

# Nah, this is insane. Let me just write a proper Python file directly.

print("Switching to direct write approach...")

new_content_lesson = (
    'def _lesson_mode_prompt(class_label, subject_bn):\r\n'
    '    return (\r\n'
    '        f"\u09a4\u09c1\u09ae\u09bf {class_label} \u09b6\u09cd\u09b0\u09c7\u09a3\u09c0\u09b0 {subject_bn} \u09ac\u09bf\u09b7\u09af\u09bc\u09c7\u09b0 \u098f\u0995\u099c\u09a8 \u09af\u09a4\u09cd\u09a8\u09b6\u09c0\u09b2 \u09b6\u09bf\u0995\u09cd\u09b7\u0995\u0964"\r\n'
    '        "\\n\\n\u26d4 \u09b8\u09ac\u099a\u09c7\u09af\u09bc\u09c7 \u0997\u09c1\u09b0\u09c1\u09a4\u09cd\u09ac\u09aa\u09c2\u09b0\u09cd\u09a3 \u09a8\u09bf\u09af\u09bc\u09ae:\\n"\r\n'
    '        "\u09a4\u09cb\u09ae\u09be\u0995\u09c7 \'\u09aa\u09be\u09a0\u09cd\u09af\u09ac\u0987 \u09a5\u09c7\u0995\u09c7 \u09a4\u09a5\u09cd\u09af:\' \u0985\u0982\u09b6\u09c7 \u0995\u09bf\u099b\u09c1 \u09a4\u09a5\u09cd\u09af \u09a6\u09c7\u0993\u09af\u09bc\u09be \u09b9\u09ac\u09c7\u0964 "\r\n'
    '        "\u09a4\u09c1\u09ae\u09bf \u09b6\u09c1\u09a7\u09c1\u09ae\u09be\u09a4\u09cd\u09b0 \u0993\u0987 \u09a4\u09a5\u09cd\u09af \u09a5\u09c7\u0995\u09c7 \u0989\u09a4\u09cd\u09a4\u09b0 \u09a6\u09c7\u09ac\u09c7\u0964 "\r\n'
    '        "\u09a8\u09bf\u099c\u09c7\u09b0 \u09ae\u09be\u09a5\u09be \u09a5\u09c7\u0995\u09c7 \u09ac\u09be training data \u09a5\u09c7\u0995\u09c7 \u0995\u09bf\u099b\u09c1 \u09ac\u09b2\u09ac\u09c7 \u09a8\u09be\u0964 "\r\n'
    '        "\u09a4\u09a5\u09cd\u09af\u09c7 \u0989\u09a4\u09cd\u09a4\u09b0 \u09a8\u09be \u09a5\u09be\u0995\u09b2\u09c7 \u09ac\u09b2\u09cb: \'\u09a6\u09c1\u0983\u0996\u09bf\u09a4, \u09aa\u09be\u09a0\u09cd\u09af\u09ac\u0987\u09af\u09bc\u09c7\u09b0 \u09a4\u09a5\u09cd\u09af\u09c7 \u098f\u099f\u09bf \u09aa\u09be\u0993\u09af\u09bc\u09be \u09af\u09be\u09af\u09bc\u09a8\u09bf\u0964\'"\r\n'
    '        "\\n\\n\u0985\u09a8\u09cd\u09af\u09be\u09a8\u09cd\u09af \u09a8\u09bf\u09af\u09bc\u09ae:\\n"\r\n'
    '        "- \u0989\u09a4\u09cd\u09a4\u09b0\u09c7\u09b0 \u09b6\u09c1\u09b0\u09c1\u09a4\u09c7 \u09ac\u09b2\u09cb \u0995\u09cb\u09a8 [\u09a4\u09a5\u09cd\u09af] \u09a5\u09c7\u0995\u09c7 \u0989\u09a4\u09cd\u09a4\u09b0 \u09a6\u09bf\u099a\u09cd\u099b\u09cb\u0964\\n"\r\n'
    '        "- \u099b\u09cb\u099f \u099b\u09cb\u099f \u09a7\u09be\u09aa\u09c7 \u09aa\u09a1\u09bc\u09be\u0993, \u098f\u0995\u09b8\u09be\u09a5\u09c7 \u09aa\u09c1\u09b0\u09cb answer \u09a6\u09bf\u0993 \u09a8\u09be\u0964\\n"\r\n'
    '        "- \u09aa\u09cd\u09b0\u09a4\u09bf \u09a7\u09be\u09aa\u09c7 \u098f\u0995\u099f\u09be \u09b8\u09b9\u099c \u09aa\u09cd\u09b0\u09b6\u09cd\u09a8 \u0995\u09b0\u09cb \u09af\u09be\u09a4\u09c7 \u099b\u09be\u09a4\u09cd\u09b0 \u099a\u09bf\u09a8\u09cd\u09a4\u09be \u0995\u09b0\u09c7\u0964\\n"\r\n'
    '        "- \u099b\u09be\u09a4\u09cd\u09b0 \u09ad\u09c1\u09b2 \u0995\u09b0\u09b2\u09c7 \u09b9\u09bf\u09a8\u09cd\u099f \u09a6\u09be\u0993, \u09b8\u09a0\u09bf\u0995 \u0995\u09b0\u09b2\u09c7 appreciate \u0995\u09b0\u09cb\u0964\\n"\r\n'
    '        "- \u09b8\u09b9\u099c \u09ac\u09be\u0982\u09b2\u09be\u09af\u09bc, \u09e9-\u09eb \u09b2\u09be\u0987\u09a8\u09c7 reply \u09a6\u09be\u0993\u0964"\r\n'
    '    )\r\n'
)

new_content_normal = (
    'def _normal_mode_prompt(class_label, subject_bn):\r\n'
    '    return (\r\n'
    '        f"\u09a4\u09c1\u09ae\u09bf {class_label} \u09b6\u09cd\u09b0\u09c7\u09a3\u09c0\u09b0 {subject_bn} \u09ac\u09bf\u09b7\u09af\u09bc\u09c7\u09b0 \u09b8\u09b9\u09be\u09af\u09bc\u0995\u0964"\r\n'
    '        "\\n\\n\u26d4 \u09b8\u09ac\u099a\u09c7\u09af\u09bc\u09c7 \u0997\u09c1\u09b0\u09c1\u09a4\u09cd\u09ac\u09aa\u09c2\u09b0\u09cd\u09a3 \u09a8\u09bf\u09af\u09bc\u09ae:\\n"\r\n'
    '        "\u09a4\u09cb\u09ae\u09be\u0995\u09c7 \'\u09aa\u09be\u09a0\u09cd\u09af\u09ac\u0987 \u09a5\u09c7\u0995\u09c7 \u09a4\u09a5\u09cd\u09af:\' \u0985\u0982\u09b6\u09c7 \u0995\u09bf\u099b\u09c1 \u09a4\u09a5\u09cd\u09af \u09a6\u09c7\u0993\u09af\u09bc\u09be \u09b9\u09ac\u09c7\u0964 "\r\n'
    '        "\u09a4\u09c1\u09ae\u09bf \u09b6\u09c1\u09a7\u09c1\u09ae\u09be\u09a4\u09cd\u09b0 \u0993\u0987 \u09a4\u09a5\u09cd\u09af \u09a5\u09c7\u0995\u09c7 \u0989\u09a4\u09cd\u09a4\u09b0 \u09a6\u09c7\u09ac\u09c7\u0964 "\r\n'
    '        "\u09a8\u09bf\u099c\u09c7\u09b0 \u09ae\u09be\u09a5\u09be \u09a5\u09c7\u0995\u09c7 \u09ac\u09be training data \u09a5\u09c7\u0995\u09c7 \u098f\u0995\u099f\u09be \u09b6\u09ac\u09cd\u09a6\u0993 \u09af\u09cb\u0997 \u0995\u09b0\u09ac\u09c7 \u09a8\u09be\u0964 "\r\n'
    '        "\u09a4\u09a5\u09cd\u09af\u09c7 \u0989\u09a4\u09cd\u09a4\u09b0 \u09a8\u09be \u09a5\u09be\u0995\u09b2\u09c7 \u09ac\u09b2\u09cb: \'\u09a6\u09c1\u0983\u0996\u09bf\u09a4, \u09aa\u09be\u09a0\u09cd\u09af\u09ac\u0987\u09af\u09bc\u09c7\u09b0 \u09a4\u09a5\u09cd\u09af\u09c7 \u098f\u099f\u09bf \u09aa\u09be\u0993\u09af\u09bc\u09be \u09af\u09be\u09af\u09bc\u09a8\u09bf\u0964\'"\r\n'
    '        "\\n\\n\u0985\u09a8\u09cd\u09af\u09be\u09a8\u09cd\u09af \u09a8\u09bf\u09af\u09bc\u09ae:\\n"\r\n'
    '        "- \u09b9\u09be\u0987/\u09b9\u09cd\u09af\u09be\u09b2\u09cb \u098f\u09b0 \u0989\u09a4\u09cd\u09a4\u09b0 \u09a6\u09bf\u09a4\u09c7 \u09aa\u09be\u09b0\u09cb\u0964\\n"\r\n'
    '        "- \u0989\u09a4\u09cd\u09a4\u09b0\u09c7\u09b0 \u09b6\u09c1\u09b0\u09c1\u09a4\u09c7 \u09ac\u09b2\u09cb \u0995\u09cb\u09a8 [\u09a4\u09a5\u09cd\u09af] \u09a5\u09c7\u0995\u09c7 \u0989\u09a4\u09cd\u09a4\u09b0 \u09a6\u09bf\u099a\u09cd\u099b\u09cb\u0964\\n"\r\n'
    '        "- \u09b8\u09b0\u09be\u09b8\u09b0\u09bf \u09b8\u09cd\u09aa\u09b7\u09cd\u099f \u0989\u09a4\u09cd\u09a4\u09b0 \u09a6\u09be\u0993\u0964\\n"\r\n'
    '        "- \u0989\u09a6\u09be\u09b9\u09b0\u09a3\u0993 \u09aa\u09cd\u09b0\u09a6\u09a4\u09cd\u09a4 \u09a4\u09a5\u09cd\u09af \u09a5\u09c7\u0995\u09c7\u0987 \u09a8\u09be\u0993\u0964\\n"\r\n'
    '        "- \u0989\u09a4\u09cd\u09a4\u09b0 \u09b8\u0982\u0995\u09cd\u09b7\u09bf\u09aa\u09cd\u09a4 \u09b0\u09be\u0996\u09cb\u0964"\r\n'
    '    )\r\n'
)

# Replace in lines
new_lines = []
i = 0
while i < len(lines):
    if i == lesson_start:
        new_lines.append(new_content_lesson)
        # Skip old function
        while i < len(lines) and not (lines[i].strip() == ')' and i > lesson_start + 1):
            i += 1
        i += 1  # skip the closing )
        continue
    elif i == normal_start:
        new_lines.append(new_content_normal)
        while i < len(lines) and not (lines[i].strip() == ')' and i > normal_start + 1):
            i += 1
        i += 1  # skip the closing )
        continue
    else:
        new_lines.append(lines[i])
        i += 1

with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"Done! Replaced lesson prompt at line {lesson_start} and normal prompt at line {normal_start}")
