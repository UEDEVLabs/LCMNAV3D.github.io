#!/usr/bin/env python3
"""Bring page bodies up to date with the plugin's Markdown, without losing edits made on the site.

    python tools/sync-md.py .              merge every mapped page, report, write
    python tools/sync-md.py . --dry-run    report only

The Markdown under Plugins/LCMNav3D/Documentation is the source of truth, but some pages were
corrected here after they were converted. A plain re-conversion would undo those corrections, so
each page is a three-way merge:

    base   = the Markdown version this page was last converted from (tools/md-sync.json; on the
             first run, the historical version whose conversion matches the page best)
    theirs = the Markdown at the plugin's HEAD, converted the same way
    ours   = the page body as it is now

`git merge-file` applies the Markdown's changes since `base` onto the page. A block both sides
changed is left with conflict markers and the page is not written; resolve it by hand. Then run
tools/build.js, which regenerates the head, breadcrumb, sidebar, pager, tables and search index.
"""
import difflib, json, re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else '.').resolve()
DRY = '--dry-run' in sys.argv
PLUGIN = Path(r'E:\OnGoingUE\Nav3D_UE5\Adv_Nav_UE5')
DOC = 'Plugins/LCMNav3D/Documentation'
STATE = ROOT / 'tools' / 'md-sync.json'

# page -> Markdown source (relative to DOC)
MAP = {
    'installation.html': 'Tutorials/01_Installation.md',
    'core-concepts.html': 'Tutorials/02_CoreConcepts.md',
    'your-first-flying-agent.html': 'Tutorials/03_YourFirstFlyingAgent.md',
    'statetree-agent.html': 'Tutorials/04_StateTreeAgent.md',
    'dynamic-obstacles.html': 'Tutorials/05_DynamicObstacles.md',
    'mass-entity-crowds.html': 'Tutorials/06_MassIntegration.md',
    'tactical-eqs.html': 'Tutorials/07_TacticalEQS.md',
    'ai-perception.html': 'Tutorials/08_PerceptionIntegration.md',
    'hybrid-recast.html': 'Tutorials/09_HybridApexRecastCrowd.md',
    'nav-links-and-areas.html': 'Tutorials/10_NavLinksAndAreaModifiers.md',
    'gameplay-debugger.html': 'Tutorials/11_GameplayDebugger.md',
    'small-worlds.html': 'Tutorials/12_SmallWorlds.md',
    'fly-to-location.html': 'Tutorials/13_FlyToLocationNode.md',
    'stock-navigation.html': 'Tutorials/14_StockNavigation.md',
    'behaviour-nodes.html': 'Tutorials/15_BehaviourNodes.md',
    'bt-wait.html': 'Tutorials/BT_Wait_StockPattern.md',
    'bt-is-at-location.html': 'Tutorials/BT_IsAtLocation_StockPattern.md',
    'bt-look-at.html': 'Tutorials/BT_LookAt_StockPattern.md',
    'bt-turn-in-place.html': 'Tutorials/BT_TurnInPlace_StockPattern.md',
    'bt-health-below.html': 'Tutorials/BT_HealthBelow_StockPattern.md',
    'bt-perception-relay.html': 'Tutorials/BT_PerceptionRelay_StockPattern.md',
    'bt-memory-decay.html': 'Tutorials/BT_MemoryDecay_StockPattern.md',
    'editor-tools.html': 'Editor_Tools.md',
    'feature-examples.html': 'Feature_Examples.md',
    'settings.html': 'Settings_Reference.md',
    'troubleshooting.html': 'Troubleshooting.md',
    'flight-locomotion.html': 'Flight_Locomotion_Reference.md',
    'mass-traits.html': 'Mass_Traits_Reference.md',
    'api-reference.html': 'API_Reference.md',
}
# Markdown file name -> page, for rewriting links between documents
LINKS = {Path(md).name: page for page, md in MAP.items()}
LINKS['README.md'] = 'index.html'

BLOCK = r'(?:/?(?:p|h[1-6]|ul|ol|li|table|thead|tbody|tr|th|td|div|pre|blockquote|hr|dl|dt|dd|figure|figcaption|nav|section)\b)'


def git(*args):
    return subprocess.run(['git', '-C', str(PLUGIN), *args], capture_output=True, text=True, encoding='utf-8', check=True).stdout


def rewrite(html):
    def link(m):
        href = m.group(1)
        if re.match(r'^(https?:|mailto:|#)', href):
            return m.group(0)
        path, _, frag = href.partition('#')
        name = Path(path).name
        if name in LINKS:
            return f'href="{LINKS[name]}' + (f'#{frag}' if frag else '') + '"'
        if name.endswith('.pdf'):
            return 'href="pdf/LCM_Nav3D_Manual.pdf"'
        return m.group(0)
    html = re.sub(r'href="([^"]+)"', link, html)
    html = re.sub(r'src="(?:\.\./)*(?:Images|images)/([^"]+)"', r'src="images/\1"', html)
    return html


def normalize(html):
    """One block per line, so a line-based merge sees paragraphs, list items and cells."""
    pres = []
    html = re.sub(r'<pre[\s\S]*?</pre>', lambda m: pres.append(m.group(0)) or f'\x00{len(pres) - 1}\x00', html)
    html = re.sub(r'\s*\n\s*', '\n', html.strip())
    html = re.sub(r'\n(?!<' + BLOCK + r')(?!\x00)', ' ', html)          # unwrap text lines
    html = re.sub(r'(?<!\n)(<' + BLOCK + r'[^>]*>)', r'\n\1', html)   # each block tag on its own line
    html = re.sub(r'\n{2,}', '\n', html).strip()
    html = re.sub(r'\x00(\d+)\x00', lambda m: pres[int(m.group(1))], html)
    return html + '\n'


def convert(md_text):
    out = subprocess.run(['pandoc', '-f', 'gfm', '-t', 'html5'], input=md_text, capture_output=True, text=True, encoding='utf-8', check=True).stdout
    return normalize(rewrite(out))


def body_of(page_html):
    main = page_html.split('<main id="content">', 1)[1].split('<div class="pager">', 1)[0]
    main = re.sub(r'\s*<nav class="crumbs"[\s\S]*?</nav>', '', main, count=1)
    main = re.sub(r'<div class="table-wrap"[^>]*>\s*(<table>[\s\S]*?</table>)\s*</div>', r'\1', main)
    return normalize(main)


def similarity(a, b):
    # Line level: the bodies are one block per line, and a character-level match on the API
    # reference against every historical version would take minutes.
    return difflib.SequenceMatcher(None, a.splitlines(), b.splitlines(), autojunk=False).ratio()


def main():
    state = json.loads(STATE.read_text('utf-8')) if STATE.exists() else {}
    head = git('rev-parse', 'HEAD').strip()
    report, conflicts = [], 0
    for page, md in MAP.items():
        src = f'{DOC}/{md}'
        theirs = convert(git('show', f'HEAD:{src}'))
        file = ROOT / page
        if not file.exists():
            report.append(f'  NEW      {page:30s} <- {md}')
            if not DRY:
                skeleton = (ROOT / 'small-worlds.html').read_text('utf-8').replace('\r\n', '\n')
                pre, rest = skeleton.split('<main id="content">', 1)
                post = rest.split('<div class="pager">', 1)[1]
                file.write_text(pre + '<main id="content">\n' + theirs + '<div class="pager">' + post, 'utf-8')
                state[page] = head
            continue
        raw = file.read_text('utf-8').replace('\r\n', '\n')
        ours = body_of(raw)
        if page in state:
            base_rev = state[page]
            base = convert(git('show', f'{base_rev}:{src}'))
        else:
            revs = git('log', '--format=%H', '--', src).split()
            scored = []
            for rev in revs:
                try:
                    conv = convert(git('show', f'{rev}:{src}'))
                except subprocess.CalledProcessError:
                    continue
                scored.append((similarity(conv, ours), rev, conv))
            scored.sort(key=lambda t: -t[0])
            score, base_rev, base = scored[0]
        if base == theirs:
            report.append(f'  current  {page:30s} (Markdown unchanged since {base_rev[:9]})')
            state[page] = head
            continue
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'ours').write_text(ours, 'utf-8'); (p / 'base').write_text(base, 'utf-8'); (p / 'theirs').write_text(theirs, 'utf-8')
            r = subprocess.run(['git', 'merge-file', '-p', '-L', 'site', '-L', 'base', '-L', 'markdown',
                                str(p / 'ours'), str(p / 'base'), str(p / 'theirs')], capture_output=True, text=True, encoding='utf-8')
            merged, n = r.stdout, r.returncode
        site_only = sum(1 for _ in difflib.unified_diff(base.splitlines(), ours.splitlines(), n=0) if _.startswith('+') and not _.startswith('+++'))
        md_changes = sum(1 for _ in difflib.unified_diff(base.splitlines(), theirs.splitlines(), n=0) if _[:1] in '+-' and _[:3] not in ('+++', '---'))
        status = 'CONFLICT' if n else 'merged'
        report.append(f'  {status:8s} {page:30s} base {base_rev[:9]}  markdown lines changed {md_changes:4d}  site-only lines kept {site_only:3d}' + (f'  conflicts {n}' if n else ''))
        if n:
            conflicts += n
            (ROOT / 'tools' / f'{page}.conflict.html').write_text(merged, 'utf-8')
            continue
        if not DRY:
            pre, rest = raw.split('<main id="content">', 1)
            crumbs = (re.search(r'\s*<nav class="crumbs"[\s\S]*?</nav>', rest) or [''])[0]
            post = rest.split('<div class="pager">', 1)[1]
            file.write_text(pre + '<main id="content">' + crumbs + '\n' + merged + '<div class="pager">' + post, 'utf-8')
            state[page] = head
    print('\n'.join(report))
    if not DRY:
        STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n', 'utf-8')
    print(f'sync-md: plugin HEAD {head[:9]}; {conflicts} conflict(s)' + (' (dry run)' if DRY else ''))
    sys.exit(1 if conflicts else 0)


if __name__ == '__main__':
    main()
