# Copy of the author's avatar drawing from another project of theirs (copied 2026-10-27 so this folder runs on its own).
"""Avatares pixel 32x32 de los visionarios: retrato (base) y chibi kawaii (cuando interactúan).
Deterministas: mismos rasgos para el mismo id. Uso: import avatar32; avatar32.retrato(id) / avatar32.chibi(id, "feliz")."""
import csv, json, os, random
YT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# Only change from the original: the two CSVs of the original project are optional here (this folder does not ship them).
# Everything that `sprites.py` uses (SKIN, HAIR, Lienzo, pelo_*, heroe_chibi) does not need them.
try:
    P = {r["id"].zfill(2): r for r in csv.DictReader(open(f"{YT}/ideas/angular-quest/personas.csv", encoding='utf-8'))}
    CAST = {r["id"]: r for r in csv.DictReader(open(f"{YT}/visionarios/roster.csv", encoding='utf-8'))}
except OSError:
    P, CAST = {}, {}
VOTO_COL = {"RESCATE": "#ffcf4a", "SAAS": "#5fd068", "JUEGO": "#3ee6e0", "SIN_TECLADO": "#b48cff", "CLON": "#ef5350"}
SKIN = [("#f6d3b3", "#e0b48e"), ("#e8b98f", "#cf9a6d"), ("#c98e62", "#a87248"), ("#a26b44", "#84532f"), ("#7a4e30", "#5f3a22")]
HAIR = [("#1b1410", "#3a2a20"), ("#3b2516", "#5a3a22"), ("#5a3a22", "#7b5233"), ("#7b4a2a", "#9c6238"), ("#c9a05a", "#e0bf7a")]
GRIS = ("#8d8d8d", "#b5b5b5")
OUT = "#120d0a"

def dark(hexc, f=0.7):
    r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (int(r * f), int(g * f), int(b * f))

def rasgos(nid, actual=True):
    """actual=False dibuja la identidad de la ronda 1 (antes del bautizo): solo Lucía (#12) era mujer."""
    p, c = P[nid], CAST[nid]
    rng = random.Random(int(nid) * 7919)
    mujer = c["genero"] == "mujer" if actual else nid == "12"
    edad = int(p["edad"])
    pelo = GRIS if edad >= 40 and rng.random() < 0.55 else rng.choice(HAIR[:4] if rng.random() < 0.9 else HAIR)
    estilos = ["largo", "coleta", "chongo", "rizado_largo", "melena"] if mujer else ["corto", "rizado", "lateral", "rapado", "afro", "copete"]
    return dict(mujer=mujer, skin=rng.choice(SKIN), pelo=pelo, estilo=rng.choice(estilos),
                lentes=p["estilo"] == "Leer docs", audif=int(p["gamer"]) >= 4,
                barba=(not mujer and edad >= 28 and rng.random() < 0.35), bigote=(not mujer and rng.random() < 0.15),
                aretes=mujer and rng.random() < 0.6, camisa=VOTO_COL[c["voto_r1"]], boca=rng.choice(["sonrisa", "neutra", "sonrisa"]))

class Lienzo:
    def __init__(s): s.g = [[None] * 32 for _ in range(32)]
    def put(s, x, y, c):
        if 0 <= x < 32 and 0 <= y < 32 and c: s.g[y][x] = c
    def rect(s, x0, y0, x1, y1, c):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1): s.put(x, y, c)
    def elipse(s, cx, cy, rx, ry, c, sombra=None, desde=None):
        for y in range(32):
            for x in range(32):
                if ((x + .5 - cx) / rx) ** 2 + ((y + .5 - cy) / ry) ** 2 <= 1:
                    s.put(x, y, sombra if sombra and desde is not None and x >= desde else c)
    def contorno(s):
        g2 = [row[:] for row in s.g]
        for y in range(32):
            for x in range(32):
                if s.g[y][x] is None and any(0 <= x + dx < 32 and 0 <= y + dy < 32 and s.g[y + dy][x + dx] not in (None, OUT)
                                             for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    g2[y][x] = OUT
        s.g = g2
    def svg(s):
        r = "".join(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{c}"/>' for y, row in enumerate(s.g) for x, c in enumerate(row) if c)
        return f'<svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">{r}</svg>'

def pelo_detras(L, t, cx, top, ancho, largo_hasta):
    h, hs = t["pelo"]
    if t["estilo"] in ("largo", "rizado_largo", "melena"):
        L.rect(cx - ancho - 1, top + 5, cx + ancho, largo_hasta, h)
        if t["estilo"] == "rizado_largo":
            for y in range(top + 6, largo_hasta, 2): L.put(cx - ancho - 2, y, h); L.put(cx + ancho + 1, y, h)

def pelo_encima(L, t, cx, top, ancho, frente):
    h, hs = t["pelo"]; e = t["estilo"]
    if e == "rapado":
        L.rect(cx - ancho + 1, top + 1, cx + ancho - 2, top + 2, hs); return
    L.elipse(cx, top + 4, ancho + .5, 4.2, h)                      # casquete
    L.rect(cx - ancho, top + 3, cx + ancho - 1, frente, h)
    for x in range(cx - ancho + 2, cx + ancho - 2, 3): L.put(x, top + 1, hs)   # brillo
    if e == "lateral": L.rect(cx - ancho, frente + 1, cx - 1, frente + 1, h)
    if e == "copete": L.rect(cx - 3, top - 1, cx + 2, top, h); L.put(cx, top - 2, h)
    if e in ("rizado", "afro", "rizado_largo"):
        for x in range(cx - ancho - 1, cx + ancho + 1, 2): L.put(x, top + 1 - (x % 2), h)
        if e == "afro": L.elipse(cx, top + 4, ancho + 2.5, 6, h); L.rect(cx - ancho, top + 3, cx + ancho - 1, frente, h)
    if e == "coleta": L.rect(cx + ancho, top + 4, cx + ancho + 2, top + 12, h); L.put(cx + ancho + 1, top + 13, h)
    if e == "chongo": L.elipse(cx, top - 1, 3.2, 2.6, h)
    if e in ("largo", "melena", "rizado_largo"): L.rect(cx - ancho, top + 3, cx - ancho + 1, frente + 6, h); L.rect(cx + ancho - 2, top + 3, cx + ancho - 1, frente + 6, h)

def accesorios(L, t, cx, ojos_y, ojo_dx, oreja_y, ancho, top):
    if t["lentes"]:
        for ox in (cx - ojo_dx - 1, cx + ojo_dx - 3):
            L.rect(ox, ojos_y - 1, ox + 3, ojos_y - 1, "#2b2b2b"); L.rect(ox, ojos_y + 2, ox + 3, ojos_y + 2, "#2b2b2b")
            L.put(ox, ojos_y, "#2b2b2b"); L.put(ox, ojos_y + 1, "#2b2b2b"); L.put(ox + 3, ojos_y, "#2b2b2b"); L.put(ox + 3, ojos_y + 1, "#2b2b2b")
        L.rect(cx - 1, ojos_y, cx, ojos_y, "#2b2b2b")
    if t["audif"]:
        for x in range(cx - ancho + 1, cx + ancho - 1): L.put(x, top - 1, "#d8dee0")
        L.put(cx - ancho, top, "#d8dee0"); L.put(cx + ancho - 1, top, "#d8dee0")
        for y in range(top + 1, oreja_y): L.put(cx - ancho - 1, y, "#d8dee0"); L.put(cx + ancho, y, "#d8dee0")
        L.rect(cx - ancho - 2, oreja_y - 1, cx - ancho, oreja_y + 2, "#ef5350"); L.rect(cx + ancho - 1, oreja_y - 1, cx + ancho + 1, oreja_y + 2, "#ef5350")
    if t["aretes"] and not t["audif"]:
        L.put(cx - ancho - 1, oreja_y + 3, "#ffcf4a"); L.put(cx + ancho, oreja_y + 3, "#ffcf4a")

def retrato(nid, actual=True):
    t, L = rasgos(nid, actual), Lienzo(); sk, sks = t["skin"]; cx = 16
    pelo_detras(L, t, cx, 5, 7, 27)
    L.rect(4, 26, 27, 31, t["camisa"]); L.rect(4, 26, 6, 31, dark(t["camisa"])); L.rect(25, 26, 27, 31, dark(t["camisa"]))
    L.rect(13, 21, 18, 26, sks); L.put(15, 27, sks); L.put(16, 27, sks)                     # cuello
    L.elipse(cx, 14.5, 7, 8.5, sk, sks, desde=20)                                          # cabeza
    L.rect(8, 14, 8, 16, sk); L.rect(23, 14, 23, 16, sks)                                  # orejas
    pelo_encima(L, t, cx, 5, 7, 9)
    for ox in (12, 18):                                                                    # ojos
        L.put(ox, 14, "#ffffff"); L.put(ox + 1, 14, "#1b1b1b"); L.put(ox, 15, "#ffffff"); L.put(ox + 1, 15, "#1b1b1b")
        L.rect(ox - 1, 12, ox + 1, 12, dark(t["pelo"][0], .9))                              # cejas
        if t["mujer"]: L.put(ox + 2 if ox == 18 else ox - 1, 13, "#1b1b1b")                # pestañas
    L.put(16, 17, sks); L.put(15, 18, sks)                                                 # nariz
    if t["boca"] == "sonrisa": L.rect(14, 20, 17, 20, "#7a3b2e"); L.put(13, 19, "#7a3b2e"); L.put(18, 19, "#7a3b2e")
    else: L.rect(14, 20, 17, 20, "#7a3b2e")
    if t["barba"]:
        for y in range(19, 23):
            for x in range(10, 22):
                if L.g[y][x] in (sk, sks) and not (y == 20 and 14 <= x <= 17): L.put(x, y, t["pelo"][0])
    if t["bigote"]: L.rect(13, 19, 18, 19, t["pelo"][0])
    if t["mujer"]: L.put(11, 18, "#f2a0a0"); L.put(20, 18, "#e08a8a")                       # mejillas
    accesorios(L, t, cx, 14, 4, 13, 7, 5)
    L.contorno(); return L.svg()

def chibi(nid, gesto="feliz", actual=True):
    t, L = rasgos(nid, actual), Lienzo(); sk, sks = t["skin"]; cx = 16
    pelo_detras(L, t, cx, 2, 10, 25)
    L.rect(11, 25, 20, 30, t["camisa"]); L.rect(9, 27, 10, 29, sk); L.rect(21, 27, 22, 29, sk)   # cuerpito y manos
    L.rect(12, 31, 14, 31, "#2b2b2b"); L.rect(17, 31, 19, 31, "#2b2b2b")                          # pies
    L.elipse(cx, 13.5, 10, 10.5, sk, sks, desde=24)
    pelo_encima(L, t, cx, 2, 10, 7)
    for ox in (9, 19):                                                                      # ojos grandes
        if gesto == "feliz":
            L.put(ox, 14, "#1b1b1b"); L.put(ox + 3, 14, "#1b1b1b"); L.rect(ox + 1, 13, ox + 2, 13, "#1b1b1b")
        else:
            L.rect(ox, 12, ox + 3, 16, "#1b1b1b"); L.put(ox + 1, 13, "#ffffff"); L.put(ox + 2, 13, "#ffffff"); L.put(ox + 2, 15, "#ffffff")
            if gesto == "pensativo": L.rect(ox, 12, ox + 3, 12, sk)
    L.rect(7, 18, 9, 18, "#f6a2b0"); L.rect(23, 18, 25, 18, "#f6a2b0")                     # rubor
    if gesto == "pensativo":                                                            # nube de "..."
        for x, y in ((25, 4), (27, 3), (29, 2)): L.put(x, y, "#eef3f1")
    if gesto == "sorprendido": L.rect(15, 19, 16, 20, "#7a3b2e")
    elif gesto == "pensativo": L.rect(15, 19, 17, 19, "#7a3b2e"); L.put(22, 21, sk); L.put(22, 20, sk)
    else: L.rect(14, 19, 17, 19, "#7a3b2e"); L.put(13, 18, "#7a3b2e"); L.put(18, 18, "#7a3b2e"); L.rect(15, 20, 16, 20, "#e8707a")
    if t["lentes"]:
        for ox in (8, 18): L.rect(ox, 11, ox + 5, 11, "#2b2b2b"); L.rect(ox, 17, ox + 5, 17, "#2b2b2b"); L.rect(ox, 11, ox, 17, "#2b2b2b"); L.rect(ox + 5, 11, ox + 5, 17, "#2b2b2b")
    if t["audif"]:
        for x in range(8, 24): L.put(x, 1, "#d8dee0")
        L.rect(4, 11, 6, 16, "#ef5350"); L.rect(25, 11, 27, 16, "#ef5350"); L.rect(6, 2, 7, 10, "#d8dee0"); L.rect(24, 2, 25, 10, "#d8dee0")
    L.contorno(); return L.svg()

GESTOS = ("feliz", "sorprendido", "pensativo")
if __name__ == "__main__":   # exporta los SVG de los 50: retrato y chibi en cada gesto
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "svg")
    os.makedirs(out, exist_ok=True)
    for nid in sorted(CAST):
        open(f"{out}/{nid}-retrato.svg", "w", encoding='utf-8').write(retrato(nid))
        for g in GESTOS: open(f"{out}/{nid}-chibi-{g}.svg", "w", encoding='utf-8').write(chibi(nid, g))
    print("ok", len(os.listdir(out)), "svg")

def heroe_chibi(gesto="feliz", microfono=True):
    """El héroe del canal en chibi: pelo negro rizado, túnica verde, escudo rojo con la "A" y micrófono."""
    L = Lienzo(); sk, sks = SKIN[1]; cx = 16; h, hs = ("#1b1410", "#3a2a20")
    L.rect(11, 25, 20, 30, "#3f9b4a"); L.rect(11, 27, 20, 27, "#6b4a2a")                   # túnica y cinturón
    L.rect(12, 31, 14, 31, "#5a3a22"); L.rect(17, 31, 19, 31, "#5a3a22")                   # botas
    L.rect(4, 23, 9, 30, "#c0392b"); L.rect(5, 24, 8, 29, "#e04a3a")                       # escudo
    for x, y in ((6, 25), (7, 25), (5, 26), (8, 26), (5, 27), (6, 27), (7, 27), (8, 27), (5, 28), (8, 28)): L.put(x, y, "#f4f1e8")   # "A"
    L.elipse(cx, 13.5, 10, 10.5, sk, sks, desde=24)
    L.elipse(cx, 6, 10.5, 4.6, h)                                                           # pelo rizado
    L.rect(6, 5, 25, 8, h)
    for x in range(5, 27, 2): L.put(x, 2 + (x % 4 == 1), h); L.put(x, 9, h)
    for y in range(9, 17, 2): L.put(5, y, h); L.put(26, y, h)
    for ox in (9, 19):
        if gesto == "feliz":
            L.put(ox, 14, "#1b1b1b"); L.put(ox + 3, 14, "#1b1b1b"); L.rect(ox + 1, 13, ox + 2, 13, "#1b1b1b")
        else:
            L.rect(ox, 12, ox + 3, 16, "#1b1b1b"); L.put(ox + 1, 13, "#ffffff"); L.put(ox + 2, 13, "#ffffff"); L.put(ox + 2, 15, "#ffffff")
    L.rect(7, 18, 9, 18, "#f6a2b0"); L.rect(23, 18, 25, 18, "#f6a2b0")
    L.rect(14, 19, 17, 19, "#7a3b2e"); L.put(13, 18, "#7a3b2e"); L.put(18, 18, "#7a3b2e")
    if microfono:
        L.rect(21, 27, 22, 29, sk)                                                          # mano
        L.rect(23, 22, 23, 28, "#5f6b70")                                                   # mango
        L.rect(22, 19, 25, 22, "#1b1b1b"); L.rect(23, 20, 24, 21, "#3a3a3a")                # cabeza del micro
    L.contorno(); return L.svg()
