"""Piezas de la oficina isométrica, dibujadas con el motor `iso` (cubos, caras y pixeles). Todas devuelven
anclas cuando hace falta (dónde sentarse, dónde está la pantalla) para que la capa viva en SVG las use.
"""
from iso import sombra

# paleta clara (la misma familia que escena.py)
PARED, ZOCLO = '#efe7d6', '#b9a78c'
MADERA = '#d8a86f'
ESCRITORIO = '#c98d5c'
MONITOR = '#3a3f47'
SILLA = '#4b5563'
CIELO, MARCO = '#bfe3f7', '#fbfaf6'
TERRACOTA, HOJA = '#b9865a', '#2f9e5f'
TAPETE = '#9bb7d4'
LIBROS = ['#d64545', '#2d8fbf', '#d9a21b', '#2f9e5f', '#8e6ac8', '#e8622c']


def habitacion(E, alto=48, estilo=None):
    """Piso de madera y las dos paredes del fondo con zoclo. Con estilo='sotano', el garaje (ver `habitacion_sotano`)."""
    if estilo == 'sotano':
        return habitacion_sotano(E, alto)
    for i in range(E.ni):
        for j in range(E.nj):
            E.piso(i, j, MADERA if (i + j) % 2 == 0 else sombra(MADERA, 0.95), borde=sombra(MADERA, 0.82))
    g = 0.4                                                   # grosor de pared
    E.caja(-g, -g, 0, g, E.nj + g, alto, PARED, top='#f7f1e3', izq='#efe7d6', der='#e3d9c3', contorno=False)   # pared izquierda (i = 0)
    E.caja(0, -g, 0, E.ni, g, alto, PARED, top='#f7f1e3', izq='#e9e0cb', der='#ddd2ba', contorno=False)       # pared derecha (j = 0)
    E.cara_izq(0, 0, 0, E.nj, 2.5, ZOCLO)
    E.cara_der(0, 0, 0, E.ni, 2.5, ZOCLO)
    # líneas de ladrillo en las paredes
    for z in range(6, alto - 4, 6):
        E.cara_izq(0.01, 0, z, E.nj, 0.6, '#e4dac5')
        E.cara_der(0, 0.01, z, E.ni, 0.6, '#dcd1b9')


def ventana_izq(E, j, dj=1.6, z=18, h=22):
    """Ventana en la pared izquierda (plano i = 0)."""
    E.cara_izq(0.02, j, z - 1, dj + 0.2, h + 2, MARCO)
    E.cara_izq(0.03, j + 0.1, z, dj, h, CIELO)
    E.cara_izq(0.03, j + 0.1, z, dj, h * 0.45, '#a9d9f3')
    E.cara_izq(0.04, j + dj / 2, z, 0.08, h, MARCO)
    E.cara_izq(0.04, j + 0.1, z + h / 2, dj, 1.2, MARCO)
    E.cara_izq(0.05, j + 0.3, z + h * 0.7, 0.4, 2, '#ffffff')          # nube


def ventana_der(E, i, di=1.6, z=18, h=22):
    E.cara_der(i, 0.02, z - 1, di + 0.2, h + 2, MARCO)
    E.cara_der(i + 0.1, 0.03, z, di, h, CIELO)
    E.cara_der(i + 0.1, 0.03, z, di, h * 0.45, '#a9d9f3')
    E.cara_der(i + di / 2, 0.04, z, 0.08, h, MARCO)
    E.cara_der(i + 0.1, 0.04, z + h / 2, di, 1.2, MARCO)


def escritorio(E, i, j, di=2, dj=1, h=13):
    """Escritorio en la capa 'frente' (tapa los pies de quien se sienta detrás). Devuelve la posición del monitor."""
    E.caja(i, j, 0, di, dj, h, ESCRITORIO, capa='frente')
    E.caja(i + 0.1, j + 0.1, h, di - 0.2, dj - 0.2, 1, sombra(ESCRITORIO, 1.08), capa='frente', contorno=False)   # tapa
    # monitor al fondo del escritorio, de espaldas al que mira: se ve su respaldo y el borde superior
    mi, mj = i + di - 0.4, j + 0.18
    E.caja(mi - 0.15, mj, h + 1, 0.3, 0.1, 2, MONITOR, capa='frente', contorno=False)                            # base
    E.caja(mi - 0.4, mj + 0.02, h + 3, 0.8, 0.08, 9, MONITOR, capa='frente', contorno=False)                      # pantalla
    E.caja(i + 0.25, j + 0.55, h + 1, 0.9, 0.25, 0.8, '#2b2f36', capa='frente', contorno=False)                    # teclado
    E.caja(i + 0.15, j + 0.15, h + 1, 0.2, 0.2, 3, '#d64545', capa='frente', contorno=False)                       # taza
    return {'pantalla': (mi - 0.4, mj + 0.02, h + 3, 0.8, 9)}


def silla(E, i, j, hacia='j'):
    """Silla de oficina: asiento, respaldo (del lado opuesto al escritorio) y base. Capa 'fondo'."""
    E.caja(i + 0.3, j + 0.45, 0, 0.4, 0.1, 6, '#2b2f36', contorno=False)                     # poste
    E.caja(i + 0.15, j + 0.3, 6, 0.7, 0.55, 2.5, SILLA)                                       # asiento
    E.caja(i + 0.15, j + 0.22, 8, 0.7, 0.1, 11, sombra(SILLA, 0.9))                          # respaldo
    for di, dj in ((0.15, 0.3), (0.6, 0.3), (0.15, 0.75), (0.6, 0.75)):
        E.pixel(i + di, j + dj, 0, '#2b2f36')


def librero(E, j, dj=1.4, alto=34, i0=0):
    """Librero contra una pared o mampara del lado i = i0, con libros de colores."""
    E.caja(i0, j, 0, 0.5, dj, alto, '#a9775a')
    for repisa, z in enumerate((3, 13, 23)):
        E.cara_izq(i0 + 0.51, j + 0.05, z, dj - 0.1, 0.8, '#8b5a3c')
        for k in range(5):
            E.cara_izq(i0 + 0.52, j + 0.12 + k * (dj - 0.2) / 5, z + 0.8, (dj - 0.2) / 5 * 0.8, 7 - (k % 2), LIBROS[(k + repisa) % len(LIBROS)])


def mampara(E, i0, j0, di, dj, alto=13, color='#e6e0d2', estilo=None):
    """Mamparas bajas de una oficina: una a lo largo de j (lado i = i0) y otra a lo largo de i (lado j = j0).
    Con estilo='sotano': biombo de contrachapado a lo largo de j y lámina acanalada a lo largo de i."""
    g = 0.18
    if estilo == 'sotano':
        return mampara_taller(E, i0, j0, di, dj, alto)
    E.caja(i0, j0, 0, g, dj, alto, color, top='#f3eee3', izq='#e6e0d2', der='#d6cfbf')
    E.caja(i0, j0, 0, di, g, alto, color, top='#f3eee3', izq='#e0d9c9', der='#cfc7b5')
    E.cara_izq(i0 + g + 0.01, j0 + g, 0, dj - g, 1.5, ZOCLO)
    E.cara_der(i0 + g, j0 + g + 0.01, 0, di - g, 1.5, ZOCLO)


def barra_cocina(E, i, j, di=3, dj=0.8):
    E.caja(i, j, 0, di, dj, 10, '#fbfaf6', top='#e4e8ec', izq='#fbfaf6', der='#d9dde2')
    E.caja(i + 0.3, j + 0.2, 10, 0.5, 0.45, 5, '#2b2420', contorno=False)                                    # cafetera
    E.caja(i + 0.4, j + 0.25, 15, 0.1, 0.2, 1, '#d64545', contorno=False)
    E.caja(i + 1.3, j + 0.15, 10, 0.9, 0.55, 4, '#d6d9dd', contorno=False)                                   # microondas
    E.caja(i + 1.4, j + 0.1, 11, 0.5, 0.1, 2.5, '#3a3f47', contorno=False)
    E.caja(i + 2.4, j + 0.2, 10, 0.4, 0.4, 0.6, '#9aa3ad', contorno=False)                                   # tarja


def refrigerador(E, i, j):
    E.caja(i, j, 0, 0.8, 0.8, 24, '#b5bdc6', top='#d0d6dc', izq='#c3cad1', der='#9aa3ad')
    E.cara_izq(i + 0.81, j + 0.1, 15, 0.6, 0.6, '#8f98a3')
    E.cara_izq(i + 0.81, j + 0.1, 6, 0.6, 0.6, '#8f98a3')


def mesa(E, i, j, di=1.6, dj=1.0, h=9):
    E.caja(i, j, 0, di, dj, h, ESCRITORIO)
    E.caja(i + 0.3, j + 0.3, h, 0.35, 0.35, 0.8, '#fbfaf6', contorno=False)
    E.caja(i + di - 0.7, j + 0.3, h, 0.35, 0.35, 0.8, '#fbfaf6', contorno=False)


def puf(E, i, j, color):
    E.caja(i + 0.15, j + 0.15, 0, 0.7, 0.7, 4, color, contorno=False)
    E.caja(i + 0.3, j + 0.3, 4, 0.4, 0.4, 2, sombra(color, 1.1), contorno=False)


def bici(E, i, j):
    """Bicicleta muy simple: dos ruedas y cuadro, contra una mampara."""
    for di in (0.1, 0.9):
        E.caja(i + di, j + 0.35, 0, 0.3, 0.1, 7, '#2b2420', contorno=False)
        E.caja(i + di + 0.08, j + 0.33, 2, 0.14, 0.14, 3, '#9aa3ad', contorno=False)
    E.caja(i + 0.3, j + 0.38, 5, 0.5, 0.06, 1.2, '#2d8fbf', contorno=False)
    E.caja(i + 0.55, j + 0.38, 6, 0.08, 0.06, 4, '#2d8fbf', contorno=False)


def planta(E, i, j):
    E.caja(i + 0.3, j + 0.3, 0, 0.4, 0.4, 6, TERRACOTA)
    E.caja(i + 0.2, j + 0.2, 6, 0.6, 0.6, 4, HOJA, contorno=False)
    E.caja(i + 0.32, j + 0.32, 10, 0.36, 0.36, 4, '#3fbf74', contorno=False)
    E.caja(i + 0.42, j + 0.42, 14, 0.16, 0.16, 3, '#2b7a48', contorno=False)


def tapete(E, i, j, di, dj, color=TAPETE):
    L = E.capas['fondo']
    L.poly([E.p(i, j, 0.5), E.p(i + di, j, 0.5), E.p(i + di, j + dj, 0.5), E.p(i, j + dj, 0.5)], color)
    L.poly([E.p(i + 0.2, j + 0.2, 0.5), E.p(i + di - 0.2, j + 0.2, 0.5), E.p(i + di - 0.2, j + dj - 0.2, 0.5), E.p(i + 0.2, j + dj - 0.2, 0.5)], sombra(color, 1.1))


def sofa(E, i, j, di=2, dj=0.8):
    E.caja(i, j, 0, di, dj, 7, '#f1ece2', contorno=True)                                   # base
    E.caja(i, j, 7, di, 0.25, 8, '#e9e3d6', contorno=False)                                  # respaldo (lado j)
    E.caja(i, j, 7, 0.25, dj, 5, '#e9e3d6', contorno=False)                                  # brazo
    E.caja(i + di - 0.25, j, 7, 0.25, dj, 5, '#e9e3d6', contorno=False)
    E.caja(i + 0.25, j + 0.25, 7, di - 0.5, dj - 0.25, 1.5, '#fbfaf6', contorno=False)       # cojines


def letrero_svg(E, texto, j0, z, color_fondo='#2b2420', color='#fbfaf6', tam=4.6):
    """Letrero en la pared izquierda (plano i = 0), con el texto inclinado en el plano de la pared. Devuelve SVG y su ancho en celdas."""
    ancho = (len(texto) * tam * 1.05 + 6) / 16          # 16 px por celda a lo largo de la pared izquierda
    j1 = j0 + ancho
    pts = [E.p(0.06, j0, z), E.p(0.06, j1, z), E.p(0.06, j1, z + tam + 5), E.p(0.06, j0, z + tam + 5)]
    x, y = E.p(0.06, j1 - 3 / 16, z + 2.4)                # el texto avanza hacia +x: de la punta izquierda (j1) hacia j0
    return (E.poligono_svg(pts, color_fondo) +
            f'<text transform="translate({x:.1f},{y:.1f}) matrix(1,-0.5,0,1,0,0)" font-family="Press Start 2P,monospace" font-size="{tam}" fill="{color}">{texto}</text>'), ancho


def sombra_svg(E, i, j, rx=7, ry=2.6):
    x, y = E.p(i, j, 0)
    return f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{rx}" ry="{ry}" fill="#000" opacity=".14"/>'


# ---------- decoración por familia de proyecto ----------

def avioncito(E, i, j):
    """Avión de maqueta sobre un pedestal."""
    E.caja(i + 0.35, j + 0.35, 0, 0.3, 0.3, 2, '#2b2f36', contorno=False)
    E.caja(i + 0.47, j + 0.47, 2, 0.08, 0.08, 7, '#9aa3ad', contorno=False)
    E.caja(i + 0.05, j + 0.4, 9, 0.9, 0.22, 2.2, '#fbfaf6', top='#ffffff', der='#d9dde2')          # fuselaje
    E.caja(i + 0.38, j + 0.08, 9.6, 0.26, 0.86, 0.7, '#d64545', contorno=False)                   # alas
    E.caja(i + 0.08, j + 0.44, 11, 0.14, 0.14, 2.4, '#d64545', contorno=False)                    # cola
    E.caja(i + 0.84, j + 0.46, 9.8, 0.12, 0.1, 0.8, '#2d8fbf', contorno=False)                     # cabina


def maleta(E, i, j, color='#2d5fa8'):
    E.caja(i + 0.2, j + 0.3, 0, 0.55, 0.25, 7, color)
    E.caja(i + 0.38, j + 0.36, 7, 0.2, 0.12, 1.2, '#2b2f36', contorno=False)                      # asa
    E.cara_izq(i + 0.76, j + 0.33, 3, 0.19, 0.6, '#ffffff')                                        # etiqueta


def camioneta(E, i, j):
    E.caja(i + 0.1, j + 0.25, 1.2, 1.2, 0.55, 4.5, '#2d8fbf', top='#5fb0e0', der='#1f6f9a')        # carrocería
    E.caja(i + 0.1, j + 0.25, 5.7, 0.45, 0.55, 2.2, '#5fb0e0', contorno=False)                     # cabina
    E.cara_izq(i + 0.56, j + 0.3, 6, 0.45, 2, '#dff3ff')                                           # parabrisas lateral
    for di in (0.25, 0.95):
        E.caja(i + di, j + 0.2, 0, 0.22, 0.1, 2.2, '#2b2420', contorno=False)
        E.caja(i + di, j + 0.78, 0, 0.22, 0.1, 2.2, '#2b2420', contorno=False)


def cama_mascota(E, i, j):
    E.caja(i + 0.1, j + 0.1, 0, 0.9, 0.9, 2.2, '#b9865a', top='#d2a071')                           # borde de la cama
    E.caja(i + 0.25, j + 0.25, 0.5, 0.6, 0.6, 2, '#f1e7d6', contorno=False)                        # cojín
    E.caja(i + 0.4, j + 0.35, 2.5, 0.35, 0.45, 2.4, '#8a5a2b', contorno=False)                     # perrito dormido
    E.caja(i + 0.3, j + 0.45, 2.5, 0.16, 0.25, 2.6, '#8a5a2b', contorno=False)                     # cabeza
    E.pixel(i + 0.3, j + 0.5, 4.4, '#2b2420')


def plato_mascota(E, i, j):
    E.caja(i + 0.3, j + 0.3, 0, 0.35, 0.35, 1.6, '#d64545', contorno=False)
    E.caja(i + 0.38, j + 0.38, 1.6, 0.19, 0.19, 0.6, '#b9865a', contorno=False)
    E.caja(i + 0.1, j + 0.75, 0, 0.3, 0.1, 0.9, '#fbfaf6', contorno=False)                         # hueso


def tripie_camara(E, i, j):
    for di, dj in ((0.2, 0.3), (0.75, 0.3), (0.48, 0.8)):
        E.caja(i + di, j + dj, 0, 0.07, 0.07, 11, '#2b2f36', contorno=False)
    E.caja(i + 0.3, j + 0.32, 11, 0.5, 0.32, 3.2, '#2b2420', top='#3a3f47')                        # cámara
    E.caja(i + 0.8, j + 0.42, 11.6, 0.14, 0.14, 1.8, '#3be8ff', contorno=False)                    # lente
    E.pixel(i + 0.35, j + 0.33, 14.5, '#d64545')                                                   # luz de grabación


def aro_de_luz(E, i, j):
    E.caja(i + 0.45, j + 0.45, 0, 0.1, 0.1, 12, '#2b2f36', contorno=False)
    E.caja(i + 0.15, j + 0.46, 12, 0.7, 0.08, 7, '#fff3c4', top='#fff8dc', contorno=False)        # aro (visto como placa)
    E.caja(i + 0.3, j + 0.47, 13.5, 0.4, 0.06, 4, '#fbfaf6', contorno=False)


def mesa_laboratorio(E, i, j):
    E.caja(i + 0.05, j + 0.2, 0, 1.1, 0.6, 9, '#e9e4d8', top='#f7f3ea', der='#d6cfbf')             # mesa blanca
    for k, c in enumerate(('#3be8ff', '#5fd068', '#ffcf4a')):
        E.caja(i + 0.15 + k * 0.32, j + 0.35, 9, 0.18, 0.18, 2.6 + k, c, contorno=False)          # matraces
        E.caja(i + 0.19 + k * 0.32, j + 0.39, 11.6 + k, 0.1, 0.1, 1.4, '#dff3ff', contorno=False)
    E.caja(i + 0.75, j + 0.5, 9, 0.3, 0.16, 3.4, '#2b2420', contorno=False)                        # teléfono en soporte
    E.cara_izq(i + 1.06, j + 0.52, 9.4, 0.12, 2.6, '#3be8ff')


def portafolio(E, i, j):
    E.caja(i + 0.2, j + 0.35, 0, 0.7, 0.2, 5, '#7a4e30', top='#8f5f3a')
    E.caja(i + 0.45, j + 0.4, 5, 0.2, 0.1, 1, '#2b2420', contorno=False)
    E.cara_izq(i + 0.91, j + 0.4, 2, 0.1, 1.2, '#d9a21b')                                          # cierre


def trofeo(E, i, j):
    E.caja(i + 0.25, j + 0.25, 0, 0.5, 0.5, 6, '#e9e4d8', top='#f7f3ea')                           # pedestal
    E.caja(i + 0.38, j + 0.38, 6, 0.24, 0.24, 1.2, '#2b2420', contorno=False)
    E.caja(i + 0.44, j + 0.44, 7.2, 0.12, 0.12, 2.5, '#d9a21b', contorno=False)                    # tallo
    E.caja(i + 0.3, j + 0.3, 9.7, 0.4, 0.4, 3, '#ffcf4a', top='#ffe08a', contorno=False)           # copa
    E.caja(i + 0.2, j + 0.44, 10.5, 0.1, 0.12, 1.4, '#d9a21b', contorno=False); E.caja(i + 0.7, j + 0.44, 0.1, 0.1, 0.12, 1.4, '#d9a21b', contorno=False)


def buzon(E, i, j):
    E.caja(i + 0.45, j + 0.45, 0, 0.1, 0.1, 9, '#5a3a22', contorno=False)
    E.caja(i + 0.25, j + 0.3, 9, 0.5, 0.4, 4.5, '#2d5fa8', top='#4f8ff7')
    E.cara_izq(i + 0.76, j + 0.4, 10.5, 0.2, 1.2, '#fbfaf6')
    E.pixel(i + 0.3, j + 0.72, 13.5, '#d64545')                                                    # banderita
    E.caja(i + 0.1, j + 0.75, 0, 0.35, 0.2, 1.4, '#fbfaf6', contorno=False)                        # sobres apilados
    E.caja(i + 0.14, j + 0.78, 1.4, 0.3, 0.16, 1.2, '#fbfaf6', contorno=False)


def arcade(E, i, j):
    E.caja(i + 0.15, j + 0.15, 0, 0.75, 0.6, 16, '#8e6ac8', top='#a98be0', der='#6b4fa0')          # gabinete
    E.cara_izq(i + 0.91, j + 0.22, 8.5, 0.46, 4.5, '#2b2420')                                      # pantalla
    E.cara_izq(i + 0.92, j + 0.27, 9.2, 0.36, 3.2, '#3be8ff')
    E.cara_izq(i + 0.91, j + 0.2, 14, 0.5, 1.6, '#ffcf4a')                                         # marquesina
    E.caja(i + 0.9, j + 0.3, 6.5, 0.2, 0.3, 0.8, '#2b2420', contorno=False)                        # panel de control
    E.pixel(i + 1.0, j + 0.4, 7.5, '#d64545'); E.pixel(i + 1.0, j + 0.52, 7.5, '#2f9e5f')


def caja_fuerte(E, i, j):
    E.caja(i + 0.2, j + 0.2, 0, 0.6, 0.6, 8, '#5f6b70', top='#8a969c', der='#46525a')
    E.cara_izq(i + 0.81, j + 0.35, 3.5, 0.3, 2.4, '#2b2420')
    E.pixel(i + 0.82, j + 0.5, 4.7, '#ffcf4a')
    for k in range(3):                                                                            # monedas apiladas
        E.caja(i + 0.1 + k * 0.05, j + 0.85 - k * 0.02, k * 0.9, 0.3, 0.3, 0.9, '#ffcf4a', top='#ffe08a', contorno=False)


def cajas_carton(E, i, j):
    E.caja(i + 0.1, j + 0.1, 0, 0.7, 0.6, 5, '#c9a06a', top='#dcb67e')
    E.caja(i + 0.2, j + 0.15, 5, 0.5, 0.45, 4, '#c9a06a', top='#dcb67e')
    E.cara_izq(i + 0.81, j + 0.25, 1.5, 0.3, 1.2, '#8f5f3a')


def pila_libros(E, i, j):
    for k, c in enumerate(('#d64545', '#2d8fbf', '#2f9e5f', '#d9a21b')):
        E.caja(i + 0.2 + (k % 2) * 0.05, j + 0.3, k * 1.3, 0.5, 0.35, 1.3, c, contorno=False)


def placa_pared(E, i0, j, z, di, h, color):
    """Placa flotante sobre la mampara derecha (plano j = const), para carteles. Devuelve los puntos para SVG."""
    return [E.p(i0, j, z), E.p(i0 + di, j, z), E.p(i0 + di, j, z + h), E.p(i0, j, z + h)]


def torre_papeles(E, i, j, hojas, desbordada=False, z=13):
    """Pila de hojas en la esquina del escritorio (capa 'frente'): crece con el contexto de la sesión. Si está
    desbordada, caen hojas sueltas al piso junto al escritorio. Devuelve (z_tope, puntos de la cara superior)
    para que la capa viva pinte la hoja de arriba parpadeando."""
    di, dj, h = 0.45, 0.4, 0.9
    for n in range(hojas):
        E.caja(i + (0.03 if n % 3 == 1 else 0), j + (0.03 if n % 3 == 2 else 0), z + n * h, di, dj, h,
               '#fbfaf6' if n % 2 == 0 else '#ece6d8', capa='frente', contorno=False)
    if desbordada:
        E.caja(i + 0.95, j + 0.3, 0, 0.55, 0.45, 0.35, '#fbfaf6', capa='frente', contorno=False)      # hojas en el piso
        E.caja(i + 0.5, j + 0.9, 0, 0.5, 0.45, 0.35, '#ece6d8', capa='frente', contorno=False)
        E.caja(i + 1.2, j + 0.95, 0, 0.5, 0.4, 0.35, '#fbfaf6', capa='frente', contorno=False)
    zt = z + hojas * h
    return zt, [E.p(i, j, zt), E.p(i + di, j, zt), E.p(i + di, j + dj, zt), E.p(i, j + dj, zt)]


def sobre(E, i, j, z=14, n=1):
    """Sobre cerrado sobre el escritorio (capa 'frente'): hay notas en ideas/. Con más de una, dos sobres apilados.
    Devuelve el punto de pantalla sobre el sobre de arriba, para la cuenta en SVG."""
    for k in range(min(2, n)):
        E.caja(i + k * 0.06, j - k * 0.04, z + k * 0.5, 0.5, 0.34, 0.5, '#fbfaf6', capa='frente')
    zt = z + min(2, n) * 0.5
    E.caja(i + 0.2, j + 0.12, zt, 0.1, 0.1, 0.15, '#d64545', capa='frente', contorno=False)   # sello
    return E.p(i + 0.25, j + 0.17, zt)


def rotafolio(E, i, j, di=1.3, z0=9, h=15):
    """Rotafolio de pie (capa 'fondo'): tres patas y el pliego blanco mirando al frente (plano j = const).
    Devuelve los puntos del pliego para escribir encima en SVG."""
    E.caja(i + 0.1, j + 0.05, 0, 0.08, 0.08, z0 + h, '#8b5a3c', contorno=False)               # pata izquierda
    E.caja(i + di - 0.18, j + 0.05, 0, 0.08, 0.08, z0 + h, '#8b5a3c', contorno=False)         # pata derecha
    E.caja(i + di / 2 - 0.04, j - 0.35, 0, 0.08, 0.08, z0 + h - 2, '#6f4630', contorno=False)  # pata trasera
    E.caja(i, j, z0, di, 0.1, h, '#fbfaf6')                                                    # pliego
    E.caja(i - 0.04, j, z0 + h, di + 0.08, 0.14, 1.2, '#2b2420', contorno=False)              # pinza de arriba
    E.caja(i + 0.05, j + 0.02, z0 - 1, di - 0.1, 0.18, 1, '#8b5a3c', contorno=False)          # repisa de plumones
    jf = j + 0.1
    return [E.p(i, jf, z0), E.p(i + di, jf, z0), E.p(i + di, jf, z0 + h), E.p(i, jf, z0 + h)]


# ---------- la azotea (piso de ocio) ----------

def caminadora(E, i, j):
    """Caminadora contra la mampara izquierda: banda baja a lo largo de i y consola con pantalla en el extremo bajo."""
    E.caja(i + 0.2, j, 0, 1.8, 0.8, 2.5, '#3a3f47', top='#2b2f36')
    for k in range(5):                                                                            # rayas de la banda
        E.caja(i + 0.45 + k * 0.32, j + 0.1, 2.5, 0.05, 0.6, 0.1, '#5a6270', contorno=False)
    E.caja(i, j + 0.05, 0, 0.2, 0.7, 2.5, '#2b2f36', contorno=False)
    E.caja(i + 0.05, j + 0.1, 2.5, 0.1, 0.1, 11, '#9aa3ad', contorno=False)                       # barras
    E.caja(i + 0.05, j + 0.6, 2.5, 0.1, 0.1, 11, '#9aa3ad', contorno=False)
    E.caja(i, j + 0.05, 13, 0.25, 0.7, 4, '#2b2f36', contorno=False)                              # tablero
    E.cara_izq(i + 0.26, j + 0.15, 14, 0.5, 2.2, '#3be8ff')


def banca_pesas(E, i, j):
    """Banca de press con barra: dos soportes, la barra y un disco en cada punta."""
    E.caja(i + 0.1, j + 0.2, 0, 1.4, 0.45, 4.5, '#2b2f36', top='#c0392b', der='#1d1f24')
    for x in (0.2, 1.2):
        E.caja(i + x, j + 0.12, 4.5, 0.1, 0.1, 6, '#9aa3ad', contorno=False)
    E.caja(i - 0.1, j + 0.15, 10.5, 1.8, 0.07, 0.8, '#c4ccd2', contorno=False)
    for x in (-0.12, 1.62):
        E.caja(i + x, j + 0.05, 8.7, 0.12, 0.28, 4.4, '#2b2420', contorno=False)


def rack_mancuernas(E, i, j):
    """Estante bajo con una fila de mancuernas de colores."""
    E.caja(i, j, 0, 1.2, 0.5, 6, '#4b5563')
    for k, c in enumerate(('#d64545', '#d9a21b', '#2f9e5f', '#2d8fbf')):
        E.caja(i + 0.1 + k * 0.28, j + 0.12, 6, 0.2, 0.26, 1.8, c, contorno=False)


def tele(E, i, j):
    """Tele sobre un mueble bajo, contra la mampara izquierda, con la pantalla encendida mirando a +i."""
    E.caja(i, j, 0, 0.7, 2.4, 6, '#8b5a3c')
    E.caja(i + 0.2, j + 0.3, 6, 0.15, 1.8, 11, '#1d1f24', contorno=False)
    E.cara_izq(i + 0.36, j + 0.38, 7, 1.64, 9, '#3a6fd8')
    E.cara_izq(i + 0.37, j + 0.5, 11, 0.9, 3.5, '#8fbcff')                                        # brillo
    E.cara_izq(i + 0.37, j + 1.5, 8, 0.4, 1.2, '#ffcf4a')


def mesa_pingpong(E, i, j, di=2.4, dj=1.2):
    """Mesa de ping-pong larga en i: cuatro patas, tablero verde, línea central y red."""
    for x in (0.1, di - 0.22):
        for y in (0.1, dj - 0.22):
            E.caja(i + x, j + y, 0, 0.12, 0.12, 6, '#9aa3ad', contorno=False)
    E.caja(i, j, 6, di, dj, 1.2, '#1f7a4d', top='#2f9e5f')
    E.caja(i + 0.05, j + dj / 2 - 0.02, 7.2, di - 0.1, 0.04, 0.05, '#fbfaf6', contorno=False)      # línea central
    E.caja(i + di / 2 - 0.03, j - 0.05, 7.2, 0.06, dj + 0.1, 2.4, '#fbfaf6', contorno=False)       # red


def mesa_juego(E, i, j):
    """Mesa con un tablero de ajedrez encima."""
    E.caja(i, j, 0, 1.4, 0.9, 8, ESCRITORIO)
    E.caja(i + 0.2, j + 0.15, 8, 1.0, 0.6, 0.4, '#fbfaf6', contorno=False)
    for a in range(3):
        for b in range(2):
            if (a + b) % 2:
                E.caja(i + 0.2 + a * 0.333, j + 0.15 + b * 0.3, 8.4, 0.333, 0.3, 0.1, '#2b2420', contorno=False)


def ducha(E, i, j):
    """Regadera contra la mampara izquierda: base, marco de cristal, tubo y cabezal."""
    E.caja(i, j, 0, 1.0, 1.0, 1.5, '#dfe6ea')
    E.caja(i, j, 1.5, 0.08, 1.0, 26, '#cfe3ee', contorno=False)
    for y in (0, 0.92):
        E.caja(i + 0.92, j + y, 1.5, 0.08, 0.08, 26, '#9aa3ad', contorno=False)
    E.caja(i, j, 27.5, 1.0, 1.0, 0.6, '#9aa3ad', contorno=False)
    E.caja(i + 0.12, j + 0.46, 1.5, 0.06, 0.06, 22, '#c4ccd2', contorno=False)
    E.caja(i + 0.12, j + 0.34, 23.5, 0.4, 0.3, 0.9, '#c4ccd2', contorno=False)


def lavabo(E, i, j):
    """Lavabo contra la mampara derecha, con espejo."""
    E.cara_der(i + 0.05, j + 0.02, 13, 1.1, 14, MARCO)
    E.cara_der(i + 0.1, j + 0.03, 14, 1.0, 12, CIELO)
    E.caja(i, j, 0, 1.2, 0.5, 8, '#dfe6ea')
    E.caja(i + 0.15, j + 0.1, 8, 0.9, 0.35, 0.8, '#fbfaf6', contorno=False)
    E.caja(i + 0.55, j + 0.05, 8.8, 0.1, 0.1, 2.5, '#9aa3ad', contorno=False)


def inodoro(E, i, j):
    """Inodoro contra la mampara derecha: tanque, taza y tapa."""
    E.caja(i + 0.1, j + 0.1, 0, 0.6, 0.25, 9, '#fbfaf6')
    E.caja(i + 0.15, j + 0.35, 0, 0.5, 0.55, 5, '#fbfaf6')
    E.caja(i + 0.2, j + 0.4, 5, 0.4, 0.45, 0.6, '#e6eef2', contorno=False)


# ---------- el garaje del sótano ----------

CONCRETO, BLOCK = '#8e9298', '#5f646b'
CONTRACHAPADO, LAMINA = '#c4a06c', '#a9b2ba'
TUBO = '#7d6a58'


def habitacion_sotano(E, alto=44):
    """Garaje: losas de concreto con juntas y manchas de aceite, paredes de block gris oscuro, dos tubos expuestos
    cerca del techo y ventanitas altas a ras de calle (las pone quien arma el piso con `ventanita_izq/der`)."""
    for i in range(E.ni):
        for j in range(E.nj):
            E.piso(i, j, CONCRETO if (i + j) % 2 == 0 else sombra(CONCRETO, 0.94), borde=sombra(CONCRETO, 0.72))
    L = E.capas['fondo']
    for i, j, rx, ry in ((0.3, 3.2, 0.5, 0.35), (0.5, 8.3, 0.4, 0.3), (6.5, 0.4, 0.6, 0.3), (13.4, 0.6, 0.5, 0.3), (6.5, 6.5, 0.5, 0.4), (20.2, 6.5, 0.6, 0.35)):
        if i + rx < E.ni and j + ry < E.nj:                                                  # mancha de aceite en el pasillo
            L.poly([E.p(i - rx, j, 0), E.p(i, j - ry, 0), E.p(i + rx, j, 0), E.p(i, j + ry, 0)], '#4a4d52')
            L.poly([E.p(i - rx / 2, j, 0), E.p(i, j - ry / 2, 0), E.p(i + rx / 2, j, 0), E.p(i, j + ry / 2, 0)], '#3a3d42')
    g = 0.4
    E.caja(-g, -g, 0, g, E.nj + g, alto, BLOCK, top='#70757c', izq='#5f646b', der='#4f545a', contorno=False)    # pared izquierda (i = 0)
    E.caja(0, -g, 0, E.ni, g, alto, BLOCK, top='#70757c', izq='#585d64', der='#464b51', contorno=False)        # pared derecha (j = 0)
    E.cara_izq(0, 0, 0, E.nj, 2.5, '#3d4147')
    E.cara_der(0, 0, 0, E.ni, 2.5, '#363a40')
    for k, z in enumerate(range(5, alto - 1, 5)):                                           # hileras de block con juntas alternadas
        E.cara_izq(0.01, 0, z, E.nj, 0.5, '#4b5056')
        E.cara_der(0, 0.01, z, E.ni, 0.5, '#43474d')
        for q in range(k % 2, int(E.nj * 2), 2):
            E.cara_izq(0.01, q * 0.5, z - 5, 0.04, 5, '#4b5056')
        for q in range(k % 2, int(E.ni * 2), 2):
            E.cara_der(q * 0.5, 0.01, z - 5, 0.04, 5, '#43474d')
    tubos(E, alto)


def tubos(E, alto):
    """Dos tubos expuestos por pared cerca del techo (uno grueso y uno fino) con abrazaderas."""
    for z, gr, color in ((alto - 6, 2.2, TUBO), (alto - 2.6, 1.2, '#9a9fa6')):
        E.caja(0.02, 0, z, 0.32, E.nj, gr, color, contorno=False, top=sombra(color, 1.25), izq=sombra(color, 0.9), der=sombra(color, 0.7))
        E.caja(0, 0.02, z, E.ni, 0.32, gr, color, contorno=False, top=sombra(color, 1.25), izq=sombra(color, 0.9), der=sombra(color, 0.7))
    for q in range(2, int(E.nj) - 1, 4):                                                    # abrazaderas
        E.caja(0.0, q, alto - 6.4, 0.4, 0.12, 3.0, '#3d4147', contorno=False)
    for q in range(2, int(E.ni) - 1, 4):
        E.caja(q, 0.0, alto - 6.4, 0.12, 0.4, 3.0, '#3d4147', contorno=False)


def ventanita_izq(E, j, dj=1.4, z=26, h=8):
    """Ventana alta de sótano en la pared izquierda: marco, vidrio oscuro con un poco de calle y dos barrotes."""
    E.cara_izq(0.02, j, z - 1, dj + 0.2, h + 2, '#2b2f36')
    E.cara_izq(0.03, j + 0.1, z, dj, h, '#1d2a3f')
    E.cara_izq(0.04, j + 0.1, z + h * 0.55, dj, h * 0.45, '#43597a')                       # claridad de la calle
    for k in (0.25, 0.5, 0.75):
        E.cara_izq(0.05, j + 0.1 + dj * k - 0.03, z, 0.06, h, '#9aa0a8')                   # barrotes
    E.cara_izq(0.05, j + 0.1, z - 1.5, dj, 0.7, '#4b5056')                                 # repisa de la ventana


def ventanita_der(E, i, di=1.4, z=26, h=8):
    E.cara_der(i, 0.02, z - 1, di + 0.2, h + 2, '#2b2f36')
    E.cara_der(i + 0.1, 0.03, z, di, h, '#1d2a3f')
    E.cara_der(i + 0.1, 0.04, z + h * 0.55, di, h * 0.45, '#43597a')
    for k in (0.25, 0.5, 0.75):
        E.cara_der(i + 0.1 + di * k - 0.03, 0.05, z, 0.06, h, '#9aa0a8')
    E.cara_der(i + 0.1, 0.05, z - 1.5, di, 0.7, '#4b5056')


def mampara_taller(E, i0, j0, di, dj, alto=13):
    """Mamparas de taller: biombo de contrachapado con vetas y tornillos (lado i = i0) y lámina acanalada (lado j = j0)."""
    g = 0.18
    E.caja(i0, j0, 0, g, dj, alto, CONTRACHAPADO, top='#dcc08e', izq='#b78f58', der='#b08a57')
    E.caja(i0, j0, 0, di, g, alto, LAMINA, top='#cdd4da', izq='#a9b2ba', der='#8e98a1')
    x = i0 + g + 0.01
    for q in range(1, int(dj / 0.9)):                                                       # juntas de los tableros
        E.cara_izq(x, j0 + q * 0.9, 1.5, 0.04, alto - 1.5, '#8f6b3e')
    for z in (3, alto - 3):
        for q in range(int(dj / 0.45)):
            E.pixel(x, j0 + 0.3 + q * 0.45, z, '#5a4326')                                   # tornillos
    y = j0 + g + 0.01
    for q in range(int((di - g) / 0.2)):                                                    # acanaladuras
        E.cara_der(i0 + g + q * 0.2, y, 1.5, 0.1, alto - 1.5, '#c4ccd3')
    E.cara_izq(x, j0 + g, 0, dj - g, 1.5, '#4a3a26')
    E.cara_der(i0 + g, y, 0, di - g, 1.5, '#5c646b')


def banco_trabajo(E, i, j, di=2, dj=1, h=13, monitor=True):
    """Banco de trabajo: tablón sobre caballetes con travesaño (capa 'frente', como el escritorio). Con monitor=True
    lleva monitor, teclado y taza y devuelve el ancla de la pantalla, igual que `escritorio`."""
    for x in (0.12, di - 0.3):
        for y in (0.08, dj - 0.2):
            E.caja(i + x, j + y, 0, 0.18, 0.12, h - 1.5, '#6f4a2a', capa='frente', contorno=False)          # patas del caballete
        E.caja(i + x, j + 0.12, 3.5, 0.18, dj - 0.24, 0.9, '#6f4a2a', capa='frente', contorno=False)        # larguero del caballete
    if di >= dj:                                                                                              # travesaño a lo largo del lado largo
        E.caja(i + 0.3, j + dj / 2 - 0.05, 5.5, di - 0.6, 0.1, 0.9, '#5a3b20', capa='frente', contorno=False)
    else:
        E.caja(i + di / 2 - 0.05, j + 0.3, 5.5, 0.1, dj - 0.6, 0.9, '#5a3b20', capa='frente', contorno=False)
    E.caja(i, j, h - 1.5, di, dj, 1.5, '#a9794a', capa='frente')                                              # tablón
    E.caja(i + 0.1, j + 0.1, h, di - 0.2, dj - 0.2, 1, '#b98a58', capa='frente', contorno=False)
    if not monitor:
        return None
    mi, mj = i + di - 0.4, j + 0.18
    E.caja(mi - 0.15, mj, h + 1, 0.3, 0.1, 2, MONITOR, capa='frente', contorno=False)
    E.caja(mi - 0.4, mj + 0.02, h + 3, 0.8, 0.08, 9, MONITOR, capa='frente', contorno=False)
    E.caja(i + 0.25, j + 0.55, h + 1, 0.9, 0.25, 0.8, '#2b2f36', capa='frente', contorno=False)
    E.caja(i + 0.15, j + 0.15, h + 1, 0.2, 0.2, 3, '#d64545', capa='frente', contorno=False)
    return {'pantalla': (mi - 0.4, mj + 0.02, h + 3, 0.8, 9)}


def foco_pelon(E, i, j, z_techo=40, caida=5):
    """Foco colgando de su cable (capa 'frente'): cable, casquillo y bombilla amarilla. Devuelve el punto de pantalla
    del foco para el resplandor en SVG."""
    L = E.capas['frente']
    x, y = E.p(i, j, z_techo); xf, yf = E.p(i, j, z_techo - caida)
    L.linea(x, y, xf, yf, '#1d1f24')
    xi, yi = int(round(xf)), int(round(yf))
    for dx in (-1, 0, 1):                                                                    # casquillo
        L.put(xi + dx, yi + 1, '#3d4147'); L.put(xi + dx, yi + 2, '#575c63')
    bombilla = ((-1, 3, '#ffe9a0'), (0, 3, '#fff6cf'), (1, 3, '#ffe9a0'),
                (-2, 4, '#ffe9a0'), (-1, 4, '#fff6cf'), (0, 4, '#ffffff'), (1, 4, '#fff6cf'), (2, 4, '#ffe9a0'),
                (-2, 5, '#ffd86b'), (-1, 5, '#ffe9a0'), (0, 5, '#fff6cf'), (1, 5, '#ffe9a0'), (2, 5, '#ffd86b'),
                (-1, 6, '#ffd86b'), (0, 6, '#ffd86b'), (1, 6, '#ffd86b'))
    for dx, dy, c in bombilla:
        L.put(xi + dx, yi + dy, c)
    return xi, yi + 5


def cable_focos(E, i0, j0, di, dj, focos, z=40, tendido=True):
    """Focos repartidos de (i0, j0) a (i0+di, j0+dj) a la altura z. Con tendido=True, unidos por un cable a lo largo
    (junto a una pared); con False, cada foco cuelga solo de su cable (sobre los pasillos del centro, donde un cable
    largo se veía como una raya suelta cruzando el piso). Devuelve los puntos de pantalla de los focos."""
    if tendido:
        xa, ya = E.p(i0, j0, z); xb, yb = E.p(i0 + di, j0 + dj, z)
        E.capas['frente'].linea(xa, ya, xb, yb, '#1d1f24')
    pts = []
    for k in range(focos):
        t = (k + 0.5) / focos
        pts.append(foco_pelon(E, i0 + di * t, j0 + dj * t, z))
    return pts


def guirnalda(E, plano, a, b, z=20, caida=3.5, tramos=3):
    """Guirnalda de foquitos de colores en la pared, de `a` a `b` (a lo largo de j si plano='izq', de i si 'der'),
    en festones. Va en la capa de fondo, sobre la pared."""
    L = E.capas['fondo']
    colores = ('#ff6b6b', '#ffd86b', '#6bd6ff', '#9be37a')
    paso = (b - a) / tramos
    n = 0
    for t in range(tramos):
        for q in range(0, 13):
            u = q / 12
            x = a + t * paso + u * paso
            zz = z - caida * 4 * u * (1 - u)
            pt = E.p(0.04, x, zz) if plano == 'izq' else E.p(x, 0.04, zz)
            L.put(int(pt[0]), int(pt[1]), '#1d1f24')
            if q % 3 == 1:
                c = colores[n % len(colores)]; n += 1
                L.put(int(pt[0]), int(pt[1]) + 1, c); L.put(int(pt[0]) + 1, int(pt[1]) + 1, c)


def tablero_herramientas(E, i, j, dj=2.4, h=24):
    """Tablero de herramientas (pegboard) de pie contra la mampara izquierda: bastidor de madera, tablero con
    agujeros y siluetas de martillo, llave inglesa, serrucho y pinzas colgadas."""
    E.caja(i, j, 0, 0.12, dj, h, '#a98259', top='#c29a6c', izq='#a98259', der='#8f6b46')
    x = i + 0.13
    E.cara_izq(x, j + 0.08, 1.5, dj - 0.16, h - 3, '#c9a77a')
    for a in range(int((dj - 0.4) / 0.3)):                                                   # agujeros
        for b in range(int((h - 5) / 3)):
            E.pixel(x + 0.01, j + 0.3 + a * 0.3, 3.5 + b * 3, '#8f6b46')
    E.cara_izq(x + 0.01, j + 0.35, 14, 0.12, 8, '#4a4d52'); E.cara_izq(x + 0.01, j + 0.23, 20, 0.36, 2.5, '#6a6f76')   # martillo
    E.cara_izq(x + 0.01, j + 0.85, 12, 0.1, 10, '#9aa0a8'); E.cara_izq(x + 0.01, j + 0.8, 21.5, 0.2, 2, '#9aa0a8')    # llave
    E.cara_izq(x + 0.01, j + 1.25, 14, 0.7, 5, '#b8bec5'); E.cara_izq(x + 0.01, j + 1.25, 11.5, 0.2, 2.5, '#8b5a3c')  # serrucho
    E.cara_izq(x + 0.01, j + 2.0, 13, 0.1, 6, '#d64545'); E.cara_izq(x + 0.01, j + 2.15, 13, 0.1, 6, '#d64545')     # pinzas


def taza_cafe(E, i, j, z):
    """Taza de café humeante sobre una superficie a altura z."""
    E.caja(i, j, z, 0.28, 0.28, 2.6, '#fbfaf6', contorno=False)
    E.caja(i + 0.04, j + 0.04, z + 2.6, 0.2, 0.2, 0.2, '#4a2c14', contorno=False)
    E.caja(i + 0.26, j + 0.1, z + 0.8, 0.1, 0.1, 1.2, '#fbfaf6', contorno=False)           # asa
    E.pixel(i + 0.12, j + 0.12, z + 4.4, '#e7e7e7'); E.pixel(i + 0.16, j + 0.1, z + 5.6, '#d0d0d0')   # vapor


def botella_ron(E, i, j, z):
    """Botella de ron: cuerpo ámbar, cuello, tapón y etiqueta."""
    E.caja(i, j, z, 0.3, 0.3, 5.5, '#6b3a1a', top='#8a5226', contorno=False)
    E.caja(i + 0.08, j + 0.08, z + 5.5, 0.14, 0.14, 2.4, '#6b3a1a', contorno=False)
    E.caja(i + 0.06, j + 0.06, z + 7.9, 0.18, 0.18, 0.8, '#c0392b', contorno=False)
    E.cara_izq(i + 0.31, j + 0.05, z + 1.5, 0.2, 2.4, '#f1e3b8')                            # etiqueta
    E.cara_der(i + 0.05, j + 0.31, z + 1.5, 0.2, 2.4, '#f1e3b8')


def sillon_viejo(E, i, j):
    """Sillón individual gastado: tela café con remiendo, brazos y un cojín hundido."""
    cafe = '#7a4e3a'
    E.caja(i, j, 0, 1.2, 1.0, 6, cafe)
    E.caja(i, j, 6, 1.2, 0.25, 8, sombra(cafe, 0.92), contorno=False)                       # respaldo
    E.caja(i, j, 6, 0.25, 1.0, 4, sombra(cafe, 0.88), contorno=False)                       # brazos
    E.caja(i + 0.95, j, 6, 0.25, 1.0, 4, sombra(cafe, 0.88), contorno=False)
    E.caja(i + 0.25, j + 0.25, 6, 0.7, 0.75, 1.2, '#9a6a50', contorno=False)               # cojín
    E.cara_izq(i + 1.21, j + 0.2, 2, 0.3, 2, '#b08a57')                                      # remiendo
    E.cara_der(i + 0.3, j + 1.01, 3, 0.4, 2, '#5a3b2a')


def boiler(E, i, j):
    """Calentador de agua: tanque cilíndrico (caja), tapa, manómetro, llave y tubos."""
    E.caja(i + 0.1, j + 0.1, 0, 0.8, 0.8, 22, '#b9c2c9', top='#d4dadf', izq='#b9c2c9', der='#8f99a1')
    E.caja(i + 0.1, j + 0.1, 22, 0.8, 0.8, 1.2, '#4b5056', contorno=False)
    E.caja(i + 0.1, j + 0.1, 0, 0.8, 0.8, 2, '#4b5056', contorno=False)                    # base
    E.cara_izq(i + 0.91, j + 0.3, 14, 0.4, 3.5, '#2b2f36'); E.cara_izq(i + 0.92, j + 0.38, 15, 0.24, 1.6, '#ffcf4a')   # manómetro
    E.caja(i + 0.55, j + 0.45, 23.2, 0.14, 0.14, 5, TUBO, contorno=False)                   # tubo de salida
    E.caja(i + 0.15, j + 0.15, 7, 0.2, 0.2, 0.2, '#d64545', contorno=False)
    E.pixel(i + 0.92, j + 0.55, 8, '#d64545'); E.pixel(i + 0.92, j + 0.55, 9, '#d64545')   # llave


def estante_cajas(E, i, j, di=1.8):
    """Estante metálico de tres repisas con cajas de cartón."""
    for x in (0.0, di - 0.1):
        E.caja(i + x, j, 0, 0.1, 0.55, 26, '#4b5056', contorno=False)
    for z in (1, 9.5, 18):
        E.caja(i, j, z, di, 0.55, 0.8, '#6a6f76', contorno=False)
    cajas = ((0.15, 1.8, '#c9a06a'), (0.8, 1.2, '#b88a54'), (1.2, 1.6, '#c9a06a'), (0.2, 1.5, '#d8b27a'), (0.9, 1.9, '#c9a06a'), (0.3, 1.7, '#b88a54'))
    for q, (x, w, c) in enumerate(cajas):
        z = (1.8, 10.3, 18.8)[q // 2]
        if x + 0.5 <= di:
            E.caja(i + x, j + 0.07, z, min(0.55, di - x - 0.05), 0.4, 4 + (q % 3), c, top=sombra(c, 1.12), contorno=True)


def neon_svg(E, texto, i, j0, z, color='#ff3df0', tam=4.2):
    """Letrero de neón en la pared izquierda (plano i = const): caja negra, borde y texto que brillan en `color`.
    Devuelve el SVG y su ancho en celdas."""
    ancho = (len(texto) * tam * 1.05 + 6) / 16
    j1 = j0 + ancho
    alto = tam + 5
    pts = [E.p(i, j0, z), E.p(i, j1, z), E.p(i, j1, z + alto), E.p(i, j0, z + alto)]
    x, y = E.p(i, j1 - 3 / 16, z + 2.4)
    t = f'transform="translate({x:.1f},{y:.1f}) matrix(1,-0.5,0,1,0,0)" font-family="Press Start 2P,monospace" font-size="{tam}"'
    pts_l = ' '.join(f'{px:.1f},{py:.1f}' for px, py in pts)
    return (E.poligono_svg(pts, '#14101c')
            + f'<polygon points="{pts_l}" fill="none" stroke="{color}" stroke-width="1.2" opacity=".35"/>'
            + f'<polygon points="{pts_l}" fill="none" stroke="{color}" stroke-width=".5"/>'
            + f'<text {t} fill="none" stroke="{color}" stroke-width="1.4" opacity=".4">{texto}</text>'
            + f'<text {t} fill="#ffffff" stroke="{color}" stroke-width=".25">{texto}</text>'), ancho
