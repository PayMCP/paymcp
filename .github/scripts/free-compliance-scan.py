#!/usr/bin/env python3
"""
Compliance scanner for payment processing security
Checks for common security issues and compliance requirements
"""

import os
import re
import json
from pathlib import Path

def scan_for_secrets(directory):
    """Scan for potential secrets and API keys"""
    issues = []
    patterns = {
        'api_key': r'(?i)(api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*["\']?[a-zA-Z0-9_-]{20,}["\']?',
        'password': r'(?i)(password|pwd)\s*[:=]\s*["\'][^"\']{8,}["\']',
        'jwt_token': r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+',
        'private_key': r'-----BEGIN.*PRIVATE KEY-----',
        'aws_key': r'(A3T[A-Z0-9]|AKIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASIA)[A-Z0-9]{16}'
    }

    excluded_dirs = {'.git', '__pycache__', '.venv', 'venv', 'node_modules', '.pytest_cache', '.github'}
    excluded_files = {'test_', '_test', '.test', 'free-compliance-scan.py', 'compliance-scan-results.json'}

    for root, dirs, files in os.walk(directory):
        # Skip excluded directories
        dirs[:] = [d for d in dirs if d not in excluded_dirs]

        for file in files:
            if file.endswith(('.py', '.yml', '.yaml', '.json', '.env')):
                # Skip test files
                if any(exc in file.lower() for exc in excluded_files):
                    continue

                # Skip files in test directories
                if 'test' in str(root).lower():
                    continue

                file_path = Path(root) / file
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()

                    for pattern_name, pattern in patterns.items():
                        matches = re.finditer(pattern, content, re.MULTILINE)
                        for match in matches:
                            # Skip obvious test/example values
                            matched_text = match.group().lower()
                            if any(skip in matched_text for skip in ['test', 'example', 'mock', 'fake', 'dummy']):
                                continue

                            line_num = content[:match.start()].count('\n') + 1
                            issues.append({
                                'type': pattern_name,
                                'file': str(file_path),
                                'line': line_num,
                                'text': match.group()[:50] + '...' if len(match.group()) > 50 else match.group()
                            })

                except Exception as e:
                    print(f"Error reading {file_path}: {e}")

    return issues

def scan_for_payment_data(directory):
    """Scan for potential payment data exposure"""
    issues = []
    patterns = {
        'credit_card': r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3[0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b',
        'cvv': r'(?i)(cvv|cvc)\s*[:=]\s*["\']?[0-9]{3,4}["\']?',
        'payment_log': r'(?i)(log|print).*\b(card\s*number|card\s*data|pan\s*data|cvv\s*data|cvc\s*data)\b'
    }

    excluded_dirs = {'.git', '__pycache__', '.venv', 'venv', 'node_modules', '.pytest_cache', '.github'}
    excluded_files = {'test_', '_test', '.test', 'free-compliance-scan.py', 'compliance-scan-results.json'}

    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in excluded_dirs]

        for file in files:
            if file.endswith(('.py', '.yml', '.yaml', '.json')):
                # Skip test files and scanner files
                if any(exc in file.lower() for exc in excluded_files):
                    continue

                # Skip files in test directories
                if 'test' in str(root).lower():
                    continue

                file_path = Path(root) / file
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()

                    for pattern_name, pattern in patterns.items():
                        matches = re.finditer(pattern, content, re.MULTILINE)
                        for match in matches:
                            # Skip matches that are clearly safe (comments, variable names, etc.)
                            matched_text = match.group().lower()
                            context_before = content[max(0, match.start()-50):match.start()]
                            context_after = content[match.end():match.end()+50]
                            full_context = (context_before + matched_text + context_after).lower()

                            # Skip if it's in comments, documentation, or variable definitions
                            if any(skip in full_context for skip in [
                                '#', '//', '"""', "'''", 'def ', 'class ', 'import ',
                                'description', 'docstring', 'comment', 'note:', 'todo:',
                                'variable', 'constant', 'enum', 'type hint', 'annotation'
                            ]):
                                continue

                            line_num = content[:match.start()].count('\n') + 1
                            issues.append({
                                'type': pattern_name,
                                'file': str(file_path),
                                'line': line_num,
                                'severity': 'high' if pattern_name in ['credit_card', 'cvv'] else 'medium'
                            })

                except Exception as e:
                    print(f"Error reading {file_path}: {e}")

    return issues

def check_dependencies():
    """Check for known vulnerable dependencies"""
    issues = []

    # Check requirements files
    req_files = ['requirements.txt', 'requirements-dev.txt', 'pyproject.toml', 'Pipfile']
    vulnerable_packages = {
        'requests': '2.31.0',  # Example: versions below this have vulnerabilities
        'urllib3': '1.26.0',
        'pyyaml': '5.4.0'
    }

    for req_file in req_files:
        if os.path.exists(req_file):
            try:
                with open(req_file, 'r') as f:
                    content = f.read()

                for package, min_version in vulnerable_packages.items():
                    if package in content:
                        issues.append({
                            'type': 'dependency_check',
                            'file': req_file,
                            'message': f'Check {package} version against known vulnerabilities'
                        })
            except Exception as e:
                print(f"Error reading {req_file}: {e}")

    return issues

def main():
    """Main compliance scanner"""
    print("🔍 Starting compliance scan...")

    # Scan current directory
    directory = '.'

    # Run all scans
    secret_issues = scan_for_secrets(directory)
    payment_issues = scan_for_payment_data(directory)
    dependency_issues = check_dependencies()

    # Generate report
    report = {
        'summary': {
            'secrets_found': len(secret_issues),
            'payment_issues': len(payment_issues),
            'dependency_checks': len(dependency_issues),
            'high_severity': len([i for i in payment_issues if i.get('severity') == 'high'])
        },
        'secrets': secret_issues,
        'payment_data': payment_issues,
        'dependencies': dependency_issues
    }

    # Save detailed report
    with open('compliance-scan-results.json', 'w') as f:
        json.dump(report, f, indent=2)

    # Generate summary
    print(f"\n📊 Compliance Scan Summary:")
    print(f"   - Potential secrets: {report['summary']['secrets_found']}")
    print(f"   - Payment data issues: {report['summary']['payment_issues']}")
    print(f"   - High severity: {report['summary']['high_severity']}")
    print(f"   - Dependency checks: {report['summary']['dependency_checks']}")

    if report['summary']['high_severity'] > 0:
        print("\n🚨 HIGH SEVERITY ISSUES DETECTED!")
        return 1
    elif report['summary']['secrets_found'] > 0 or report['summary']['payment_issues'] > 0:
        print("\n⚠️  Security warnings detected")
        return 1
    else:
        print("\n✅ No critical security issues detected")
        return 0

if __name__ == "__main__":
    exit(main())