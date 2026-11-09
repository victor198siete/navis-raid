"""Prueba de portabilidad (E8a): la oficina no depende de `fcntl` y sus `git` no tocan el `.git/index` de otros repos.

  1. Sin `fcntl` (se simula con `sys.modules['fcntl'] = None` antes del import, en un subproceso), `bitacora` importa y
     `actualizar()` anota las llamadas sin candado.
  2. Con `fcntl`, el candado sigue funcionando: si otro descriptor tiene el `.lock`, `actualizar()` devuelve None y no escribe.
  3. `plan._correr` llama a `git --no-optional-locks -C <repo> …` (así `git status` no reescribe el índice del repo).
  4. (E8f-A) Windows simulado en un subproceso (sin `os.getuid`, `sys.platform == 'win32'`, `platform.system() == 'Windows'`,
     sin `fcntl`): todos los módulos del programa se importan.
  5. (E8f-A) En esa simulación, con `chat_sesion` en el config el chat queda apagado: `POST /chat` → 404, no se llama a `lsof`,
     `datos_vivos` deja `chat` en null y el pie no lo menciona.
  6. (E8f-A) En esa simulación, `oficina.py --doctor` termina sin excepciones (aun con una consola cp1252), sale con 0 y avisa
     de lo que no hay en Windows (el servicio y el chat). No compara el texto exacto: depende del idioma.
  7. (E8f-A) Todo `open()` de texto de los `.py` del paquete pasa `encoding=` (en Windows el valor por defecto es cp1252, no
     UTF-8). Una razón escrita en un comentario `# sin encoding: <razón>` en la misma línea lo exime.
  8. (E8d-4) Toda llamada a `subprocess.run`/`check_output`/`Popen` en modo texto (`text=True` o `universal_newlines=True`)
     de los `.py` del paquete pasa `encoding='utf-8', errors='replace'` (en Windows cp1252 no define 0x81, 0x8D, 0x8F, 0x90 ni
     0x9D, y UTF-8 los usa en «Á», «Í» y los emojis: el `UnicodeDecodeError` no lo atrapa ningún `except OSError`). Y, de
     forma funcional, `plan._correr` lee un commit «Á 🐛» aunque la codificación del equipo no sea UTF-8 (locale C sin coerción).
  9. (E8f-B1) El servicio de Windows, simulado (como la 4, con `NAVIS_RAID_SERVICIO=1` y `sys.stdout`/`sys.stderr` en None, que es
     lo que deja `pythonw.exe`): `oficina.main(['--serve', puerto])` deja su línea en `DATOS/servicio.log`, escribe
     `servicio.pid` con su PID mientras sirve y lo borra al salir limpio. El servidor HTTP se sustituye por uno falso (la
     prueba no abre puertos): lo que se comprueba es el log y el PID, no la red. Fuera del servicio (sin la variable) no
     escribe ni log ni PID.

Todo ocurre en un directorio temporal (la bitácora real vive junto al código y no se toca; se comprueba la fecha de su
`.offsets.json`). No ejecuta git de verdad: sustituye `subprocess.run`.

Uso: python3 pruebas/portabilidad.py     (sale con 0 si todo pasa)
"""
import ast
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL = os.path.join(AQUI, 'bitacora', '.offsets.json')
fallos = []


def comprobar(ok, que):
    print(('ok     ' if ok else 'FALLA  ') + que)
    if not ok:
        fallos.append(que)


def llamada(t, i):
    return json.dumps({
        'type': 'assistant', 'timestamp': t, 'requestId': f'r{i}',
        'message': {'role': 'assistant', 'model': 'claude-sonnet-5-5', 'id': f'm{i}', 'content': [],
                    'usage': {'input_tokens': 10 + i, 'cache_creation_input_tokens': 20, 'cache_read_input_tokens': 30,
                              'output_tokens': 5}},
    }).encode() + b'\n'


def preparar(raiz):
    """Una transcripción de 5 llamadas en `raiz/projects`; devuelve la carpeta de proyectos."""
    proyectos = os.path.join(raiz, 'projects')
    carpeta = os.path.join(proyectos, '-Users-ejemplo-Desktop-Workspace-Prueba')
    os.makedirs(carpeta)
    ahora = dt.datetime.now(dt.timezone.utc)
    with open(os.path.join(carpeta, 'aaaaaaaa-0000-4000-8000-000000000001.jsonl'), 'wb') as fh:
        for i in range(5):
            fh.write(llamada((ahora - dt.timedelta(seconds=100 - i)).strftime('%Y-%m-%dT%H:%M:%S.000Z'), i))
    return proyectos


def apuntar(bitacora, raiz, proyectos):
    bitacora.DIR = os.path.join(raiz, 'bitacora')
    bitacora.OFFSETS = os.path.join(bitacora.DIR, '.offsets.json')
    bitacora.CUOTA = os.path.join(bitacora.DIR, 'cuota.jsonl')
    bitacora.PROYECTOS = proyectos
    bitacora.APP = None
    assert os.path.realpath(bitacora.DIR).startswith(os.path.realpath(raiz)), 'la bitácora de prueba no es temporal'


# Subproceso sin fcntl: imprime cuántas llamadas anotó y cuántas líneas hay en disco.
SIN_FCNTL = r'''
import sys, os, json
sys.modules['fcntl'] = None            # «import fcntl» lanza ImportError, como en Windows
sys.path.insert(0, sys.argv[1])
import bitacora
raiz, proyectos = sys.argv[2], sys.argv[3]
bitacora.DIR = os.path.join(raiz, 'bitacora')
bitacora.OFFSETS = os.path.join(bitacora.DIR, '.offsets.json')
bitacora.CUOTA = os.path.join(bitacora.DIR, 'cuota.jsonl')
bitacora.PROYECTOS = proyectos
bitacora.APP = None
assert os.path.realpath(bitacora.DIR).startswith(os.path.realpath(raiz))
n = bitacora.actualizar(reconstruir=True)
lineas = sum(len(open(os.path.join(bitacora.DIR, f)).read().splitlines()) for f in os.listdir(bitacora.DIR)
             if len(f) == 16 and f.endswith('.jsonl') and f != 'cuota.jsonl')
print(json.dumps({'n': n, 'lineas': lineas}))
'''


# Windows simulado (E8f-A). Se importa antes todo lo estándar que usan los módulos (con `sys.platform == 'win32'`,
# `subprocess` pediría `msvcrt`, que aquí no existe) y luego se quita lo que Windows no tiene.
SIM_WINDOWS = r'''
import ast, glob, importlib, os, platform, sys
aqui, raiz = sys.argv[1], sys.argv[2]
os.environ['NAVIS_RAID_DATA'] = os.path.join(raiz, 'datos')
os.environ['CLAUDE_CONFIG_DIR'] = os.path.join(raiz, 'claude')
os.environ['NAVIS_RAID_SOLO_TERMINAL'] = '1'
os.environ.pop('NAVIS_RAID_CONFIG', None)
for f in glob.glob(os.path.join(aqui, '*.py')) + [os.path.join(aqui, 'pruebas', 'servidor.py')]:
    with open(f, encoding='utf-8') as fh:
        arbol = ast.parse(fh.read())
    for n in ast.walk(arbol):
        nombres = [a.name for a in n.names] if isinstance(n, ast.Import) else \
                  [n.module] if isinstance(n, ast.ImportFrom) and n.module and not n.level else []
        for nombre in nombres:
            if not os.path.exists(os.path.join(aqui, nombre.split('.')[0] + '.py')):
                try:
                    importlib.import_module(nombre)
                except ImportError:
                    pass
for nombre in ('getuid', 'geteuid', 'getgid'):
    if hasattr(os, nombre):
        delattr(os, nombre)
sys.modules['fcntl'] = None
sys.platform = 'win32'
platform.system = lambda: 'Windows'
sys.path[:0] = [aqui, os.path.join(aqui, 'pruebas')]
'''

SIM_IMPORTAR = r'''
import glob, importlib, json, os
malos = {}
nombres = sorted(os.path.basename(f)[:-3] for f in glob.glob(os.path.join(aqui, '*.py')))
for nombre in nombres:
    try:
        importlib.import_module(nombre)
    except BaseException as e:
        malos[nombre] = '%s: %s' % (type(e).__name__, e)
print(json.dumps({'n': len(nombres), 'malos': malos}))
'''

SIM_CHAT = r'''
import json, subprocess
llamadas = []
real = subprocess.run
subprocess.run = lambda cmd, *a, **k: (llamadas.append(list(cmd)), real(cmd, *a, **k))[1]
import oficina, servidor as prueba
enviado, error = oficina.chat_enviar('hola')
sesiones, eventos = oficina.recoger()
datos = oficina.datos_vivos(sesiones, eventos)
pagina = oficina.render_pixel(sesiones, eventos, 0)
srv, puerto, conectar, parar, modo = prueba.levantar(oficina, 'tok')
c = conectar()
c.request('POST', '/chat', body=json.dumps({'texto': 'hola'}),
          headers={'Host': '127.0.0.1:%d' % puerto, 'Content-Type': 'application/json', 'X-Navis-Raid-Token': 'tok',
                   'Origin': 'http://127.0.0.1:%d' % puerto})
codigo = c.getresponse().status
parar()
print(json.dumps({'codigo': codigo, 'enviados': enviado, 'error': error, 'lsof': [l for l in llamadas if 'lsof' in l],
                  'destino': oficina.chat_destino(), 'sesion': oficina.CHAT_SESION, 'chat': datos['chat'],
                  'pie_menciona': 'salvo lo que hables' in pagina}))
'''

SIM_SERVICIO = r'''
import json
import oficina, servicio
visto = {}


class Falso:
    server_address = ('127.0.0.1', 8999)

    def serve_forever(self):
        try:
            with open(servicio.ruta_pid(), encoding='utf-8') as fh:
                visto['pid'] = fh.read().strip()
        except OSError:
            visto['pid'] = None
        print('http-falso')

    def server_close(self):
        pass


oficina.servidor = lambda puerto, token: Falso()
if os.environ.get('PRUEBA_SIN_SERVICIO'):
    os.environ.pop('NAVIS_RAID_SERVICIO', None)
else:
    os.environ['NAVIS_RAID_SERVICIO'] = '1'
sys.stdout = None                       # lo que deja pythonw.exe
sys.stderr = None
codigo = oficina.main(['--serve', '8999'])
if sys.stdout:
    sys.stdout.flush()
log = servicio.ruta_log()
sys.__stdout__.write(json.dumps({
    'codigo': codigo, 'pid_visto': visto.get('pid'), 'mi_pid': os.getpid(),
    'pid_despues': os.path.exists(servicio.ruta_pid()), 'log_existe': os.path.exists(log),
    'log': open(log, encoding='utf-8').read() if os.path.exists(log) else None}) + '\n')
'''

SIM_DOCTOR = r'''
import runpy
sys.argv = [os.path.join(aqui, 'oficina.py'), '--doctor']
try:
    runpy.run_path(sys.argv[0], run_name='__main__')
except SystemExit as e:
    sys.stdout.flush()
    sys.stderr.write('SALIDA %s\n' % (e.code or 0))
'''


def simular_windows(cuerpo, raiz, chat=True, extra_env=None):
    """Corre `cuerpo` en un subproceso que se hace pasar por Windows. `raiz`: datos y transcripciones temporales."""
    proyectos = preparar(os.path.join(raiz, 'claude'))
    os.makedirs(os.path.join(raiz, 'datos'), exist_ok=True)
    with open(os.path.join(raiz, 'datos', 'config.json'), 'w', encoding='utf-8') as fh:
        json.dump({'chat_sesion': 'sesion-central' if chat else None, 'idioma': 'en'}, fh)
    return subprocess.run([sys.executable, '-c', SIM_WINDOWS + cuerpo, AQUI, raiz], capture_output=True, text=True, encoding='utf-8', errors='replace',
                          timeout=180, env=dict(os.environ, **(extra_env or {})))


def ultima_linea(p):
    return p.stderr.strip().splitlines()[-1] if p.stderr.strip() else 'salió con %s' % p.returncode


def sin_encoding(carpeta):
    """[(archivo, línea)] de los open()/read_text()/write_text() de texto sin `encoding=` en los .py de `carpeta` y de
    `carpeta/pruebas`, salvo los que lleven `# sin encoding: <razón>` en su línea."""
    malos = []
    for f in sorted(glob.glob(os.path.join(carpeta, '*.py')) + glob.glob(os.path.join(carpeta, 'pruebas', '*.py'))):
        with open(f, encoding='utf-8') as fh:
            fuente = fh.read()
        lineas = fuente.splitlines()
        for n in ast.walk(ast.parse(fuente)):
            if not isinstance(n, ast.Call):
                continue
            nombre = n.func.id if isinstance(n.func, ast.Name) else n.func.attr if isinstance(n.func, ast.Attribute) else None
            if nombre not in ('open', 'read_text', 'write_text'):
                continue
            if nombre == 'open' and isinstance(n.func, ast.Attribute) and not (isinstance(n.func.value, ast.Name) and n.func.value.id in ('io', 'codecs', 'os', 'gzip')):
                continue                                   # un método .open() de otra cosa (un Path, un zip…), no la función open()
            modo = n.args[1] if nombre == 'open' and len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == 'mode'), None)
            if isinstance(modo, ast.Constant) and isinstance(modo.value, str) and 'b' in modo.value:
                continue                                   # binario
            if any(k.arg == 'encoding' for k in n.keywords) or (n.args and any(isinstance(a, ast.Starred) for a in n.args)):
                continue
            if re.search(r'#\s*sin encoding:\s*\S', ' '.join(lineas[n.lineno - 1:n.end_lineno])):
                continue
            malos.append((os.path.relpath(f, carpeta), n.lineno))
    return malos


def sin_encoding_subprocess(carpeta):
    """[(archivo, línea)] de las llamadas a subprocess.run/check_output/Popen/call/check_call en modo texto sin
    `encoding=` o sin `errors=` en los .py de INCLUIR de `carpeta` y de `carpeta/pruebas`. `# sin encoding: <razón>` en la línea las exime."""
    malos = []
    incluir = None
    if os.path.isfile(os.path.join(carpeta, 'empaquetar.py')):     # en el origen hay herramientas del autor que no salen: solo INCLUIR
        import importlib.util
        spec = importlib.util.spec_from_file_location('_empaquetar', os.path.join(carpeta, 'empaquetar.py'))
        modulo = importlib.util.module_from_spec(spec)
        dont, sys.dont_write_bytecode = sys.dont_write_bytecode, True
        try:
            spec.loader.exec_module(modulo)
        finally:
            sys.dont_write_bytecode = dont
        incluir = set(modulo.INCLUIR)
    for f in sorted(glob.glob(os.path.join(carpeta, '*.py')) + glob.glob(os.path.join(carpeta, 'pruebas', '*.py'))):
        if incluir is not None and os.path.relpath(f, carpeta).replace(os.sep, '/') not in incluir:
            continue
        with open(f, encoding='utf-8') as fh:
            fuente = fh.read()
        lineas = fuente.splitlines()
        for n in ast.walk(ast.parse(fuente)):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == 'subprocess' and n.func.attr in ('run', 'check_output', 'Popen', 'call', 'check_call')):
                continue
            texto = any(k.arg in ('text', 'universal_newlines') and not (isinstance(k.value, ast.Constant) and k.value.value is False)
                        for k in n.keywords)
            if not texto:
                continue
            if all(any(k.arg == nombre for k in n.keywords) for nombre in ('encoding', 'errors')):
                continue
            if re.search(r'#\s*sin encoding:\s*\S', ' '.join(lineas[n.lineno - 1:n.end_lineno])):
                continue
            malos.append((os.path.relpath(f, carpeta), n.lineno))
    return malos


CODIGO_COMMIT_UTF8 = """
import sys
sys.path.insert(0, sys.argv[1])
import plan
print(ascii(plan._correr(sys.argv[2], 'log', '-1', '--format=%s')))
"""


def git_lee_utf8_con_locale_ajeno():
    """(ok, detalle): un repo temporal con un commit «Á 🐛»; `plan._correr` lo lee con un locale que no es UTF-8."""
    with tempfile.TemporaryDirectory() as repo:
        for orden in (['init', '-q'], ['-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false',
                                       'commit', '-q', '--allow-empty', '-m', 'Á 🐛 arreglo']):
            r = subprocess.run(['git', '-C', repo, *orden], capture_output=True, timeout=30)
            if r.returncode != 0:
                return False, 'git no pudo preparar el repo: ' + r.stderr.decode('utf-8', 'replace')[-120:]
        env = {k: v for k, v in os.environ.items() if not k.startswith('LC_') and k not in ('LANG', 'PYTHONUTF8', 'PYTHONIOENCODING')}
        env.update({'LC_ALL': 'C', 'PYTHONUTF8': '0', 'PYTHONCOERCECLOCALE': '0', 'PYTHONDONTWRITEBYTECODE': '1'})
        p = subprocess.run([sys.executable, '-c', CODIGO_COMMIT_UTF8, AQUI, repo], capture_output=True, env=env, timeout=60)
        salida = p.stdout.decode('ascii', 'replace') + p.stderr.decode('ascii', 'replace')
        return p.returncode == 0 and 'arreglo' in salida and 'Traceback' not in salida, salida.strip().splitlines()[-1][:160] if salida.strip() else 'sin salida'


def main():
    antes = os.path.getmtime(REAL) if os.path.exists(REAL) else None

    # 1 · sin fcntl
    with tempfile.TemporaryDirectory() as raiz:
        proyectos = preparar(raiz)
        p = subprocess.run([sys.executable, '-c', SIN_FCNTL, AQUI, raiz, proyectos], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
        if p.returncode != 0:
            ultima = p.stderr.strip().splitlines()[-1] if p.stderr.strip() else f'salió con {p.returncode}'
            comprobar(False, f'sin fcntl, bitacora importa y actualizar() anota las llamadas ({ultima})')
        else:
            r = json.loads(p.stdout.splitlines()[-1])
            comprobar(r == {'n': 5, 'lineas': 5}, f'sin fcntl, bitacora importa y actualizar() anota las 5 llamadas ({r})')

    # 2 · con fcntl: el candado sigue impidiendo escribir a dos a la vez
    sys.path.insert(0, AQUI)
    import bitacora
    with tempfile.TemporaryDirectory() as raiz:
        proyectos = preparar(raiz)
        apuntar(bitacora, raiz, proyectos)
        os.makedirs(bitacora.DIR)
        try:
            import fcntl
        except ImportError:
            fcntl = None
        if fcntl is None or getattr(bitacora, 'fcntl', None) is None:
            print('omitida  con fcntl: este sistema no lo tiene')
        else:
            with open(os.path.join(bitacora.DIR, '.lock'), 'w', encoding='utf-8') as otro:
                fcntl.flock(otro, fcntl.LOCK_EX | fcntl.LOCK_NB)      # «otro proceso» tiene el candado
                n = bitacora.actualizar(reconstruir=True)
                escrito = [f for f in os.listdir(bitacora.DIR) if f.endswith('.jsonl')]
                comprobar(n is None and not escrito, f'con el candado tomado por otro, actualizar() devuelve None y no escribe (n={n}, {escrito})')
            n = bitacora.actualizar(reconstruir=True)
            comprobar(n == 5, f'con el candado libre, actualizar() anota las 5 llamadas (anotó {n})')

    # 3 · git sin locks opcionales
    import plan
    vistas = []
    real = plan.subprocess.run

    def falso(cmd, *a, **k):
        vistas.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

    plan.subprocess.run = falso
    try:
        plan._correr('/repo/de/prueba', 'status', '--porcelain=v1', '-b')
    finally:
        plan.subprocess.run = real
    esperado = ['git', '--no-optional-locks', '-C', '/repo/de/prueba', 'status', '--porcelain=v1', '-b']
    comprobar(vistas == [esperado], f'plan._correr pasa --no-optional-locks antes de -C ({vistas})')

    # 4 · Windows simulado: los módulos se importan
    with tempfile.TemporaryDirectory() as raiz:
        p = simular_windows(SIM_IMPORTAR, raiz)
        if p.returncode != 0:
            comprobar(False, f'Windows simulado: el subproceso corre ({ultima_linea(p)})')
        else:
            r = json.loads(p.stdout.splitlines()[-1])
            comprobar(not r['malos'] and r['n'] > 10, f'Windows simulado: los {r["n"]} módulos se importan sin os.getuid ({r["malos"]})')

    # 5 · Windows simulado: con chat_sesion configurado, el chat queda apagado
    with tempfile.TemporaryDirectory() as raiz:
        p = simular_windows(SIM_CHAT, raiz)
        if p.returncode != 0:
            comprobar(False, f'Windows + chat_sesion: el subproceso corre ({ultima_linea(p)})')
        else:
            r = json.loads(p.stdout.splitlines()[-1])
            comprobar(r['codigo'] == 404, f'Windows + chat_sesion: POST /chat con token bueno → 404, como sin chat (fue {r["codigo"]})')
            comprobar(r['lsof'] == [], f'Windows + chat_sesion: no se llama a lsof ({r["lsof"]})')
            comprobar(r['enviados'] == 0 and r['destino'] is None, f'Windows + chat_sesion: chat_enviar no envía y chat_destino es None ({r["enviados"]}, {r["destino"]})')
            comprobar(r['chat'] is None and r['pie_menciona'] is False, 'Windows + chat_sesion: datos_vivos deja chat = null y el pie no lo menciona')

    # 6 · Windows simulado: --doctor termina, avisa y no revienta con una consola cp1252
    with tempfile.TemporaryDirectory() as raiz:
        p = simular_windows(SIM_DOCTOR, raiz, extra_env={'PYTHONIOENCODING': 'cp1252'})
        salida = p.stdout + p.stderr
        comprobar(p.returncode == 0 and 'Traceback' not in salida and 'SALIDA 0' in p.stderr,
                  f'Windows simulado: --doctor termina con 0 y sin excepciones, aun con stdout cp1252 ({ultima_linea(p)})')
        minusculas = p.stdout.lower()
        comprobar('windows' in minusculas and '--serve' in minusculas and 'chat' in minusculas,
                  'Windows simulado: --doctor dice que no hay servicio (se arranca con --serve) ni chat')

    # 6b · Windows simulado: como servicio (pythonw, sin stdout) --serve deja log y PID
    with tempfile.TemporaryDirectory() as raiz:
        p = simular_windows(SIM_SERVICIO, raiz)
        if p.returncode != 0:
            comprobar(False, f'Windows + servicio: el subproceso corre ({ultima_linea(p)})')
        else:
            r = json.loads(p.stdout.splitlines()[-1])
            comprobar(r['codigo'] == 0 and r['log_existe'] and 'http-falso' in (r['log'] or '') and 'localhost:8999' in (r['log'] or ''),
                      f'Windows + servicio: con stdout None, --serve deja su salida en servicio.log ({r["log"]!r})')
            comprobar(r['pid_visto'] == '%s 8999' % r['mi_pid'], f'Windows + servicio: servicio.pid lleva el PID del servidor y el puerto en que escucha, «PID PUERTO» ({r["pid_visto"]} frente a {r["mi_pid"]} 8999)')
            comprobar(r['pid_despues'] is False, 'Windows + servicio: servicio.pid desaparece al salir limpio')
    with tempfile.TemporaryDirectory() as raiz:
        p = simular_windows(SIM_SERVICIO, raiz, extra_env={'PRUEBA_SIN_SERVICIO': '1'})
        if p.returncode != 0:
            comprobar(False, f'Windows sin servicio: el subproceso corre ({ultima_linea(p)})')
        else:
            r = json.loads(p.stdout.splitlines()[-1])
            comprobar(r['pid_visto'] is None and not r['log_existe'], f'Windows a mano (sin NAVIS_RAID_SERVICIO): no escribe PID ni log ({r["pid_visto"]}, {r["log_existe"]})')

    # 7 · UTF-8 explícito
    malos = sin_encoding(AQUI)
    comprobar(not malos, f'todo open() de texto pasa encoding= ({len(malos)} sin él: {malos[:6]})')

    # 8 · UTF-8 también en subprocess
    malos = sin_encoding_subprocess(AQUI)
    comprobar(not malos, f'toda llamada a subprocess en modo texto pasa encoding= y errors= ({len(malos)} sin ellos: {malos[:6]})')
    ok, detalle = git_lee_utf8_con_locale_ajeno()
    comprobar(ok, f'plan._correr lee un commit «Á 🐛» aunque el locale no sea UTF-8 ({detalle})')

    despues = os.path.getmtime(REAL) if os.path.exists(REAL) else None
    comprobar(antes == despues, 'el .offsets.json real no se tocó')
    print('\nSALIÓ LIMPIO' if not fallos else f'\n{len(fallos)} FALLO(S)')
    return 1 if fallos else 0


if __name__ == '__main__':
    sys.exit(main())
