import os
import logging
import markdown
from fpdf import FPDF
import re

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def convert_to_pdf(book_dir, output_filename):
    logger.info(f"Scanning {book_dir}...")
    
    # List files: exclude README, sort alphabetically
    files = sorted([f for f in os.listdir(book_dir) if f.endswith('.md') and not f.lower().startswith('readme')])
    
    if not files:
        logger.error("No markdown files found.")
        return

    logger.info(f"Found {len(files)} chapters. Combining...")

    combined_md = ""
    for f in files:
        path = os.path.join(book_dir, f)
        with open(path, 'r', encoding='utf-8') as file:
            content = file.read()
            # Add some spacing
            combined_md += f"\n\n{content}\n\n<div style='page-break-after: always;'></div>\n\n"

    logger.info("Converting Markdown to HTML...")
    try:
        html = markdown.markdown(combined_md, extensions=['fenced_code', 'tables', 'attr_list', 'nl2br', 'sane_lists'])
    except Exception as e:
        logger.error(f"Markdown conversion failed: {e}")
        return
    
    cwd = os.getcwd()
    try:
        os.chdir(book_dir)
        
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        
        # Add a Unicode font if possible?
        # fpdf2 comes with some built-in support but for full unicode we need a .ttf.
        # We will use Arial from system fonts.
        font_dir = "/System/Library/Fonts/Supplemental"
        font_path = os.path.join(font_dir, "Arial.ttf")
        
        if os.path.exists(font_path):
            pdf.add_font("Arial", fname=os.path.join(font_dir, "Arial.ttf"))
            pdf.add_font("Arial", style="B", fname=os.path.join(font_dir, "Arial Bold.ttf"))
            pdf.add_font("Arial", style="I", fname=os.path.join(font_dir, "Arial Italic.ttf"))
            pdf.add_font("Arial", style="BI", fname=os.path.join(font_dir, "Arial Bold Italic.ttf"))
            pdf.set_font("Arial", size=12)
        else:
            logger.warning("Arial font not found. Falling back to Helvetica (might fail on unicode).")
            pdf.set_font("Helvetica", size=12)
        
        logger.info("Generating PDF (this might take a while)...")
        
        # Remove internal links to avoid "Named destination referenced but never set" errors
        # Replacing with a dummy external link so fpdf2 doesn't crash on missing href
        html = re.sub(r'href="#[^"]*"', 'href="http://internal-link"', html)
        
        # Use pre_code_font to force Arial (ignoring the deprecation warning for now as it's easier)
        pdf.write_html(html, pre_code_font="Arial")
        
        output_path = os.path.join("..", output_filename)
        pdf.output(output_path)
        logger.info(f"Successfully created {output_path}")
        
    except Exception as e:
        logger.error(f"PDF Generation failed: {e}")
        # Save HTML for debugging/fallback
        with open("../debug_eth.html", "w", encoding='utf-8') as f:
            f.write(html)
        logger.info("Saved HTML to debug_eth.html for manual conversion.")
    finally:
        os.chdir(cwd)

if __name__ == "__main__":
    convert_to_pdf("eth_book", "eth_book.pdf")
