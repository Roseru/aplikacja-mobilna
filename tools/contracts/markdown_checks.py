"""Check active Markdown links without treating fenced examples as navigation."""
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


def outside_fences(contents: str) -> str:
    active = []
    fence = None
    for line in contents.splitlines(keepends=True):
        if fence is not None:
            char, length = fence
            if re.fullmatch(r' {0,3}' + re.escape(char) + '{' + str(length) + r',}[ \t]*', line.rstrip('\r\n')):
                fence = None
            active.append('\n')
            continue
        opening = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line.rstrip('\r\n'))
        if opening and not (opening[1][0] == '`' and '`' in opening[2]):
            fence = (opening[1][0], len(opening[1]))
            active.append('\n')
        else:
            active.append(line)
    return ''.join(active)


def check_local_links(path: Path) -> int:
    count = 0
    contents = outside_fences(path.read_text(encoding='utf-8'))
    for link in re.findall(r'(?<!!)\[[^\]]+\]\(([^)]+)\)', contents):
        link = link.strip('<>')
        if urlsplit(link).scheme or link.startswith('#'):
            continue
        dest = unquote(link.partition('#')[0])
        assert (path.parent / dest).exists(), f'Broken local link: {path}: {link}'
        count += 1
    return count
