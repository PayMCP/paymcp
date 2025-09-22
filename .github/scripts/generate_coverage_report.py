#!/usr/bin/env python3
"""Generate detailed coverage report for GitHub Actions."""

import json
import xml.etree.ElementTree as ET
import sys


def main():
    try:
        # Read JSON for detailed data
        with open('coverage.json') as f:
            json_data = json.load(f)

        # Read XML for line numbers (if needed)
        try:
            xml_tree = ET.parse('coverage.xml')
            xml_root = xml_tree.getroot()
        except Exception:
            xml_root = None

        print('| File | Statements | Branches | Functions | Lines | Uncovered Lines |')
        print('|------|------------|----------|-----------|-------|-----------------|')

        files = json_data.get('files', {})
        totals = json_data.get('totals', {})

        # Sort files by path for consistent ordering
        sorted_files = sorted(files.items())

        for filepath, file_data in sorted_files:
            if filepath.startswith('src/paymcp/'):
                # Clean file path for display
                display_path = filepath.replace('src/paymcp/', '')

                summary = file_data.get('summary', {})

                # Get coverage percentages
                num_statements = summary.get('num_statements', 0)
                covered_statements = summary.get('covered_statements', 0)

                num_branches = summary.get('num_branches', 0)
                covered_branches = summary.get('covered_branches', 0)

                # Calculate percentages
                stmt_pct = round((covered_statements / num_statements * 100) if num_statements > 0 else 100, 1)
                branch_pct = round((covered_branches / num_branches * 100) if num_branches > 0 else 100, 1)

                # For Python, functions and lines are typically the same as statements
                func_pct = stmt_pct  # Python doesn't separate functions in coverage.py
                line_pct = round(summary.get('percent_covered', 0), 1)

                # Get uncovered lines
                missing_lines = file_data.get('missing_lines', [])
                if missing_lines:
                    # Group consecutive lines into ranges
                    ranges = []
                    start = missing_lines[0]
                    end = start

                    for line in missing_lines[1:]:
                        if line == end + 1:
                            end = line
                        else:
                            if start == end:
                                ranges.append(str(start))
                            else:
                                ranges.append(f'{start}-{end}')
                            start = end = line

                    if start == end:
                        ranges.append(str(start))
                    else:
                        ranges.append(f'{start}-{end}')

                    uncovered_display = ', '.join(ranges) if len(ranges) <= 5 else f'{ranges[0]}, {ranges[1]}, ... ({len(missing_lines)} lines)'
                else:
                    uncovered_display = '-'

                # Format percentages
                stmt_display = f'{stmt_pct}%' if stmt_pct < 100 else '💯'
                branch_display = f'{branch_pct}%' if branch_pct < 100 else '💯'
                func_display = f'{func_pct}%' if func_pct < 100 else '💯'
                line_display = f'{line_pct}%' if line_pct < 100 else '💯'

                print(f'| {display_path} | {stmt_display} | {branch_display} | {func_display} | {line_display} | {uncovered_display} |')

        # Add totals row
        total_stmt_pct = round(totals.get('percent_covered', 0), 1)
        print(f'| **TOTAL** | **{total_stmt_pct}%** | **{total_stmt_pct}%** | **{total_stmt_pct}%** | **{total_stmt_pct}%** | - |')

    except Exception as e:
        print('| File | Error |')
        print('|------|-------|')
        print(f'| Coverage Report | Error: {str(e)} |')
        sys.exit(1)


if __name__ == "__main__":
    main()