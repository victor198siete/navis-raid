"""Navis Raid como servicio de usuario (E8e-1): un agente de launchd en macOS o una unidad de systemd en Linux.

El servicio arranca solo al iniciar sesión y se relanza si el servidor se cae (no si sale limpio, con código 0). Lo usan
las opciones de `oficina.py`:
  --instalar-servicio [puerto]   escribe el archivo del servicio y lo carga (8765 por defecto); si ya existía, lo reescribe
  --quitar-servicio              lo para y borra el archivo (si no existe, lo dice y sale con 0)
  --estado-servicio              si está instalado, a qué `oficina.py` y a qué carpeta de datos apunta, si algo escucha

El servicio recibe las variables que importan de la terminal (`VARIABLES`) y `NAVIS_RAID_SERVICIO=1`, con lo que
`--serve` sabe que lo lanza el servicio: con el puerto ocupado sale con 0 (launchd no relanza tras un 0) en vez de
reintentar para siempre.

Fuera de la carpeta del programa solo escribe el archivo del servicio:
  macOS  ~/Library/LaunchAgents/navis-raid.plist     (se carga con launchctl bootstrap gui/<uid>)
  Linux  ~/.config/systemd/user/navis-raid.service   (se activa con systemctl --user enable --now)
y, dentro de la carpeta de datos, el `servicio.log` donde el servicio deja su salida.

La lógica va separada de los efectos para poder probarla sin instalar nada:
  - `texto_plist` y `texto_unit` son funciones puras (parámetros → texto);
  - `leer_plist` y `leer_unit` hacen el camino de vuelta (texto → parámetros);
  - `correr` ejecuta `launchctl`/`systemctl` con lista de argumentos, sin shell; `instalar` y `quitar` reciben un `runner`
    (por defecto `correr`) que las pruebas sustituyen por uno falso;
  - la carpeta HOME, el sistema, el uid, el intérprete, la carpeta de datos y la prueba del puerto se resuelven en una
    función cada una (`home`, `sistema`, `uid`, `python`, `datos`, `escucha`), para sustituirlas en las pruebas.
"""
import os
import platform
import plistlib
import re
import shlex
import socket
import subprocess
import time

import config
from textos import t

NOMBRE = 'navis-raid'
PUERTO = 8765
TIEMPO_ORDEN_S = 30        # tope de cada launchctl/systemctl
INTENTOS_SUGERIDO = 20     # cuántos puertos prueba `puerto_libre` a partir del ocupado
ESPERA_ARRANQUE_S = 5      # cuánto espera `instalar(verificar=True)` a que el servicio escuche, y cada cuánto mira
PAUSA_ARRANQUE_S = 0.5
# Variables de la terminal que se copian al servicio si están definidas y no vacías (NAVIS_RAID_DATA va aparte: es la carpeta de datos).
VARIABLES = ('CLAUDE_CONFIG_DIR', 'NAVIS_RAID_CONFIG', 'NAVIS_RAID_SOLO_TERMINAL')
SERVICIO = 'NAVIS_RAID_SERVICIO'      # =1 en el plist y el unit: `--serve` sabe que corre como servicio
# `launchctl bootout` de algo que no está cargado: 3 («No such process», lo que da macOS hoy) o 113 («Could not find
# specified service»); ver `launchctl error posix 3` y `launchctl error bootstrap 113`.
BOOTOUT_NO_CARGADO = (3, 113)
SYSTEMCTL_NO_EXISTE = ('does not exist', 'not found', 'not loaded', 'no such file')   # mensajes de `disable --now` sin unit


# ---------- el entorno (se sustituye en las pruebas) ----------

def home():
    """La carpeta HOME, resuelta aquí y solo aquí."""
    return os.path.expanduser('~')


def sistema():
    """'Darwin', 'Linux' u otro."""
    return platform.system()


def uid():
    return os.getuid()


def python():
    """El intérprete con el que se lanzará el servicio."""
    import sys
    return sys.executable


def datos():
    """La carpeta de datos (la de NAVIS_RAID_DATA, o la del código)."""
    return config.DATOS


def entorno_terminal():
    """Las variables de `VARIABLES` definidas y no vacías en este proceso."""
    return {n: os.environ[n] for n in VARIABLES if os.environ.get(n)}


def escucha(puerto):
    """¿Hay algo escuchando en 127.0.0.1:puerto?"""
    try:
        with socket.create_connection(('127.0.0.1', puerto), timeout=0.5):
            return True
    except OSError:
        return False


def ruta_plist():
    return os.path.join(home(), 'Library', 'LaunchAgents', NOMBRE + '.plist')


def ruta_unit():
    return os.path.join(home(), '.config', 'systemd', 'user', NOMBRE + '.service')


def ruta_servicio():
    """El archivo del servicio en este sistema, o None si no hay soporte."""
    s = sistema()
    return ruta_plist() if s == 'Darwin' else ruta_unit() if s == 'Linux' else None


def ruta_log(carpeta=None):
    return os.path.join(carpeta or datos(), 'servicio.log')


# ---------- el contenido (funciones puras) ----------

def texto_plist(python_, script, puerto, carpeta, entorno=None):
    """El plist de launchd. `plistlib` se ocupa de escapar; sale en XML. `entorno`: variables además de NAVIS_RAID_DATA."""
    log = ruta_log(carpeta)
    return plistlib.dumps({
        'Label': NOMBRE,
        'ProgramArguments': [python_, '-B', script, '--serve', str(puerto)],
        'EnvironmentVariables': dict({'NAVIS_RAID_DATA': carpeta}, **(entorno or {})),
        'RunAtLoad': True,
        'KeepAlive': {'SuccessfulExit': False},      # relanza tras una caída; no tras una salida limpia (código 0)
        'StandardOutPath': log,
        'StandardErrorPath': log,
    }, fmt=plistlib.FMT_XML).decode('utf-8')


def _sin_saltos(s):
    """`s`, o ValueError si lleva un salto de línea: en un unit de systemd inyectaría líneas."""
    if '\n' in s or '\r' in s:
        raise ValueError(s)
    return s


def _comillas(s, ejecutable=False):
    """Un argumento para una línea de unit de systemd: entre comillas, con \\ \" y los especificadores (% y, en
    ExecStart, $) duplicados. Un valor con \\n o \\r lanza ValueError."""
    s = _sin_saltos(s).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    if ejecutable:
        s = s.replace('$', '$$')
    return '"' + s + '"'


def texto_unit(python_, script, puerto, carpeta, entorno=None):
    """La unidad de systemd (de usuario). `entorno`: variables además de NAVIS_RAID_DATA. ValueError si algún valor lleva
    un salto de línea."""
    log = _sin_saltos(ruta_log(carpeta)).replace('%', '%%')
    variables = dict({'NAVIS_RAID_DATA': carpeta}, **(entorno or {}))
    return '\n'.join([
        '[Unit]',
        'Description=Navis Raid, a local dashboard of your Claude Code sessions',
        '',
        '[Service]',
        'ExecStart=' + ' '.join(_comillas(a, True) for a in (python_, '-B', script, '--serve', str(puerto))),
        ] + ['Environment=' + _comillas('%s=%s' % (k, v)) for k, v in variables.items()] + [
        'Restart=on-failure',                          # relanza tras una caída; no tras una salida limpia (código 0)
        'RestartSec=10',
        'StandardOutput=append:' + log,
        'StandardError=append:' + log,
        '',
        '[Install]',
        'WantedBy=default.target',
        ''])


# ---------- el camino de vuelta ----------

def _de_argumentos(args):
    """(script, puerto) a partir de [python, -B, oficina.py, --serve, puerto]."""
    script = next((a for a in args if a.endswith('.py')), None)
    puerto = None
    if '--serve' in args and args.index('--serve') + 1 < len(args):
        try:
            puerto = int(args[args.index('--serve') + 1])
        except ValueError:
            pass
    return script, puerto


def _de_entorno(env):
    """{'datos', 'entorno'}: la carpeta de datos y las variables de `VARIABLES` que lleve el servicio (solo las definidas)."""
    return {'datos': env.get('NAVIS_RAID_DATA'), 'entorno': {n: env[n] for n in VARIABLES if env.get(n)}}


def leer_plist(contenido):
    """{'python', 'script', 'puerto', 'datos', 'entorno'} de un plist (bytes o texto); {} si no se entiende."""
    try:
        d = plistlib.loads(contenido if isinstance(contenido, bytes) else contenido.encode('utf-8'))
        args = [str(a) for a in d.get('ProgramArguments', [])]
        script, puerto = _de_argumentos(args)
        return dict({'python': args[0] if args else None, 'script': script, 'puerto': puerto},
                    **_de_entorno({str(k): str(v) for k, v in (d.get('EnvironmentVariables') or {}).items()}))
    except Exception:
        return {}


def _de_comillas(valor, ejecutable=False):
    """Lo contrario de `_comillas` sobre una línea entera: los argumentos, ya sin el escape de % (y de $ en ExecStart)."""
    return [(a.replace('$$', '$') if ejecutable else a).replace('%%', '%') for a in shlex.split(valor)]


def leer_unit(contenido):
    """{'python', 'script', 'puerto', 'datos', 'entorno'} de una unidad de systemd (texto); {} si no se entiende."""
    try:
        exec_, entorno = [], []
        for linea in contenido.splitlines():
            if linea.startswith('ExecStart='):
                exec_ = _de_comillas(linea[len('ExecStart='):], True)
            elif linea.startswith('Environment='):
                entorno += _de_comillas(linea[len('Environment='):])
        script, puerto = _de_argumentos(exec_)
        env = dict(e.split('=', 1) for e in entorno if '=' in e)
        return dict({'python': exec_[0] if exec_ else None, 'script': script, 'puerto': puerto}, **_de_entorno(env))
    except Exception:
        return {}


def leer():
    """Lo instalado, o {'instalado': False}: archivo, intérprete, script, puerto, datos, variables, si el intérprete y el
    script existen y si algo escucha."""
    s, ruta = sistema(), ruta_servicio()
    info = {'sistema': s, 'instalado': False, 'archivo': ruta, 'python': None, 'script': None, 'puerto': None, 'datos': None,
            'entorno': {}, 'python_existe': None, 'script_existe': None, 'escucha': None}
    if not ruta or not os.path.isfile(ruta):
        return info
    info['instalado'] = True
    try:
        if s == 'Darwin':
            with open(ruta, 'rb') as fh:
                info.update(leer_plist(fh.read()))
        else:
            with open(ruta, encoding='utf-8', errors='replace') as fh:
                info.update(leer_unit(fh.read()))
    except OSError:
        pass
    if info['python'] and os.path.isabs(info['python']):          # un nombre sin ruta («python3») se busca en el PATH: no se sabe
        info['python_existe'] = os.path.isfile(info['python'])
    if info['script']:
        info['script_existe'] = os.path.isfile(info['script'])
    if info['puerto']:
        info['escucha'] = bool(escucha(info['puerto']))
    return info


# ---------- los efectos ----------

def correr(args):
    """El runner por defecto: una orden como lista de argumentos, sin shell. Devuelve el resultado de subprocess.run."""
    return subprocess.run(list(args), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=TIEMPO_ORDEN_S)


class _Fallo(Exception):
    """Algo no salió: el mensaje ya está dicho al usuario."""


def _orden(runner, args, tolerar=False):
    """Corre una orden. Devuelve el resultado; si no puede lanzarse o sale con error y no se tolera, dice por qué y lanza
    _Fallo. `tolerar` es True (devuelve el resultado aunque falle) o una función `resultado -> bool` que dice si ese fallo
    se tolera. Un fallo al lanzar la orden siempre es fallo."""
    texto = ' '.join(args)
    try:
        r = runner(args)
    except (OSError, subprocess.SubprocessError) as e:
        print(t('No se pudo ejecutar `{orden}`: {motivo}', orden=texto, motivo=e))
        raise _Fallo()
    if r.returncode != 0 and not (tolerar(r) if callable(tolerar) else tolerar):
        detalle = ((r.stderr or '') + (r.stdout or '')).strip() or t('sin mensaje')
        print(t('`{orden}` falló (código {codigo}): {motivo}', orden=texto, codigo=r.returncode, motivo=detalle))
        raise _Fallo()
    return r


def _escribir(ruta, contenido):
    """Escritura atómica (temporal + os.replace); crea las carpetas que falten."""
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    tmp = ruta + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(contenido)
    os.replace(tmp, ruta)


def puerto_libre(desde, intentos=INTENTOS_SUGERIDO):
    """El primer puerto sin nadie escuchando a partir de `desde` (incluido), o None si en `intentos` seguidos no hay."""
    for p in range(desde, min(desde + intentos, 65536)):
        if not escucha(p):
            return p
    return None


def _ocupado_por_otro(puerto):
    """¿Escucha algo en `puerto` que no sea nuestro propio servicio? Si el servicio instalado usa ese mismo puerto, es una
    reinstalación (`bootout` o `restart` lo liberan), no un choque."""
    if not escucha(puerto):
        return False
    info = leer()
    return not (info['instalado'] and info['puerto'] == puerto)


def _espera_escucha(puerto, dormir, intentos=int(ESPERA_ARRANQUE_S / PAUSA_ARRANQUE_S)):
    """Mira cada PAUSA_ARRANQUE_S, hasta ESPERA_ARRANQUE_S, si algo escucha en `puerto` (con `escucha`, que se sustituye)."""
    for _ in range(intentos):
        if escucha(puerto):
            return True
        dormir(PAUSA_ARRANQUE_S)
    return bool(escucha(puerto))


def instalar(puerto, script, runner=None, dormir=time.sleep, verificar=False):
    """--instalar-servicio: escribe el archivo del servicio (reescribe el que hubiera) y lo carga. Devuelve el código de
    salida: 0 bien, 1 si algo falló (permisos, launchctl/systemctl), 2 si el puerto no vale, un valor lleva un salto
    de línea o el sistema no está soportado, 4 si otra cosa ya usa el puerto (no se instala nada) y, solo con `verificar=True`
    (lo pide `oficina.py --instalar-servicio`), 5 si se instaló pero nada escucha en el puerto tras ~5 s (queda instalado;
    el aviso lleva la última línea de `servicio.log`). Sin `verificar` no espera: devuelve 0 en cuanto el servicio carga."""
    runner = runner or correr
    s = sistema()
    if s not in ('Darwin', 'Linux'):
        print(t('El servicio solo está soportado en macOS (launchd) y Linux (systemd); este sistema es {sistema}.', sistema=s))
        return 2
    if not isinstance(puerto, int) or not 1 <= puerto <= 65535:
        print(t('Puerto no válido: {puerto} (debe estar entre 1 y 65535).', puerto=puerto))
        return 2
    if _ocupado_por_otro(puerto):                      # antes de escribir nada; ThreadingHTTPServer puede enlazar aun así (SO_REUSEADDR)
        sugerido = puerto_libre(puerto + 1)
        if sugerido:
            print(t('El puerto {puerto} ya está en uso (¿una oficina lanzada a mano? Párala con Ctrl+C). O instala en otro puerto: /navis-raid:start {sugerido}',
                    puerto=puerto, sugerido=sugerido))
        else:
            print(t('El puerto {puerto} ya está en uso (¿una oficina lanzada a mano? Párala con Ctrl+C) y no hay otro libre justo después; elige uno con /navis-raid:start <puerto>',
                    puerto=puerto))
        return 4
    ruta, carpeta, py = ruta_servicio(), datos(), python()
    existia = os.path.isfile(ruta)
    entorno = dict(entorno_terminal(), **{SERVICIO: '1'})
    try:
        contenido = (texto_plist if s == 'Darwin' else texto_unit)(py, script, puerto, carpeta, entorno)
    except ValueError as e:                            # un salto de línea en una ruta o variable inyectaría líneas en el unit
        print(t('No se puede instalar: un valor lleva un salto de línea y rompería el archivo del servicio: {valor!r}', valor=e.args[0] if e.args else ''))
        return 2
    try:
        os.makedirs(carpeta, exist_ok=True)            # launchd no crea la carpeta del log: si falta, el servicio no arranca
        _escribir(ruta, contenido)
    except OSError as e:
        print(t('No se pudo escribir {ruta}: {motivo}', ruta=e.filename or ruta, motivo=e.strerror or e))
        return 1
    try:
        if s == 'Darwin':
            destino = 'gui/%d' % uid()
            _orden(runner, ['launchctl', 'bootout', '%s/%s' % (destino, NOMBRE)], tolerar=True)   # puede no estar cargado
            r = _orden(runner, ['launchctl', 'bootstrap', destino, ruta], tolerar=True)
            if r.returncode != 0:                      # bootout puede tardar un instante en soltar la etiqueta: un reintento
                dormir(1)
                _orden(runner, ['launchctl', 'bootstrap', destino, ruta])
        else:
            _orden(runner, ['systemctl', '--user', 'daemon-reload'])
            _orden(runner, ['systemctl', '--user', 'enable', '--now', NOMBRE])
            if existia:                                # enable --now no reinicia lo que ya corría con la versión vieja
                _orden(runner, ['systemctl', '--user', 'restart', NOMBRE])
    except _Fallo:
        print(t('El archivo quedó escrito en {ruta}; corrige el problema y vuelve a lanzar --instalar-servicio.', ruta=ruta))
        return 1
    print(t('Servicio instalado: {ruta}', ruta=ruta))
    if verificar and not _espera_escucha(puerto, dormir):
        linea = ultima_linea_log()
        print(t('Pero nada escucha en el puerto {puerto} tras {segundos} s. El servicio sigue instalado. Última línea de servicio.log: {linea}. Mira `--estado-servicio` (o /navis-raid:doctor).',
                puerto=puerto, segundos=ESPERA_ARRANQUE_S, linea=linea or t('(no hay servicio.log o está vacío)')))
        return 5
    print(t('Navis Raid arrancará solo en cada inicio de sesión, en http://127.0.0.1:{puerto}/', puerto=puerto))
    return 0


def quitar(runner=None):
    """--quitar-servicio: lo para y borra el archivo. Sin servicio instalado, lo dice y devuelve 0. Solo tolera que no
    estuviera cargado (launchctl bootout con código 3 o 113; systemctl con «el unit no existe»): con cualquier otro fallo
    avisa, deja el archivo y devuelve 1, para no decir «quitado» de algo que sigue corriendo."""
    runner = runner or correr
    s = sistema()
    ruta = ruta_servicio()
    if not ruta:
        print(t('El servicio solo está soportado en macOS (launchd) y Linux (systemd); este sistema es {sistema}.', sistema=s))
        return 2
    if not os.path.isfile(ruta):
        print(t('No hay servicio instalado (no existe {ruta}).', ruta=ruta))
        return 0
    try:
        if s == 'Darwin':
            _orden(runner, ['launchctl', 'bootout', 'gui/%d/%s' % (uid(), NOMBRE)], tolerar=lambda r: r.returncode in BOOTOUT_NO_CARGADO)
        else:
            _orden(runner, ['systemctl', '--user', 'disable', '--now', NOMBRE],
                   tolerar=lambda r: any(m in ((r.stderr or '') + (r.stdout or '')).lower() for m in SYSTEMCTL_NO_EXISTE))
    except _Fallo:
        print(t('No se pudo parar el servicio; el archivo {ruta} sigue ahí.', ruta=ruta))
        return 1
    try:
        os.remove(ruta)
    except OSError as e:
        print(t('No se pudo borrar {ruta}: {motivo}', ruta=ruta, motivo=e.strerror or e))
        return 1
    if s == 'Linux':
        try:
            _orden(runner, ['systemctl', '--user', 'daemon-reload'], tolerar=True)
        except _Fallo:
            pass
    print(t('Servicio quitado: {ruta}', ruta=ruta))
    return 0


def aviso_puerto_ocupado(puerto):
    """La línea que escribe `--serve` en stderr cuando el puerto está ocupado."""
    return t('el puerto {puerto} ya está en uso; Navis Raid no arranca. Libéralo o reinstala con otro puerto', puerto=puerto)


# La línea de arriba, en cada idioma, para reconocerla en el log aunque se escribiera con otro idioma que el actual.
_AVISO_PUERTO = re.compile(r'^(el puerto \d+ ya está en uso; Navis Raid no arranca\.|port \d+ is already in use; Navis Raid does not start\.)')


def ultima_linea_log(carpeta=None):
    """La última línea no vacía de `servicio.log` (recortada a 300 caracteres); None si no hay log, está vacío o no se puede leer."""
    try:
        with open(ruta_log(carpeta), 'rb') as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 4096))
            lineas = fh.read().decode('utf-8', errors='replace').splitlines()
    except OSError:
        return None
    lineas = [l.strip() for l in lineas if l.strip()]
    return lineas[-1][:300] if lineas else None


def ultimo_aviso(carpeta=None):
    """La última línea de `servicio.log` si es el aviso de puerto ocupado; None si no, o si no se puede leer el log."""
    linea = ultima_linea_log(carpeta)
    return linea if linea and _AVISO_PUERTO.match(linea) else None


def aviso_pendiente(info):
    """El aviso de puerto ocupado de `servicio.log` si el servicio está instalado y nada escucha en su puerto (si algo
    escucha, el aviso es de un arranque anterior); None si no."""
    if not info.get('instalado') or info.get('escucha'):
        return None
    return ultimo_aviso(info.get('datos') or None)


def estado():
    """--estado-servicio: lo que hay instalado. Devuelve 0 (es solo información)."""
    info = leer()
    if not info['archivo']:
        print(t('El servicio solo está soportado en macOS (launchd) y Linux (systemd); este sistema es {sistema}.', sistema=info['sistema']))
        return 0
    if not info['instalado']:
        print(t('Servicio: no instalado (se esperaría en {ruta}).', ruta=info['archivo']))
        return 0
    print(t('Servicio: instalado en {ruta}', ruta=info['archivo']))
    if info['script']:
        print(t('  oficina.py: {ruta} ({existe})', ruta=info['script'],
                existe=t('existe') if info['script_existe'] else t('NO existe: vuelve a lanzar /navis-raid:start')))
    else:
        print(t('  oficina.py: no se pudo leer del archivo del servicio.'))
    print(t('  Datos: {ruta}', ruta=info['datos'] or t('(no definida)')))
    for nombre, valor in info['entorno'].items():
        print(t('  Variable {nombre}: {valor}', nombre=nombre, valor=valor))
    if info['puerto']:
        print(t('  Puerto {puerto}: {estado}', puerto=info['puerto'], estado=t('algo escucha') if info['escucha'] else t('nada escucha')))
    aviso = aviso_pendiente(info)
    if aviso:
        print(t('  Último aviso del servicio: {aviso}', aviso=aviso))
    return 0
