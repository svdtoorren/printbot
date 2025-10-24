import subprocess, shlex, tempfile, os
from bs4 import BeautifulSoup
from weasyprint import HTML, CSS
from typing import Optional

def html_to_text(html: str) -> str:
    """Legacy function for backwards compatibility. Converts HTML to plain text."""
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script','style']):
            tag.decompose()
        text = soup.get_text('\n')
        lines = [l.strip() for l in text.splitlines()]
        text = '\n'.join([l for l in lines if l])
        return text
    except Exception:
        return html

def html_to_pdf(html_content: str, title: str = "Email") -> str:
    """Convert HTML content to PDF file. Returns path to temporary PDF file."""
    # Add basic email styling
    styled_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                margin: 2cm;
            }}
            body {{
                font-family: Arial, Helvetica, sans-serif;
                font-size: 11pt;
                line-height: 1.4;
                margin: 0;
                color: #000;
            }}
            h1, h2, h3 {{ color: #333; }}
            table {{ border-collapse: collapse; width: 100%; }}
            table, th, td {{ border: 1px solid #ddd; padding: 8px; }}
            a {{ color: #0066cc; text-decoration: underline; }}
            img {{ max-width: 100%; height: auto; }}
            pre {{ background: #f5f5f5; padding: 10px; overflow-x: auto; }}
        </style>
    </head>
    <body>
        {html_content}
    </body>
    </html>
    """

    fd, pdf_path = tempfile.mkstemp(prefix="printbot_", suffix=".pdf")
    os.close(fd)  # Close the file descriptor, WeasyPrint will write to the path

    try:
        HTML(string=styled_html).write_pdf(pdf_path)
        return pdf_path
    except Exception as e:
        # Clean up on error
        try:
            os.remove(pdf_path)
        except OSError:
            pass
        raise RuntimeError(f"Failed to convert HTML to PDF: {e}") from e

def text_to_pdf(text_content: str, title: str = "Email") -> str:
    """Convert plain text to PDF file. Returns path to temporary PDF file."""
    # Escape HTML special characters
    text_escaped = text_content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # Wrap in HTML with monospace font
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                margin: 2cm;
            }}
            body {{
                font-family: 'Courier New', Courier, monospace;
                font-size: 10pt;
                line-height: 1.3;
                margin: 0;
                color: #000;
                white-space: pre-wrap;
                word-wrap: break-word;
            }}
        </style>
    </head>
    <body>
        {text_escaped}
    </body>
    </html>
    """

    return html_to_pdf(html, title)

def print_pdf(printer_name: str, title: str, pdf_path: str, cleanup: bool = True) -> None:
    """Print PDF file to CUPS printer, or simulate if DRY_RUN=true.

    Args:
        printer_name: Name of the CUPS printer
        title: Job title for the print queue
        pdf_path: Path to the PDF file to print
        cleanup: If True, delete the PDF file after printing (default: True)

    Raises:
        RuntimeError: If printing fails
    """
    dry_run = os.getenv('DRY_RUN', '').lower() in ('true', '1', 'yes')

    if dry_run:
        print(f"[DRY_RUN] Would print PDF to '{printer_name}': {title}")
        print(f"[DRY_RUN] PDF file: {pdf_path}")
        if cleanup:
            try:
                os.remove(pdf_path)
            except OSError:
                pass
        return

    cmd = f"lp -d {shlex.quote(printer_name)} -o media=A4 -o orientation-requested=3 -t {shlex.quote(title)} {shlex.quote(pdf_path)}"
    print(f"[Printing] Sending PDF print job to CUPS: {title}")
    print(f"[Printing] Command: {cmd}")

    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True, timeout=30)
        print(f"[Printing] Print job successfully submitted to CUPS")
        if result.stdout:
            print(f"[Printing] CUPS output: {result.stdout.strip()}")
    except subprocess.CalledProcessError as e:
        print(f"[Printing] ERROR: CUPS command failed with exit code {e.returncode}")
        print(f"[Printing] stdout: {e.stdout}")
        print(f"[Printing] stderr: {e.stderr}")
        raise RuntimeError(f"Failed to submit print job to CUPS: {e.stderr}") from e
    except subprocess.TimeoutExpired:
        print(f"[Printing] ERROR: CUPS command timed out after 30 seconds")
        raise RuntimeError("Print job submission timed out") from None
    finally:
        if cleanup:
            try:
                os.remove(pdf_path)
            except OSError:
                pass

def print_text(printer_name: str, title: str, content: str) -> None:
    """Legacy function: Print text to CUPS printer, or simulate if DRY_RUN=true.

    DEPRECATED: Use print_pdf() with text_to_pdf() or html_to_pdf() instead.
    This function is kept for backwards compatibility.

    Raises exception if printing fails."""
    dry_run = os.getenv('DRY_RUN', '').lower() in ('true', '1', 'yes')

    if dry_run:
        print(f"[DRY_RUN] Would print to '{printer_name}': {title}")
        print(f"[DRY_RUN] Content preview (first 100 chars): {content[:100]}...")
        return

    if not content.endswith('\n'):
        content = content + '\n'
    fd, path = tempfile.mkstemp(prefix="printbot_", suffix=".txt")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
        cmd = f"lp -d {shlex.quote(printer_name)} -o media=A4 -o orientation-requested=3 -t {shlex.quote(title)} {shlex.quote(path)}"
        print(f"[Printing] Sending print job to CUPS: {title}")
        print(f"[Printing] Command: {cmd}")

        try:
            result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True, timeout=30)
            print(f"[Printing] Print job successfully submitted to CUPS")
            if result.stdout:
                print(f"[Printing] CUPS output: {result.stdout.strip()}")
        except subprocess.CalledProcessError as e:
            print(f"[Printing] ERROR: CUPS command failed with exit code {e.returncode}")
            print(f"[Printing] stdout: {e.stdout}")
            print(f"[Printing] stderr: {e.stderr}")
            raise RuntimeError(f"Failed to submit print job to CUPS: {e.stderr}") from e
        except subprocess.TimeoutExpired:
            print(f"[Printing] ERROR: CUPS command timed out after 30 seconds")
            raise RuntimeError("Print job submission timed out") from None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
