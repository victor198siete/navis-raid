"""Motor isométrico en pixel art, sin dependencias: proyección 2:1 (celda de 32x16), cubos con tres caras
sombreadas, relleno de polígonos por barrido y salida a PNG (base64) por capas.

Coordenadas: (i, j) son celdas del piso; i crece hacia abajo-derecha y j hacia abajo-izquierda; z sube.
Las paredes del fondo están en i = 0 (izquierda) y j = 0 (derecha). Cada pieza se dibuja en una capa:
'fondo' (piso, paredes, muebles detrás de los asientos) o 'frente' (muebles delante de los asientos), para
que los personajes, que van en SVG encima, queden entre las dos capas.
"""
import base64
import struct
import zlib

TW, TH = 32, 16          # celda isométrica en pixeles


def hex_rgb(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def sombra(c, f):
    r, g, b = hex_rgb(c)
    return '#%02x%02x%02x' % (min(255, int(r * f)), min(255, int(g * f)), min(255, int(b * f)))


class Lienzo:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.g = [[None] * w for _ in range(h)]

    def put(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h and c:
            self.g[y][x] = c

    def poly(self, pts, c):
        """Relleno por barrido de un polígono (puntos en pixeles, flotantes). Regla par-impar en centros de pixel."""
        ys = [p[1] for p in pts]
        n = len(pts)
        for y in range(max(0, int(min(ys))), min(self.h, int(max(ys)) + 1)):
            yc = y + 0.5
            xs = []
            for k in range(n):
                (x0, y0), (x1, y1) = pts[k], pts[(k + 1) % n]
                if (y0 <= yc < y1) or (y1 <= yc < y0):
                    xs.append(x0 + (yc - y0) * (x1 - x0) / (y1 - y0))
            xs.sort()
            for a, b in zip(xs[::2], xs[1::2]):
                for x in range(max(0, int(a + 0.5)), min(self.w, int(b + 0.5))):
                    self.put(x, y, c)

    def linea(self, x0, y0, x1, y1, c):
        x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            self.put(x0, y0, c)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy; x0 += sx
            if e2 <= dx:
                err += dx; y0 += sy

    def png_b64(self):
        try:
            from PIL import Image
            im = Image.new('RGBA', (self.w, self.h), (0, 0, 0, 0))
            px = im.load()
            for y, row in enumerate(self.g):
                for x, c in enumerate(row):
                    if c:
                        px[x, y] = hex_rgb(c) + (255,)
            import io
            buf = io.BytesIO(); im.save(buf, 'PNG', optimize=True)
            datos = buf.getvalue()
        except ImportError:
            raw = b''.join(b'\x00' + b''.join((bytes(hex_rgb(c)) + b'\xff') if c else b'\x00\x00\x00\x00' for c in row) for row in self.g)

            def chunk(t, d):
                return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
            datos = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', self.w, self.h, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b'')
        return base64.b64encode(datos).decode()


class Escena:
    """Una escena isométrica: dos lienzos (fondo y frente) y la proyección con su origen."""

    def __init__(self, celdas_i, celdas_j, alto_pared=48, margen=8):
        self.ni, self.nj = celdas_i, celdas_j
        self.ox = celdas_j * TW // 2 + margen
        self.oy = alto_pared + margen
        self.w = (celdas_i + celdas_j) * TW // 2 + 2 * margen
        self.h = (celdas_i + celdas_j) * TH // 2 + alto_pared + 2 * margen
        self.capas = {'fondo': Lienzo(self.w, self.h), 'frente': Lienzo(self.w, self.h)}
        self.alto_pared = alto_pared

    def p(self, i, j, z=0):
        return (self.ox + (i - j) * TW / 2, self.oy + (i + j) * TH / 2 - z)

    # --- primitivas ---
    def piso(self, i, j, color, borde=None, capa='fondo'):
        L = self.capas[capa]
        L.poly([self.p(i, j), self.p(i + 1, j), self.p(i + 1, j + 1), self.p(i, j + 1)], color)
        if borde:
            L.linea(*self.p(i + 1, j + 1), *self.p(i, j + 1), borde); L.linea(*self.p(i + 1, j + 1), *self.p(i + 1, j), borde)

    def caja(self, i, j, z, di, dj, h, color, capa='fondo', contorno=True, top=None, izq=None, der=None):
        """Cubo con huella (i..i+di, j..j+dj) desde z hasta z+h. Cara superior clara, izquierda media, derecha oscura."""
        L = self.capas[capa]
        top, izq, der = top or sombra(color, 1.12), izq or color, der or sombra(color, 0.78)
        A, B, C, D = self.p(i, j, z), self.p(i + di, j, z), self.p(i + di, j + dj, z), self.p(i, j + dj, z)
        A2, B2, C2, D2 = self.p(i, j, z + h), self.p(i + di, j, z + h), self.p(i + di, j + dj, z + h), self.p(i, j + dj, z + h)
        L.poly([D, C, C2, D2], izq)      # cara izquierda (frente-izquierda)
        L.poly([C, B, B2, C2], der)      # cara derecha (frente-derecha)
        L.poly([A2, B2, C2, D2], top)
        if contorno:
            o = sombra(color, 0.45)
            L.linea(*D2, *C2, o); L.linea(*C2, *B2, o); L.linea(*C2, *C, o); L.linea(*D2, *D, o); L.linea(*B2, *B, o)
            L.linea(*D, *C, o); L.linea(*C, *B, o)

    def cara_izq(self, i, j, z, dj, h, color, capa='fondo'):
        """Rectángulo plano en la cara izquierda (paralelo a j), p. ej. una ventana o un póster en la pared i=const."""
        L = self.capas[capa]
        L.poly([self.p(i, j, z), self.p(i, j + dj, z), self.p(i, j + dj, z + h), self.p(i, j, z + h)], color)

    def cara_der(self, i, j, z, di, h, color, capa='fondo'):
        L = self.capas[capa]
        L.poly([self.p(i, j, z), self.p(i + di, j, z), self.p(i + di, j, z + h), self.p(i, j, z + h)], color)

    def pixel(self, i, j, z, color, capa='fondo'):
        x, y = self.p(i, j, z)
        self.capas[capa].put(int(x), int(y), color)

    def capa_img(self, nombre):
        # pointer-events:none: una <image> captura los clics en todo su rectángulo, también en lo transparente,
        # y taparía las burbujas y oficinas que están debajo en el SVG
        return f'<image href="data:image/png;base64,{self.capas[nombre].png_b64()}" x="0" y="0" width="{self.w}" height="{self.h}" image-rendering="pixelated" style="image-rendering:pixelated;pointer-events:none"/>'

    def poligono_svg(self, pts, color, extra=''):
        return f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="{color}"{extra}/>'
