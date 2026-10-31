"""Logos genéricos por proyecto: color propio (del nombre), iniciales y un icono pixel 8x8 según la familia.
Se personalizan después con los logos reales; aquí solo viven los genéricos.
"""
import hashlib
import html

import config

ICONOS = {
    'avion':      ["...##...", "...##...", "..####..", ".######.", "########", "...##...", "..####..", "........"],
    'huella':     [".#....#.", "###..###", ".#....#.", "..####..", ".######.", ".######.", "..####..", "........"],
    'camioneta':  ["........", ".######.", ".#.##.#.", ".######.", ".######.", "########", ".#....#.", "........"],
    'camara':     ["........", "..##....", "#######.", "#.###.#.", "#.#.#.#.", "#.###.#.", "#######.", "........"],
    'matraz':     ["..####..", "...##...", "...##...", "..####..", ".######.", ".######.", "..####..", "........"],
    'portafolio': ["..####..", "..#..#..", "########", "#......#", "########", "#......#", "########", "........"],
    'trofeo':     ["########", ".######.", ".######.", "..####..", "...##...", "...##...", "..####..", "........"],
    'sobre':      ["........", "########", "#.....##", "##...#.#", "#.#.#..#", "#..#...#", "########", "........"],
    'control':    ["........", ".######.", "##.##.##", "#.####.#", "##.##.##", ".######.", "........", "........"],
    'moneda':     ["..####..", ".#....#.", "#..##..#", "#.#..#.#", "#.#..#.#", "#..##..#", ".#....#.", "..####.."],
    'cubo':       ["...##...", ".##..##.", "#......#", "#.#..#.#", "#..##..#", ".#....#.", "..#..#..", "...##..."],
}


def _familias():
    """`familias_iconos` de la configuración → [(claves, icono)] en el orden del archivo. Un icono que no existe en
    ICONOS se ignora y queda avisado en `config.AVISOS`."""
    out = []
    for nombre, claves in config.valor('familias_iconos').items():
        if nombre not in ICONOS:
            config.AVISOS.append(f'familias_iconos: el icono «{nombre}» no existe (hay: {", ".join(ICONOS)}): se ignora.')
            continue
        out.append((tuple(k.lower() for k in claves if k), nombre))
    return out


FAMILIAS = _familias()
PALETA = ['#d64545', '#e8622c', '#d9a21b', '#2f9e5f', '#2d8fbf', '#4f6fd8', '#8e6ac8', '#c94f8a', '#1f8a8a', '#7a5c3a']


def icono(titulo):
    """Icono de la familia cuyo nombre aparece en el título. Si hay familias configuradas y ninguna casa, `cubo` (el
    neutro de quien configuró). Sin familias, uno por hash del título, como el color: una oficina sin configurar
    sale variada y no toda de cubos."""
    t = titulo.lower()
    for claves, nombre in FAMILIAS:
        if any(k in t for k in claves):
            return nombre
    if FAMILIAS:
        return 'cubo'
    return list(ICONOS)[int(hashlib.md5(t.encode()).hexdigest(), 16) % len(ICONOS)]


def color(titulo):
    return PALETA[int(hashlib.md5(titulo.lower().encode()).hexdigest(), 16) % len(PALETA)]


def iniciales(titulo):
    partes = [p for p in titulo.replace('_', '-').replace(' ', '-').split('-') if p]
    if len(partes) >= 2:
        return (partes[0][0] + partes[1][0]).upper()
    return titulo[:2].upper()


def simbolo_icono(nombre):
    filas = ICONOS[nombre]
    cuerpo = ''.join(f'<rect x="{x}" y="{y}" width="1" height="1" fill="#fbfaf6"/>' for y, f in enumerate(filas) for x, c in enumerate(f) if c == '#')
    return f'<symbol id="ic-{nombre}" viewBox="0 0 8 8">{cuerpo}</symbol>'


def placa_svg(E, titulo, i0, j, z, registrar):
    """Placa de logo de pie sobre la mampara derecha (plano j = const): color, icono e iniciales. Devuelve SVG."""
    nombre = icono(titulo)
    registrar('ic-' + nombre, simbolo_icono(nombre))
    c = color(titulo)
    di, h = 1.9, 11
    pts = [E.p(i0, j, z), E.p(i0 + di, j, z), E.p(i0 + di, j, z + h), E.p(i0, j, z + h)]
    x, y = E.p(i0 + 0.15, j, z + h - 1.5)
    ini = html.escape(iniciales(titulo))
    return (E.poligono_svg(pts, c) +
            f'<g transform="translate({x:.1f},{y:.1f}) matrix(1,0.5,0,1,0,0)"><use href="#ic-{nombre}" x="0" y="-8" width="8" height="8"/>'
            f'<text x="10" y="-1" font-family="Press Start 2P,monospace" font-size="5" fill="#fbfaf6">{ini}</text></g>')
