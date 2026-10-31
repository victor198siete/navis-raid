"""La oficina isométrica (prueba): una habitación por sesión con el héroe sentado y los agentes de pie.

Uso: python3 oficina_iso.py [titulo-de-sesion]  →  escribe _preview-iso.html con la habitación de esa sesión
(sin argumento: la sesión con más agentes trabajando, o la primera activa).
"""
import html
import sys

import config
import logos
import muebles
import sprites
from iso import Escena
import textos
from textos import t

ESCALA = 3
UMBRAL_K = config.valor('umbral_relevo_k')   # contexto (en miles de tokens) desde el que toca relevo


def habitacion_sesion(s, simbolo, ni=7, nj=6):
    """SVG completo de la habitación de una sesión. `simbolo(clave, cuerpo)` registra sprites compartidos."""
    h = html.escape
    E = Escena(ni, nj)
    muebles.habitacion(E)
    muebles.ventana_izq(E, 1.0); muebles.ventana_izq(E, 3.4)
    muebles.ventana_der(E, 3.2)
    muebles.librero(E, 4.9)
    muebles.tapete(E, 4.2, 3.2, 2.4, 2.2)
    muebles.sofa(E, 4.4, 3.3)
    muebles.planta(E, 0.1, 0.1); muebles.planta(E, ni - 1, 0.1)
    # escritorio en medio, silla detrás (lado j menor), agentes delante (lado j mayor)
    di_e, dj_e = 2.4, 1
    ie, je = 1.8, 1.6
    ancla = muebles.escritorio(E, ie, je, di_e, dj_e)
    muebles.silla(E, ie + 0.05, je - 1.0)
    activa = s['activa']

    # --- capa viva en SVG ---
    heroe = None if vacio else simbolo('heroe-feliz' if activa else 'heroe-pensativo', sprites.heroe('feliz' if activa else 'pensativo'))
    sx, sy = E.p(ie + 0.5, je - 0.3, 0)                                    # pies del héroe, sentado
    bob = ' class="bob"' if activa else ''
    vivo = [f'<use href="#{heroe}" x="{sx - 12:.1f}" y="{sy - 26:.1f}" width="24" height="24"{bob}/>']
    frente = E.capa_img('frente')
    # borde encendido de la pantalla (arista superior del monitor) y resplandor sobre el escritorio
    pi, pj, pz, pdi, ph = ancla['pantalla']
    color = '#5fd068' if activa else '#7c8490'
    vivo_frente = [E.poligono_svg([E.p(pi, pj, pz + ph), E.p(pi + pdi, pj, pz + ph), E.p(pi + pdi, pj + 0.08, pz + ph), E.p(pi, pj + 0.08, pz + ph)], color)]
    if activa:
        vivo_frente.append(E.poligono_svg([E.p(pi - 0.3, pj - 0.9, 14), E.p(pi + pdi + 0.3, pj - 0.9, 14), E.p(pi + pdi + 0.3, pj, 14), E.p(pi - 0.3, pj, 14)], '#5fd068', ' opacity=".22"'))
    de_pie = [a for a in s['subagentes'] if a['estado'] == 'trabajando']
    for k, a in enumerate(de_pie[:3]):
        clave = simbolo('ag-' + ''.join(c if c.isalnum() else '-' for c in a['agente']), sprites.agente(a['agente'], 'feliz'))
        ax, ay = E.p(ie + 0.4 + k * 0.9, je + dj_e + 0.75, 0)
        vivo_frente.append(muebles.sombra_svg(E, ie + 0.4 + k * 0.9, je + dj_e + 0.75))
        vivo_frente.append(f'<use href="#{clave}" x="{ax - 12:.1f}" y="{ay - 24:.1f}" width="24" height="24" class="bob"><title>{h(a["agente"])}: {h(a["tarea"])}</title></use>')
    # letrero con el nombre en la pared izquierda; barra de contexto en el piso, frente a la pared derecha
    letrero, ancho = muebles.letrero_svg(E, h(s['titulo'][:16]), 0.25, 32, '#2f9e5f' if activa else '#2b2420')
    k = s['contexto_k']
    celdas = min(10, int(round(k * 10 / UMBRAL_K)))
    ck = '#d64545' if k >= UMBRAL_K else ('#d9a21b' if k >= UMBRAL_K * 0.8 else '#2f9e5f')
    barra = []
    paso = ancho / 10
    for q in range(10):
        bj = 0.25 + q * paso
        barra.append(E.poligono_svg([E.p(0.06, bj, 28.5), E.p(0.06, bj + paso * 0.8, 28.5), E.p(0.06, bj + paso * 0.8, 31), E.p(0.06, bj, 31)], ck if q < celdas else '#d9cfb8'))
    estado = f'<title>{h(s["titulo"])} · {h(s["estado"])} · {k}K · {h(s["modelo"])}</title>'
    return (f'<svg class="iso" viewBox="0 0 {E.w} {E.h}" width="{E.w * ESCALA}" height="{E.h * ESCALA}" shape-rendering="crispEdges">{estado}'
            f'{E.capa_img("fondo")}{letrero}{"".join(barra)}{"".join(vivo)}{frente}{"".join(vivo_frente)}</svg>')



ZI, ZJ, PASILLO = 6, 5, 1          # oficina de 6x5 celdas y pasillos de 1


def _oficina(E, s, zi, zj, simbolo, h, estilo=None):
    """Dibuja una oficina (mamparas, escritorio, silla, planta) y devuelve la capa viva SVG (héroe, pantalla, agentes, letrero, barra).
    Con estilo='sotano' la mampara es de taller y el escritorio un banco de trabajo; lo demás es igual."""
    activa, fria = s['activa'], s.get('fria', False)
    vacio = s.get('vacio', False)              # cubículo fijo sin sesión que dibujar: luz apagada, sin héroe, burbuja ni papeles
    muebles.mampara(E, zi, zj, ZI, ZJ, estilo=estilo)
    di_e, dj_e = 2.4, 1
    ie, je = zi + 1.5, zj + 1.7
    ancla = (muebles.banco_trabajo if estilo == 'sotano' else muebles.escritorio)(E, ie, je, di_e, dj_e)
    muebles.silla(E, ie + 0.05, je - 1.0)
    muebles.planta(E, zi + ZI - 1.1, zj + ZJ - 1.1)
    cartel = _decorar(E, s['titulo'], zi, zj)
    if activa:
        muebles.tapete(E, ie - 0.3, je - 1.3, di_e + 0.6, dj_e + 2.3, '#dcebd9')
    heroe = simbolo('heroe-feliz' if activa else 'heroe-pensativo', sprites.heroe('feliz' if activa else 'pensativo'))
    sx, sy = E.p(ie + 0.5, je - 0.3, 0)
    bob = ' class="bob"' if activa else ''
    velo = ([E.poligono_svg([E.p(zi + 0.15, zj + 0.15, 0), E.p(zi + ZI - 0.15, zj + 0.15, 0), E.p(zi + ZI - 0.15, zj + ZJ - 0.15, 0), E.p(zi + 0.15, zj + ZJ - 0.15, 0)],
                              '#2c3a55', ' opacity=".30"')] if fria else [])          # luces apagadas: la sesión está fría
    medio = velo + ([] if vacio else [f'<use href="#{heroe}" x="{sx - 12:.1f}" y="{sy - 26:.1f}" width="24" height="24"{bob}/>'])
    bx, by = sx + 4, sy - 30                                               # burbuja de diálogo con el menú de acciones (capa de frente: recibe el clic)
    burbuja = (f'<g class="burbuja" data-menu="{h(s["cli"])}"><title>{t("Acciones de {titulo}", titulo=h(s["titulo"]))}</title>'
                 f'<path d="M{bx - 1},{by - 10} h16 v9 h-10 l-3,3 v-3 h-3 z" fill="#fbfaf6" stroke="#2b2420" stroke-width="1"/>'
                 f'<circle cx="{bx + 3}" cy="{by - 5.5}" r="1" fill="#2b2420"/><circle cx="{bx + 7}" cy="{by - 5.5}" r="1" fill="#2b2420"/><circle cx="{bx + 11}" cy="{by - 5.5}" r="1" fill="#2b2420"/></g>')
    # torre de papeles en la esquina delantera derecha del escritorio: crece con el contexto; se desborda al umbral (UMBRAL_K)
    kk = s['contexto_k']
    hojas = 1 if kk < UMBRAL_K * 0.4 else (3 if kk < UMBRAL_K * 0.6 else (5 if kk < UMBRAL_K * 0.8 else (7 if kk < UMBRAL_K else 10)))
    relevo = kk >= UMBRAL_K
    tope = None if vacio else muebles.torre_papeles(E, ie + di_e - 0.6, je + dj_e - 0.55, hojas, desbordada=relevo)[1]
    pi, pj, pz, pdi, ph = ancla['pantalla']
    frente = ([] if vacio else [burbuja]) + [E.poligono_svg([E.p(pi, pj, pz + ph), E.p(pi + pdi, pj, pz + ph), E.p(pi + pdi, pj + 0.08, pz + ph), E.p(pi, pj + 0.08, pz + ph)], '#5fd068' if activa else ('#1d1f24' if fria else '#7c8490'))]
    if s.get('fuera'):                                                         # tarea programada en un modelo más caro que su regla
        frente.append(_placa_modelo(sx - 20, sy - 22, s['modelo'], t('{titulo}: tarea programada en {modelo} · la regla dice {regla}', titulo=h(s["titulo"]), modelo=h(s["modelo"]), regla=h(s["fuera"]))))
    if fria:                                                                   # pantalla negra y, si hay sesión, un zzz sobre el héroe
        frente.append(E.poligono_svg([E.p(pi, pj, pz), E.p(pi + pdi, pj, pz), E.p(pi + pdi, pj, pz + ph), E.p(pi, pj, pz + ph)], '#1d1f24'))
        if not vacio:
            frente.append(f'<text x="{sx + 8:.1f}" y="{sy - 22:.1f}" font-family="Press Start 2P,monospace" font-size="4" fill="#8a93a6">z<tspan dx="1" dy="-3" font-size="5">z</tspan></text>')
    if activa:
        frente.append(E.poligono_svg([E.p(pi - 0.3, pj - 0.9, 14), E.p(pi + pdi + 0.3, pj - 0.9, 14), E.p(pi + pdi + 0.3, pj, 14), E.p(pi - 0.3, pj, 14)], '#5fd068', ' opacity=".22"'))
    if vacio:
        pass
    elif fria:                                                                 # fría: la hoja queda fija en gris; reanudarla reescribe todo
        frente.append(f'<g class="hoja-fria"><title>' + t('{titulo}: {kk}K y más de 1 h quieta · no reanudar: sesión nueva con /handoff', titulo=h(s["titulo"]), kk=kk) + '</title>'
                      + E.poligono_svg(tope, '#8a93a6') + '</g>')
    elif relevo:                                                               # la hoja de arriba parpadea en rojo
        frente.append(f'<g class="relevo"><title>' + t('{titulo}: {kk}K, pasó de {umbral}K · toca relevo', titulo=h(s["titulo"]), kk=kk, umbral=UMBRAL_K) + '</title>'
                      + E.poligono_svg(tope, '#d64545', ' class="hoja-roja"') + '</g>')
    frente += _plan(E, s, zi, zj, ie, je, h)
    de_pie = [a for a in s['subagentes'] if a['estado'] == 'trabajando']
    for k, a in enumerate(de_pie[:3]):
        clave = simbolo('ag-' + ''.join(c if c.isalnum() else '-' for c in a['agente']), sprites.agente(a['agente'], 'feliz'))
        ai, aj = ie + 0.35 + k * 0.85, je + dj_e + 0.75
        ax, ay = E.p(ai, aj, 0)
        frente.append(muebles.sombra_svg(E, ai, aj))
        detalle = ' · '.join(x for x in (a.get('herramienta') or t('trabajando'), a.get('modelo') or '') if x)
        if a.get('fuera'):
            detalle += t(' · fuera de regla: dice {regla}', regla=a["fuera"])
        frente.append(f'<use href="#{clave}" x="{ax - 12:.1f}" y="{ay - 24:.1f}" width="24" height="24" class="bob agente" data-sesion="{h(s["cli"])}" '
                      f'data-agente="{h(a["agente"])}" data-tarea="{h(a["tarea"])}" data-detalle="{h(detalle)}"/>')
    for k, a in enumerate(de_pie[:3]):                                         # placa roja sobre el agente fuera de regla
        if a.get('fuera'):
            ax, ay = E.p(ie + 0.35 + k * 0.85, je + dj_e + 0.75, 0)
            frente.append(_placa_modelo(ax + 4, ay - 28, a.get('modelo'), t('{agente} corre en {modelo} · la regla dice {regla}', agente=h(a["agente"]), modelo=h(a.get("modelo")), regla=h(a["fuera"]))))
    if len(de_pie) > 3:
        ax, ay = E.p(ie + 0.35 + 3 * 0.85, je + dj_e + 0.75, 0)
        frente.append(f'<text x="{ax - 4:.1f}" y="{ay - 8:.1f}" font-family="Press Start 2P,monospace" font-size="5" fill="#d9a21b">+{len(de_pie) - 3}</text>')
    # letrero sobre la mampara izquierda y barra de contexto en su cara
    letrero, ancho = _letrero(E, h(s['titulo'][:15]), zi + 0.2, zj + 0.3, 13.5, '#2f9e5f' if activa else '#2b2420')
    k = s['contexto_k']
    celdas = min(10, int(round(k * 10 / UMBRAL_K)))
    ck = '#d64545' if k >= UMBRAL_K else ('#d9a21b' if k >= UMBRAL_K * 0.8 else '#2f9e5f')
    paso = min(ancho, ZJ - 0.6) / 10
    barra = []
    for q in range(10):
        bj = zj + 0.3 + q * paso
        barra.append(E.poligono_svg([E.p(zi + 0.2, bj, 4), E.p(zi + 0.2, bj + paso * 0.8, 4), E.p(zi + 0.2, bj + paso * 0.8, 7), E.p(zi + 0.2, bj, 7)], ck if q < celdas else '#cfc7b5'))
    titulo = (f'<title>{h(s["titulo"])} · {t("sin actividad")}</title>' if vacio else
              f'<title>{h(s["titulo"])} · {h(s["estado"])} · {k}K · {h(s["modelo"])}</title>')
    placa = logos.placa_svg(E, s['titulo'], zi + ZI - 2.3, zj + 0.2, 13.5, lambda k_, c_: simbolo(k_, c_, raw=True))
    marca = f'data-vacia="1" data-enlace="{h(s.get("enlace") or "")}"' if vacio else f'data-sesion="{h(s["cli"])}"'
    return [f'<g {marca}>{titulo}{letrero}{placa}{cartel}{"".join(barra)}{"".join(medio)}</g>'], frente


FUENTE = 'font-family="Press Start 2P,monospace"'


def _plan(E, s, zi, zj, ie, je, h):
    """El plan del producto en la oficina (decisión del autor, 21 oct): rotafolio con el avance del ROADMAP, sobre en
    el escritorio si hay notas en ideas/, y sobre la placa del logo ↑N (commits sin subir), punto (sin commitear) y
    ⚠ (ROADMAP más viejo que el código). Todo lleva clase `plan-obj`: el clic abre la pestaña Plan. Sin producto, nada."""
    p = s.get('plan')
    if not p:
        return []
    cli, out = h(s['cli']), []
    g = lambda titulo, cuerpo: f'<g class="plan-obj" data-plan="{cli}"><title>{titulo}</title>{cuerpo}</g>'
    # rotafolio al frente a la derecha, entre el escritorio y la planta
    ri, rj, rdi, rz, rh = zi + 4.45, zj + 2.05, 1.3, 9, 15
    muebles.rotafolio(E, ri, rj, rdi, rz, rh)
    x, y = E.p(ri, rj + 0.1, rz + rh)
    ancho = rdi * 16 - 2
    if p['avance']:
        cols = p['avance'][:4]
        barras = ''.join(f'<rect x="1" y="{8 + k * 2.2:.1f}" width="{ancho:.1f}" height="1.4" fill="#e3dccd"/>'
                         f'<rect x="1" y="{8 + k * 2.2:.1f}" width="{ancho * (c["hechas"] / c["total"] if c["total"] else 0):.1f}" height="1.4" fill="#2f9e5f"/>'
                         for k, c in enumerate(cols))
        texto = f'<text x="1.5" y="5" {FUENTE} font-size="3" fill="#2b2420">{p["hechas"]}/{p["total"]}</text>'
        detalle = ' · '.join(f'{c["col"]} {c["hechas"]}/{c["total"]}' for c in p['avance'])
    else:
        barras, detalle = '', (t('sin ROADMAP en Planning') if p['roadmap'] == 'sin-roadmap' else t('el ROADMAP no tiene fila Total en el Marcador'))
        texto = f'<text x="1.5" y="6" {FUENTE} font-size="2.4" fill="#9a9184">{t("sin")}</text><text x="1.5" y="10" {FUENTE} font-size="2.4" fill="#9a9184">{t("plan")}</text>'
    out.append(g(f'{h(p["producto"])} · {h(detalle)}', f'<g transform="translate({x:.1f},{y:.1f}) matrix(1,0.5,0,1,0,0)">{texto}{barras}</g>'))
    # sobre en el escritorio, entre el teclado y la torre de papeles
    n = len(p['ideas'])
    if n:
        sx, sy = muebles.sobre(E, ie + 1.22, je + 0.48, n=n)
        out.append(g((t('{n} nota en ideas/ de {producto}: ', n=n, producto=h(p["producto"])) if n == 1 else t('{n} notas en ideas/ de {producto}: ', n=n, producto=h(p["producto"])))
                     + h('; '.join(i['titulo'] for i in p['ideas'])),
                     f'<circle cx="{sx + 3:.1f}" cy="{sy - 3:.1f}" r="2.4" fill="#d64545" stroke="#2b2420" stroke-width=".5"/>'
                     f'<text x="{sx + 3:.1f}" y="{sy - 2:.1f}" text-anchor="middle" {FUENTE} font-size="2.4" fill="#fbfaf6">{n if n < 10 else "+"}</text>'))
    # marcas sobre la placa del logo (mampara derecha)
    marcas = []
    if p['adelante']:
        marcas.append((f'↑{p["adelante"]}', '#d9a21b', '#2b2420', t('{n} commit sin subir', n=p["adelante"]) if p["adelante"] == 1 else t('{n} commits sin subir', n=p["adelante"])))
    if p['sucios']:
        marcas.append(('●', '#fbfaf6', '#e8622c', t('{n} archivo sin commitear', n=p["sucios"]) if p["sucios"] == 1 else t('{n} archivos sin commitear', n=p["sucios"])))
    if p['roadmap_viejo']:
        marcas.append(('!', '#d64545', '#fbfaf6', t('el ROADMAP de Planning es {dias} días más viejo que el último commit', dias=p["desfase_d"])))
    if marcas:
        x, y = E.p(zi + ZI - 2.3, zj + 0.2, 13.5 + 11 + 14)           # por encima del icono, que sobresale 8 de la placa
        cuerpo, dx = '', 0
        for txt, fondo, color, _ in marcas:
            w = len(txt) * 3 + 3
            cuerpo += (f'<rect x="{dx}" y="0" width="{w}" height="6" rx="1" fill="{fondo}" stroke="#2b2420" stroke-width=".5"/>'
                       f'<text x="{dx + w / 2:.1f}" y="4.6" text-anchor="middle" {FUENTE} font-size="3.2" fill="{color}">{txt}</text>')
            dx += w + 1.5
        out.append(g(h(p['producto'] + ' · ' + ' · '.join(m[3] for m in marcas)),
                     f'<g transform="translate({x:.1f},{y:.1f}) matrix(1,0.5,0,1,0,0)">{cuerpo}</g>'))
    return out


def _placa_modelo(x, y, modelo, titulo):
    """Placa roja de 7x7 con la inicial del modelo (O, F...): el modelo está fuera de regla."""
    letra = ((modelo or '?').strip()[:1] or '?').upper()
    return (f'<g class="regla"><title>{titulo}</title><rect x="{x:.1f}" y="{y:.1f}" width="7" height="7" rx="1" fill="#d64545" stroke="#2b2420" stroke-width=".6"/>'
            f'<text x="{x + 3.5:.1f}" y="{y + 5.6:.1f}" text-anchor="middle" font-family="Press Start 2P,monospace" font-size="4.5" fill="#fbfaf6">{letra}</text></g>')


def _familia(titulo):
    t = titulo.lower()
    if 'claude' in t:
        return 'tablero'
    return logos.icono(titulo)


def _decorar(E, titulo, zi, zj):
    """Objetos propios de cada familia: uno al fondo a la derecha (A), uno pequeño al frente a la izquierda (B)
    y, en algunas, un cartel en la mampara derecha. Devuelve el SVG del cartel (o '')."""
    fam = _familia(titulo)
    A = (zi + 4.3, zj + 0.35)
    B = (zi + 0.35, zj + 3.1)
    cartel = ''
    if fam == 'avion':
        muebles.avioncito(E, *A); muebles.maleta(E, *B)
    elif fam == 'camioneta':
        muebles.camioneta(E, zi + 4.1, zj + 0.3); muebles.maleta(E, *B, color='#8f5f3a')
    elif fam == 'huella':
        muebles.cama_mascota(E, *A); muebles.plato_mascota(E, *B)
    elif fam == 'camara':
        muebles.tripie_camara(E, *A); muebles.aro_de_luz(E, *B)
        cartel = _cartel(E, zi + 0.4, zj + 0.2, 1.6, '#d64545', 'ON AIR', '#fbfaf6')
    elif fam == 'matraz':
        muebles.mesa_laboratorio(E, zi + 4.2, zj + 0.3); muebles.pila_libros(E, *B)
    elif fam == 'portafolio':
        muebles.portafolio(E, *B); muebles.pila_libros(E, *A)
        cartel = _mapa_mundi(E, zi + 0.4, zj + 0.2, 1.8)
    elif fam == 'trofeo':
        muebles.trofeo(E, *A); muebles.pila_libros(E, *B)
    elif fam == 'sobre':
        muebles.buzon(E, *A)
    elif fam == 'control':
        muebles.arcade(E, *A); muebles.pila_libros(E, *B)
    elif fam == 'moneda':
        muebles.caja_fuerte(E, *A)
    elif fam == 'tablero':
        muebles.pila_libros(E, *A); muebles.pila_libros(E, *B)
        cartel = _kanban(E, zi + 0.4, zj + 0.2, 1.9)
    else:
        muebles.cajas_carton(E, *A)
    return cartel


def _cartel(E, i0, j, di, fondo, texto, color):
    pts = muebles.placa_pared(E, i0, j, 14.5, di, 8, fondo)
    x, y = E.p(i0 + 0.12, j, 20.5)
    return (E.poligono_svg(pts, fondo) +
            f'<g transform="translate({x:.1f},{y:.1f}) matrix(1,0.5,0,1,0,0)"><text font-family="Press Start 2P,monospace" font-size="4" fill="{color}">{texto}</text></g>')


def _mapa_mundi(E, i0, j, di):
    pts = muebles.placa_pared(E, i0, j, 14, di, 10, '#9bb7d4')
    x, y = E.p(i0, j, 24)
    manchas = ''.join(f'<rect x="{a}" y="{b}" width="{w}" height="{hh}" fill="#2f9e5f"/>' for a, b, w, hh in ((3, 2, 7, 4), (12, 3, 6, 3), (20, 2, 5, 5), (6, 7, 4, 2), (15, 7, 3, 2)))
    return E.poligono_svg(pts, '#9bb7d4') + f'<g transform="translate({x:.1f},{y:.1f}) matrix(1,0.5,0,1,0,0)">{manchas}</g>'


def _kanban(E, i0, j, di):
    pts = muebles.placa_pared(E, i0, j, 14, di, 10, '#fbfaf6')
    x, y = E.p(i0, j, 24)
    notas = ''.join(f'<rect x="{a}" y="{b}" width="4" height="3" fill="{c}"/>' for a, b, c in ((2, 2, '#ffcf4a'), (2, 6, '#ffcf4a'), (9, 2, '#3be8ff'), (9, 6, '#3be8ff'), (16, 2, '#5fd068'), (23, 2, '#f6a2b0'), (23, 6, '#5fd068')))
    return E.poligono_svg(pts, '#fbfaf6') + f'<g transform="translate({x:.1f},{y:.1f}) matrix(1,0.5,0,1,0,0)"><rect x="7.5" y="0" width="0.6" height="10" fill="#d6cfc2"/><rect x="14.5" y="0" width="0.6" height="10" fill="#d6cfc2"/><rect x="21.5" y="0" width="0.6" height="10" fill="#d6cfc2"/>{notas}</g>'


def _elevador(E, j1, pisos=((t('Planta baja'), 'PB'), (t('Piso {n}', n=1), '1'))):
    """Elevador en la pared izquierda (plano i = 0), con su borde izquierdo en j1 (el extremo izquierdo de la
    pared en pantalla). Puertas, marcador de piso y una botonera con un botón <g data-piso="i"> por piso, de
    abajo (k = 0) hacia arriba, cada uno con su etiqueta (S, PB, 1…), que el JS enciende y engancha. Devuelve SVG para la capa media (va sobre la
    pared, detrás de los muebles)."""
    i = 0.02
    P = lambda j, z: E.p(i, j, z)
    def rect(j0, j1_, z0, z1, color, extra=''):
        return E.poligono_svg([P(j0, z0), P(j1_, z0), P(j1_, z1), P(j0, z1)], color, extra)
    def texto(j, z, t, tam, color):
        x, y = P(j, z)
        return f'<text transform="translate({x:.1f},{y:.1f}) matrix(1,-0.5,0,1,0,0)" font-family="Press Start 2P,monospace" font-size="{tam}" fill="{color}">{t}</text>'
    j0 = j1 - 2.2                                   # puerta de 2,2 celdas de ancho
    out = [rect(j0 - 0.15, j1 + 0.15, 0, 37, '#4b5563'),                                   # marco
           rect(j0, j1, 0, 30, '#9ca3af'),                                                 # puertas
           rect(j0 + 0.05, j1 - 0.05, 30, 31.5, '#374151'),                                # dintel
           rect((j0 + j1) / 2 - 0.05, (j0 + j1) / 2 + 0.05, 0, 30, '#374151'),            # ranura central
           rect(j0 + 0.25, j1 - 0.25, 32, 36, '#111827'),                                  # marcador
           rect(j0 + 0.3, j1 - 0.3, 32.4, 35.6, '#1f2937')]
    for n in range(1, 6):                                                                 # líneas de las puertas
        out.append(rect(j0 + 0.1, (j0 + j1) / 2 - 0.1, n * 6 - 0.3, n * 6 + 0.3, '#6b7280'))
        out.append(rect((j0 + j1) / 2 + 0.1, j1 - 0.1, n * 6 - 0.3, n * 6 + 0.3, '#6b7280'))
    out.append(texto(j1 - 0.55, 33.1, '', 3, '#5fd068').replace('></text>', ' data-elev-piso="1"></text>'))   # el JS pone la etiqueta del piso
    # botonera a la derecha de la puerta (j menor): un botón por piso, el PB abajo, con su contador de activas
    b1, b0 = j0 - 0.45, j0 - 1.9
    n, paso, z0 = max(1, len(pisos)), 5.2, 11
    z1 = z0 + 1.6 + n * paso
    out.append(rect(b0, b1, z0, z1, '#d9d2c2'))
    out.append(rect(b0 + 0.05, b1 - 0.05, z0 + 0.3, z1 - 0.3, '#e9e2d2'))
    for k, (nombre, etiqueta) in enumerate(pisos):               # k, no i: `i` es el plano de la pared que usan P y rect
        z = z0 + 1.4 + k * paso
        out.append(f'<g class="elev-btn" data-piso="{k}"><title>{html.escape(str(nombre))}</title>'
                   + rect(b1 - 0.55, b1 - 0.1, z, z + 4.4, '#2b2420', ' class="borde"')
                   + rect(b1 - 0.5, b1 - 0.15, z + 0.4, z + 4.0, '#fbfaf6', ' class="cara"')
                   + texto(b1 - 0.17, z + 1.1, html.escape(etiqueta), 2.2 if len(etiqueta) < 3 else 1.6, '#2b2420').replace('<text ', '<text class="flecha" ')
                   + texto(b1 - 0.78, z + 1.1, '', 2.4, '#2b2420').replace('></text>', f' class="cuenta" data-cuenta="{k}"></text>')
                   + '</g>')
    return ''.join(out)


def _tablon(E, i1):
    """Tablón de avisos en la pared derecha (plano j = 0), con su borde derecho en i1 (el extremo derecho de
    la pared en pantalla). Corcho con notas clavadas y un contador encima que el JS rellena con los eventos
    recientes. Es un <g data-tablon> que el JS engancha para abrir el modal del feed."""
    j = 0.02
    P = lambda i, z: E.p(i, j, z)
    def rect(i0, i1_, z0, z1, color, extra=''):
        return E.poligono_svg([P(i0, z0), P(i1_, z0), P(i1_, z1), P(i0, z1)], color, extra)
    i0 = i1 - 2.6
    out = ['<g class="tablon" data-tablon="1"><title>' + t('Lo que pasa en la oficina') + '</title>',
           rect(i0 - 0.12, i1 + 0.12, 13, 31.5, '#8b5a3c'),                                # marco de madera
           rect(i0, i1, 13.8, 30.7, '#c9a06a')]                                            # corcho
    notas = [(0.15, 23, '#fbfaf6'), (0.95, 25.5, '#ffe9a8'), (1.7, 22.5, '#d7f0d9'), (0.4, 16, '#ffd6d6'), (1.3, 17.5, '#fbfaf6'), (2.0, 15.5, '#dbe9ff')]
    for di, z, color in notas:
        out.append(rect(i0 + di, i0 + di + 0.55, z, z + 5.5, color))
        out.append(rect(i0 + di + 0.22, i0 + di + 0.33, z + 4.6, z + 5.2, '#d64545'))      # chincheta
        for n in range(3):
            out.append(rect(i0 + di + 0.08, i0 + di + 0.47, z + 1 + n * 1.2, z + 1.4 + n * 1.2, '#d9d2c2'))
    # rótulo y contador sobre el marco
    x, y = P(i0 + 0.1, 33.6)
    out.append(f'<g transform="translate({x:.1f},{y:.1f}) matrix(1,0.5,0,1,0,0)"><text font-family="Press Start 2P,monospace" font-size="3" fill="#8b5a3c">AVISOS</text>'
               f'<text x="26" font-family="Press Start 2P,monospace" font-size="3" fill="#d64545" data-tablon-cuenta="1"></text></g></g>')
    return ''.join(out)


def _letrero(E, texto, i, j0, z, color_fondo, color='#fbfaf6', tam=4.2):
    """Placa de pie sobre la mampara izquierda (plano i = const). Devuelve SVG y su ancho en celdas."""
    ancho = (len(texto) * tam * 1.05 + 6) / 16
    j1 = j0 + ancho
    pts = [E.p(i, j0, z), E.p(i, j1, z), E.p(i, j1, z + tam + 5), E.p(i, j0, z + tam + 5)]
    x, y = E.p(i, j1 - 3 / 16, z + 2.4)
    return (E.poligono_svg(pts, color_fondo) +
            f'<text transform="translate({x:.1f},{y:.1f}) matrix(1,-0.5,0,1,0,0)" font-family="Press Start 2P,monospace" font-size="{tam}" fill="{color}">{texto}</text>'), ancho


def _sala(E, zi, zj, activas, trabajando):
    muebles.mampara(E, zi, zj, ZI, ZJ)
    muebles.librero(E, zj + 0.4, 1.6, 30, i0=zi + 0.2)
    muebles.tapete(E, zi + 1.4, zj + 1.0, 3.6, 3.2)
    muebles.sofa(E, zi + 1.8, zj + 1.2, 2.4, 0.8)
    muebles.mesa(E, zi + 2.1, zj + 2.6, 1.6, 0.8, 6)
    muebles.puf(E, zi + 4.2, zj + 1.4, '#2d8fbf'); muebles.puf(E, zi + 4.2, zj + 3.0, '#d64545')
    muebles.planta(E, zi + ZI - 1.1, zj + 0.3); muebles.bici(E, zi + 0.6, zj + ZJ - 1.2)
    # pizarrón sobre la mampara izquierda: el % semanal de la cuota en grande (lo rellena el JS desde D.costo) y los
    # contadores de siempre. Es un <g class="pizarron"> que el JS engancha para abrir el modal de costo.
    z0, z1 = 13.5, 37.5                                     # el marco subió de 30 a 37,5 para que quepa el % sin quitar los contadores
    pts = [E.p(zi + 0.2, zj + 2.4, z0), E.p(zi + 0.2, zj + 4.6, z0), E.p(zi + 0.2, zj + 4.6, z1), E.p(zi + 0.2, zj + 2.4, z1)]
    blanco = [E.p(zi + 0.21, zj + 2.55, z0 + 1), E.p(zi + 0.21, zj + 4.45, z0 + 1), E.p(zi + 0.21, zj + 4.45, z1 - 1), E.p(zi + 0.21, zj + 2.55, z1 - 1)]
    def fila(z, texto, tam, color, extra=''):
        x, y = E.p(zi + 0.2, zj + 4.4, z)                   # arranca en el borde izquierdo en pantalla (j mayor); z = línea base
        return (f'<text transform="translate({x:.1f},{y:.1f}) matrix(1,-0.5,0,1,0,0)" font-family="Press Start 2P,monospace" '
                f'font-size="{tam}" fill="{color}"{extra}>{texto}</text>')
    return ('<g class="pizarron" data-pizarron="1"><title>' + t('Costo de la cuota: clic para el detalle') + '</title>'
            + E.poligono_svg(pts, '#8b5a3c') + E.poligono_svg(blanco, '#fbfaf6')
            + fila(33, t('OFICINA'), 3.4, '#2b2420')
            + fila(26.5, '--%', 6.5, '#7a6f66', ' data-pizarron-pct="1"')
            + fila(23.3, t('semana'), 2.6, '#7a6f66')
            + fila(19.8, t('activas {n}', n=activas), 3, '#2f9e5f')
            + fila(16.2, t('agentes {n}', n=trabajando), 3, '#d9a21b') + '</g>')


def _descanso(E, zi, zj):
    """Sala de descanso del piso de arriba: tapete, sofá, pufs, librero, planta y bici."""
    muebles.mampara(E, zi, zj, ZI, ZJ)
    muebles.librero(E, zj + 0.4, 1.6, 30, i0=zi + 0.2)
    muebles.tapete(E, zi + 1.4, zj + 1.0, 3.6, 3.2)
    muebles.sofa(E, zi + 1.8, zj + 1.2, 2.4, 0.8)
    muebles.mesa(E, zi + 2.1, zj + 2.6, 1.6, 0.8, 6)
    muebles.puf(E, zi + 4.2, zj + 1.4, '#2d8fbf'); muebles.puf(E, zi + 4.2, zj + 3.0, '#d64545')
    muebles.planta(E, zi + ZI - 1.1, zj + 0.3); muebles.bici(E, zi + 0.6, zj + ZJ - 1.2)


def _cocina(E, zi, zj):
    muebles.mampara(E, zi, zj, ZI, ZJ)
    muebles.refrigerador(E, zi + 0.3, zj + 0.3)
    muebles.barra_cocina(E, zi + 1.4, zj + 0.3, 3.2, 0.8)
    muebles.mesa(E, zi + 2.0, zj + 2.6, 1.8, 1.0, 9)
    muebles.silla(E, zi + 1.0, zj + 2.6); muebles.silla(E, zi + 3.9, zj + 2.6)
    muebles.planta(E, zi + ZI - 1.1, zj + ZJ - 1.1)


def _rincon(E, zi, zj):
    """El rincón del raid (solo en el sótano): banco con café y ron frente a un tablero de herramientas, sillón viejo,
    boiler, estantes con cajas y el neón «NAVIS RAID». Sustituye al descanso."""
    muebles.mampara(E, zi, zj, ZI, ZJ, estilo='sotano')
    muebles.tapete(E, zi + 1.6, zj + 2.6, 3.2, 2.0, '#6b5a48')
    muebles.tablero_herramientas(E, zi + 0.3, zj + 0.5, 2.4, 24)
    muebles.banco_trabajo(E, zi + 0.75, zj + 0.5, 0.95, 2.4, 10, monitor=False)
    muebles.taza_cafe(E, zi + 1.05, zj + 0.85, 11)
    muebles.botella_ron(E, zi + 1.05, zj + 1.85, 11)
    muebles.estante_cajas(E, zi + 2.7, zj + 0.25, 1.9)
    muebles.boiler(E, zi + ZI - 1.2, zj + 0.3)
    muebles.sillon_viejo(E, zi + 2.4, zj + 3.2)
    muebles.pila_libros(E, zi + 4.6, zj + 3.2)
    return muebles.neon_svg(E, 'NAVIS RAID', zi + 0.2, zj + 0.3, 27, tam=5.2)[0]           # 4,5 celdas: cabe en la zona (ZJ = 5)


# ---------- la azotea (piso de ocio) ----------

# Cada zona de la azotea: letrero y dónde se para cada agente según su actividad. Un puesto es (i, j, z) relativo al
# origen de la zona (z = altura a la que pisa: encima de la caminadora, del sofá, de un puf).
OCIO_ZONAS = ('gym', 'juegos', 'tele', 'restroom')
OCIO_LETRERO = {'gym': (t('GYM'), '#c0392b'), 'juegos': (t('JUEGOS'), '#8e6ac8'), 'tele': (t('TELE'), '#2d5fa8'), 'restroom': (t('RESTROOM'), '#2d8fbf')}


def actividad(act):
    """El nombre de una actividad de la azotea para mostrar. Los códigos internos (`OCIO`, `durmiendo`...) se quedan en español."""
    return {'gym': t('gym'), 'restroom': t('restroom'), 'durmiendo': t('durmiendo'), 'videojuegos': t('videojuegos'),
            'juegos de mesa': t('juegos de mesa'), 'tele': t('tele'), 'ping-pong': t('ping-pong')}.get(act, act)
OCIO_PUESTOS = {                       # actividad → (zona, [puestos])
    'gym': ('gym', [(1.5, 0.8, 2.5), (3.6, 1.8, 0), (5.2, 1.6, 0), (3.0, 3.5, 0), (4.5, 3.5, 0)]),
    'videojuegos': ('juegos', [(1.7, 0.9, 0), (1.7, 2.2, 0)]),
    'ping-pong': ('juegos', [(5.3, 1.0, 0), (3.3, 2.3, 0)]),
    'juegos de mesa': ('juegos', [(4.3, 4.3, 0), (5.5, 3.3, 0)]),
    'tele': ('tele', [(5.1, 2.25, 6), (2.3, 4.4, 0), (3.5, 4.5, 0), (4.6, 4.4, 0)]),
    'restroom': ('restroom', [(1.9, 1.0, 0), (1.9, 2.4, 0), (3.2, 1.9, 0), (4.9, 1.7, 0)]),
}
OCIO_SOFA = (3.2, 3.4, 7)              # dónde duerme el dormido: centro del sofá de la tele y altura del asiento
OCIO_ACTIVOS = ('gym', 'ping-pong', 'videojuegos', 'restroom')   # estos se mueven (bob); el resto está quieto


def _zona_letrero(E, zona, zi, zj):
    texto, color = OCIO_LETRERO[zona]
    return _letrero(E, texto, zi + 0.2, zj + 0.3, 30, color)[0]


def _gym(E, zi, zj):
    muebles.mampara(E, zi, zj, ZI, ZJ)
    muebles.tapete(E, zi + 2.4, zj + 2.7, 3.4, 1.8, '#9ad3a1')                   # colchoneta
    muebles.caminadora(E, zi + 0.5, zj + 0.4)
    muebles.banca_pesas(E, zi + 2.8, zj + 0.5)
    muebles.rack_mancuernas(E, zi + 4.6, zj + 0.3)
    muebles.planta(E, zi + ZI - 1.1, zj + ZJ - 1.1)
    return _zona_letrero(E, 'gym', zi, zj)


def _juegos(E, zi, zj):
    muebles.mampara(E, zi, zj, ZI, ZJ)
    muebles.arcade(E, zi + 0.2, zj + 0.4); muebles.arcade(E, zi + 0.2, zj + 1.7)
    muebles.mesa_pingpong(E, zi + 2.3, zj + 0.4)
    muebles.mesa_juego(E, zi + 3.6, zj + 2.8)
    muebles.planta(E, zi + 0.4, zj + ZJ - 1.1)
    return _zona_letrero(E, 'juegos', zi, zj)


def _tele(E, zi, zj):
    muebles.mampara(E, zi, zj, ZI, ZJ)
    muebles.tele(E, zi + 0.2, zj + 1.0)
    muebles.tapete(E, zi + 1.4, zj + 1.5, 4.4, 3.2, '#e8c4a0')
    muebles.sofa(E, zi + 1.8, zj + 3.0, 2.8, 0.8)
    muebles.puf(E, zi + 4.6, zj + 1.9, '#2d8fbf')
    muebles.planta(E, zi + ZI - 1.1, zj + 0.3)
    return _zona_letrero(E, 'tele', zi, zj)


def _restroom(E, zi, zj):
    muebles.mampara(E, zi, zj, ZI, ZJ)
    muebles.tapete(E, zi + 1.4, zj + 0.6, 4.4, 3.4, '#bfe3f7')                   # baldosa
    muebles.ducha(E, zi + 0.3, zj + 0.5); muebles.ducha(E, zi + 0.3, zj + 1.9)
    muebles.lavabo(E, zi + 2.5, zj + 0.2)
    muebles.inodoro(E, zi + 4.3, zj + 0.3)
    return _zona_letrero(E, 'restroom', zi, zj)


_ZONAS_OCIO = {'gym': _gym, 'juegos': _juegos, 'tele': _tele, 'restroom': _restroom}


def _ocio_agentes(E, origen, ocio, simbolo, h):
    """Los agentes de la azotea en su puesto, con `<title>` «nombre corto · actividad». `origen` = zona → (zi, zj);
    `ocio` = [{tipo, actividad, porque}]. El dormido va tumbado en el sofá con «z z»; si faltan puestos sale «+n»."""
    out, usados = [], {}
    for a in sorted(ocio, key=lambda a: a['tipo']):
        dormido = a['actividad'] == 'durmiendo'
        clave = simbolo('ag-' + ''.join(c if c.isalnum() else '-' for c in a['tipo']) + ('-zz' if dormido else ''), sprites.agente(a['tipo'], 'pensativo' if dormido else 'feliz'))
        titulo = f"<title>{h(sprites.corto(a['tipo']))} · {h(actividad(a['actividad']))}</title>"
        if dormido:
            zi, zj = origen['tele']
            x, y = E.p(zi + OCIO_SOFA[0], zj + OCIO_SOFA[1], OCIO_SOFA[2])
            out.append(f'<use href="#{clave}" x="{x - 12:.1f}" y="{y - 20:.1f}" width="24" height="24" transform="rotate(-90 {x:.1f} {y - 8:.1f})">{titulo}</use>')
            out.append(f'<text x="{x + 6:.1f}" y="{y - 14:.1f}" font-family="Press Start 2P,monospace" font-size="4" fill="#8a93a6">z<tspan dx="1" dy="-3" font-size="5">z</tspan></text>')
            continue
        zona, puestos = OCIO_PUESTOS[a['actividad']]
        n = usados.get(a['actividad'], 0)
        usados[a['actividad']] = n + 1
        zi, zj = origen[zona]
        if n >= len(puestos):                                                   # sin puesto: se cuenta aparte
            continue
        pi, pj, pz = puestos[n]
        x, y = E.p(zi + pi, zj + pj, pz)
        bob = ' class="bob"' if a['actividad'] in OCIO_ACTIVOS else ''
        if pz == 0:
            out.append(muebles.sombra_svg(E, zi + pi, zj + pj))
        out.append(f'<use href="#{clave}" x="{x - 12:.1f}" y="{y - 24:.1f}" width="24" height="24"{bob}>{titulo}</use>')
    for act, n in usados.items():
        puestos = OCIO_PUESTOS[act][1]
        if n > len(puestos):
            zi, zj = origen[OCIO_PUESTOS[act][0]]
            x, y = E.p(zi + puestos[-1][0] + 0.6, zj + puestos[-1][1], 0)
            out.append(f'<text x="{x:.1f}" y="{y - 8:.1f}" font-family="Press Start 2P,monospace" font-size="5" fill="#d9a21b"><title>{h(actividad(act))}: {t("{n} más sin puesto", n=n - len(puestos))}</title>+{n - len(puestos)}</text>')
    return out


def render_piso(sesiones, simbolo, cols=4, escala=2, extras=('sala', 'cocina'), contadores=None, pisos=None, ocio=None, estilo=None):
    """Un piso: una oficina por sesión en retícula, más las zonas extra al frente. Devuelve SVG.
    `contadores` = (activas, trabajando) para el pizarrón de la sala; si no se da, se cuentan las sesiones del piso.
    `pisos` = (nombre, etiqueta) de todos los pisos, de abajo arriba, para la botonera del elevador.
    `ocio` = los agentes de la azotea ([{tipo, actividad, porque}]); con las zonas gym/juegos/tele/restroom en `extras`.
    `estilo` = 'sotano' para el garaje (paredes de block, ventanitas, focos, cubículos de taller y la zona `rincon`)."""
    h = html.escape
    activas, trabajando = contadores or (sum(1 for s in sesiones if s['activa']), sum(s['encargos_activos'] for s in sesiones))
    zonas = [('sesion', s) for s in sesiones] + [(z, None) for z in extras]
    cols = max(1, min(cols, len(zonas)))
    filas = (len(zonas) + cols - 1) // cols
    ni = cols * (ZI + PASILLO) + PASILLO
    nj = filas * (ZJ + PASILLO) + PASILLO
    E = Escena(ni, nj, alto_pared=44)
    garaje = estilo == 'sotano'
    muebles.habitacion(E, alto=44, estilo=estilo)
    j_elev = nj - 0.3                                       # borde izquierdo del elevador, pegado a la esquina izquierda
    for j in range(1, nj - 1, 3):
        if j + 1.6 < j_elev - 4.3:                          # sin ventana donde van el elevador y su botonera
            (muebles.ventanita_izq(E, j, 1.4) if garaje else muebles.ventana_izq(E, j, 1.6, 16, 20))
    i_tablon = ni - 0.3                                     # borde derecho del tablón, pegado a la esquina derecha
    for i in range(1, ni - 1, 3):
        if i + 1.6 < i_tablon - 2.9:                        # sin ventana donde va el tablón
            (muebles.ventanita_der(E, i, 1.4) if garaje else muebles.ventana_der(E, i, 1.6, 16, 20))
    resplandor = _luz_garaje(E, ni, nj, j_elev, i_tablon) if garaje else []
    medio, frente = [_elevador(E, j_elev, pisos or ((t('Planta baja'), 'PB'), (t('Piso {n}', n=1), '1'))), _tablon(E, i_tablon)], []
    origen = {}
    orden = sorted(range(len(zonas)), key=lambda k: (k // cols + k % cols, k // cols))   # de atrás hacia adelante
    for k in orden:
        tipo, s = zonas[k]
        zi = PASILLO + (k % cols) * (ZI + PASILLO)
        zj = PASILLO + (k // cols) * (ZJ + PASILLO)
        if tipo == 'sesion':
            m, f = _oficina(E, s, zi, zj, simbolo, h, estilo)
            medio += m; frente += f
        elif tipo == 'sala':
            medio.append(_sala(E, zi, zj, activas, trabajando))
        elif tipo == 'descanso':
            _descanso(E, zi, zj)
        elif tipo == 'rincon':
            medio.append(_rincon(E, zi, zj))
        elif tipo in _ZONAS_OCIO:
            origen[tipo] = (zi, zj)
            medio.append(_ZONAS_OCIO[tipo](E, zi, zj))
        else:
            _cocina(E, zi, zj)
    if ocio and len(origen) == len(OCIO_ZONAS):
        frente += _ocio_agentes(E, origen, ocio, simbolo, h)
    return (f'<svg class="iso" viewBox="0 0 {E.w} {E.h}" width="{E.w * escala}" height="{E.h * escala}" shape-rendering="crispEdges">'
            f'{E.capa_img("fondo")}{"".join(medio)}{E.capa_img("frente")}{"".join(resplandor)}{"".join(frente)}</svg>')


def _luz_garaje(E, ni, nj, j_elev, i_tablon):
    """La luz del sótano: cables con focos pelones sobre los pasillos (unos cuantos) y una guirnalda de foquitos en
    cada pared. Dibuja en las capas de la escena y devuelve el resplandor de los focos (círculos SVG sin clics)."""
    puntos = muebles.cable_focos(E, 1, 0.5, ni - 2, 0, 3)                                    # pasillo del fondo derecho
    puntos += muebles.cable_focos(E, 0.5, 1, 0, max(2, j_elev - 5), 2)                       # pasillo del fondo izquierdo
    for fila in range(1, (nj - PASILLO) // (ZJ + PASILLO)):                                   # pasillos entre filas de cubículos
        puntos += muebles.cable_focos(E, 1, fila * (ZJ + PASILLO) + 0.5, ni - 2, 0, 2, z=34, tendido=False)
    muebles.guirnalda(E, 'izq', 1, j_elev - 4.8, 20.5, 3.5, max(1, int((j_elev - 5.8) // 4)))
    muebles.guirnalda(E, 'der', 1, i_tablon - 3.4, 20.5, 3.5, max(1, int((i_tablon - 4.4) // 4)))
    return [f'<circle cx="{x}" cy="{y}" r="11" fill="#ffd86b" opacity=".14" style="pointer-events:none"/>'
            f'<circle cx="{x}" cy="{y}" r="5" fill="#fff0b0" opacity=".28" style="pointer-events:none"/>' for x, y in puntos]


PAGINA = """<!doctype html><html lang="%LANG%"><head><meta charset="utf-8"><title>La oficina · prueba isométrica</title>
<style>@font-face{font-family:'Press Start 2P';font-style:normal;font-weight:400;font-display:swap;src:url('fuentes/press-start-2p-latin-400-normal.woff2') format('woff2')}
body{margin:0;background:#efe9df;color:#2b2420;font:13px/1.5 "JetBrains Mono",monospace;padding:20px}
h1{font:12px "Press Start 2P",monospace;color:#8b5a3c;margin:0 0 14px}.iso{display:block;image-rendering:pixelated;max-width:100%;height:auto}
.bob{animation:bob .5s steps(2) infinite}@keyframes bob{to{transform:translateY(.5px)}}
p{color:#7a6f66;max-width:720px}</style></head><body><h1>LA OFICINA · prueba isométrica</h1>
<svg width="0" height="0" style="position:absolute"><defs>%SIMBOLOS%</defs></svg>%SVG%
<p>%NOTA%</p></body></html>"""


def main(argv):
    import oficina
    sesiones, _ = oficina.recoger()
    simbolos = {}

    def simbolo(clave, cuerpo, raw=False):
        simbolos.setdefault(clave, cuerpo if raw else f'<symbol id="{clave}" viewBox="0 0 32 32">{cuerpo}</symbol>')
        return clave

    if argv and argv[0] != '--piso':
        elegida = next((s for s in sesiones if argv[0].lower() in s['titulo'].lower()), sesiones[0])
        svg = habitacion_sesion(elegida, simbolo)
        nota = f"Sesión: {elegida['titulo']} · {elegida['estado']} · {elegida['contexto_k']}K."
    else:
        svg = render_piso(sesiones, simbolo)
        nota = f"{len(sesiones)} sesiones, más la sala y la cocina."
    open('_preview-iso.html', 'w').write(PAGINA.replace('%LANG%', textos.idioma()).replace('%SIMBOLOS%', ''.join(simbolos.values())).replace('%SVG%', svg).replace('%NOTA%', html.escape(nota)))
    print('ok →', '_preview-iso.html', nota)


if __name__ == '__main__':
    main(sys.argv[1:])
