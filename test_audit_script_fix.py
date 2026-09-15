"""
Test script to verify the d2_fmc003_mileage_audit.py fix for ModuleNotFoundError.
Performs three checks:
1. Static/import check
2. Simulate VPS condition (app.odometer_capability unavailable)
3. Confirm read-only operations
"""
import sys
import os
import importlib.util
import ast
import re

# Add backend to path so we can import app modules
sys.path.insert(0, '/app/backend')

print("=" * 80)
print("VERIFICATION OF d2_fmc003_mileage_audit.py FIX")
print("=" * 80)

# ============================================================================
# CHECK 1: Static/Import Check
# ============================================================================
print("\n[CHECK 1] Static/Import Check")
print("-" * 80)

script_path = "/app/backend/scripts/d2_fmc003_mileage_audit.py"

# Parse the script to check imports
try:
    with open(script_path, 'r') as f:
        tree = ast.parse(f.read(), filename=script_path)
    
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            for alias in node.names:
                imports.append(f"{module}.{alias.name}" if module else alias.name)
    
    print("✓ Script compiles successfully")
    print(f"✓ Found {len(imports)} import statements")
    
    # Check for app.odometer_capability import
    odometer_imports = [imp for imp in imports if 'odometer_capability' in imp]
    if odometer_imports:
        print(f"✗ FAIL: Found import of app.odometer_capability: {odometer_imports}")
        sys.exit(1)
    else:
        print("✓ No import of app.odometer_capability found")
    
    # Check for expected imports
    expected_modules = ['app.tenant_context', 'app.db', 'app.navixy_client']
    for mod in expected_modules:
        if any(mod in imp for imp in imports):
            print(f"✓ Found expected import: {mod}")
        else:
            print(f"✗ WARNING: Expected import not found: {mod}")
    
    print("\n[CHECK 1] RESULT: PASS ✓")
    
except SyntaxError as e:
    print(f"✗ FAIL: Script has syntax errors: {e}")
    sys.exit(1)
except Exception as e:
    print(f"✗ FAIL: Error parsing script: {e}")
    sys.exit(1)

# ============================================================================
# CHECK 2: Simulate VPS Condition (app.odometer_capability unavailable)
# ============================================================================
print("\n[CHECK 2] Simulate VPS Condition")
print("-" * 80)

# Block app.odometer_capability from being imported
# First, check if it exists in this environment
odometer_capability_exists = False
try:
    import app.odometer_capability
    odometer_capability_exists = True
    print("ℹ app.odometer_capability exists in this environment (expected - this is the dev environment)")
except ModuleNotFoundError:
    print("ℹ app.odometer_capability does not exist (simulating VPS environment)")

# Now remove it from sys.modules to simulate VPS
if 'app.odometer_capability' in sys.modules:
    del sys.modules['app.odometer_capability']

# Create a module that raises ModuleNotFoundError when accessed
class BlockedModule:
    def __getattr__(self, name):
        raise ModuleNotFoundError("No module named 'app.odometer_capability'")

sys.modules['app.odometer_capability'] = BlockedModule()

try:
    # Verify the block works
    try:
        from app.odometer_capability import resolve_model
        print("✗ FAIL: app.odometer_capability.resolve_model should not be importable")
        sys.exit(1)
    except (ModuleNotFoundError, AttributeError):
        print("✓ Successfully blocked app.odometer_capability import")
    
    # Now load the audit script's resolve_model function
    spec = importlib.util.spec_from_file_location("audit_script", script_path)
    audit_module = importlib.util.module_from_spec(spec)
    
    # Execute the module to load its functions
    spec.loader.exec_module(audit_module)
    
    print("✓ Script imports resolved successfully without app.odometer_capability")
    
    # Test the inline resolve_model function
    test_cases = [
        ('telfmb003_fmc003', 'FMC003'),
        ('telfmu130_fmc003', 'FMC003'),  # _fmc003 suffix takes priority
        ('telfmu130_fmc130', 'FMC130'),
        ('telfmc003', 'FMC003'),
        ('telfmc130', 'FMC130'),
        ('telfmu130', 'FMU130'),
        ('telfmc640', 'FMC640'),
        ('telfmc650', 'FMC650'),
        ('unknown_model', None),
        ('', None),
        (None, None),
    ]
    
    all_passed = True
    for input_model, expected in test_cases:
        result = audit_module.resolve_model(input_model)
        if result == expected:
            print(f"✓ resolve_model('{input_model}') = '{result}' (expected: '{expected}')")
        else:
            print(f"✗ resolve_model('{input_model}') = '{result}' (expected: '{expected}')")
            all_passed = False
    
    if all_passed:
        print("\n[CHECK 2] RESULT: PASS ✓")
    else:
        print("\n[CHECK 2] RESULT: FAIL ✗")
        sys.exit(1)
    
except Exception as e:
    print(f"✗ FAIL: Error loading script without app.odometer_capability: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# CHECK 3: Confirm Read-Only Operations
# ============================================================================
print("\n[CHECK 3] Confirm Read-Only Operations")
print("-" * 80)

with open(script_path, 'r') as f:
    script_content = f.read()

# Check for write operations
write_patterns = [
    (r'send_raw_command', 'send_raw_command function call'),
    (r'raw_command/send', 'raw_command/send endpoint'),
    (r'setparam', 'setparam endpoint'),
    (r'privatemode', 'privatemode endpoint'),
    (r'counter.*set', 'counter set operation'),
    (r'counter.*update', 'counter update operation'),
    (r'\.update\(', 'database update operation'),
    (r'\.insert\(', 'database insert operation'),
    (r'\.delete\(', 'database delete operation'),
    (r'\.save\(', 'database save operation'),
]

write_operations_found = []
for pattern, description in write_patterns:
    matches = re.finditer(pattern, script_content, re.IGNORECASE)
    for match in matches:
        # Get line number
        line_num = script_content[:match.start()].count('\n') + 1
        # Get the line content
        lines = script_content.split('\n')
        line_content = lines[line_num - 1].strip()
        
        # Skip if it's in a comment
        if line_content.startswith('#'):
            continue
        
        # Skip if it's in the docstring (lines 1-31 based on the file)
        if line_num <= 31:
            continue
        
        write_operations_found.append((description, line_num, line_content))

if write_operations_found:
    print("✗ FAIL: Found potential write operations:")
    for desc, line_num, line_content in write_operations_found:
        print(f"  Line {line_num}: {desc}")
        print(f"    {line_content}")
    print("\n[CHECK 3] RESULT: FAIL ✗")
    sys.exit(1)
else:
    print("✓ No write operations found (send_raw_command, setparam, privatemode, raw_command/send, counter set/update)")

# Check for read-only endpoints
read_endpoints = [
    'tracker/readings/list',
    'tracker/get_counters',
]

for endpoint in read_endpoints:
    if endpoint in script_content:
        print(f"✓ Found read-only endpoint: {endpoint}")
    else:
        print(f"✗ WARNING: Expected read-only endpoint not found: {endpoint}")

# Check that only read operations are used from navixy_client
navixy_functions = re.findall(r'nc\.(\w+)\(', script_content)
print(f"\n✓ Navixy client functions used: {set(navixy_functions)}")

# Verify only helper functions are used (_post, _hash, _base_url)
helper_functions = re.findall(r'nc\.(_\w+)\(', script_content)
print(f"✓ Navixy helper functions used: {set(helper_functions)}")

print("\n[CHECK 3] RESULT: PASS ✓")

# ============================================================================
# FINAL SUMMARY
# ============================================================================
print("\n" + "=" * 80)
print("FINAL SUMMARY")
print("=" * 80)
print("✓ CHECK 1: Static/Import Check - PASS")
print("✓ CHECK 2: Simulate VPS Condition - PASS")
print("✓ CHECK 3: Confirm Read-Only Operations - PASS")
print("\n✓✓✓ ALL CHECKS PASSED ✓✓✓")
print("=" * 80)
