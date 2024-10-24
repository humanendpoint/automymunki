"""
helper for gathering and comparing docstrings.

Usage: python3 test_docstrings.py <current_script_content> <previous_script_content>
"""

import ast
import sys


def get_docstring(script_content):
    try:
        tree = ast.parse(script_content)
        return ast.get_docstring(tree)
    except SyntaxError as e:
        return None  # Return None if parsing fails


def compare_docstrings(current_content, previous_content):
    current_docstring = get_docstring(current_content)
    previous_docstring = get_docstring(previous_content)

    if current_docstring == previous_docstring:
        return "FALSE"  # Docstring hasn't changed
    else:
        return "TRUE"  # Docstring has changed


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: python3 test_docstrings.py <current_script_content> <previous_script_content>"
        )
        sys.exit(1)

    current_script_content = sys.argv[1]
    previous_script_content = sys.argv[2]

    result = compare_docstrings(current_script_content, previous_script_content)
    print(result)


if __name__ == "__main__":
    main()
