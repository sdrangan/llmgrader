#!/usr/bin/env python3
"""
create_soln_pkg.py

Creates a solution package for the LLM Grader by collecting unit XML files
specified in a configuration file.

Usage:
    python create_soln_pkg.py --config llmgrader_config.xml
"""

import os
import shutil
import zipfile
import xml.etree.ElementTree as ET
import argparse
from pathlib import Path

from llmgrader.services.unit_parser import UnitParser


def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='Build a solution package for LLM Grader'
    )
    parser.add_argument(
        '--config',
        default='llmgrader_config.xml',
        help='Path to the llmgrader_config.xml file'
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    
    # Verify config file exists
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}")
        return 1

    validation_errors = UnitParser.validate_course_package_config(str(config_path.resolve()))
    if validation_errors:
        print("Validation errors found in course package source files:")
        print()
        for error in validation_errors:
            print(f"- {error}")
        print()
        print("Fix the XML validation errors above and rerun create_soln_pkg.")
        return 1

    # Parse the XML configuration
    try:
        tree = ET.parse(config_path)
        root = tree.getroot()
    except ET.ParseError as e:
        print(f"Error parsing XML config: {e}")
        return 1

    # Extract course information
    course_elem = root.find('course')
    if course_elem is not None:
        course_name = course_elem.findtext('name', 'Unknown Course')
        course_term = course_elem.findtext('term') or course_elem.findtext('semester')
        if course_term:
            print(f"Course: {course_name}")
            print(f"Term: {course_term}")
        else:
            print(f"Course: {course_name}")
    
    print()

    # Create output directory
    output_dir = Path('soln_package')
    if output_dir.exists():
        print(f"Clearing existing directory: {output_dir}")
        shutil.rmtree(output_dir)
    
    output_dir.mkdir()
    print(f"Created output directory: {output_dir}")
    print()

    # Copy config file to output directory
    config_dest = output_dir / 'llmgrader_config.xml'
    shutil.copy2(config_path, config_dest)
    print(f"Copied config: {config_path} -> {config_dest}")
    print()

    # Get the directory containing the config file (for resolving relative paths)
    config_dir = config_path.parent.resolve()

    # Process each unit
    units_elem = root.find('units')
    if units_elem is None:
        print("Warning: No <units> section found in config")
        return 1

    unit_list = units_elem.findall('unit')
    if not unit_list:
        print("Warning: No <unit> elements found in config")
        return 1

    print(f"Packaging {len(unit_list)} unit(s):")
    print()

    copied_files = []
    for unit in unit_list:
        unit_name = unit.findtext('name', 'unknown')
        source_path = unit.findtext('source')
        dest_filename = unit.findtext('destination')

        if not source_path or not dest_filename:
            print(f"Warning: Skipping unit '{unit_name}' - missing source or destination")
            continue

        # Resolve source path relative to config directory
        source_full = config_dir / source_path
        
        if not source_full.exists():
            print(f"Warning: Source file not found: {source_full}")
            continue

        # Copy to output directory
        dest_full = output_dir / dest_filename
        shutil.copy2(source_full, dest_full)
        
        copied_files.append((unit_name, source_path, dest_filename))
        print(f"  [{unit_name}]")
        print(f"    Source: {source_path}")
        print(f"    Destination: {dest_filename}")
        print()

    # Create ZIP archive
    zip_filename = 'soln_package.zip'
    print(f"Creating archive: {zip_filename}")
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path in output_dir.rglob('*'):
            if file_path.is_file():
                arcname = file_path.relative_to(output_dir)
                zipf.write(file_path, arcname)
    
    print()
    print("=" * 60)
    print("Summary:")
    print(f"  Total units packaged: {len(copied_files)}")
    print(f"  Output directory: {output_dir}")
    print(f"  ZIP archive: {zip_filename}")
    print("=" * 60)
    
    return 0


if __name__ == '__main__':
    exit(main())
