#!/usr/bin/env python3
"""
Create a simple HTML file from a unit XML file containing all questions.

This script reads a unit XML file (e.g., unit1_basic_logic.xml) and produces
an HTML file with all questions from the unit.
"""

import argparse
import asyncio
import os
import re
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

from llmgrader.services.unit_parser import UnitParser


def dedent_code_blocks(html_text):
    """
    Find <pre><code>...</code></pre> blocks and dedent the code inside.
    
    Args:
        html_text: HTML text that may contain code blocks
        
    Returns:
        HTML text with dedented code blocks
    """
    def dedent_match(match):
        """Dedent the code content from a regex match."""
        code_content = match.group(1)
        dedented_code = textwrap.dedent(code_content)
        # Remove leading newlines (but preserve internal formatting)
        dedented_code = dedented_code.lstrip('\n')
        return f'<pre><code>{dedented_code}</code></pre>'
    
    # Pattern to match <pre><code>...</code></pre> blocks
    # Uses non-greedy matching and DOTALL flag to handle multiline code
    pattern = r'<pre><code>(.*?)</code></pre>'
    result = re.sub(pattern, dedent_match, html_text, flags=re.DOTALL)
    
    return result


def split_solution_paragraph(solution_html):
    """
    Split solution HTML into first paragraph content and remaining HTML.
    
    Args:
        solution_html: HTML text of the solution
        
    Returns:
        Tuple of (first_paragraph_content, remaining_html)
        If solution starts with <p>, extracts its inner content.
        Otherwise returns (empty, full_solution).
    """
    solution_html = solution_html.strip()
    
    # Pattern to match the first <p> tag and its content
    # Matches <p> or <p class="..." etc>
    pattern = r'^\s*<p(?:\s+[^>]*)?>(.+?)</p>(.*)'
    match = re.match(pattern, solution_html, flags=re.DOTALL)
    
    if match:
        first_para_content = match.group(1).strip()
        remaining_html = match.group(2).strip()
        return (first_para_content, remaining_html)
    else:
        # Solution doesn't start with <p>, return empty first part
        return ('', solution_html)


def normalize_config_path(path_value):
    normalized = path_value.strip().replace('\\', '/')
    pure_path = PurePosixPath(normalized)
    return Path(*[part for part in pure_path.parts if part not in ('', '.')])


def discover_config_path(xml_file):
    xml_path = Path(xml_file).resolve()
    for directory in [xml_path.parent, *xml_path.parent.parents]:
        candidate = directory / 'llmgrader_config.xml'
        if candidate.exists():
            return candidate
    return None


def load_config_context(config_path):
    config_tree = ET.parse(config_path)
    config_root = config_tree.getroot()
    config_dir = Path(config_path).resolve().parent

    asset_mappings = []
    assets_elem = config_root.find('assets')
    if assets_elem is not None:
        for asset_elem in assets_elem.findall('asset'):
            source_text = (asset_elem.findtext('source') or '').strip()
            destination_text = (asset_elem.findtext('destination') or '').strip()
            if not source_text or not destination_text:
                continue

            source_path = (config_dir / normalize_config_path(source_text)).resolve()
            destination_path = normalize_config_path(destination_text).as_posix()
            asset_mappings.append(
                {
                    'source': source_path,
                    'destination': destination_path,
                }
            )

    unit_destinations = {}
    units_elem = config_root.find('units')
    if units_elem is not None:
        for unit_elem in units_elem.findall('unit'):
            source_text = (unit_elem.findtext('source') or '').strip()
            destination_text = (unit_elem.findtext('destination') or '').strip()
            if not source_text or not destination_text:
                continue
            source_path = (config_dir / normalize_config_path(source_text)).resolve()
            unit_destinations[source_path] = Path(destination_text).stem

    return {
        'config_path': Path(config_path).resolve(),
        'asset_mappings': asset_mappings,
        'unit_destinations': unit_destinations,
    }


def resolve_pkg_asset_path(pkg_url, *, xml_file, config_context):
    if not pkg_url.startswith('/pkg_assets/'):
        return None

    pkg_path = pkg_url[len('/pkg_assets/'):].lstrip('/')
    asset_mappings = sorted(
        config_context.get('asset_mappings', []),
        key=lambda mapping: len(mapping['destination']),
        reverse=True,
    )

    for mapping in asset_mappings:
        destination = mapping['destination']
        source_path = mapping['source']
        if pkg_path == destination:
            return source_path
        prefix = f'{destination}/'
        if pkg_path.startswith(prefix):
            suffix = PurePosixPath(pkg_path[len(prefix):])
            return source_path.joinpath(*suffix.parts)

    xml_path = Path(xml_file).resolve()
    unit_destinations = config_context.get('unit_destinations', {})
    destination_stem = unit_destinations.get(xml_path)
    if destination_stem:
        legacy_prefix = f'{destination_stem}_images'
        if pkg_path == legacy_prefix:
            return xml_path.parent / 'images'
        prefix = f'{legacy_prefix}/'
        if pkg_path.startswith(prefix):
            suffix = PurePosixPath(pkg_path[len(prefix):])
            return xml_path.parent.joinpath('images', *suffix.parts)

    return None


def make_html_asset_url(asset_path, *, output_file):
    output_dir = Path(output_file).resolve().parent
    try:
        relative_path = os.path.relpath(asset_path, output_dir)
        return Path(relative_path).as_posix()
    except ValueError:
        return Path(asset_path).resolve().as_uri()


def rewrite_pkg_asset_urls(html_text, *, xml_file, output_file, config_context, errors):
    if not html_text or '/pkg_assets/' not in html_text:
        return html_text

    if config_context is None:
        errors.append(
            f"Asset resolution error in {xml_file}: found /pkg_assets/ URL but no llmgrader_config.xml was provided or discovered."
        )
        return html_text

    pattern = r'(?P<prefix>\b(?:src|href)\s*=\s*["\'])(?P<url>/pkg_assets/[^"\']+)(?P<suffix>["\'])'

    def replace_match(match):
        pkg_url = match.group('url')
        resolved_path = resolve_pkg_asset_path(pkg_url, xml_file=xml_file, config_context=config_context)
        if resolved_path is None:
            errors.append(
                f"Asset resolution error in {xml_file}: destination path {pkg_url} was not found in llmgrader_config.xml."
            )
            return match.group(0)
        if not Path(resolved_path).exists():
            errors.append(
                f"Asset resolution error in {xml_file}: source asset for {pkg_url} was not found at {resolved_path}."
            )
            return match.group(0)
        local_url = make_html_asset_url(resolved_path, output_file=output_file)
        return f"{match.group('prefix')}{local_url}{match.group('suffix')}"

    return re.sub(pattern, replace_match, html_text)


def parse_xml_file(xml_file, *, output_file=None, config_context=None, errors=None):
    """
    Parse the XML file and extract questions.
    
    Args:
        xml_file: Path to the XML file
        
    Returns:
        Tuple of (unit_title, questions) where questions is a list of dictionaries
    """
    tree = ET.parse(xml_file)
    root = tree.getroot()
    errors = errors if errors is not None else []
    
    # Extract unit title from root element
    unit_title = root.get('title', 'Questions')
    
    questions = []
    for question in root.findall('question'):
        qtag = question.get('qtag', 'Untitled Question')
        
        # Find the question_text element
        text_elem = question.find('question_text')
        if text_elem is not None:
            # Extract CDATA content
            text_content = text_elem.text if text_elem.text else ''
            # Dedent code blocks
            text_content = dedent_code_blocks(text_content)
            if output_file is not None:
                text_content = rewrite_pkg_asset_urls(
                    text_content,
                    xml_file=xml_file,
                    output_file=output_file,
                    config_context=config_context,
                    errors=errors,
                )
        else:
            text_content = ''
        
        # Find the solution element
        solution_elem = question.find('solution')
        if solution_elem is not None:
            # Extract CDATA content
            solution_content = solution_elem.text if solution_elem.text else ''
            # Dedent code blocks
            solution_content = dedent_code_blocks(solution_content)
            if output_file is not None:
                solution_content = rewrite_pkg_asset_urls(
                    solution_content,
                    xml_file=xml_file,
                    output_file=output_file,
                    config_context=config_context,
                    errors=errors,
                )
        else:
            solution_content = ''
        
        questions.append({
            'qtag': qtag,
            'text': text_content,
            'solution': solution_content
        })
    
    return unit_title, questions


def generate_html(questions, output_file, unit_title='Questions', include_solutions=False):
    """
    Generate HTML file from questions.
    
    Args:
        questions: List of question dictionaries
        output_file: Path to the output HTML file
        unit_title: Title of the unit (from XML)
        include_solutions: Whether to include solutions in the output
    """
    # Set page title based on whether solutions are included
    page_title = f"{unit_title} Solutions" if include_solutions else f"{unit_title} Questions"
    
    html_parts = [
        '<!DOCTYPE html>',
        '<html>',
        '<head>',
        '    <meta charset="UTF-8">',
        f'    <title>{page_title}</title>',
        '    <style>',
        '        body {',
        '            font-family: Arial, sans-serif;',
        '            max-width: 800px;',
        '            margin: 0 auto;',
        '            padding: 20px;',
        '        }',
        '        h2 {',
        '            color: #333;',
        '            border-bottom: 2px solid #007acc;',
        '            padding-bottom: 5px;',
        '        }',
        '        .question {',
        '            margin-bottom: 40px;',
        '        }',
        '        pre code {',
        '            background-color: #f7f7f7;',
        '            padding: 10px;',
        '            border-radius: 4px;',
        '            font-family: Consolas, "Courier New", monospace;',
        '            font-size: 0.95em;',
        '            display: block;',
        '        }',
        '    </style>',
        '    <script>',
        '    window.MathJax = {',
        '      tex: {',
        '        inlineMath: [["\\\\(", "\\\\)"]],',
        '        displayMath: [["\\\\[", "\\\\]"]]',
        '      }',
        '    };',
        '    </script>',
        '    <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>',
        '</head>',
        '<body>',
        f'    <h1>{page_title}</h1>',
    ]
    
    for i, question in enumerate(questions, start=1):
        html_parts.append('    <div class="question">')
        html_parts.append(f'        <h2>Question {i}. {question["qtag"]}</h2>')
        html_parts.append(f'{question["text"]}')
        
        # Add solution if requested and available
        if include_solutions and question.get('solution'):
            solution_html = question['solution']
            first_para, remaining = split_solution_paragraph(solution_html)
            
            if first_para:
                # Inline first paragraph content after "Solution:"
                html_parts.append(f'        <p><strong>Solution:</strong> {first_para}</p>')
                # Add remaining solution HTML if any
                if remaining:
                    html_parts.append(f'{remaining}')
            else:
                # No <p> tag found, just add the solution as-is
                html_parts.append(f'        <p><strong>Solution:</strong> {solution_html}</p>')
        
        html_parts.append('    </div>')
    
    html_parts.extend([
        '</body>',
        '</html>',
    ])
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_parts))


async def generate_pdf_from_html(html_file, pdf_file):
    """
    Generate a PDF from an HTML file using Playwright.
    
    Args:
        html_file: Path to the input HTML file
        pdf_file: Path to the output PDF file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Error: playwright is not installed.")
        print("Install it with: pip install playwright")
        print("Then run: playwright install chromium")
        return False
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            
            # Load the HTML file using file:// protocol
            html_path = os.path.abspath(html_file)
            file_url = f'file:///{html_path.replace(os.sep, "/")}'
            await page.goto(file_url)
            
            # Wait for MathJax to render
            try:
                # Wait for MathJax to be defined
                await page.wait_for_function(
                    "typeof MathJax !== 'undefined' && MathJax.startup && MathJax.startup.promise",
                    timeout=5000
                )
                # Wait for MathJax rendering to complete
                await page.evaluate("MathJax.startup.promise")
            except Exception:
                # MathJax might not be present or already rendered
                pass
            
            # Additional wait to ensure everything is fully rendered
            await page.wait_for_timeout(500)
            
            # Generate PDF
            await page.pdf(
                path=pdf_file,
                format='Letter',
                margin={'top': '0.75in', 'right': '0.75in', 'bottom': '0.75in', 'left': '0.75in'},
                print_background=True
            )
            
            await browser.close()
            return True
    except Exception as e:
        print(f"Error generating PDF: {e}")
        return False


def main():
    """Main function to parse arguments and generate HTML."""
    parser = argparse.ArgumentParser(
        description='Create HTML file from unit XML file containing questions.'
    )
    parser.add_argument(
        '--input',
        required=True,
        help='Path to the input XML file'
    )
    parser.add_argument(
        '--output',
        required=False,
        help='Path to the output HTML file (default: derived from input filename)'
    )
    parser.add_argument(
        '--config',
        required=False,
        help='Path to llmgrader_config.xml used to resolve /pkg_assets URLs for standalone HTML output'
    )
    parser.add_argument(
        '--soln',
        action='store_true',
        help='Include solutions in the output HTML'
    )
    parser.add_argument(
        '--pdf',
        action='store_true',
        help='Generate a PDF file from the HTML output'
    )
    
    args = parser.parse_args()

    input_path = os.path.abspath(args.input)

    validation_errors = UnitParser.validate_unit_file(input_path)
    if validation_errors:
        print('Validation errors found in input XML file:')
        print()
        for error in validation_errors:
            print(f'- {error}')
        print()
        print('Fix the XML validation errors above and rerun create_qfile.')
        return 1
    
    # Determine output filename
    if args.output:
        output_file = args.output
    else:
        # Derive output filename from input: replace .xml with .html
        base_name = os.path.splitext(args.input)[0]
        if args.soln:
            output_file = base_name + '_soln.html'
        else:
            output_file = base_name + '.html'

    config_path = Path(args.config).resolve() if args.config else discover_config_path(input_path)
    config_context = None
    if config_path is not None:
        config_validation_errors = UnitParser.validate_config_file(str(config_path))
        if config_validation_errors:
            print('Validation errors found in llmgrader_config.xml:')
            print()
            for error in config_validation_errors:
                print(f'- {error}')
            print()
            print('Fix the XML validation errors above and rerun create_qfile.')
            return 1
        config_context = load_config_context(config_path)

    asset_errors = []
    
    # Parse XML and extract questions
    unit_title, questions = parse_xml_file(
        input_path,
        output_file=output_file,
        config_context=config_context,
        errors=asset_errors,
    )

    if asset_errors:
        print('Asset resolution errors found while generating standalone HTML:')
        print()
        for error in asset_errors:
            print(f'- {error}')
        print()
        print('Fix the asset mappings above and rerun create_qfile.')
        return 1
    
    # Generate HTML output
    generate_html(questions, output_file, unit_title=unit_title, include_solutions=args.soln)

    print(f'Successfully created {output_file} with {len(questions)} question(s).')
    
    # Generate PDF if requested
    if args.pdf:
        pdf_file = os.path.splitext(output_file)[0] + '.pdf'
        print(f'Generating PDF: {pdf_file}...')
        success = asyncio.run(generate_pdf_from_html(output_file, pdf_file))
        if success:
            print(f'Successfully created {pdf_file}')
        else:
            print('Failed to create PDF')

    return 0


if __name__ == "__main__":
    raise SystemExit(main())