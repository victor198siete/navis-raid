"""Prueba de la carpeta de datos (E8d-1): con `NAVIS_RAID_DATA`, Navis Raid escribe todo su estado en esa carpeta y
nada junto al código; sin la variable, todo queda donde siempre.

Trabaja sobre una COPIA del código en un temporal (sin `bitacora/`, `chat/`, `index.html`, `tabla.html`,
`estado.json`, `config.json` ni `pisos.json`), como `pruebas/paquete.py`: así no toca la bitácora real ni se
confunde con un servidor encendido sobre la carpeta de verdad. En subprocesos, con un `CLAUDE_CONFIG_DIR` falso
(una transcripción mínima) y `NAVIS_RAID_DATA` en otro temporal, genera la página una vez. Comprueba:
  1. `index.html`, `tabla.html`, `estado.json` y `bitacora/` existen en la carpeta de datos;
  2. en la carpeta del código no cambió nada (lista de archivos y fechas de modificación, antes y después);
  3. la página carga las fuentes de la carpeta del código con una URL `file://` absoluta y no pide nada a la red;
  4. `NAVIS_RAID_DATA` admite `~`; vacía o sin definir, `config.DATOS` es la carpeta del código, y entonces
     `bitacora.DIR` y `config.RUTA` son los de siempre y la página lleva `fuentes/` relativo (sin generar nada);
  5. `--doctor` dice la carpeta de datos, y marca como fallo una carpeta donde no se puede escribir.

Uso: python3 pruebas/datos.py
"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENERADOS = ('bitacora', 'chat', 'index.html', 'tabla.html', 'estado.json', 'config.json', 'pisos.json', '__pycache__',
             'auditorias', 'encargos')
IGNORAR = shutil.ignore_patterns(*GENERADOS, '_preview-*', '*.tmp')

MUESTRA = r'''
import json, os, sys
sys.path.insert(0, os.getcwd())
import config, bitacora, oficina
print(json.dumps({'aqui': config.AQUI, 'datos': config.DATOS, 'ruta': config.RUTA, 'bitacora': bitacora.DIR,
                  'cuota': bitacora.CUOTA, 'pixel': oficina.render_pixel([], [], 0)}, ensure_ascii=False))
'''


def j(**kw):
    return json.dumps(kw, ensure_ascii=False)


def claude_falso(raiz):
    """Un CLAUDE_CONFIG_DIR con una sola transcripción mínima."""
    carpeta = os.path.join(raiz, 'projects', '-nonexistent-proyecto-falso')
    os.makedirs(carpeta)
    ahora = dt.datetime.now(dt.timezone.utc)
    t = lambda s: (ahora - dt.timedelta(seconds=s)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    comun = dict(cwd='/nonexistent/proyecto-falso', entrypoint='cli', version='2.1.299', sessionId='x')
    uso = {'input_tokens': 10, 'cache_creation_input_tokens': 20, 'cache_read_input_tokens': 30, 'output_tokens': 5}
    lineas = [
        j(type='user', timestamp=t(60), message={'role': 'user', 'content': 'hola'}, **comun),
        j(type='assistant', timestamp=t(50), requestId='r1',
          message={'role': 'assistant', 'model': 'claude-sonnet-5-5', 'id': 'm1', 'stop_reason': 'end_turn', 'usage': uso,
                   'content': [{'type': 'text', 'text': 'listo'}]}, **comun),
    ]
    with open(os.path.join(carpeta, 'dddddddd-0000-4000-8000-000000000004.jsonl'), 'w') as fh:
        fh.write('\n'.join(lineas) + '\n')


def instantanea(raiz):
    """{ruta relativa: (tamaño, mtime_ns)} de todo lo que hay bajo `raiz`, carpetas incluidas (salvo __pycache__)."""
    r = {}
    for base, dirs, archivos in os.walk(raiz):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for n in dirs + archivos:
            ruta = os.path.join(base, n)
            st = os.lstat(ruta)
            r[os.path.relpath(ruta, raiz)] = (st.st_size, st.st_mtime_ns)
    return r


def main():
    fallos = []

    def comprobar(ok, texto):
        print(('✓ ' if ok else '✗ ') + texto)
        if not ok:
            fallos.append(texto)

    tmp = tempfile.mkdtemp(prefix='raid-datos-')
    try:
        copia = os.path.join(tmp, 'oficina')
        shutil.copytree(AQUI, copia, ignore=IGNORAR)
        claude = os.path.join(tmp, 'claude')
        claude_falso(claude)
        datos = os.path.join(tmp, 'datos', 'nueva')       # no existe: se crea al escribir
        base = {k: v for k, v in os.environ.items() if not k.startswith('NAVIS_RAID_')}
        base.update(CLAUDE_CONFIG_DIR=claude, NAVIS_RAID_SOLO_TERMINAL='1', PYTHONDONTWRITEBYTECODE='1', HOME=tmp)
        env = dict(base, NAVIS_RAID_DATA=datos)

        # 1-3 · una pasada con la variable
        antes = instantanea(copia)
        p = subprocess.run([sys.executable, 'oficina.py'], capture_output=True, text=True, env=env, cwd=copia, timeout=180)
        comprobar(p.returncode == 0, 'oficina.py genera una vez con NAVIS_RAID_DATA' +
                  ('' if p.returncode == 0 else f' (salió con {p.returncode}: {p.stderr.strip()[-300:]})'))
        for nombre in ('index.html', 'tabla.html', 'estado.json', 'bitacora'):
            comprobar(os.path.exists(os.path.join(datos, nombre)), f'{nombre} existe en la carpeta de datos')
        despues = instantanea(copia)
        cambios = sorted(set(antes) ^ set(despues)) + sorted(k for k in antes if k in despues and antes[k] != despues[k])
        comprobar(not cambios, 'en la carpeta del código no cambió nada (archivos ni fechas)' +
                  ('' if not cambios else f': {cambios[:6]}'))
        pagina = os.path.join(datos, 'index.html')
        html = open(pagina, encoding='utf-8').read() if os.path.isfile(pagina) else ''
        urls = re.findall(r"url\('([^']*\.woff2)'\)", html)
        comprobar(len(urls) == 3, f'la página carga 3 fuentes ({len(urls)})')
        comprobar(bool(urls) and all(u.startswith('file://') for u in urls), 'las fuentes son URL file:// absolutas')
        carpeta_fuentes = os.path.join(os.path.realpath(copia), 'fuentes')
        existen = [u for u in urls if os.path.isfile(os.path.join(carpeta_fuentes, os.path.basename(u)))
                   and re.sub(r'^file://', '', u).startswith(carpeta_fuentes)]
        comprobar(bool(urls) and len(existen) == len(urls), 'cada fuente existe en fuentes/ de la carpeta del código')
        fuera = [u for u in re.findall(r'https?://[^\s"\'<>)]+', html) if not u.startswith('http://www.w3.org/')]
        comprobar(bool(html) and not fuera, f'la página no pide nada a la red ({fuera[:3]})')
        comprobar(bool(html) and "url('fuentes/" not in html, 'ninguna fuente queda con la ruta relativa fuentes/')

        # 4 · sin variable, vacía, con «~»
        antes = instantanea(copia)
        r = subprocess.run([sys.executable, '-c', MUESTRA], capture_output=True, text=True, env=base, cwd=copia, timeout=120)
        if r.returncode != 0:
            comprobar(False, f'importar config, bitacora y oficina sin la variable ({r.stderr.strip()[-300:]})')
        else:
            m = json.loads(r.stdout.splitlines()[-1])
            aqui = os.path.realpath(copia)
            comprobar(os.path.realpath(m['aqui']) == aqui and m['datos'] == m['aqui'], 'sin la variable, config.DATOS es AQUI')
            comprobar(m['bitacora'] == os.path.join(m['aqui'], 'bitacora') and m['cuota'] == os.path.join(m['aqui'], 'bitacora', 'cuota.jsonl'),
                      'sin la variable, bitacora.DIR y bitacora.CUOTA son los de siempre')
            comprobar(m['ruta'] == os.path.join(m['aqui'], 'config.json'), 'sin la variable, config.RUTA es AQUI/config.json')
            comprobar("url('fuentes/press-start-2p-latin-400-normal.woff2')" in m['pixel'] and "url('file://" not in m['pixel'],
                      'sin la variable, la página lleva fuentes/ relativo (idéntica a la de siempre)')
        r = subprocess.run([sys.executable, '-c', MUESTRA], capture_output=True, text=True, env=dict(base, NAVIS_RAID_DATA='  '), cwd=copia, timeout=120)
        m = json.loads(r.stdout.splitlines()[-1]) if r.returncode == 0 else {}
        comprobar(m.get('datos') == m.get('aqui') and bool(m), 'con la variable vacía, config.DATOS es AQUI')
        r = subprocess.run([sys.executable, '-c', MUESTRA], capture_output=True, text=True, env=dict(base, NAVIS_RAID_DATA='~/mis-datos'), cwd=copia, timeout=120)
        m = json.loads(r.stdout.splitlines()[-1]) if r.returncode == 0 else {}
        esperado = os.path.join(tmp, 'mis-datos')
        comprobar(bool(m) and os.path.realpath(m['datos']) == os.path.realpath(esperado) and m['bitacora'] == os.path.join(m['datos'], 'bitacora')
                  and m['ruta'] == os.path.join(m['datos'], 'config.json'),
                  'NAVIS_RAID_DATA admite «~»; el config por defecto y la bitácora cuelgan de la carpeta de datos')
        despues = instantanea(copia)
        comprobar(antes == despues and not os.path.exists(esperado), 'esas comprobaciones no generaron nada')

        # 5 · --doctor
        r = subprocess.run([sys.executable, 'oficina.py', '--doctor'], capture_output=True, text=True, env=env, cwd=copia, timeout=180)
        linea = next((l for l in r.stdout.splitlines() if 'NAVIS_RAID_DATA' in l), '')
        comprobar(datos in linea and linea.startswith('✓'), f'--doctor dice la carpeta de datos y que viene de NAVIS_RAID_DATA ({linea.strip()[:100]})')
        r = subprocess.run([sys.executable, 'oficina.py', '--doctor'], capture_output=True, text=True, env=base, cwd=copia, timeout=180)
        linea = next((l for l in r.stdout.splitlines() if 'NAVIS_RAID_DATA' in l), '')
        comprobar(os.path.realpath(copia) in os.path.realpath(linea.replace('✓ ', '')) or str(copia) in linea,
                  f'--doctor sin la variable dice que la carpeta de datos es la del código ({linea.strip()[:100]})')
        if hasattr(os, 'geteuid') and os.geteuid() != 0:
            cerrada = os.path.join(tmp, 'cerrada')
            os.mkdir(cerrada, 0o500)
            r = subprocess.run([sys.executable, 'oficina.py', '--doctor'], capture_output=True, text=True,
                               env=dict(base, NAVIS_RAID_DATA=os.path.join(cerrada, 'datos')), cwd=copia, timeout=180)
            malas = [l for l in r.stdout.splitlines() if l.startswith('✗') and cerrada in l]
            comprobar(bool(malas), 'si la carpeta de datos no se puede escribir, --doctor lo marca como fallo')
            os.chmod(cerrada, 0o700)
    finally:
        for base_, dirs, _ in os.walk(tmp):
            for d in dirs:
                try:
                    os.chmod(os.path.join(base_, d), 0o700)
                except OSError:
                    pass
        shutil.rmtree(tmp, ignore_errors=True)

    print('\nTodo en verde.' if not fallos else f'\n{len(fallos)} fallo(s).')
    return 1 if fallos else 0


if __name__ == '__main__':
    sys.exit(main())
