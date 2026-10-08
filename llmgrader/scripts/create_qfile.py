#!/usr/bin/env python3
"""
Create a simple HTML file from a unit XML file containing all questions.

This script reads a unit XML file (e.g., unit1_basic_logic.xml) and produces
an HTML file with all questions from the unit.

``--print [ID]`` renders one of the unit's ``<print>`` blocks instead: a
paper exam with a title page and answer pages, or a handout
(plans/exam_units.md, decision 5; docs/admin/buildcourse/print.md).
"""

import argparse
import asyncio
import html
import os
import re
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

from llmgrader.services.unit_parser import UnitParser, element_text


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


def question_points(question):
    """A question's total points: the sum of its parts, read as UnitParser reads them."""
    total = 0.0
    parts_elem = question.find('parts')
    for part in parts_elem.findall('part') if parts_elem is not None else []:
        value = part.findtext('points') or part.get('points') or '0'
        try:
            total += float(value.strip())
        except ValueError:
            pass
    return total


def format_points(points):
    return f'{points:g}'


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
            'solution': solution_content,
            'points': question_points(question),
        })
    
    return unit_title, questions


# MathJax with \( \) and \[ \] delimiters, as the portal renders them.
MATHJAX_HEAD = [
    '    <script>',
    '    window.MathJax = {',
    '      tex: {',
    '        inlineMath: [["\\\\(", "\\\\)"]],',
    '        displayMath: [["\\\\[", "\\\\]"]]',
    '      }',
    '    };',
    '    </script>',
    '    <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>',
]


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
        *MATHJAX_HEAD,
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


class PrintError(Exception):
    """A --print request that cannot be met, with a message for the author."""


def read_print_block(xml_file, print_id=None):
    """The ``<print>`` block to render, with every default filled in.

    *print_id* None picks the only block; a unit with no block prints as a
    plain heading and every question.  Returns a dict: ``id``,
    ``title_page`` (dict or None), ``page_per_question`` and ``questions``,
    a list of ``(qtag, answer_pages)`` in printed order.
    """
    root = ET.parse(xml_file).getroot()
    blocks = root.findall('print')
    if print_id is None:
        if len(blocks) > 1:
            ids = ', '.join(b.get('id', '') for b in blocks)
            raise PrintError(f'This unit has several <print> blocks ({ids}); name one: --print <id>.')
        block = blocks[0] if blocks else ET.Element('print')
    else:
        matches = [b for b in blocks if b.get('id') == print_id]
        if not matches:
            ids = ', '.join(b.get('id', '') for b in blocks) or 'none'
            raise PrintError(f'No <print id="{print_id}"> in this unit (its blocks: {ids}).')
        block = matches[0]

    title_page = None
    title_elem = block.find('title_page')
    if title_elem is not None:
        def text(tag):
            return (title_elem.findtext(tag) or '').strip()

        title_page = {
            'title': text('title') or root.get('title', ''),
            'course': text('course'),
            'instructors': text('instructors'),
            'date': text('date'),
            'duration': text('duration'),
            'fields': [(f.text or '').strip() for f in title_elem.findall('fields/field')],
            'instructions': [element_text(i) for i in title_elem.findall('instructions/item')],
        }

    # Defaults: an exam (a block with a title page) gets a page per question
    # and one answer page after each; a handout gets neither.
    default_pages = int(block.get('answer_pages', 1 if title_page else 0))
    page_per_question = (block.get('page_per_question', 'true' if title_page else 'false') == 'true')
    entries = block.findall('question')
    if entries:
        questions = [(e.get('qtag', '').strip(), int(e.get('answer_pages', default_pages)))
                     for e in entries]
    else:
        questions = [(q.get('qtag', ''), default_pages) for q in root.findall('question')]
    return {'id': block.get('id', ''), 'title_page': title_page,
            'page_per_question': page_per_question, 'questions': questions}


PRINT_STYLE = """
@page { size: Letter; margin: 0.8in 0.85in 0.9in 0.85in; }
body {
    font-family: "Computer Modern Serif", "Latin Modern Roman", "CMU Serif", Georgia, serif;
    font-size: 11.5pt;
    line-height: 1.4;
    color: #000;
    margin: 0;
}
h1 { font-size: 20pt; font-weight: normal; margin: 0 0 0.4em; }
.newpage { break-before: page; }
.problem-head { font-weight: bold; margin: 0 0 0.6em; }
.problem-head .points { font-weight: normal; }
pre code, code {
    font-family: "Computer Modern Typewriter", "CMU Typewriter Text", "Courier New", monospace;
}
pre { border-left: 2px solid #999; padding: 0.3em 0.8em; margin: 0.6em 0; }
pre code { display: block; white-space: pre; font-size: 10pt; }
img { max-width: 100%; }
.solution { margin-top: 1em; border-top: 1px solid #000; padding-top: 0.6em; }
.answer-page .answer-head { font-style: italic; color: #333; }
.title-page { text-align: center; padding-top: 1.2in; }
.title-page .course { font-size: 13pt; margin-bottom: 0.2em; }
.title-page .instructors, .title-page .when { margin-bottom: 0.2em; }
.title-page .fields { width: 75%; margin: 0.6in auto 0.4in; text-align: left; }
.title-page .field { display: flex; align-items: flex-end; margin-bottom: 0.35in; }
.title-page .field span { white-space: nowrap; margin-right: 0.6em; }
.title-page .field .line { flex: 1; border-bottom: 1px solid #000; }
.title-page .instructions { width: 85%; margin: 0 auto; text-align: left; }
.title-page table { margin: 0.4in auto 0; border-collapse: collapse; }
.title-page td, .title-page th { border: 1px solid #000; padding: 0.25em 1.2em; text-align: center; }
"""

# Computer Modern for text: the same family as MathJax's TeX math.
CM_FONTS = 'https://cdn.jsdelivr.net/gh/aaaakshat/cm-web-fonts@latest/fonts.css'


def _starts_with_qtag(text_html, qtag):
    """Whether the question text already opens with its own title."""
    plain = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', text_html)).split()).lower()
    return plain.startswith(qtag.strip().lower().rstrip('.'))


def generate_print_html(questions, output_file, block, unit_title='Questions',
                        include_solutions=False):
    """Write *block* (``read_print_block``) of *questions* as print-styled HTML.

    Answer pages are headed "Use this page for Problem n" -- generated, so
    the header cannot go stale when questions move.  With
    *include_solutions*, each question is followed by its solution and the
    answer pages are left out: it is the key.
    """
    by_tag = {q['qtag']: q for q in questions}
    printed = [(by_tag[qtag], pages) for qtag, pages in block['questions']]
    title_page = block['title_page']
    heading = (title_page or {}).get('title') or unit_title
    if include_solutions:
        heading += ' (Solutions)'

    out = [
        '<!DOCTYPE html>', '<html>', '<head>', '    <meta charset="UTF-8">',
        f'    <title>{html.escape(heading)}</title>',
        f'    <link rel="stylesheet" href="{CM_FONTS}">',
        f'    <style>{PRINT_STYLE}</style>',
        *MATHJAX_HEAD,
        '</head>', '<body>',
    ]

    if title_page:
        out.append('<div class="title-page">')
        out.append(f'  <h1>{html.escape(heading)}</h1>')
        for key, cls in (('course', 'course'), ('instructors', 'instructors')):
            if title_page[key]:
                out.append(f'  <div class="{cls}">{html.escape(title_page[key])}</div>')
        when = ', '.join(v for v in (title_page['date'], title_page['duration']) if v)
        if when:
            out.append(f'  <div class="when">{html.escape(when)}</div>')
        if title_page['fields']:
            out.append('  <div class="fields">')
            for field in title_page['fields']:
                out.append(f'    <div class="field"><span>{html.escape(field)}:</span>'
                           '<div class="line"></div></div>')
            out.append('  </div>')
        if title_page['instructions']:
            out.append('  <div class="instructions"><p><em>Instructions:</em></p><ul>')
            out.extend(f'    <li>{item}</li>' for item in title_page['instructions'])
            out.append('  </ul></div>')
        total = sum(q['points'] for q, _ in printed)
        if total:
            out.append('  <table><tr><th>Problem</th><th>Points</th><th>Score</th></tr>')
            for number, (question, _) in enumerate(printed, start=1):
                out.append(f'    <tr><td>{number}</td><td>{format_points(question["points"])}</td>'
                           '<td></td></tr>')
            out.append(f'    <tr><th>Total</th><th>{format_points(total)}</th><td></td></tr>')
            out.append('  </table>')
        out.append('</div>')
    else:
        out.append(f'<h1>{html.escape(heading)}</h1>')

    previous_pages = 0
    for number, (question, pages) in enumerate(printed, start=1):
        if include_solutions:
            pages = 0
        new_page = (title_page is not None if number == 1
                    else block['page_per_question'] or previous_pages > 0)
        out.append(f'<div class="question{" newpage" if new_page else ""}">')
        head = f'Problem {number}'
        if not _starts_with_qtag(question['text'], question['qtag']):
            head += f'. {html.escape(question["qtag"])}'
        if question['points']:
            plural = '' if question['points'] == 1 else 's'
            head += f' <span class="points">({format_points(question["points"])} point{plural})</span>'
        out.append(f'  <div class="problem-head">{head}</div>')
        out.append(question['text'])
        if include_solutions and question.get('solution'):
            out.append(f'  <div class="solution"><p><strong>Solution.</strong></p>'
                       f'{question["solution"]}</div>')
        out.append('</div>')
        for _ in range(pages):
            out.append(f'<div class="answer-page newpage"><p class="answer-head">'
                       f'Use this page for Problem {number}.</p></div>')
        previous_pages = pages

    out.extend(['</body>', '</html>'])
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    return len(printed)


async def generate_pdf_from_html(html_file, pdf_file, *, page_footer=False):
    """
    Generate a PDF from an HTML file using Playwright.
    
    Args:
        html_file: Path to the input HTML file
        pdf_file: Path to the output PDF file
        page_footer: Number every page "Page n of N", and let the HTML's own
            @page rule set the margins (the --print layout)
        
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
            if page_footer:
                await page.pdf(
                    path=pdf_file,
                    format='Letter',
                    prefer_css_page_size=True,
                    print_background=True,
                    display_header_footer=True,
                    header_template='<span></span>',
                    footer_template=(
                        '<div style="width:100%; text-align:center; font-size:9pt; '
                        'font-family: Georgia, serif;">Page <span class="pageNumber"></span> '
                        'of <span class="totalPages"></span></div>'
                    ),
                )
            else:
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
    parser.add_argument(
        '--print',
        dest='print_id',
        nargs='?',
        const='',
        default=None,
        metavar='ID',
        help='Render the unit\'s <print> block ID (the only block when ID is omitted) '
             'as an exam or handout: title page, points, answer pages'
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
        if args.print_id:
            base_name += f'_{args.print_id}'
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
    if args.print_id is not None:
        try:
            block = read_print_block(input_path, args.print_id or None)
        except PrintError as exc:
            print(f'Error: {exc}')
            return 1
        count = generate_print_html(questions, output_file, block, unit_title=unit_title,
                                    include_solutions=args.soln)
    else:
        generate_html(questions, output_file, unit_title=unit_title, include_solutions=args.soln)
        count = len(questions)

    print(f'Successfully created {output_file} with {count} question(s).')

    # Generate PDF if requested
    if args.pdf:
        pdf_file = os.path.splitext(output_file)[0] + '.pdf'
        print(f'Generating PDF: {pdf_file}...')
        success = asyncio.run(generate_pdf_from_html(
            output_file, pdf_file, page_footer=args.print_id is not None))
        if success:
            print(f'Successfully created {pdf_file}')
        else:
            print('Failed to create PDF')

    return 0


if __name__ == "__main__":
    raise SystemExit(main())