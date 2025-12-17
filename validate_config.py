#!/usr/bin/env python3
"""
YAML Configuration Validator for Home Assistant Heating Control
Validates YAML syntax and checks for common configuration issues.
"""

import yaml
import sys
from pathlib import Path
from typing import List, Dict, Tuple


class ConfigValidator:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.info = []

    def validate_yaml_file(self, filepath: Path) -> bool:
        """Validate YAML syntax of a file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                yaml.safe_load(f)
            self.info.append(f"✅ {filepath.name}: YAML Syntax OK")
            return True
        except yaml.YAMLError as e:
            self.errors.append(f"❌ {filepath.name}: YAML Syntax Error\n   {str(e)}")
            return False
        except Exception as e:
            self.errors.append(f"❌ {filepath.name}: Error reading file\n   {str(e)}")
            return False

    def check_indentation(self, filepath: Path) -> None:
        """Check for common indentation issues."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            for i, line in enumerate(lines, 1):
                # Skip empty lines and comments
                if not line.strip() or line.strip().startswith('#'):
                    continue
                
                # Check for tabs
                if '\t' in line:
                    self.warnings.append(
                        f"⚠️  {filepath.name}:{i}: Tab character found (use spaces)"
                    )
                
                # Check for trailing spaces
                if line.rstrip() != line.rstrip(' '):
                    self.warnings.append(
                        f"⚠️  {filepath.name}:{i}: Trailing whitespace"
                    )
                    
        except Exception as e:
            self.warnings.append(f"⚠️  {filepath.name}: Could not check indentation: {str(e)}")

    def check_entity_references(self, data: dict, filepath: Path) -> None:
        """Check for potentially missing entity references."""
        # This is a simplified check - would need actual HA state to verify
        if not data:
            return
        
        # Collect defined entities
        defined_entities = set()
        
        # Check input_number
        if 'input_number' in data:
            for key in data['input_number'].keys():
                defined_entities.add(f"input_number.{key}")
        
        # Check input_boolean
        if 'input_boolean' in data:
            for key in data['input_boolean'].keys():
                defined_entities.add(f"input_boolean.{key}")
        
        # Check input_select
        if 'input_select' in data:
            for key in data['input_select'].keys():
                defined_entities.add(f"input_select.{key}")
        
        # Check input_datetime
        if 'input_datetime' in data:
            for key in data['input_datetime'].keys():
                defined_entities.add(f"input_datetime.{key}")
        
        self.info.append(f"ℹ️  {filepath.name}: Found {len(defined_entities)} defined entities")

    def check_automation_structure(self, data: dict, filepath: Path) -> None:
        """Check automation structure for common issues."""
        if 'automation' not in data:
            return
        
        automations = data['automation']
        if not isinstance(automations, list):
            self.errors.append(f"❌ {filepath.name}: 'automation' should be a list")
            return
        
        for i, auto in enumerate(automations):
            if 'id' not in auto:
                self.warnings.append(
                    f"⚠️  {filepath.name}: Automation #{i+1} missing 'id' field"
                )
            if 'alias' not in auto:
                self.warnings.append(
                    f"⚠️  {filepath.name}: Automation #{i+1} missing 'alias' field"
                )
            if 'trigger' not in auto:
                self.errors.append(
                    f"❌ {filepath.name}: Automation '{auto.get('alias', i+1)}' missing 'trigger'"
                )
            if 'action' not in auto:
                self.errors.append(
                    f"❌ {filepath.name}: Automation '{auto.get('alias', i+1)}' missing 'action'"
                )

    def validate_file(self, filepath: Path) -> None:
        """Run all validation checks on a file."""
        print(f"\n🔍 Validating {filepath.name}...")
        
        # Check YAML syntax
        if not self.validate_yaml_file(filepath):
            return
        
        # Check indentation
        self.check_indentation(filepath)
        
        # Load and analyze structure
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            
            if data:
                self.check_entity_references(data, filepath)
                self.check_automation_structure(data, filepath)
        except Exception as e:
            self.errors.append(f"❌ {filepath.name}: Could not analyze structure: {str(e)}")

    def print_results(self) -> int:
        """Print validation results and return exit code."""
        print("\n" + "="*70)
        print("VALIDATION RESULTS")
        print("="*70)
        
        if self.errors:
            print("\n🔴 ERRORS:")
            for error in self.errors:
                print(f"  {error}")
        
        if self.warnings:
            print("\n🟡 WARNINGS:")
            for warning in self.warnings:
                print(f"  {warning}")
        
        if self.info:
            print("\n🔵 INFO:")
            for info in self.info:
                print(f"  {info}")
        
        print("\n" + "="*70)
        print(f"Summary: {len(self.errors)} errors, {len(self.warnings)} warnings, {len(self.info)} info")
        print("="*70)
        
        if self.errors:
            print("\n❌ Validation FAILED - Please fix errors before deploying")
            return 1
        elif self.warnings:
            print("\n⚠️  Validation passed with warnings")
            return 0
        else:
            print("\n✅ Validation PASSED")
            return 0


def main():
    """Main validation function."""
    print("="*70)
    print("Home Assistant Heating Control - Configuration Validator")
    print("="*70)
    
    validator = ConfigValidator()
    
    # Get the script directory
    script_dir = Path(__file__).parent
    original_dir = script_dir / "original"
    
    if not original_dir.exists():
        # Fallback to current directory if original/ doesn't exist
        # This allows running validation on files in the root or other folders
        print(f"\\nℹ️  Directory '{original_dir}' not found, checking current directory...")
        original_dir = script_dir
    
    # Find YAML files
    yaml_files = list(original_dir.glob("*.yaml")) + list(original_dir.glob("*.yml"))
    
    if not yaml_files:
        print(f"\n❌ Error: No YAML files found in '{original_dir}'")
        return 1
    
    print(f"\nFound {len(yaml_files)} YAML file(s) to validate")
    
    # Validate each file
    for yaml_file in yaml_files:
        validator.validate_file(yaml_file)
    
    # Print results
    exit_code = validator.print_results()
    
    # Additional known issues from analysis
    print("\n" + "="*70)
    print("KNOWN ISSUES FROM MANUAL ANALYSIS")
    print("="*70)
    print("""
🔴 CRITICAL:
  - fussboden_dashboard_neu.yaml: Line 7 - Incorrect indentation for 'cards'
  - fussboden_dashboard_neu.yaml: Multiple lines - Inconsistent card property indentation
  
⚠️  WARNINGS:
  - fussboden_heizung.yaml: Missing entity 'input_number.fussbodenheizung_druck'
  - Both files: Duplicate sensor 'sensor.temp_wohnzimmer_sb' for Küche and Wohnzimmer
  - fussboden_heizung.yaml: Binary valve control (no proportional control)
  - fussboden_heizung.yaml: Unused input_select helpers for temperature sensors

See FEHLERANALYSE.md for detailed information.
""")
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
