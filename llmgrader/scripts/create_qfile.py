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


def parse_xml_file(xml_file):
    """
    Parse the XML file and extract questions.
    
    Args:
        xml_file: Path to the XML file
        
    Returns:
        Tuple of (unit_title, questions) where questions is a list of dictionaries
    """
    tree = ET.parse(xml_file)
    root = tree.getroot()
    
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
        else:
            text_content = ''
        
        # Find the solution element
        solution_elem = question.find('solution')
        if solution_elem is not None:
            # Extract CDATA content
            solution_content = solution_elem.text if solution_elem.text else ''
            # Dedent code blocks
            solution_content = dedent_code_blocks(solution_content)
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
    
    # Parse XML and extract questions
    unit_title, questions = parse_xml_file(args.input)
    
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


if __name__ == "__main__":
    main()