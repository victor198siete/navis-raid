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
        servicio.sistema = lambda: 'Windows'
        r = Runner()
        codigo, salida = captura(servicio.instalar, 8765, codigo_1, runner=r)
        comprobar(codigo != 0 and not r.llamadas and salida.strip() and not os.path.exists(os.path.join(casa, 'Library', 'LaunchAgents', 'navis-raid.plist')),
                  'otro sistema: error claro, nada escrito ni ejecutado (%s)' % salida.strip()[:60])
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
        r = subprocess.run([sys.executable, 'oficina.py', '--doctor'], capture_output=True, text=True, env=base, cwd=copia, timeout=180)
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
    r = subprocess.run([sys.executable, 'oficina.py', '--doctor'], capture_output=True, text=True, env=base, cwd=copia, timeout=180)
    lineas = [l for l in r.stdout.splitlines() if py_muerto in l]
    comprobar(bool(lineas) and lineas[0].startswith('✗') and '/navis-raid:start' in lineas[0],
              'S6 --doctor marca como fallo un servicio cuyo intérprete guardado ya no existe y dice cómo arreglarlo (%s)' % (lineas[0][:90] if lineas else 'sin línea'))
    comprobar(not any(l.startswith('✓') and 'Servicio:' in l for l in r.stdout.splitlines()),
              'S6 --doctor no da por bueno ese servicio')
    comprobar(aviso in r.stdout, 'S5 --doctor muestra el aviso de puerto ocupado de servicio.log cuando nada escucha')
    e = subprocess.run([sys.executable, 'oficina.py', '--estado-servicio'], capture_output=True, text=True, env=base, cwd=copia, timeout=60)
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
