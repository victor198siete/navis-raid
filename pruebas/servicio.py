"""Prueba del servicio de usuario (E8e-1): Navis Raid se instala como servicio de launchd (macOS) o de systemd (Linux).

NUNCA toca el HOME real, `launchctl` ni `systemctl`: usa un HOME temporal y un *runner* falso que solo anota las
llamadas (y, por si acaso, hace explotar `subprocess.run` mientras corre). Comprueba:
  1. el plist (que `plistlib` parsea) y el unit llevan las rutas, el puerto, `NAVIS_RAID_DATA` y la política de reinicio
     (relanzar tras una caída, no tras una salida limpia); el unit sobrevive a una ruta con espacios;
  2. instalar dos veces deja un solo archivo, con el contenido nuevo (así `/navis-raid:start` tras actualizar el plugin
     apunta a la versión nueva); en Linux la segunda vez reinicia el servicio;
  3. quitar borra el archivo y llama a `bootout` o a `disable --now`; quitar sin servicio no falla ni llama a nada;
  4. en otro sistema, error claro y nada escrito; si no se puede escribir (sandbox), código 1 con el motivo y sin
     llamar a `launchctl`/`systemctl`;
  5. `--estado-servicio` lee lo instalado: ruta, `oficina.py`, datos, puerto y si algo escucha;
  6. `oficina.py --doctor` (en un subproceso, con HOME temporal) marca como fallo un servicio cuyo `oficina.py` ya no
     existe y lo da por bueno si existe; sin servicio no dice nada.
  7. (E8e-2a) el unit no admite inyección ni `%` sin duplicar; `correr` usa lista y sin shell; `quitar` no miente si
     `bootout`/`disable` fallan; las variables del entorno llegan al servicio; con el puerto ocupado `--serve` no
     entra en bucle (sale con 0 como servicio y con 3 en la terminal); `--doctor` marca el intérprete que ya no existe.
  8. (E8e-4) con el puerto ocupado por otra cosa `instalar` no instala (código 4, nada escrito, ningún runner) y sugiere
     el primer puerto libre; si lo ocupa nuestro propio servicio, es una reinstalación y sigue. Con `verificar=True`
     (lo que pasa `oficina.py --instalar-servicio`) espera a que el servicio escuche y, si no llega, sale con 5.
  9. (E8f-A, reescrito en la E8f-B1) un sistema desconocido sigue dando «no soportado» (código 2, nada escrito ni ejecutado);
     `--estado-servicio` informa lo mismo y sale con 0. Windows ya está soportado (punto 10).
 10. (E8f-B1) Windows simulado (`platform.system() == 'Windows'`, HOME temporal, `runner` y `lanzar` falsos): `instalar`
     escribe `navis-raid.cmd` en la carpeta Inicio y arranca el servidor con `lanzar`; `texto_cmd`/`leer_cmd` hacen
     ida y vuelta y rechazan `%`, `"` y saltos de línea (código 2, nada escrito); `quitar` lee `servicio.pid`, comprueba
     con `tasklist` que es python antes de `taskkill`, y no miente si `taskkill` falla; `estado` describe el `.cmd`;
     macOS y Linux no cambian (plist y unit idénticos a los de antes, byte a byte, se comprueban aparte con `cmp`).

Uso: python3 pruebas/servicio.py
"""
import contextlib
import errno
import io
import os
import plistlib
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import types

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True
# Este archivo también se llama servicio.py: sin quitar su carpeta del path, `import servicio` se importaría a sí mismo.
sys.path[:] = [AQUI] + [p for p in sys.path if os.path.abspath(p or '.') not in (AQUI, os.path.join(AQUI, 'pruebas'))]
GENERADOS = ('bitacora', 'chat', 'index.html', 'tabla.html', 'estado.json', 'config.json', 'pisos.json', '__pycache__',
             'auditorias', 'encargos')
IGNORAR = shutil.ignore_patterns(*GENERADOS, '_preview-*', '*.tmp')


class Runner:
    """El runner falso: anota cada llamada y contesta lo que se le diga (por defecto, éxito)."""

    def __init__(self, falla=None, lanza=None):
        self.llamadas = []
        self.falla = falla or (lambda args: 0)
        self.lanza = lanza

    def __call__(self, args):
        self.llamadas.append(list(args))
        if self.lanza:
            raise self.lanza
        return types.SimpleNamespace(returncode=self.falla(args), stdout='', stderr='fallo simulado')


def sin_subprocess_real(*a, **k):
    raise AssertionError('la prueba intentó lanzar un proceso de verdad: %r' % (a[:1],))


def captura(f, *a, **k):
    """(valor, lo que imprimió) de `f`."""
    salida = io.StringIO()
    with contextlib.redirect_stdout(salida):
        valor = f(*a, **k)
    return valor, salida.getvalue()


def main():
    fallos = []

    def comprobar(ok, texto):
        print(('✓ ' if ok else '✗ ') + texto)
        if not ok:
            fallos.append(texto)

    tmp = tempfile.mkdtemp(prefix='raid-servicio-')
    try:
        servicio = None
        try:
            import servicio
        except ImportError as e:
            comprobar(False, 'existe el módulo servicio.py (%s)' % e)
        if servicio:
            en_proceso(servicio, tmp, comprobar)
            en_proceso_e8e2a(servicio, tmp, comprobar)
            en_proceso_e8e4(servicio, tmp, comprobar)
            en_verificar_e8e4(servicio, tmp, comprobar)
            en_windows_e8fb(servicio, tmp, comprobar)
        en_doctor(tmp, comprobar)
        if servicio:
            en_doctor_e8e2a(servicio, tmp, comprobar)
    finally:
        for base, dirs, _ in os.walk(tmp):
            for d in dirs:
                try:
                    os.chmod(os.path.join(base, d), 0o700)
                except OSError:
                    pass
        shutil.rmtree(tmp, ignore_errors=True)

    print('\nTodo en verde.' if not fallos else '\n%d fallo(s).' % len(fallos))
    return 1 if fallos else 0


def en_proceso(servicio, tmp, comprobar):
    """Las comprobaciones 1 a 5: dentro del proceso, con HOME temporal y runner falso."""
    real_run = subprocess.run
    subprocess.run = sin_subprocess_real
    guardado = {n: getattr(servicio, n) for n in ('home', 'sistema', 'uid', 'datos', 'python', 'escucha')}
    try:
        casa = os.path.join(tmp, 'casa')
        os.makedirs(casa)
        datos = os.path.join(tmp, 'mis datos')              # con espacio, a propósito
        codigo_1 = os.path.join(tmp, 'plugin 0.1.0', 'oficina.py')
        codigo_2 = os.path.join(tmp, 'plugin 0.2.0', 'oficina.py')
        sistema_real = servicio.sistema           # el de verdad (platform.system()), por si una prueba lo necesita
        servicio.home = lambda: casa
        servicio.uid = lambda: 501
        servicio.datos = lambda: datos
        servicio.python = lambda: '/usr/bin/python3'
        servicio.escucha = lambda puerto: False
        plist = os.path.join(casa, 'Library', 'LaunchAgents', 'navis-raid.plist')
        unit = os.path.join(casa, '.config', 'systemd', 'user', 'navis-raid.service')

        # 1 · el contenido, sin escribir nada
        crudo = servicio.texto_plist('/usr/bin/python3', codigo_1, 8766, datos)
        p = plistlib.loads(crudo.encode('utf-8'))
        comprobar(p.get('Label') == 'navis-raid', 'plist: Label navis-raid')
        comprobar(p.get('ProgramArguments') == ['/usr/bin/python3', '-B', codigo_1, '--serve', '8766'],
                  'plist: ProgramArguments (python, -B, oficina.py, --serve, puerto)')
        comprobar(p.get('EnvironmentVariables') == {'NAVIS_RAID_DATA': datos}, 'plist: NAVIS_RAID_DATA es la carpeta de datos')
        comprobar(p.get('RunAtLoad') is True, 'plist: RunAtLoad (arranca al iniciar sesión)')
        comprobar(p.get('KeepAlive') == {'SuccessfulExit': False}, 'plist: KeepAlive/SuccessfulExit false (relanza tras caída, no tras salida limpia)')
        log = os.path.join(datos, 'servicio.log')
        comprobar(p.get('StandardOutPath') == log and p.get('StandardErrorPath') == log, 'plist: stdout y stderr van a DATOS/servicio.log')

        texto = servicio.texto_unit('/usr/bin/python3', codigo_1, 8766, datos)
        comprobar('[Service]' in texto and '[Install]' in texto and 'WantedBy=default.target' in texto, 'unit: secciones y WantedBy=default.target')
        comprobar('Restart=on-failure' in texto, 'unit: Restart=on-failure (relanza tras caída, no tras salida limpia)')
        comprobar('NAVIS_RAID_DATA=' in texto and datos in texto, 'unit: Environment lleva NAVIS_RAID_DATA')
        comprobar(('append:' + log) in texto, 'unit: stdout y stderr van a DATOS/servicio.log')
        escrito = servicio.leer_unit(texto)
        comprobar(escrito.get('script') == codigo_1 and escrito.get('puerto') == 8766 and escrito.get('datos') == datos,
                  'unit: ExecStart y Environment se leen de vuelta con las rutas con espacios intactas (%r)' % (escrito,))

        # 2 · macOS: instalar dos veces
        servicio.sistema = lambda: 'Darwin'
        r = Runner()
        codigo, salida = captura(servicio.instalar, 8766, codigo_1, runner=r)
        comprobar(codigo == 0 and os.path.isfile(plist), 'macOS: instalar escribe %s y sale con 0 (%s)' % (plist, salida.strip()[:80]))
        comprobar(os.path.isdir(datos), 'macOS: crea la carpeta de datos (launchd no crea la del log)')
        comprobar(['launchctl', 'bootstrap', 'gui/501', plist] in r.llamadas, 'macOS: llama a launchctl bootstrap gui/<uid> <plist>')
        comprobar(any(c[:3] == ['launchctl', 'bootout', 'gui/501/navis-raid'] for c in r.llamadas), 'macOS: descarga primero lo que hubiera (bootout)')
        comprobar(all(c[0] == 'launchctl' and 'shell' not in c for c in r.llamadas), 'macOS: solo llama a launchctl, con lista de argumentos')
        r2 = Runner()
        codigo, _ = captura(servicio.instalar, 8767, codigo_2, runner=r2)
        p = plistlib.loads(open(plist, 'rb').read())
        comprobar(codigo == 0 and p['ProgramArguments'][2] == codigo_2 and p['ProgramArguments'][-1] == '8767',
                  'macOS: instalar de nuevo reescribe con el contenido nuevo (oficina.py y puerto)')
        comprobar(os.listdir(os.path.dirname(plist)) == ['navis-raid.plist'], 'macOS: tras dos instalaciones queda un solo archivo')
        comprobar(['launchctl', 'bootstrap', 'gui/501', plist] in r2.llamadas, 'macOS: la segunda vez también lo carga')

        # 3 · macOS: estado y quitar
        servicio.escucha = lambda puerto: puerto == 8767
        e, salida = captura(servicio.estado)
        comprobar(e == 0 and plist in salida and codigo_2 in salida and datos in salida and '8767' in salida,
                  'macOS: --estado-servicio dice archivo, oficina.py, datos y puerto')
        info = servicio.leer()
        comprobar(info['instalado'] and info['script'] == codigo_2 and info['puerto'] == 8767 and info['datos'] == datos
                  and info['archivo'] == plist and info['script_existe'] is False and info['escucha'] is True,
                  'macOS: leer() da los campos (script que no existe, algo escucha) (%r)' % (info,))
        r3 = Runner()
        codigo, _ = captura(servicio.quitar, runner=r3)
        comprobar(codigo == 0 and not os.path.exists(plist), 'macOS: quitar borra el plist')
        comprobar(any(c[:3] == ['launchctl', 'bootout', 'gui/501/navis-raid'] for c in r3.llamadas), 'macOS: quitar llama a launchctl bootout')
        r4 = Runner()
        codigo, salida = captura(servicio.quitar, runner=r4)
        comprobar(codigo == 0 and not r4.llamadas and salida.strip(), 'macOS: quitar sin servicio dice que no hay, sale con 0 y no llama a nada')
        e, salida = captura(servicio.estado)
        comprobar(e == 0 and not servicio.leer()['instalado'], 'macOS: --estado-servicio sin servicio sale con 0 y dice que no está instalado')

        # 4 · Linux: instalar, reinstalar, quitar
        servicio.sistema = lambda: 'Linux'
        servicio.escucha = lambda puerto: False
        r = Runner()
        codigo, salida = captura(servicio.instalar, 8765, codigo_1, runner=r)
        comprobar(codigo == 0 and os.path.isfile(unit), 'Linux: instalar escribe %s y sale con 0 (%s)' % (unit, salida.strip()[:80]))
        comprobar(r.llamadas[:2] == [['systemctl', '--user', 'daemon-reload'], ['systemctl', '--user', 'enable', '--now', 'navis-raid']],
                  'Linux: daemon-reload y luego enable --now (%r)' % (r.llamadas,))
        comprobar(not any('restart' in c for c in r.llamadas), 'Linux: la primera vez no reinicia')
        r2 = Runner()
        codigo, _ = captura(servicio.instalar, 8770, codigo_2, runner=r2)
        l = servicio.leer_unit(open(unit, encoding='utf-8').read())
        comprobar(codigo == 0 and l['script'] == codigo_2 and l['puerto'] == 8770, 'Linux: instalar de nuevo reescribe con el contenido nuevo')
        comprobar(['systemctl', '--user', 'restart', 'navis-raid'] in r2.llamadas, 'Linux: la segunda vez reinicia el servicio para que tome la versión nueva')
        comprobar(os.listdir(os.path.dirname(unit)) == ['navis-raid.service'], 'Linux: tras dos instalaciones queda un solo archivo')
        info = servicio.leer()
        comprobar(info['instalado'] and info['archivo'] == unit and info['script'] == codigo_2 and info['puerto'] == 8770,
                  'Linux: leer() lee el unit instalado (%r)' % (info,))
        r3 = Runner()
        codigo, _ = captura(servicio.quitar, runner=r3)
        comprobar(codigo == 0 and not os.path.exists(unit), 'Linux: quitar borra el unit')
        comprobar(['systemctl', '--user', 'disable', '--now', 'navis-raid'] in r3.llamadas, 'Linux: quitar llama a disable --now')
        r4 = Runner()
        codigo, _ = captura(servicio.quitar, runner=r4)
        comprobar(codigo == 0 and not r4.llamadas, 'Linux: quitar sin servicio sale con 0 y no llama a nada')

        # 5 · otro sistema y fallos de permisos
        servicio.sistema = lambda: 'Plan9'
        r = Runner()
        codigo, salida = captura(servicio.instalar, 8765, codigo_1, runner=r)
        comprobar(codigo == 2 and not r.llamadas and salida.strip() and not os.path.exists(os.path.join(casa, 'Library', 'LaunchAgents', 'navis-raid.plist')),
                  'otro sistema: error claro, código 2, nada escrito ni ejecutado (%s)' % salida.strip()[:60])
        # E8f-A, reescrito en la E8f-B1: un sistema desconocido (`platform.system()`, sin sustituir servicio.sistema) sigue
        # dando «no soportado» en instalar, quitar y estado; Windows ya no (lo cubre `en_windows_e8fb`)
        servicio.sistema = sistema_real
        real_system, platform.system = platform.system, lambda: 'Plan9'
        try:
            for nombre, args in (('--instalar-servicio', (servicio.instalar, 8765, codigo_1)), ('--quitar-servicio', (servicio.quitar,))):
                r = Runner()
                codigo, salida = captura(*args, runner=r)
                comprobar(codigo == 2 and not r.llamadas and 'Plan9' in salida,
                          'Plan9: %s dice que no está soportado, sale con %s y no ejecuta nada (%s)' % (nombre, codigo, salida.strip()[:50]))
            codigo, salida = captura(servicio.estado)
            comprobar(codigo == 0 and 'Plan9' in salida, 'Plan9: --estado-servicio informa que no está soportado y sale con 0')
        finally:
            platform.system = real_system
        servicio.sistema = lambda: 'Darwin'
        r = Runner(lanza=PermissionError(1, 'Operation not permitted'))
        codigo, salida = captura(servicio.instalar, 8765, codigo_1, runner=r)
        comprobar(codigo == 1 and 'Operation not permitted' in salida, 'si launchctl no se puede ejecutar (sandbox), sale con 1 y dice el motivo')
        r = Runner(falla=lambda a: 5 if a[1] == 'bootstrap' else 0)
        codigo, salida = captura(servicio.instalar, 8765, codigo_1, runner=r, dormir=lambda s: None)
        comprobar(codigo == 1 and 'fallo simulado' in salida and sum(1 for c in r.llamadas if c[1] == 'bootstrap') == 2,
                  'si bootstrap falla, reintenta una vez y sale con 1 mostrando el error de launchctl')
        if hasattr(os, 'geteuid') and os.geteuid() != 0:
            cerrada = os.path.join(tmp, 'cerrada')
            os.mkdir(cerrada, 0o500)
            servicio.home = lambda: cerrada
            r = Runner()
            codigo, salida = captura(servicio.instalar, 8765, codigo_1, runner=r)
            comprobar(codigo == 1 and not r.llamadas and salida.strip(), 'sin permiso para escribir el plist: sale con 1, dice el motivo y no llama a launchctl (%s)' % salida.strip()[:70])
            servicio.home = lambda: casa
        for puerto_malo in (0, 70000):
            codigo, _ = captura(servicio.instalar, puerto_malo, codigo_1, runner=Runner())
            comprobar(codigo != 0, 'puerto %d: se rechaza' % puerto_malo)
    finally:
        subprocess.run = real_run
        for n, v in guardado.items():
            setattr(servicio, n, v)


def escribe(ruta, texto):
    with open(ruta, 'w', encoding='utf-8') as fh:
        fh.write(texto)


def en_windows_e8fb(servicio, tmp, comprobar):
    """La comprobación 10 (E8f-B1): el servicio de Windows, simulado en macOS. Nada se ejecuta de verdad: `runner` y `lanzar` falsos."""
    real_run = subprocess.run
    subprocess.run = sin_subprocess_real
    guardado = {n: getattr(servicio, n) for n in ('home', 'sistema', 'datos', 'python', 'escucha', 'lanzar') if hasattr(servicio, n)}
    appdata = os.environ.pop('APPDATA', None)
    try:
        casa = os.path.join(tmp, 'casa-w')
        os.makedirs(casa)
        datos = os.path.join(tmp, 'datos w')                       # con espacio, a propósito
        script = os.path.join(tmp, 'plugin w', 'oficina.py')
        carpeta_py = os.path.join(tmp, 'py')
        os.makedirs(carpeta_py)
        for n in ('python.exe', 'pythonw.exe'):
            open(os.path.join(carpeta_py, n), 'w', encoding='utf-8').close()
        servicio.home = lambda: casa
        servicio.sistema = lambda: 'Windows'
        servicio.datos = lambda: datos
        servicio.python = lambda: os.path.join(carpeta_py, 'python.exe')
        servicio.escucha = lambda puerto: False
        inicio = os.path.join(casa, 'AppData', 'Roaming', 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
        cmd = os.path.join(inicio, 'navis-raid.cmd')
        pid = os.path.join(datos, 'servicio.pid')
        pythonw = os.path.join(carpeta_py, 'pythonw.exe')

        class Lanzador:
            def __init__(self, lanza=None):
                self.llamadas, self.lanza = [], lanza

            def __call__(self, args, entorno):
                self.llamadas.append((list(args), dict(entorno)))
                if self.lanza:
                    raise self.lanza
                return None

        # S1 · el contenido y su camino de vuelta
        texto = servicio.texto_cmd(pythonw, script, 8765, datos, {'CLAUDE_CONFIG_DIR': 'C:\\Users\\Ana\\.claude', 'NAVIS_RAID_SERVICIO': '1'})
        leido = servicio.leer_cmd(texto)
        comprobar(leido.get('python') == pythonw and leido.get('script') == script and leido.get('puerto') == 8765
                  and leido.get('datos') == datos and leido.get('entorno') == {'CLAUDE_CONFIG_DIR': 'C:\\Users\\Ana\\.claude'},
                  'Windows: leer_cmd(texto_cmd(...)) devuelve los mismos valores (%r)' % (leido,))
        comprobar('set "NAVIS_RAID_SERVICIO=1"' in texto and 'start ""' in texto and '--serve 8765' in texto,
                  'Windows: el .cmd pone NAVIS_RAID_SERVICIO=1 con set "..." y lanza con start "" ... --serve <puerto>')
        for malo in ('C:\\100%\\oficina.py', 'C:\\a"b\\oficina.py', 'C:\\a\nb\\oficina.py'):
            try:
                servicio.texto_cmd(pythonw, malo, 8765, datos)
                comprobar(False, 'Windows: texto_cmd rechaza %r' % malo)
            except ValueError:
                comprobar(True, 'Windows: texto_cmd rechaza %r' % malo)

        # S1 · instalar
        r, l = Runner(), Lanzador()
        codigo, salida = captura(servicio.instalar, 8765, script, runner=r, lanzar=l)
        comprobar(codigo == 0 and os.path.isfile(cmd), 'Windows: instalar escribe el .cmd en la carpeta Inicio y sale con 0 (%s)' % salida.strip()[:80])
        comprobar(len(l.llamadas) == 1 and l.llamadas[0][0] == [pythonw, '-B', script, '--serve', '8765']
                  and l.llamadas[0][1].get('NAVIS_RAID_DATA') == datos and l.llamadas[0][1].get('NAVIS_RAID_SERVICIO') == '1',
                  'Windows: instalar arranca el servidor ya, una vez, con pythonw, --serve 8765 y NAVIS_RAID_DATA (%r)' % (l.llamadas,))
        comprobar(not r.llamadas, 'Windows: instalar sin servicio previo no llama a tasklist ni taskkill (%r)' % (r.llamadas,))
        with open(cmd, encoding='utf-8') as fh:
            leido = servicio.leer_cmd(fh.read())
        comprobar(leido.get('script') == script and leido.get('puerto') == 8765 and leido.get('python') == pythonw,
                  'Windows: el .cmd escrito se lee de vuelta (%r)' % (leido,))
        # sin pythonw.exe al lado: python.exe
        os.remove(pythonw)
        l2 = Lanzador()
        captura(servicio.instalar, 8766, script, runner=Runner(), lanzar=l2)
        comprobar(l2.llamadas and l2.llamadas[0][0][0] == os.path.join(carpeta_py, 'python.exe'), 'Windows: sin pythonw.exe usa python.exe')
        open(pythonw, 'w', encoding='utf-8').close()
        os.remove(cmd)
        for malo in ('C:\\100%\\oficina.py', 'C:\\a"b\\oficina.py'):
            r, l = Runner(), Lanzador()
            codigo, salida = captura(servicio.instalar, 8765, malo, runner=r, lanzar=l)
            comprobar(codigo == 2 and not os.path.exists(cmd) and not l.llamadas and not r.llamadas,
                      'Windows: instalar con %r sale con 2 y no escribe ni lanza nada' % malo)
        # el puerto ocupado por otra cosa
        servicio.escucha = lambda puerto: True
        r, l = Runner(), Lanzador()
        codigo, _ = captura(servicio.instalar, 8765, script, runner=r, lanzar=l)
        comprobar(codigo == 4 and not os.path.exists(cmd) and not l.llamadas, 'Windows: puerto ocupado por otro → 4, nada escrito ni lanzado')
        servicio.escucha = lambda puerto: False
        # lanzar falla (no hay permiso)
        l = Lanzador(lanza=PermissionError(13, 'Acceso denegado'))
        codigo, salida = captura(servicio.instalar, 8765, script, runner=Runner(), lanzar=l)
        comprobar(codigo == 1 and 'Acceso denegado' in salida, 'Windows: si lanzar falla, sale con 1 y dice el motivo')
        # verificar: nada escucha → 5
        os.remove(cmd)
        codigo, salida = captura(servicio.instalar, 8765, script, runner=Runner(), lanzar=Lanzador(), dormir=lambda s: None, verificar=True)
        comprobar(codigo == 5 and os.path.isfile(cmd), 'Windows: con verificar y nada escuchando, sale con 5 y queda instalado')

        # S2 · reinstalar y quitar
        def tasklist_con(imagen, pid_):
            def f(args):
                return 0
            r_ = Runner()

            def llamar(args):
                r_.llamadas.append(list(args))
                if args[0] == 'tasklist':
                    return types.SimpleNamespace(returncode=0, stderr='', stdout='"%s","%d","Console","1","20,000 K"\r\n' % (imagen, pid_) if imagen else 'INFO: No tasks are running which match the specified criteria.\r\n')
                return types.SimpleNamespace(returncode=0, stdout='', stderr='')
            llamar.llamadas = r_.llamadas
            return llamar

        nada = lambda s_: None
        vivo = [True]                                              # lo que escucha en 8765; taskkill lo apaga
        servicio.escucha = lambda puerto: vivo[0] and puerto == 8765

        def matando(f):
            def g(args):
                if args[0] == 'taskkill':
                    vivo[0] = False
                return f(args)
            g.llamadas = f.llamadas if hasattr(f, 'llamadas') else []
            return g

        os.makedirs(datos, exist_ok=True)
        vivo[0] = True
        escribe(pid, '4321 8765')
        r = tasklist_con('pythonw.exe', 4321)
        rr = matando(r)
        codigo, salida = captura(servicio.quitar, runner=rr, dormir=nada)
        comprobar(codigo == 0 and ['taskkill', '/PID', '4321', '/F'] in r.llamadas, 'Windows: quitar con tasklist = pythonw.exe llama a taskkill /PID 4321 /F (%r)' % (r.llamadas,))
        comprobar(any(c[0] == 'tasklist' and '/FO' in c and 'CSV' in c and 'PID eq 4321' in c for c in r.llamadas), 'Windows: quitar consulta tasklist /FI "PID eq N" /FO CSV /NH')
        comprobar(not os.path.exists(cmd) and not os.path.exists(pid), 'Windows: quitar borra el .cmd y el .pid')
        # PID reciclado: otra imagen
        servicio._escribir(cmd, 'x')
        vivo[0] = True
        escribe(pid, '4321 8765')
        r = tasklist_con('notepad.exe', 4321)
        codigo, _ = captura(servicio.quitar, runner=r, dormir=nada)
        comprobar(codigo == 0 and not any(c[0] == 'taskkill' for c in r.llamadas) and not os.path.exists(cmd) and not os.path.exists(pid),
                  'Windows: PID reciclado (otra imagen) → no llama a taskkill y quita igual')
        # el proceso ya no existe
        servicio._escribir(cmd, 'x')
        vivo[0] = True
        escribe(pid, '4321 8765')
        r = tasklist_con(None, 4321)
        codigo, _ = captura(servicio.quitar, runner=r, dormir=nada)
        comprobar(codigo == 0 and not any(c[0] == 'taskkill' for c in r.llamadas) and not os.path.exists(cmd), 'Windows: proceso ya muerto → sin taskkill, quita igual')
        # sin .pid
        servicio._escribir(cmd, 'x')
        r = Runner()
        codigo, _ = captura(servicio.quitar, runner=r, dormir=nada)
        comprobar(codigo == 0 and not r.llamadas and not os.path.exists(cmd), 'Windows: sin servicio.pid no llama a nada y quita el .cmd')
        # taskkill falla con otro error
        servicio._escribir(cmd, 'x')
        vivo[0] = True
        escribe(pid, '4321 8765')

        def mal_taskkill(args):
            if args[0] == 'tasklist':
                return types.SimpleNamespace(returncode=0, stderr='', stdout='"python.exe","4321","Console","1","20,000 K"\r\n')
            return types.SimpleNamespace(returncode=1, stdout='', stderr='ERROR: Access is denied.')
        codigo, salida = captura(servicio.quitar, runner=mal_taskkill, dormir=nada)
        comprobar(codigo == 1 and os.path.isfile(cmd) and os.path.isfile(pid) and 'Access is denied' in salida,
                  'Windows: si taskkill falla, sale con 1, deja el .cmd y el .pid y dice por qué')
        # el proceso murió entre tasklist y taskkill (taskkill 128): no es fallo
        def ya_muerto(args):
            if args[0] == 'tasklist':
                return types.SimpleNamespace(returncode=0, stderr='', stdout='"python.exe","4321","Console","1","20,000 K"\r\n')
            return types.SimpleNamespace(returncode=128, stdout='', stderr='ERROR: The process "4321" not found.')
        codigo, _ = captura(servicio.quitar, runner=ya_muerto, dormir=nada)
        comprobar(codigo == 0 and not os.path.exists(cmd), 'Windows: taskkill con «no encontrado» (128) no es fallo')
        # sin nada instalado
        r = Runner()
        codigo, salida = captura(servicio.quitar, runner=r, dormir=nada)
        comprobar(codigo == 0 and not r.llamadas and salida.strip(), 'Windows: quitar sin servicio sale con 0 y no llama a nada')
        # reinstalar: para al anterior antes de escribir y de lanzar
        vivo[0] = False
        captura(servicio.instalar, 8765, script, runner=Runner(), lanzar=Lanzador())
        vivo[0] = True
        escribe(pid, '999 8765')
        vivo[0] = True
        r, l = tasklist_con('python.exe', 999), Lanzador()
        codigo, _ = captura(servicio.instalar, 8765, script, runner=matando(r), lanzar=l, dormir=nada)
        comprobar(codigo == 0 and ['taskkill', '/PID', '999', '/F'] in r.llamadas and len(l.llamadas) == 1 and not os.path.exists(pid),
                  'Windows: reinstalar para antes al servidor anterior (taskkill) y lanza el nuevo')
        servicio._escribir(cmd, servicio.texto_cmd(pythonw, script, 8765, datos, {'NAVIS_RAID_SERVICIO': '1'}))
        vivo[0] = True
        escribe(pid, '999 8765')
        l3 = Lanzador()
        codigo, _ = captura(servicio.instalar, 8765, script, runner=mal_taskkill, lanzar=l3, dormir=nada)
        comprobar(codigo == 1 and not l3.llamadas, 'Windows: si no se puede parar el servidor anterior, instalar sale con 1 y no lanza otro')
        os.remove(cmd); os.remove(pid)

        # C1 · un .pid viejo cuyo PID se reciclo en otro python: la imagen es python pero nada escucha en el puerto → no se mata
        vivo[0] = False
        servicio._escribir(cmd, 'x')
        escribe(pid, '4321 8765')
        r = tasklist_con('pythonw.exe', 4321)
        codigo, _ = captura(servicio.quitar, runner=r, dormir=nada)
        comprobar(codigo == 0 and not any(c[0] == 'taskkill' for c in r.llamadas) and not os.path.exists(cmd) and not os.path.exists(pid),
                  'C1: imagen python pero nada escucha en el puerto del .pid → sin taskkill, quita y borra el .pid (%r)' % (r.llamadas,))
        # C1 · el .pid viejo de solo PID se lee como «sin puerto»: usa el del .cmd
        vivo[0] = False
        captura(servicio.instalar, 8765, script, runner=Runner(), lanzar=Lanzador())
        vivo[0] = True
        escribe(pid, '4321')
        r = tasklist_con('pythonw.exe', 4321)
        codigo, _ = captura(servicio.quitar, runner=matando(r), dormir=nada)
        comprobar(codigo == 0 and ['taskkill', '/PID', '4321', '/F'] in r.llamadas, 'C1: un .pid de solo PID sigue valiendo (el puerto sale del .cmd)')
        # C2 · tasklist que falla no es «no es python»
        vivo[0] = True
        servicio._escribir(cmd, 'x')
        escribe(pid, '4321 8765')

        def tasklist_falla(args):
            return types.SimpleNamespace(returncode=1, stdout='', stderr='ERROR: tasklist roto')
        codigo, salida = captura(servicio.quitar, runner=tasklist_falla, dormir=nada)
        comprobar(codigo == 1 and os.path.isfile(cmd) and os.path.isfile(pid), 'C2: tasklist con código 1 → quitar sale con 1 y deja el .cmd y el .pid (%s)' % salida.strip()[:60])
        if os.path.exists(pid):
            os.remove(pid)
        # C3 · quitar con el servidor vivo sin .pid: lo dice
        vivo[0] = True
        servicio._escribir(cmd, servicio.texto_cmd(pythonw, script, 8765, datos, {'NAVIS_RAID_SERVICIO': '1'}))
        codigo, salida = captura(servicio.quitar, runner=Runner(), dormir=nada)
        comprobar(codigo == 0 and '8765' in salida and ('Horario de salida' in salida or 'Clock out' in salida),
                  'C3: quitar con algo escuchando aún en el puerto del .cmd lo dice (%s)' % salida.strip().replace('\n', ' | ')[:120])
        # C3 · reinstalar con el puerto aún ocupado tras parar → 4
        servicio._escribir(cmd, servicio.texto_cmd(pythonw, script, 8765, datos, {'NAVIS_RAID_SERVICIO': '1'}))
        escribe(pid, '4321 8765')
        antes = open(cmd, encoding='utf-8').read()
        l4 = Lanzador()
        codigo, salida = captura(servicio.instalar, 8765, script, runner=tasklist_con('pythonw.exe', 4321), lanzar=l4, dormir=nada)   # taskkill «mata» pero sigue escuchando
        comprobar(codigo == 4 and not l4.llamadas and open(cmd, encoding='utf-8').read() == antes,
                  'C3: reinstalar con el puerto aún ocupado tras parar → 4, sin lanzar ni reescribir (%r)' % codigo)
        os.remove(cmd)
        if os.path.exists(pid):
            os.remove(pid)
        servicio.escucha = lambda puerto: False

        # C4 · el .cmd va con CRLF
        captura(servicio.instalar, 8765, script, runner=Runner(), lanzar=Lanzador())
        with open(cmd, 'rb') as fh:
            crudo = fh.read()
        comprobar(b'\r\n' in crudo and b'\r\r\n' not in crudo and crudo.count(b'\n') == crudo.count(b'\r\n'),
                  'C4: el .cmd escrito lleva \\r\\n en todas las líneas')
        comprobar(servicio.leer_cmd(crudo.decode('utf-8')).get('puerto') == 8765, 'C4: leer_cmd lee el .cmd con CRLF')
        os.remove(cmd)

        # C5 · reabrir_flujos sin permiso de escritura no lanza
        sin_permiso = os.path.join(tmp, 'sin-permiso')
        os.makedirs(sin_permiso)
        os.chmod(sin_permiso, 0o500)
        servicio.datos = lambda: sin_permiso
        so, se = sys.stdout, sys.stderr
        try:
            sys.stdout = sys.stderr = None
            try:
                servicio.reabrir_flujos()
                lanzo = False
            except Exception:
                lanzo = True
        finally:
            sys.stdout, sys.stderr = so, se
            os.chmod(sin_permiso, 0o700)
        comprobar(not lanzo and (os.geteuid() != 0 or True), 'C5: reabrir_flujos con la carpeta de datos sin permiso de escritura no lanza')
        servicio.datos = lambda: datos

        # S3 · estado y leer
        captura(servicio.instalar, 8765, script, runner=Runner(), lanzar=Lanzador())
        info = servicio.leer()
        comprobar(info['instalado'] and info['archivo'] == cmd and info['script'] == script and info['puerto'] == 8765 and info['datos'] == datos,
                  'Windows: leer() lee el .cmd instalado (%r)' % (info,))
        comprobar(info['script_existe'] is False and info['python_existe'] is True, 'Windows: leer() dice si el script y el intérprete existen')
        servicio.escucha = lambda puerto: True
        codigo, salida = captura(servicio.estado)
        comprobar(codigo == 0 and cmd in salida and script in salida and datos in salida and '8765' in salida,
                  'Windows: --estado-servicio imprime la ruta, el script, los datos y el puerto (%s)' % salida.strip().replace('\n', ' | ')[:100])
        servicio.escucha = lambda puerto: False
        os.remove(cmd)
        codigo, salida = captura(servicio.estado)
        comprobar(codigo == 0 and cmd in salida, 'Windows: sin .cmd, --estado-servicio dice «no instalado» con la ruta esperada')
        # APPDATA manda cuando existe
        os.environ['APPDATA'] = os.path.join(tmp, 'roaming')
        comprobar(servicio.ruta_servicio() == os.path.join(tmp, 'roaming', 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup', 'navis-raid.cmd'),
                  'Windows: con APPDATA definida la carpeta Inicio cuelga de ella')
        os.environ.pop('APPDATA')

        # S5 · macOS y Linux no se ven afectados por lanzar ni por el pid
        servicio.sistema = lambda: 'Linux'
        servicio.home = lambda: casa
        l = Lanzador()
        r = Runner()
        captura(servicio.instalar, 8765, script, runner=r, lanzar=l)
        comprobar(not l.llamadas and r.llamadas and all(c[0] == 'systemctl' for c in r.llamadas), 'Linux: instalar no usa lanzar y solo llama a systemctl')
    finally:
        subprocess.run = real_run
        if appdata is not None:
            os.environ['APPDATA'] = appdata
        for n, v in guardado.items():
            setattr(servicio, n, v)


def en_doctor(tmp, comprobar):
    """La comprobación 6: `oficina.py --doctor` de verdad, en un subproceso con HOME temporal."""
    sistema = platform.system()
    if sistema not in ('Darwin', 'Linux'):
        print('· --doctor con servicio: se salta (solo Darwin y Linux)')
        return
    copia = os.path.join(tmp, 'oficina')
    shutil.copytree(AQUI, copia, ignore=IGNORAR)
    casa = os.path.join(tmp, 'casa-doctor')
    claude = os.path.join(tmp, 'claude-doctor')
    os.makedirs(os.path.join(claude, 'projects'))
    os.makedirs(casa)
    datos = os.path.join(tmp, 'datos-doctor')
    viejo = os.path.join(tmp, 'plugin-viejo', 'oficina.py')           # esta carpeta ya no existe
    base = {k: v for k, v in os.environ.items() if not k.startswith('NAVIS_RAID_')}
    base.update(CLAUDE_CONFIG_DIR=claude, NAVIS_RAID_SOLO_TERMINAL='1', PYTHONDONTWRITEBYTECODE='1', HOME=casa, NAVIS_RAID_DATA=datos)

    def instalar_a_mano(script):
        if sistema == 'Darwin':
            ruta = os.path.join(casa, 'Library', 'LaunchAgents', 'navis-raid.plist')
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with open(ruta, 'wb') as fh:
                plistlib.dump({'Label': 'navis-raid', 'ProgramArguments': [sys.executable, '-B', script, '--serve', '8765'],
                               'EnvironmentVariables': {'NAVIS_RAID_DATA': datos}}, fh)
        else:
            ruta = os.path.join(casa, '.config', 'systemd', 'user', 'navis-raid.service')
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with open(ruta, 'w', encoding='utf-8') as fh:
                fh.write('[Service]\nExecStart="%s" -B "%s" --serve 8765\nEnvironment="NAVIS_RAID_DATA=%s"\n' % (sys.executable, script, datos))
        return ruta

    def doctor():
        r = subprocess.run([sys.executable, 'oficina.py', '--doctor'], capture_output=True, text=True, encoding='utf-8', errors='replace', env=base, cwd=copia, timeout=180)
        return r.stdout

    salida = doctor()
    comprobar(not any('navis-raid' in l and ('plist' in l or 'service' in l) for l in salida.splitlines()),
              '--doctor sin servicio instalado no dice nada del servicio')
    ruta = instalar_a_mano(viejo)
    lineas = [l for l in doctor().splitlines() if viejo in l]
    comprobar(bool(lineas) and lineas[0].startswith('✗') and '/navis-raid:start' in lineas[0],
              '--doctor marca como fallo un servicio cuyo oficina.py ya no existe y dice cómo arreglarlo (%s)' % (lineas[0][:90] if lineas else 'sin línea'))
    os.remove(ruta)
    vivo = os.path.join(copia, 'oficina.py')
    instalar_a_mano(vivo)
    lineas = [l for l in doctor().splitlines() if vivo in l and ('plist' in l or 'service' in l)]
    comprobar(bool(lineas) and lineas[0].startswith('✓'), '--doctor da por bueno un servicio cuyo oficina.py existe (%s)' % (lineas[0][:90] if lineas else 'sin línea'))


# ---------- E8e-2a ----------

class RunnerMsg(Runner):
    """Un runner falso que contesta con el código y el mensaje de error que se le pidan."""

    def __init__(self, codigo=0, stderr=''):
        Runner.__init__(self, falla=lambda a: codigo)
        self.stderr = stderr

    def __call__(self, args):
        r = Runner.__call__(self, args)
        r.stderr = self.stderr
        return r


@contextlib.contextmanager
def entorno(**variables):
    """Fija (o, con None, quita) variables de os.environ mientras dura el bloque."""
    antes = {k: os.environ.get(k) for k in variables}
    try:
        for k, v in variables.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in antes.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def en_proceso_e8e2a(servicio, tmp, comprobar):
    """Las specs S1 a S5 de la E8e-2a, dentro del proceso: HOME temporal, runner falso, nada real."""
    real_run = subprocess.run
    subprocess.run = sin_subprocess_real
    guardado = {n: getattr(servicio, n) for n in ('home', 'sistema', 'uid', 'datos', 'python', 'escucha')}
    try:
        casa = os.path.join(tmp, 'casa-e8e2a')
        os.makedirs(casa)
        hostil = os.path.join(tmp, 'a b%c%%d"e$f$$g\\h')               # espacio, %, %%, comilla, $, $$ y barra
        servicio.home = lambda: casa
        servicio.uid = lambda: 501
        servicio.datos = lambda: hostil
        servicio.python = lambda: '/usr/bin/python3'
        servicio.escucha = lambda puerto: False
        unit = os.path.join(casa, '.config', 'systemd', 'user', 'navis-raid.service')
        plist = os.path.join(casa, 'Library', 'LaunchAgents', 'navis-raid.plist')
        script = os.path.join(hostil, 'p %1 "q" $x', 'oficina.py')
        quitar_todo = ('CLAUDE_CONFIG_DIR', 'NAVIS_RAID_CONFIG', 'NAVIS_RAID_SOLO_TERMINAL', 'NAVIS_RAID_SERVICIO')
        sin_variables = dict.fromkeys(quitar_todo)

        # S1 · el unit no admite inyección y duplica los %
        servicio.sistema = lambda: 'Linux'
        with entorno(**sin_variables):
            codigo, _ = captura(servicio.instalar, 8766, script, runner=Runner())
        texto = open(unit, encoding='utf-8').read() if os.path.isfile(unit) else ''
        leido = servicio.leer_unit(texto)
        comprobar(codigo == 0 and leido.get('script') == script and leido.get('datos') == hostil and leido.get('puerto') == 8766,
                  'S1 unit: una ruta con espacio, %%, %%%%, comilla, $ y barra hace el viaje de ida y vuelta (%r)' % (leido,))
        lineas_con_ruta = [l for l in texto.splitlines() if l.startswith(('ExecStart=', 'Environment=', 'StandardOutput=', 'StandardError='))]
        comprobar(len(lineas_con_ruta) >= 4 and all('%' not in l.replace('%%', '') for l in lineas_con_ruta),
                  'S1 unit: todo % de ExecStart, Environment y de las rutas del log (StandardOutput/StandardError) va duplicado')
        for malo in ('\n', '\r'):
            if os.path.exists(unit):
                os.remove(unit)
            r = Runner()
            codigo, salida = captura(servicio.instalar, 8766, script + malo + 'ExecStartPre=/bin/x', runner=r)
            comprobar(codigo != 0 and not os.path.exists(unit) and not r.llamadas and salida.strip(),
                      'S1 unit: una ruta con %r da error claro, no escribe el archivo ni llama a systemctl (%s)' % (malo, salida.strip()[:60]))
        servicio.datos = lambda: hostil + '\nWorkingDirectory=/'
        r = Runner()
        codigo, salida = captura(servicio.instalar, 8766, script, runner=r)
        comprobar(codigo != 0 and not os.path.exists(unit) and not r.llamadas, 'S1 unit: una carpeta de datos con salto de línea tampoco se escribe')
        servicio.datos = lambda: hostil

        # S2 · correr: lista de argumentos y sin shell
        llamadas = []

        def grabadora(*a, **k):
            llamadas.append((a, k))
            return types.SimpleNamespace(returncode=0, stdout='', stderr='')
        subprocess.run = grabadora
        servicio.correr(('echo', 'a b; rm -rf x'))
        subprocess.run = sin_subprocess_real
        comprobar(len(llamadas) == 1 and isinstance(llamadas[0][0][0], list) and llamadas[0][0][0] == ['echo', 'a b; rm -rf x']
                  and not llamadas[0][1].get('shell') and llamadas[0][1].get('timeout'),
                  'S2 correr: pasa una lista de argumentos, sin shell y con tiempo límite (%r)' % (llamadas,))

        # S3 · quitar no miente
        servicio.sistema = lambda: 'Darwin'
        for codigo_bootout, tolerado in ((3, True), (113, True), (5, False)):
            with entorno(**sin_variables):
                captura(servicio.instalar, 8766, script, runner=Runner())
            r = RunnerMsg(codigo_bootout, 'Boot-out failed')
            codigo, salida = captura(servicio.quitar, runner=r)
            existe = os.path.exists(plist)
            if tolerado:
                comprobar(codigo == 0 and not existe and r.llamadas, 'S3 macOS: bootout con código %d (no estaba cargado) se tolera y el plist se borra' % codigo_bootout)
            else:
                comprobar(codigo != 0 and existe and 'Boot-out failed' in salida and 'quitado' not in salida and 'removed' not in salida,
                          'S3 macOS: bootout con código %d no borra el plist, dice el error y sale con código distinto de 0 (%s)' % (codigo_bootout, salida.strip()[:60]))
            if existe:
                os.remove(plist)
        servicio.sistema = lambda: 'Linux'
        for mensaje, tolerado in (('Failed to disable unit: Unit file navis-raid.service does not exist.', True),
                                  ('Failed to connect to bus: No medium found', False)):
            with entorno(**sin_variables):
                captura(servicio.instalar, 8766, script, runner=Runner())
            r = RunnerMsg(1, mensaje)
            codigo, salida = captura(servicio.quitar, runner=r)
            existe = os.path.exists(unit)
            if tolerado:
                comprobar(codigo == 0 and not existe, 'S3 Linux: disable --now con «unit no existe» se tolera y el unit se borra')
            else:
                comprobar(codigo != 0 and existe and 'No medium found' in salida and 'quitado' not in salida and 'removed' not in salida,
                          'S3 Linux: disable --now con otro fallo no borra el unit, dice el error y sale con código distinto de 0')
            if existe:
                os.remove(unit)

        # S4 · las variables de la terminal llegan al servicio
        valores = {'CLAUDE_CONFIG_DIR': os.path.join(tmp, 'claude cfg'), 'NAVIS_RAID_CONFIG': os.path.join(tmp, 'mi "config".json'),
                   'NAVIS_RAID_SOLO_TERMINAL': '1'}
        esperado = dict(valores)
        servicio.sistema = lambda: 'Darwin'
        with entorno(NAVIS_RAID_SERVICIO=None, **valores):
            captura(servicio.instalar, 8766, script, runner=Runner())
        p = plistlib.loads(open(plist, 'rb').read())['EnvironmentVariables']
        comprobar(p.get('NAVIS_RAID_DATA') == hostil and all(p.get(k) == v for k, v in valores.items()) and p.get('NAVIS_RAID_SERVICIO') == '1',
                  'S4 plist: lleva NAVIS_RAID_DATA, CLAUDE_CONFIG_DIR, NAVIS_RAID_CONFIG, NAVIS_RAID_SOLO_TERMINAL y NAVIS_RAID_SERVICIO=1 (%r)' % (p,))
        info = servicio.leer_plist(open(plist, 'rb').read())
        comprobar(info.get('entorno') == esperado, 'S4 leer_plist: da las variables copiadas (%r)' % (info.get('entorno'),))
        servicio.sistema = lambda: 'Linux'
        with entorno(NAVIS_RAID_SERVICIO=None, **valores):
            captura(servicio.instalar, 8766, script, runner=Runner())
        texto = open(unit, encoding='utf-8').read()
        info = servicio.leer_unit(texto)
        comprobar(info.get('entorno') == esperado and info.get('datos') == hostil and 'NAVIS_RAID_SERVICIO=1' in texto,
                  'S4 unit/leer_unit: las mismas variables, con comillas, y NAVIS_RAID_SERVICIO=1 (%r)' % (info.get('entorno'),))
        e, salida = captura(servicio.estado)
        comprobar(e == 0 and all(k in salida and v in salida for k, v in valores.items()), 'S4 --estado-servicio: muestra las variables')
        parcial = {'CLAUDE_CONFIG_DIR': valores['CLAUDE_CONFIG_DIR']}
        with entorno(NAVIS_RAID_CONFIG='', NAVIS_RAID_SOLO_TERMINAL=None, NAVIS_RAID_SERVICIO=None, CLAUDE_CONFIG_DIR=parcial['CLAUDE_CONFIG_DIR']):
            captura(servicio.instalar, 8766, script, runner=Runner())
        info = servicio.leer_unit(open(unit, encoding='utf-8').read())
        e, salida = captura(servicio.estado)
        comprobar(info.get('entorno') == parcial and 'NAVIS_RAID_CONFIG' not in salida and 'NAVIS_RAID_SOLO_TERMINAL' not in salida,
                  'S4: las variables no definidas o vacías no aparecen (ni en el unit ni en --estado-servicio) (%r)' % (info.get('entorno'),))

        # S5 · puerto ocupado: no hay bucle
        la_linea = servicio.aviso_puerto_ocupado(8765)
        comprobar('8765' in la_linea and 'Navis Raid' in la_linea, 'S5: el aviso de puerto ocupado dice el puerto (%s)' % la_linea)
        os.makedirs(hostil, exist_ok=True)
        with open(servicio.ruta_log(), 'w', encoding='utf-8') as fh:
            fh.write('http://localhost:8765/  (Ctrl+C para parar)\n' + la_linea + '\n')
        e, salida = captura(servicio.estado)
        comprobar(la_linea in salida, 'S5 --estado-servicio: muestra la última línea de servicio.log si es el aviso de puerto ocupado')
        servicio.escucha = lambda puerto: True
        e, salida = captura(servicio.estado)
        comprobar(la_linea not in salida, 'S5 --estado-servicio: si algo escucha en el puerto, el aviso viejo del log no se muestra')
        servicio.escucha = lambda puerto: False
        with open(servicio.ruta_log(), 'a', encoding='utf-8') as fh:
            fh.write('otra cosa\n')
        e, salida = captura(servicio.estado)
        comprobar(la_linea not in salida, 'S5 --estado-servicio: si la última línea no es el aviso, no se muestra')
        import textos
        for idioma in ('es', 'en'):
            textos_idioma = textos.idioma
            textos.idioma = lambda i=idioma: i
            try:
                linea = servicio.aviso_puerto_ocupado(8765)
            finally:
                textos.idioma = textos_idioma
            with open(servicio.ruta_log(), 'w', encoding='utf-8') as fh:
                fh.write(linea + '\n')
            comprobar(servicio.ultimo_aviso() == linea, 'S5: el aviso escrito en «%s» se reconoce al leer el log (%s)' % (idioma, linea[:50]))

        _puerto_ocupado(servicio, comprobar)
    finally:
        subprocess.run = real_run
        for n, v in guardado.items():
            setattr(servicio, n, v)


def _puerto_ocupado(servicio, comprobar):
    """S5: `main(['--serve', puerto])` con el puerto ocupado sale con 0 como servicio y con 3 en la terminal."""
    import oficina
    ocupante = socket.socket()
    simular = False
    try:
        ocupante.bind(('127.0.0.1', 0))
        ocupante.listen(1)
        puerto = ocupante.getsockname()[1]
    except OSError:
        simular, puerto = True, 54321              # el sandbox no deja hacer bind: se simula el OSError de servidor()
    original = oficina.servidor
    if simular:
        def ocupado(p, token):
            raise OSError(errno.EADDRINUSE, 'Address already in use')
        oficina.servidor = ocupado
    try:
        for como_servicio, esperado in (('1', 0), (None, 3)):
            with entorno(NAVIS_RAID_SERVICIO=como_servicio):
                err = io.StringIO()
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                    codigo = oficina.main(['--serve', str(puerto)])
            comprobar(codigo == esperado and str(puerto) in err.getvalue() and 'Navis Raid' in err.getvalue() and 'Traceback' not in err.getvalue(),
                      'S5 --serve con el puerto %d ocupado %s: sale con %d y escribe el aviso en stderr (%s%r)'
                      % (puerto, 'como servicio' if como_servicio else 'en la terminal', esperado, 'simulado, ' if simular else '', codigo))
    finally:
        oficina.servidor = original
        ocupante.close()


def en_doctor_e8e2a(servicio, tmp, comprobar):
    """S6 (y el aviso de S5): `oficina.py --doctor` de verdad, en un subproceso con HOME temporal."""
    sistema = platform.system()
    if sistema not in ('Darwin', 'Linux'):
        print('· --doctor E8e-2a: se salta (solo Darwin y Linux)')
        return
    copia = os.path.join(tmp, 'oficina-e8e2a')
    shutil.copytree(AQUI, copia, ignore=IGNORAR)
    casa = os.path.join(tmp, 'casa-doctor2')
    claude = os.path.join(tmp, 'claude-doctor2')
    os.makedirs(os.path.join(claude, 'projects'))
    os.makedirs(casa)
    datos = os.path.join(tmp, 'datos-doctor2')
    os.makedirs(datos)
    libre = socket.socket()
    try:
        libre.bind(('127.0.0.1', 0))
        puerto = libre.getsockname()[1]
    except OSError:
        puerto = 54322
    finally:
        libre.close()
    py_muerto = os.path.join(tmp, 'ya-no-existe', 'bin', 'python3')
    vivo = os.path.join(copia, 'oficina.py')
    base = {k: v for k, v in os.environ.items() if not k.startswith('NAVIS_RAID_')}
    base.update(CLAUDE_CONFIG_DIR=claude, NAVIS_RAID_SOLO_TERMINAL='1', PYTHONDONTWRITEBYTECODE='1', HOME=casa, NAVIS_RAID_DATA=datos)
    if sistema == 'Darwin':
        ruta = os.path.join(casa, 'Library', 'LaunchAgents', 'navis-raid.plist')
        os.makedirs(os.path.dirname(ruta))
        with open(ruta, 'wb') as fh:
            plistlib.dump({'Label': 'navis-raid', 'ProgramArguments': [py_muerto, '-B', vivo, '--serve', str(puerto)],
                           'EnvironmentVariables': {'NAVIS_RAID_DATA': datos}}, fh)
    else:
        ruta = os.path.join(casa, '.config', 'systemd', 'user', 'navis-raid.service')
        os.makedirs(os.path.dirname(ruta))
        with open(ruta, 'w', encoding='utf-8') as fh:
            fh.write('[Service]\nExecStart="%s" -B "%s" --serve %d\nEnvironment="NAVIS_RAID_DATA=%s"\n' % (py_muerto, vivo, puerto, datos))
    aviso = servicio.aviso_puerto_ocupado(puerto)
    with open(os.path.join(datos, 'servicio.log'), 'w', encoding='utf-8') as fh:
        fh.write(aviso + '\n')
    r = subprocess.run([sys.executable, 'oficina.py', '--doctor'], capture_output=True, text=True, encoding='utf-8', errors='replace', env=base, cwd=copia, timeout=180)
    lineas = [l for l in r.stdout.splitlines() if py_muerto in l]
    comprobar(bool(lineas) and lineas[0].startswith('✗') and '/navis-raid:start' in lineas[0],
              'S6 --doctor marca como fallo un servicio cuyo intérprete guardado ya no existe y dice cómo arreglarlo (%s)' % (lineas[0][:90] if lineas else 'sin línea'))
    comprobar(not any(l.startswith('✓') and 'Servicio:' in l for l in r.stdout.splitlines()),
              'S6 --doctor no da por bueno ese servicio')
    comprobar(aviso in r.stdout, 'S5 --doctor muestra el aviso de puerto ocupado de servicio.log cuando nada escucha')
    e = subprocess.run([sys.executable, 'oficina.py', '--estado-servicio'], capture_output=True, text=True, encoding='utf-8', errors='replace', env=base, cwd=copia, timeout=60)
    comprobar(aviso in e.stdout, 'S5 oficina.py --estado-servicio (subproceso) muestra ese aviso')


# ---------- E8e-4 ----------

def en_proceso_e8e4(servicio, tmp, comprobar):
    """S1 de la E8e-4: puerto ocupado antes de instalar. HOME temporal, runner falso y `escucha` sustituida (nunca real)."""
    real_run = subprocess.run
    subprocess.run = sin_subprocess_real
    guardado = {n: getattr(servicio, n) for n in ('home', 'sistema', 'uid', 'datos', 'python', 'escucha')}
    try:
        casa = os.path.join(tmp, 'casa-e8e4')
        os.makedirs(casa)
        datos = os.path.join(tmp, 'datos-e8e4')
        codigo_1 = os.path.join(tmp, 'plugin-e8e4', 'oficina.py')
        plist = os.path.join(casa, 'Library', 'LaunchAgents', 'navis-raid.plist')
        servicio.home = lambda: casa
        servicio.uid = lambda: 501
        servicio.datos = lambda: datos
        servicio.python = lambda: '/usr/bin/python3'
        servicio.sistema = lambda: 'Darwin'

        # S1 · ocupado por otra cosa y sin servicio: no instala nada
        servicio.escucha = lambda puerto: puerto == 18765
        r = Runner()
        codigo, salida = captura(servicio.instalar, 18765, codigo_1, runner=r)
        comprobar(codigo == 4 and not r.llamadas and not os.path.exists(plist) and not os.path.isdir(datos),
                  'E8e-4 S1: puerto ocupado por otra cosa: código 4, ningún runner y nada escrito (%r, %r)' % (codigo, r.llamadas))
        comprobar('18765' in salida and '/navis-raid:start 18766' in salida and 'Ctrl+C' in salida,
                  'E8e-4 S1: el mensaje dice el puerto, cómo pararlo y el comando con el puerto sugerido (%s)' % salida.strip()[:120])

        # S1 · el puerto sugerido salta los que también están ocupados
        servicio.escucha = lambda puerto: puerto in (18765, 18766, 18767)
        codigo, salida = captura(servicio.instalar, 18765, codigo_1, runner=Runner())
        comprobar(codigo == 4 and '/navis-raid:start 18768' in salida,
                  'E8e-4 S1: el puerto sugerido salta los ocupados (18766 y 18767) y es el 18768 (%s)' % salida.strip()[:120])
        comprobar(servicio.puerto_libre(18766, intentos=2) is None, 'E8e-4 S1: sin libre en los intentos que se piden, no sugiere ninguno')

        # S1 · ocupado por nuestro propio servicio con ese puerto: reinstalación
        servicio.escucha = lambda puerto: False
        codigo, _ = captura(servicio.instalar, 18765, codigo_1, runner=Runner())
        comprobar(codigo == 0 and os.path.isfile(plist), 'E8e-4 S1: (preparación) instalar con el puerto libre da 0')
        servicio.escucha = lambda puerto: puerto == 18765
        r = Runner()
        codigo, _ = captura(servicio.instalar, 18765, codigo_1, runner=r)
        comprobar(codigo == 0 and ['launchctl', 'bootstrap', 'gui/501', plist] in r.llamadas,
                  'E8e-4 S1: el puerto lo ocupa nuestro servicio, instalado con ese mismo puerto: reinstala y da 0 (%r)' % (codigo,))
    finally:
        subprocess.run = real_run
        for n, v in guardado.items():
            setattr(servicio, n, v)


def en_verificar_e8e4(servicio, tmp, comprobar):
    """S2 de la E8e-4: `instalar(verificar=True)` espera a que escuche. `dormir` y `escucha` sustituidas: no espera de verdad."""
    real_run = subprocess.run
    subprocess.run = sin_subprocess_real
    guardado = {n: getattr(servicio, n) for n in ('home', 'sistema', 'uid', 'datos', 'python', 'escucha')}
    try:
        casa = os.path.join(tmp, 'casa-e8e4v')
        os.makedirs(casa)
        datos = os.path.join(tmp, 'datos-e8e4v')
        codigo_1 = os.path.join(tmp, 'plugin-e8e4v', 'oficina.py')
        plist = os.path.join(casa, 'Library', 'LaunchAgents', 'navis-raid.plist')
        servicio.home = lambda: casa
        servicio.uid = lambda: 501
        servicio.datos = lambda: datos
        servicio.python = lambda: '/usr/bin/python3'
        servicio.sistema = lambda: 'Darwin'
        servicio.escucha = lambda puerto: False
        pausas = []

        # S2 · nada llega a escuchar: 5, instalado, con la última línea del log
        codigo, salida = captura(servicio.instalar, 18770, codigo_1, runner=Runner(), dormir=pausas.append, verificar=True)
        comprobar(codigo == 5 and os.path.isfile(plist) and 'servicio.log' in salida and '--estado-servicio' in salida,
                  'E8e-4 S2: no llega a escuchar: código 5, el archivo queda escrito y remite a --estado-servicio (%r)' % (codigo,))
        comprobar(len(pausas) == 10 and set(pausas) == {0.5}, 'E8e-4 S2: espera 10 veces 0,5 s (unos 5 s) con el `dormir` inyectado (%r)' % (pausas,))
        with open(servicio.ruta_log(), 'w', encoding='utf-8') as fh:
            fh.write('primera línea\nTraceback: algo se rompió al arrancar\n\n')
        codigo, salida = captura(servicio.instalar, 18770, codigo_1, runner=Runner(), dormir=lambda s: None, verificar=True)
        comprobar(codigo == 5 and 'Traceback: algo se rompió al arrancar' in salida and 'primera línea' not in salida,
                  'E8e-4 S2: el mensaje del 5 incluye la última línea de servicio.log (%s)' % salida.strip()[-120:])

        # S2 · camino feliz: escucha a la primera tras instalar
        mirados = []
        servicio.escucha = lambda puerto: mirados.append(puerto) or len(mirados) >= 2     # 1.ª: antes de instalar (libre); 2.ª: ya instalado (escucha)
        pausas = []
        codigo, salida = captura(servicio.instalar, 18771, codigo_1, runner=Runner(), dormir=pausas.append, verificar=True)
        comprobar(codigo == 0 and len(pausas) == 0 and 'http://127.0.0.1:18771/' in salida,
                  'E8e-4 S2: si escucha en cuanto se mira tras instalar, da 0 sin pausas (%r, %r)' % (codigo, pausas))

        # sin `verificar` no espera ni cambia el resultado
        servicio.escucha = lambda puerto: False
        pausas = []
        codigo, _ = captura(servicio.instalar, 18772, codigo_1, runner=Runner(), dormir=pausas.append)
        comprobar(codigo == 0 and not pausas, 'E8e-4 S2: sin `verificar` (el valor por defecto) no espera: da 0 y no duerme')

        # `oficina.py --instalar-servicio` pide la verificación (con `instalar` espiada: no instala nada)
        import oficina
        llamadas = []
        original = servicio.instalar
        servicio.instalar = lambda *a, **k: llamadas.append((a, k)) or 0
        try:
            codigo = oficina.main(['--instalar-servicio', '18773'])
        finally:
            servicio.instalar = original
        comprobar(codigo == 0 and len(llamadas) == 1 and llamadas[0][0][0] == 18773 and llamadas[0][1].get('verificar') is True,
                  'E8e-4 S2: `oficina.py --instalar-servicio 18773` llama a instalar con verificar=True (%r)' % (llamadas,))
    finally:
        subprocess.run = real_run
        for n, v in guardado.items():
            setattr(servicio, n, v)


if __name__ == '__main__':
    sys.exit(main())
