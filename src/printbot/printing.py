import subprocess, shlex, tempfile, os
from bs4 import BeautifulSoup

def html_to_text(html: str) -> str:
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

def print_text(printer_name: str, title: str, content: str) -> None:
    """Print text to CUPS printer, or simulate if DRY_RUN=true."""
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
        cmd = f"lp -d {shlex.quote(printer_name)} -o media=A4 -t {shlex.quote(title)} {shlex.quote(path)}"
        subprocess.check_call(cmd, shell=True)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
