"""El plan de cada oficina: a qué producto pertenece la sesión, cómo va su ROADMAP, qué notas esperan en
`ideas/` y el estado de git de sus repos.

Solo lectura y cero tokens. Usa las mismas fuentes y reglas que `/estado` (`Planning/estado.sh`):
  - `Planning/productos.tsv`: producto → repos (rutas relativas a ~/Desktop/Workspace)
  - avance: las celdas N/M de la fila Total del Marcador del ROADMAP (no contar checkboxes)
  - qué sigue: la primera `- [ ]` del ROADMAP
  - decisiones abiertas: los .md de `decisions/` (al cerrarse se mueven a `decisions/archivo/`)
  - notas sin atender: los .md de `ideas/` (al atenderse se mueven a `ideas/archivo/`; decisión del autor, 21 oct)
Del git solo se lee (`status --porcelain -b` y `log -1`), con caché de GIT_TTL segundos por repo.
"""
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import config
from textos import t

AQUI = os.path.dirname(os.path.abspath(__file__))
PLANNING = config.carpeta_planning()          # None: sin plan, la oficina se dibuja sin rotafolios
WORKSPACE = os.path.expanduser(config.valor('raiz_proyectos'))
PRODUCTOS = os.path.join(PLANNING, 'productos.tsv') if PLANNING else None
GIT_TTL = 60                  # segundos que vale el estado de git de un repo (la página pide cada 5 s)
ROADMAP_VIEJO_D = 7           # días de código posterior al ROADMAP a partir de los que se avisa con ⚠

_git = {}                     # repo → (cuándo, datos)


def productos():
    """productos.tsv → {producto: [rutas absolutas de repos]}. Sin archivo: {}."""
    out = {}
    if not PRODUCTOS:
        return out
    try:
        with open(PRODUCTOS, encoding='utf-8') as fh:
            for linea in fh:
                if linea.startswith('#') or not linea.strip():
                    continue
                partes = linea.rstrip('\n').split('\t')
                if len(partes) >= 3 and partes[0]:
                    out[partes[0]] = [os.path.join(WORKSPACE, r.strip()) for r in partes[2].split(',') if r.strip()]
    except OSError:
        pass
    return out


def _dentro(a, b):
    """¿a es b o está dentro de b?"""
    return a == b or a.startswith(b.rstrip('/') + '/')


def producto_de(cwd, mapa=None):
    """(producto, repos) de una sesión, o (None, []).
    Un worktree cuenta como la carpeta desde la que se abrió (lo de antes de `/.claude/worktrees/`). Casa el producto
    con un repo igual a esa carpeta, dentro de ella, o que la contiene; si casan varios, la carpeta es demasiado
    amplia y no se adivina. Sin fila en productos.tsv, vale una carpeta de Planning con el mismo nombre."""
    if not cwd:
        return None, []
    base = cwd.split('/.claude/worktrees/')[0].rstrip('/')
    mapa = productos() if mapa is None else mapa
    casan = [p for p, repos in mapa.items() if any(_dentro(r, base) or _dentro(base, r) for r in repos)]
    if len(casan) == 1:
        return casan[0], mapa[casan[0]]
    if casan:
        return None, []
    nombre = os.path.basename(base).lower()
    if PLANNING and os.path.isdir(os.path.join(PLANNING, nombre)):
        return nombre, ([base] if os.path.exists(os.path.join(base, '.git')) else [])
    return None, []


def _celdas(fila):
    return [c.strip() for c in fila.strip().strip('|').split('|')]


def avance(texto):
    """[(columna, hechas, total)] de la fila Total del Marcador, o None si no hay fila Total.
    La columna sale de la cabecera de esa misma tabla; las celdas sin N/M se saltan."""
    lineas = texto.splitlines()
    for k, l in enumerate(lineas):
        if re.match(r'^\| *\*{0,2}Total', l, re.I):
            ini = k
            while ini > 0 and lineas[ini - 1].lstrip().startswith('|'):
                ini -= 1
            cab = _celdas(lineas[ini])
            out = []
            for n, celda in enumerate(_celdas(l)):
                m = re.search(r'(\d+)\s*/\s*(\d+)', celda)
                if m and n > 0:
                    col = re.sub(r'[*_`]', '', cab[n] if n < len(cab) else '').strip() or t('col {n}', n=n)
                    out.append((col, int(m.group(1)), int(m.group(2))))
            return out
    return None


def siguiente(texto):
    m = re.search(r'^ *- \[ \] *(.+)$', texto, re.M)
    return re.sub(r'\*\*|`', '', m.group(1)).strip()[:140] if m else ''


def _titulo_nota(ruta):
    try:
        with open(ruta, encoding='utf-8') as fh:
            for l in fh:
                if l.startswith('# '):
                    return l[2:].strip()[:100]
    except OSError:
        pass
    return os.path.splitext(os.path.basename(ruta))[0]


def _md(carpeta):
    try:
        return sorted(f for f in os.listdir(carpeta) if f.endswith('.md'))
    except OSError:
        return []


def _correr(repo, *args):
    try:
        r = subprocess.run(['git', '--no-optional-locks', '-C', repo, *args], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def git_repo(repo):
    """{nombre, rama, sucios, adelante (None = sin upstream), remoto, ultimo_ts, ultimo} o None si no es un repo."""
    hay = _git.get(repo)
    if hay and time.time() - hay[0] < GIT_TTL:
        return hay[1]
    datos = None
    if os.path.exists(os.path.join(repo, '.git')):
        st = _correr(repo, 'status', '--porcelain=v1', '-b')
        if st is not None:
            lineas = st.splitlines()
            cab = lineas[0][3:] if lineas and lineas[0].startswith('## ') else ''
            rama = re.split(r'\.\.\.| ', cab, 1)[0] if cab else '?'
            rama = rama.replace('No commits yet on ', '')
            m = re.search(r'ahead (\d+)', cab)
            adelante = int(m.group(1)) if m else (0 if '...' in cab else None)
            log = (_correr(repo, 'log', '-1', '--format=%ct%x09%s') or '').strip()
            ts, _, asunto = log.partition('\t')
            datos = {'nombre': os.path.basename(repo), 'rama': rama, 'sucios': len(lineas) - 1, 'adelante': adelante,
                     'remoto': bool((_correr(repo, 'remote') or '').strip()),
                     'ultimo_ts': int(ts) if ts.isdigit() else 0, 'ultimo': asunto[:90]}
    _git[repo] = (time.time(), datos)
    return datos


def de_sesiones(sesiones):
    """Añade s['plan'] a cada sesión (o None si no casa con ningún producto). Lanza los git en paralelo."""
    if not PLANNING:                                                         # sin carpeta de plan: nada que leer
        for s in sesiones:
            s['plan'] = None
        return
    mapa = productos()
    por_sesion = []
    repos = set()
    for s in sesiones:
        prod, rs = producto_de(s.get('cwd') or '', mapa)
        extra = s['cwd'] if prod and '/.claude/worktrees/' in (s.get('cwd') or '') else None   # el worktree tiene su propia rama
        lista = rs + ([extra] if extra and extra not in rs else [])
        por_sesion.append((prod, lista, extra))
        repos.update(lista)
    with ThreadPoolExecutor(max_workers=8) as ex:
        estado = dict(zip(repos, ex.map(git_repo, repos)))
    cache_prod = {}
    for s, (prod, lista, extra) in zip(sesiones, por_sesion):
        if not prod:
            s['plan'] = None
            continue
        if prod not in cache_prod:
            cache_prod[prod] = _producto(prod)
        p = dict(cache_prod[prod])
        gits = []
        for r in lista:
            g = estado.get(r)
            if g:
                gits.append(dict(g, worktree=(r == extra)))
        p['git'] = gits
        p['sucios'] = sum(g['sucios'] for g in gits)
        p['adelante'] = sum(g['adelante'] or 0 for g in gits)
        p['sin_upstream'] = [g['nombre'] for g in gits if g['adelante'] is None and g['remoto']]
        p['sin_remoto'] = [g['nombre'] for g in gits if not g['remoto']]
        ult = max((g['ultimo_ts'] for g in gits), default=0)
        p['ultimo_commit_ts'] = ult
        p['desfase_d'] = int((ult - p['roadmap_ts']) / 86400) if ult and p['roadmap_ts'] else 0
        p['roadmap_viejo'] = p['desfase_d'] >= ROADMAP_VIEJO_D
        s['plan'] = p


def _producto(prod):
    """Lo que no depende de git: ROADMAP, decisiones e ideas de Planning/<producto>/."""
    carpeta = os.path.join(PLANNING, prod)
    ruta = os.path.join(carpeta, 'ROADMAP.md')
    try:
        with open(ruta, encoding='utf-8') as fh:
            texto = fh.read()
        roadmap_ts = int(os.path.getmtime(ruta))
    except OSError:
        texto, roadmap_ts = None, 0
    av = avance(texto) if texto is not None else None
    ideas = [{'archivo': f, 'titulo': _titulo_nota(os.path.join(carpeta, 'ideas', f))} for f in _md(os.path.join(carpeta, 'ideas'))]
    return {
        'producto': prod,
        'roadmap': 'sin-roadmap' if texto is None else ('sin-marcador' if av is None else 'ok'),
        'avance': [{'col': c, 'hechas': a, 'total': b} for c, a, b in (av or [])],
        'hechas': sum(a for _, a, _ in (av or [])), 'total': sum(b for _, _, b in (av or [])),
        'siguiente': siguiente(texto) if texto else '',
        'decisiones': len(_md(os.path.join(carpeta, 'decisions'))),
        'ideas': ideas,
        'roadmap_ts': roadmap_ts,
    }


if __name__ == '__main__':                      # prueba rápida: python3 plan.py <cwd>...
    import sys
    ses = [{'cwd': c, 'titulo': c} for c in sys.argv[1:]]
    de_sesiones(ses)
    for s in ses:
        print(s['cwd'], '→', s['plan'])
