"""Prueba del paquete autocontenido (E5): la carpeta `oficina/` copiada sola funciona y la página no pide nada a la red.

Copia la carpeta a un temporal (sin `bitacora/`, `chat/`, `index.html`, `estado.json`, `tabla.html` ni `__pycache__`) y, desde la
copia, en un subproceso, importa `sprites` y arma las páginas en memoria (`oficina.render_pixel` y la plantilla `PAGINA` de
`oficina_iso`); no llama a `generar()` ni escribe en la bitácora real. Comprueba:
  1. el subproceso no lanza (antes de la E5 fallaba: la copia no encontraba `avatar32`);
  2. `sprites.py` importó `avatar32` de la propia copia;
  3. el HTML no contiene `googleapis`, `gstatic` ni `http://`/`https://` hacia fuera (el `xmlns` de SVG se tolera);
  4. las `url('fuentes/…')` de las dos páginas apuntan a archivos que existen en la copia, y la licencia de cada fuente
     (`OFL-*.txt`) también;
  5. (E8a) una segunda copia sin `afk.py` también importa y arma la página, y `oficina.afk` queda en None.

Uso: python3 pruebas/paquete.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCLUIR_NOMBRES = ('bitacora', 'chat', 'index.html', 'estado.json', 'tabla.html', '__pycache__')
EXCLUIR = shutil.ignore_patterns(*EXCLUIR_NOMBRES)

# Se ejecuta en el subproceso, con la copia como carpeta de trabajo: imprime un JSON con lo que hay que comprobar.
CODIGO = r'''
import json, sys, os
sys.path.insert(0, os.getcwd())
import sprites, oficina, oficina_iso
print(json.dumps({'avatar32': os.path.abspath(sprites.A.__file__), 'afk': oficina.afk is not None,
                  'paginas': {'pixel': oficina.render_pixel([], [], 0), 'iso': oficina_iso.PAGINA}}, ensure_ascii=False))
'''


def main():
    fallos = []

    def comprobar(ok, texto):
        print(('✓ ' if ok else '✗ ') + texto)
        if not ok:
            fallos.append(texto)

    tmp = tempfile.mkdtemp(prefix='raid-paquete-')
    copia = os.path.join(tmp, 'oficina')
    try:
        shutil.copytree(AQUI, copia, ignore=EXCLUIR)
        env = dict(os.environ, NAVIS_RAID_CONFIG=os.path.join(tmp, 'no-existe.json'), CLAUDE_CONFIG_DIR=os.path.join(tmp, 'claude'))
        p = subprocess.run([sys.executable, '-c', CODIGO], capture_output=True, text=True, env=env, cwd=copia, timeout=120)
        if p.returncode != 0:
            ultima = p.stderr.strip().splitlines()[-1] if p.stderr.strip() else f'salió con {p.returncode}'
            comprobar(False, f'la copia importa sprites y arma la página sin error ({ultima})')
        else:
            r = json.loads(p.stdout.splitlines()[-1])
            comprobar(True, 'la copia importa sprites y arma la página sin error')
            comprobar(os.path.dirname(r['avatar32']) == os.path.realpath(copia),
                      f'avatar32 sale de la propia copia ({r["avatar32"]})')
            for nombre, html in r['paginas'].items():
                for malo in ('googleapis', 'gstatic'):
                    comprobar(malo not in html, f'página {nombre}: no contiene «{malo}»')
                fuera = [u for u in re.findall(r'https?://[^\s"\'<>)]+', html) if not u.startswith('http://www.w3.org/')]
                comprobar(not fuera, f'página {nombre}: ninguna URL http(s) hacia fuera ({fuera[:3]})')
                urls = re.findall(r"url\('(fuentes/[^']+)'\)", html)
                comprobar(bool(urls), f'página {nombre}: carga {len(urls)} fuente(s) desde fuentes/')
                for u in urls:
                    comprobar(os.path.isfile(os.path.join(copia, u)), f'página {nombre}: {u} existe en la copia')
            for lic in ('OFL-press-start-2p.txt', 'OFL-jetbrains-mono.txt'):
                comprobar(os.path.isfile(os.path.join(copia, 'fuentes', lic)), f'la copia lleva fuentes/{lic}')

        # 5 · sin afk.py (E8a): el protocolo «afk» es de la máquina del autor; la oficina arranca igual y no marca relevadas
        sin_afk = os.path.join(tmp, 'oficina-sin-afk')
        shutil.copytree(AQUI, sin_afk, ignore=shutil.ignore_patterns(*EXCLUIR_NOMBRES, 'afk.py'))
        comprobar(not os.path.exists(os.path.join(sin_afk, 'afk.py')), 'la segunda copia no lleva afk.py')
        p = subprocess.run([sys.executable, '-c', CODIGO], capture_output=True, text=True, env=env, cwd=sin_afk, timeout=120)
        if p.returncode != 0:
            ultima = p.stderr.strip().splitlines()[-1] if p.stderr.strip() else f'salió con {p.returncode}'
            comprobar(False, f'sin afk.py, la copia importa oficina y arma la página sin error ({ultima})')
        else:
            r = json.loads(p.stdout.splitlines()[-1])
            comprobar(True, 'sin afk.py, la copia importa oficina y arma la página sin error')
            comprobar(r['afk'] is False, 'sin afk.py, oficina.afk es None (ninguna sesión sale relevada)')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('\nTodo en verde.' if not fallos else f'\n{len(fallos)} fallo(s).')
    return 1 if fallos else 0


if __name__ == '__main__':
    sys.exit(main())
