"""Sprites pixel de la oficina: el héroe (la sesión principal), un chibi por tipo de agente y el escritorio.

Reutiliza el dibujo de avatares del autor, de otro proyecto suyo, del que `avatar32.py` (en esta
misma carpeta) es una copia: mismo lienzo 32x32, mismas paletas, mismo contorno. El aspecto de cada agente es determinista: sale del nombre de su tipo.
"""
import hashlib
import random

import avatar32 as A

# Camisa por familia de agente: colores de la marca Pixel Hero y afines, todos distinguibles entre sí
CAMISA = {
    'nestjs-backend-specialist': '#e8622c', 'angular-specialist': '#ff4d5e', 'tailwind-ui-specialist': '#38bdf8',
    'ionic-mobile-specialist': '#4f8ff7', 'typeorm-postgres-docker-specialist': '#3be8ff', 'qa-testing-specialist': '#5fd068',
    'security-specialist': '#ffcf4a', 'architecture-expert': '#b48cff', 'pm-orchestrator': '#f6a2b0',
    'devops-deployment-specialist': '#8fa3a0', 'n8n-automation-specialist': '#ff6d5a', 'Explore': '#9ad3a1',
    'Plan': '#c9b8ff', 'general-purpose': '#d8dee0', 'claude-code-guide': '#eaf2f0',
}
LENTES = {'qa-testing-specialist', 'security-specialist', 'architecture-expert', 'claude-code-guide'}
AUDIF = {'devops-deployment-specialist', 'n8n-automation-specialist'}


def corto(tipo):
    """Nombre corto para la etiqueta bajo el sprite."""
    t = tipo.replace('-specialist', '').replace('-expert', '').replace('-deployment', '').replace('-automation', '')
    return {'typeorm-postgres-docker': 'typeorm', 'general-purpose': 'general', 'claude-code-guide': 'guía'}.get(t, t)


def _rasgos(tipo):
    h = int(hashlib.md5(tipo.encode()).hexdigest(), 16)
    rng = random.Random(h)
    mujer = rng.random() < 0.45
    estilos = ['largo', 'coleta', 'chongo', 'rizado_largo', 'melena'] if mujer else ['corto', 'rizado', 'lateral', 'rapado', 'afro', 'copete']
    camisa = CAMISA.get(tipo) or '#%06x' % (h & 0xffffff | 0x404040)
    return dict(mujer=mujer, skin=rng.choice(A.SKIN), pelo=rng.choice(A.HAIR), estilo=rng.choice(estilos),
                lentes=tipo in LENTES, audif=tipo in AUDIF, barba=(not mujer and rng.random() < 0.3),
                bigote=False, aretes=mujer and rng.random() < 0.5, camisa=camisa, boca='sonrisa')


def agente(tipo, gesto='feliz'):
    """Chibi 32x32 del agente, en SVG. gesto: feliz (trabaja) · pensativo (espera) · sorprendido."""
    t, L = _rasgos(tipo), A.Lienzo()
    sk, sks = t['skin']
    cx = 16
    A.pelo_detras(L, t, cx, 2, 10, 25)
    L.rect(11, 25, 20, 30, t['camisa']); L.rect(9, 27, 10, 29, sk); L.rect(21, 27, 22, 29, sk)
    L.rect(12, 31, 14, 31, '#2b2b2b'); L.rect(17, 31, 19, 31, '#2b2b2b')
    L.elipse(cx, 13.5, 10, 10.5, sk, sks, desde=24)
    A.pelo_encima(L, t, cx, 2, 10, 7)
    for ox in (9, 19):
        if gesto == 'feliz':
            L.put(ox, 14, '#1b1b1b'); L.put(ox + 3, 14, '#1b1b1b'); L.rect(ox + 1, 13, ox + 2, 13, '#1b1b1b')
        else:
            L.rect(ox, 12, ox + 3, 16, '#1b1b1b'); L.put(ox + 1, 13, '#ffffff'); L.put(ox + 2, 13, '#ffffff'); L.put(ox + 2, 15, '#ffffff')
            if gesto == 'pensativo':
                L.rect(ox, 12, ox + 3, 12, sk)
    L.rect(7, 18, 9, 18, '#f6a2b0'); L.rect(23, 18, 25, 18, '#f6a2b0')
    if gesto == 'pensativo':
        L.rect(15, 19, 17, 19, '#7a3b2e')
    elif gesto == 'sorprendido':
        L.rect(15, 19, 16, 20, '#7a3b2e')
    else:
        L.rect(14, 19, 17, 19, '#7a3b2e'); L.put(13, 18, '#7a3b2e'); L.put(18, 18, '#7a3b2e'); L.rect(15, 20, 16, 20, '#e8707a')
    if t['lentes']:
        for ox in (8, 18):
            L.rect(ox, 11, ox + 5, 11, '#2b2b2b'); L.rect(ox, 17, ox + 5, 17, '#2b2b2b'); L.rect(ox, 11, ox, 17, '#2b2b2b'); L.rect(ox + 5, 11, ox + 5, 17, '#2b2b2b')
    if t['audif']:
        for x in range(8, 24):
            L.put(x, 1, '#d8dee0')
        L.rect(4, 11, 6, 16, '#ef5350'); L.rect(25, 11, 27, 16, '#ef5350'); L.rect(6, 2, 7, 10, '#d8dee0'); L.rect(24, 2, 25, 10, '#d8dee0')
    if t['barba']:
        for y in range(19, 23):
            for x in range(9, 23):
                if L.g[y][x] in (sk, sks) and not (y in (19, 20) and 13 <= x <= 18):
                    L.put(x, y, t['pelo'][0])
    L.contorno()
    return _cuerpo(L)


def heroe(gesto='feliz'):
    """El héroe del canal: la sesión principal de cada producto. Sin micrófono: aquí trabaja."""
    return _cuerpo_svg(A.heroe_chibi(gesto, microfono=False))


def _cuerpo(L):
    return ''.join(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{c}"/>' for y, row in enumerate(L.g) for x, c in enumerate(row) if c)


def _cuerpo_svg(svg):
    return svg[svg.index('>') + 1:-6]


def escritorio(pantalla):
    """Escritorio con monitor, en una cuadrícula 48x28. `pantalla`: color de la pantalla (estado de la sesión)."""
    r = []

    def rect(x0, y0, x1, y1, c):
        r.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0 + 1}" height="{y1 - y0 + 1}" fill="{c}"/>')

    rect(2, 16, 45, 18, '#8a5a2b'); rect(2, 19, 45, 20, '#6b4320')      # tablero y canto
    rect(4, 21, 6, 27, '#5a3a22'); rect(41, 21, 43, 27, '#5a3a22')       # patas
    rect(18, 12, 29, 15, '#2f3b4a'); rect(22, 14, 25, 15, '#1d2630')     # base del monitor
    rect(14, 1, 33, 13, '#2f3b4a')                                       # marco
    rect(15, 2, 32, 11, pantalla)                                        # pantalla
    rect(16, 3, 24, 3, '#eaf2f0'); rect(16, 5, 28, 5, '#8fa3a0'); rect(16, 7, 22, 7, '#8fa3a0'); rect(16, 9, 26, 9, '#8fa3a0')  # "código"
    rect(36, 12, 44, 15, '#eaf2f0'); rect(37, 13, 43, 14, '#5fd068')     # cuaderno
    rect(5, 10, 9, 15, '#1d2630'); rect(6, 8, 8, 9, '#3be8ff')          # taza
    return ''.join(r)
