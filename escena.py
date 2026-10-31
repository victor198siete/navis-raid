"""La escena de la oficina: un plano abierto y claro, en vista frontal 3/4 (como los juegos de gestión en pixel).

Unidades = pixeles del dibujo; la página los escala. Paredes de ladrillo claro con ventanas, piso de madera,
sala de estar a la izquierda (pizarrón, librero, sofá, tapete), cocina a la derecha (barra, refri, mesa) y en
medio las estaciones de trabajo: una por sesión, con el héroe sentado y los agentes de pie.
"""
import html
import random

import config
from textos import t

# paleta clara
PARED, PARED_LINEA, ZOCLO = '#efe7d6', '#e2d8c3', '#b9a78c'
MADERA_A, MADERA_B, MADERA_LINEA = '#d8a86f', '#cf9d64', '#b9865a'
ESCRITORIO_TOP, ESCRITORIO_FRENTE, ESCRITORIO_SOMBRA = '#c98d5c', '#a87246', '#8f5f3a'
MONITOR, PANTALLA_ON, PANTALLA_OFF = '#3a3f47', '#2f9e5f', '#7c8490'
SILLA = '#4b5563'
CIELO_A, CIELO_B, MARCO = '#bfe3f7', '#9fd2f0', '#fbfaf6'
BLANCO, GRIS, NEGRO = '#fbfaf6', '#9aa3ad', '#2b2420'
VERDE, ORO, ROJO, AZUL = '#2f9e5f', '#d9a21b', '#d64545', '#9bb7d4'

UMBRAL_K = config.valor('umbral_relevo_k')   # el mismo que oficina.py
ANCHO_SALA, ANCHO_COCINA = 76, 68
EST_W, EST_H = 50, 46             # estación de trabajo
PARED_H = 44
COLS = 4


def _r(x, y, w, h, c, extra=''):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c}"{extra}/>'


def _t(x, y, s, size=3.8, color=NEGRO, extra=''):
    return f'<text x="{x}" y="{y}" font-family="Press Start 2P,monospace" font-size="{size}" fill="{color}"{extra}>{html.escape(s)}</text>'


def medidas(n):
    filas = max(1, (n + COLS - 1) // COLS)
    W = ANCHO_SALA + COLS * EST_W + ANCHO_COCINA
    H = PARED_H + 12 + filas * EST_H + 10
    return W, H, filas


def fondo(W, H):
    p = ['<defs>',
         f'<pattern id="ladrillo" width="16" height="8" patternUnits="userSpaceOnUse">{_r(0, 0, 16, 8, PARED)}'
         f'{_r(0, 3, 16, 1, PARED_LINEA)}{_r(0, 7, 16, 1, PARED_LINEA)}{_r(7, 0, 1, 3, PARED_LINEA)}{_r(15, 4, 1, 3, PARED_LINEA)}</pattern>',
         f'<pattern id="madera" width="36" height="8" patternUnits="userSpaceOnUse">{_r(0, 0, 36, 8, MADERA_A)}'
         f'{_r(0, 4, 36, 4, MADERA_B)}{_r(0, 3, 36, 1, MADERA_LINEA)}{_r(0, 7, 36, 1, MADERA_LINEA)}{_r(11, 0, 1, 3, MADERA_LINEA)}{_r(27, 4, 1, 3, MADERA_LINEA)}</pattern>',
         '</defs>',
         _r(0, 0, W, PARED_H, 'url(#ladrillo)'),
         _r(0, PARED_H - 3, W, 3, ZOCLO),
         _r(0, PARED_H, W, H - PARED_H, 'url(#madera)'),
         ]
    # ventanas sobre la zona de escritorios
    x = ANCHO_SALA + 8
    while x + 30 <= ANCHO_SALA + COLS * EST_W - 6:
        p.append(_r(x - 1, 6, 32, 24, MARCO)); p.append(_r(x, 7, 30, 22, CIELO_A)); p.append(_r(x, 18, 30, 11, CIELO_B))
        p.append(_r(x + 14, 7, 2, 22, MARCO)); p.append(_r(x, 17, 30, 2, MARCO))
        p.append(_r(x + 3, 10, 6, 2, BLANCO)); p.append(_r(x + 20, 22, 7, 2, BLANCO))      # nubes
        x += 48
    return ''.join(p)


def sala(activas, trabajando, H):
    """Sala de estar: pizarrón con los contadores, librero, planta, tapete, sofá, mesita y pufs."""
    p = []
    p.append(_r(5, 6, 44, 28, '#8b5a3c')); p.append(_r(7, 8, 40, 24, BLANCO))               # pizarrón
    p.append(_t(10, 15, t('OFICINA'), 3.6, '#2b2420')); p.append(_t(10, 22, t('activas {n}', n=activas), 3, VERDE)); p.append(_t(10, 28, t('agentes {n}', n=trabajando), 3, ORO))
    p.append(_r(54, 4, 18, 36, '#8b5a3c')); p.append(_r(56, 6, 14, 32, '#a9775a'))         # librero
    for i, c in enumerate(['#d64545', '#2d8fbf', '#d9a21b', '#2f9e5f', '#8e6ac8', '#d64545', '#2d8fbf', '#2f9e5f']):
        p.append(_r(57 + (i % 4) * 3, 8 + (i // 4) * 14, 2, 10, c))
    p.append(_r(56, 18, 14, 1, '#8b5a3c')); p.append(_r(56, 32, 14, 1, '#8b5a3c'))
    y0 = PARED_H + 10
    p.append(_r(6, y0, 62, 44, AZUL)); p.append(_r(8, y0 + 2, 58, 40, '#b4cbe3'))         # tapete
    p.append(_r(10, y0 + 6, 36, 6, '#e9e3d6')); p.append(_r(8, y0 + 12, 40, 10, BLANCO)); p.append(_r(8, y0 + 22, 40, 3, '#d6cfc2'))   # sofá
    p.append(_r(8, y0 + 10, 4, 12, '#e9e3d6')); p.append(_r(44, y0 + 10, 4, 12, '#e9e3d6'))
    p.append(_r(16, y0 + 29, 24, 7, ESCRITORIO_TOP)); p.append(_r(16, y0 + 36, 24, 2, ESCRITORIO_FRENTE))            # mesita
    p.append(_r(22, y0 + 30, 6, 3, '#2b2420')); p.append(_r(32, y0 + 30, 3, 3, ROJO))                                   # control y taza
    p.append(_r(52, y0 + 8, 12, 9, '#2d8fbf')); p.append(_r(54, y0 + 6, 8, 3, '#2d8fbf'))                              # puf azul
    p.append(_r(52, y0 + 28, 12, 9, ROJO)); p.append(_r(54, y0 + 26, 8, 3, ROJO))                                       # puf rojo
    p.append(planta(60, H - 22)); p.append(planta(4, H - 22))
    return ''.join(p)


def cocina(x0, H):
    """Cocina: refrigerador, barra con cafetera y microondas, mesa con sillas, planta."""
    p = []
    p.append(_r(x0 + 48, PARED_H - 30, 14, 34, GRIS)); p.append(_r(x0 + 49, PARED_H - 29, 12, 12, '#b5bdc6')); p.append(_r(x0 + 59, PARED_H - 16, 1, 6, BLANCO))  # refri
    p.append(_r(x0 + 4, PARED_H - 2, 40, 10, BLANCO)); p.append(_r(x0 + 4, PARED_H - 3, 40, 2, '#cfd6dc')); p.append(_r(x0 + 4, PARED_H + 8, 40, 2, '#d6cfc2'))      # barra
    p.append(_r(x0 + 8, PARED_H - 10, 7, 8, '#2b2420')); p.append(_r(x0 + 10, PARED_H - 6, 3, 2, ROJO))                 # cafetera
    p.append(_r(x0 + 24, PARED_H - 10, 14, 8, '#d6d9dd')); p.append(_r(x0 + 26, PARED_H - 8, 8, 4, '#3a3f47'))          # microondas
    p.append(_r(x0 + 6, PARED_H - 36, 36, 1, '#8b5a3c'))                                                                 # repisa
    for i, c in enumerate([ROJO, ORO, VERDE, '#2d8fbf']):
        p.append(_r(x0 + 8 + i * 8, PARED_H - 41, 4, 5, c))
    y = PARED_H + 26
    p.append(_r(x0 + 12, y, 30, 10, ESCRITORIO_TOP)); p.append(_r(x0 + 12, y + 10, 30, 3, ESCRITORIO_FRENTE))           # mesa
    p.append(_r(x0 + 16, y + 2, 6, 4, BLANCO)); p.append(_r(x0 + 30, y + 2, 6, 4, BLANCO))                              # platos
    p.append(_r(x0 + 4, y + 1, 6, 8, SILLA)); p.append(_r(x0 + 44, y + 1, 6, 8, SILLA))                                 # sillas
    p.append(planta(x0 + 54, H - 22))
    return ''.join(p)


def planta(x, y):
    return (_r(x + 2, y + 10, 8, 8, '#b9865a') + _r(x + 3, y + 9, 6, 1, '#8f5f3a') +
            _r(x, y + 2, 4, 6, VERDE) + _r(x + 4, y, 4, 8, '#3fbf74') + _r(x + 8, y + 3, 4, 5, VERDE) + _r(x + 5, y + 7, 2, 4, '#2b7a48'))


def estacion(x, y, s, heroe_id, agentes_ids, h):
    """Una estación de trabajo: placa, silla, héroe, escritorio con monitor, agentes de pie y barra de contexto."""
    activa = s['activa']
    p = [f'<g transform="translate({x},{y})">']
    p.append(f'<title>{h(s["titulo"])} · {h(s["estado"])} · {s["contexto_k"]}K · {h(s["modelo"])}</title>')
    nombre = s['titulo'][:13]
    p.append(_r(3, 0, min(EST_W - 6, 3.4 * len(nombre) + 4), 7, VERDE if activa else '#d6cfc2'))
    p.append(_t(5, 5.2, nombre, 3.2, BLANCO if activa else '#5a5048'))
    p.append(_r(12, 11, 12, 9, SILLA)); p.append(_r(13, 20, 10, 2, '#3a4250'))                                          # silla
    bob = ' class="bob"' if activa else ''
    p.append(f'<use href="#{heroe_id}" x="10" y="8" width="16" height="16"{bob}/>')      # héroe (mitad de tamaño)
    p.append(_r(4, 22, 42, 11, ESCRITORIO_TOP)); p.append(_r(4, 33, 42, 4, ESCRITORIO_FRENTE)); p.append(_r(4, 37, 42, 1, ESCRITORIO_SOMBRA))
    p.append(_r(6, 37, 2, 6, ESCRITORIO_FRENTE)); p.append(_r(42, 37, 2, 6, ESCRITORIO_FRENTE))                        # patas
    p.append(_r(29, 11, 14, 10, MONITOR)); p.append(_r(30, 12, 12, 7, PANTALLA_ON if activa else PANTALLA_OFF))        # monitor
    if activa:
        p.append(_r(31, 13, 6, 1, '#d7f5e3')); p.append(_r(31, 15, 9, 1, '#9fdcb8')); p.append(_r(31, 17, 4, 1, '#9fdcb8'))
    p.append(_r(34, 21, 4, 2, MONITOR))
    p.append(_r(14, 25, 12, 3, '#3a3f47')); p.append(_r(40, 24, 3, 4, ROJO if activa else '#c9b8a6'))                   # teclado y taza
    xa = 2
    for aid in agentes_ids[:2]:
        p.append(f'<use href="#{aid[0]}" x="{xa}" y="27" width="16" height="16" class="bob"><title>{h(aid[1])}</title></use>')
        xa += 14
    if len(agentes_ids) > 2:
        p.append(_t(xa + 1, 38, f'+{len(agentes_ids) - 2}', 3.4, ORO))
    k, umbral = s['contexto_k'], UMBRAL_K
    celdas = min(10, int(round(k * 10 / umbral)))
    color = ROJO if k >= umbral else (ORO if k >= umbral * 0.8 else VERDE)
    for j in range(10):
        p.append(_r(4 + j * 4.2, 44, 3.4, 1.6, color if j < celdas else '#e6dccb'))
    p.append('</g>')
    return ''.join(p)
