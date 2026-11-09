"""La oficina: qué sesión de Claude Code está activa, qué agente trabaja en cada una y en qué tarea.

Solo lectura. Cruza dos fuentes que ya existen en disco:
  - las sesiones de la app (extra, solo macOS): ~/Library/Application Support/Claude/claude-code-sessions/**/local_*.json
  - las transcripciones de CLI:  ~/.claude/projects/<carpeta>/<cliSessionId>.jsonl
    y sus subagentes:            ~/.claude/projects/<carpeta>/<cliSessionId>/subagents/agent-*.{meta.json,jsonl}
La lista de sesiones sale de las transcripciones; la app, si existe, aporta título, fijada, tarea programada,
enlace y grupos. Sin la app (solo terminal, en Mac, Linux o Windows) todo funciona igual. Si `CLAUDE_CONFIG_DIR`
está definida, reemplaza a ~/.claude.

Genera `index.html`, `tabla.html` y `estado.json` en la carpeta de datos: junto a este archivo, o la de `NAVIS_RAID_DATA`
(ahí también `bitacora/`, `chat/`, `pisos.json` y el `config.json` por defecto). No llama a ningún modelo: cero tokens.

Uso:
  python3 oficina.py                 genera una vez
  python3 oficina.py --watch 5       regenera cada 5 s (Ctrl+C para parar)
  python3 oficina.py --serve 8765    sirve http://localhost:8765/ y regenera en cada carga (no probado desde el sandbox)
  python3 oficina.py --doctor        diagnóstico de solo lectura: qué encontró en este equipo y qué no (también: doctor)
  python3 oficina.py --instalar-servicio [puerto]   instala Navis Raid como servicio de usuario (launchd, systemd o la carpeta Inicio de Windows), 8765 por defecto
  python3 oficina.py --quitar-servicio              lo para y borra el archivo del servicio
  python3 oficina.py --estado-servicio              dice si está instalado, a qué oficina.py apunta y si algo escucha
  python3 oficina.py --solo-terminal ignora los archivos de la app (también: NAVIS_RAID_SOLO_TERMINAL=1)
"""
import datetime as dt
import glob
import html
import json
import os
import pathlib
import re
import shlex
import sys
import threading
import time
import zlib

import bitacora
import config
import costo
try:
    import afk        # protocolo «afk» de la máquina del autor: opcional, la oficina funciona sin afk.py
except ImportError as e:
    if getattr(e, 'name', None) != 'afk':      # un ImportError de otra cosa (dentro de afk.py) sí se ve
        raise
    afk = None
import logos      # arriba para que sus avisos de config (iconos desconocidos) salgan en --doctor
import plan
import sprites
import textos
from textos import t

AQUI = os.path.dirname(os.path.abspath(__file__))
DATOS = config.DATOS   # dónde se escribe todo el estado (index.html, tabla.html, estado.json, bitacora/, chat/) y se lee pisos.json; el código y fuentes/ se quedan en AQUI
# Las rutas las define bitacora.py (una sola fuente): CLAUDE_CONFIG_DIR reemplaza a ~/.claude, y la app de escritorio
# solo se busca en macOS y fuera del modo solo terminal; si no, APP es None y todo sale de las transcripciones.
CONFIG = bitacora.CONFIG
APP = bitacora.APP
APP_CONFIG = os.path.expanduser('~/Library/Application Support/Claude/claude_desktop_config.json')   # grupos del sidebar
SOLO_TERMINAL = bitacora.SOLO_TERMINAL   # ignora la app (--solo-terminal o NAVIS_RAID_SOLO_TERMINAL=1)
PROYECTOS = bitacora.PROYECTOS
PROBADO_CON = '2.1.299'   # versión de Claude Code con la que se probó el formato de las transcripciones (avisa si cambia mayor.menor)
UMBRAL_K = config.valor('umbral_relevo_k')   # relevo de sesión: contexto (en miles de tokens) desde el que toca
USUARIO = config.C['nombre_usuario'].strip() or t('ti')   # quien atiende las sesiones («ti» / «you» si el config no lo dice)
AGENTES_GLOBAL = os.path.join(CONFIG, 'agents')   # definiciones de agentes: su `model:` es el modelo esperado
MODELO_PROGRAMADA = config.valor('modelo_tareas_programadas')   # las tareas programadas corren sin supervisión: más caro que esto, fuera de regla
MODELO_GENERICO = config.valor('modelo_agentes_sin_definicion')   # agentes sin definición propia (general-purpose, Plan, claude...) heredan el de la sesión: se espera sonnet
PESO_MODELO = (('haiku', 0), ('sonnet', 1), ('opus', 2), ('fable', 3), ('mythos', 3))
FRIA_S = config.valor('ttl_cache_s')   # pausa tras la que la caché expiró (TTL): una sesión de UMBRAL_K o más ya no se reanuda
ACTIVO_MIN = 2            # minutos sin escribir en disco para pasar de "trabajando" a "en pausa"
HORAS_VISIBLES = config.valor('horas_visibles')   # sesiones sin actividad en más tiempo no se muestran
LECTURA_CLI = 256 * 1024  # bytes de la cola (y de la cabeza) de una transcripción que se leen para el título y el cwd
MAX_EVENTOS = 40
ESCALA = 2                # píxeles de pantalla por pixel del dibujo (--compacto: 1.5)

# El chat: la oficina habla con una sola sesión, la central, por su bandeja de entrada (socket de
# mensajería entre sesiones de Claude Code). Cada mensaje es un turno de esa sesión: ahí sí hay tokens.
CHAT_CONFIGURADO = config.valor('chat_sesion')                # lo que dice el config.json (para --doctor)
CHAT_SESION = None if sys.platform == 'win32' else CHAT_CONFIGURADO   # título de la sesión en la app; None: sin chat (en Windows no hay bandejas de Unix ni lsof)
CHAT_DIR = os.path.join(DATOS, 'chat')
CHAT_HILO = os.path.join(CHAT_DIR, 'hilo.jsonl')               # una línea por mensaje: cuando, de, texto
CHAT_MAX = 200                                                 # mensajes que se conservan en memoria
SOCKETS = ['/tmp/cc-socks', '/private/tmp/cc-socks']              # bandejas (<pid>.sock)
if hasattr(os, 'getuid'):                                            # Windows no tiene getuid (ni bandejas): no se evalúa al importar
    SOCKETS.insert(1, f'/tmp/cc-socks-{os.getuid()}')
PISOS = os.path.join(DATOS, 'pisos.json')                       # respaldo de los pisos cuando no hay grupos en el sidebar
LOBBY = tuple(config.valor('lobby'))                           # sesiones que van al lobby aunque tengan grupo
AZOTEA = {'nombre': t('Azotea · ocio'), 'proyectos': [], 'azotea': True}     # el último piso: los especialistas sin encargo (P2)
RESTROOM_MIN = 15                                              # terminó un encargo hace menos de esto: está en el restroom
GYM_DIAS = 3                                                   # sin llamadas en estos días (hoy incluido): está en el gym
OCIO = ('videojuegos', 'juegos de mesa', 'tele', 'ping-pong')  # el resto, uno por agente y por hora (códigos internos: oficina_iso los traduce al dibujar)
OCIO_ZONAS = ('gym', 'juegos', 'tele', 'restroom')
SOTANO = config.valor('sotano').lower()                        # el grupo cuyo nombre lo contiene baja al sótano; vacío: ninguno
PIE = t('navis raid · cero tokens') if config.valor('pie') == config.DEFECTOS['pie'][0] else config.valor('pie')   # pie de la página (el del config manda)
ZONA_ETIQUETA = t('hora de {nombre}', nombre=config.zona()[1]) if config.zona() else t('hora local')   # «hora de <zona>» o «hora local», para el modal Costo

_dict, _num, _txt = bitacora._dict, bitacora._num, bitacora._txt   # lectura tolerante: lo que no tiene la forma esperada cuenta como ausente

_cache = {}               # ruta → estado incremental de parseo (modo --watch)


# ---------- utilidades ----------

def ahora():
    return dt.datetime.now(dt.timezone.utc)


def ts(s):
    try:
        return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


def hace(momento):
    if not momento:
        return '—'
    seg = (ahora() - momento).total_seconds()
    if seg < 60:
        return t('hace segundos')
    if seg < 3600:
        return t('hace {n} min', n=int(seg // 60))
    if seg < 86400:
        return t('hace {n} h', n=f'{seg / 3600:.1f}')
    return t('hace {n} d', n=int(seg // 86400))


def duracion(a, b):
    if not a or not b:
        return ''
    seg = max(0, (b - a).total_seconds())
    return f'{int(seg // 60)} min' if seg < 3600 else f'{seg / 3600:.1f} h'


def corto(texto, n=90):
    texto = ' '.join(_txt(texto).split())
    return texto if len(texto) <= n else texto[:n - 1] + '…'


def primera_linea(texto):
    for l in _txt(texto).splitlines():
        l = l.strip()
        if l and not l.startswith('<'):
            return l
    return ''


def resumen_herramienta(nombre, entrada):
    """Una frase corta de lo que hace la herramienta, sacada de su entrada."""
    e = _dict(entrada)
    nombre = _txt(nombre)
    if nombre == 'Agent':
        return f"encarga a {e.get('subagent_type', 'agente')}: {e.get('description', '')}"
    for k in ('description', 'file_path', 'command', 'pattern', 'query', 'url', 'skill', 'notebook_path'):
        if e.get(k):
            v = str(e[k])
            if k == 'file_path':
                v = v.replace(os.path.expanduser('~'), '~')
            return f'{nombre}: {corto(v, 70)}'
    if e.get('prompt'):
        return f'{nombre}: {corto(primera_linea(e["prompt"]), 70)}'
    return nombre


# ---------- fuentes ----------

def peso_modelo(m):
    m = (m or '').lower()
    return next((p for clave, p in PESO_MODELO if clave in m), None)


def modelo_esperado(agente, cwd, cache={}):
    """El `model:` de la definición del agente (la del proyecto gana a la global); sin definición o con
    `inherit`, MODELO_GENERICO. Solo lectura; se cachea por ruta y fecha de modificación."""
    for carpeta in (os.path.join(cwd, '.claude', 'agents') if cwd else None, AGENTES_GLOBAL):
        if not carpeta:
            continue
        ruta = os.path.join(carpeta, agente + '.md')
        try:
            mt = os.path.getmtime(ruta)
        except OSError:
            continue
        if cache.get(ruta, (None,))[0] != mt:
            modelo = ''
            try:
                with open(ruta, encoding='utf-8') as fh:
                    lineas = fh.read(4000).split('\n')
                if lineas and lineas[0].strip() == '---':
                    for l in lineas[1:]:
                        if l.strip() == '---':
                            break
                        if l.startswith('model:'):
                            modelo = l.split(':', 1)[1].strip().strip('"\'')
            except OSError:
                pass
            cache[ruta] = (mt, modelo)
        modelo = cache[ruta][1]
        return modelo if peso_modelo(modelo) is not None else MODELO_GENERICO
    return MODELO_GENERICO


def fuera_de_regla(modelo, esperado):
    """El modelo esperado si `modelo` es más caro que él; si no, ''."""
    p, e = peso_modelo(modelo), peso_modelo(esperado)
    return esperado if p is not None and e is not None and p > e else ''


def usa_app():
    """True si se leen los archivos de la app: solo macOS, con su carpeta presente y sin --solo-terminal."""
    return bool(APP) and not SOLO_TERMINAL and os.path.isdir(APP)


def archivos_app(alcances=None):
    """Los archivos de sesión de la app que se leen bien y no están archivados (JSON de cada uno). Los rotos se saltan.
    `alcances`: si se da, solo los de esas carpetas `<cuenta>/<org>` (las demás son de otras cuentas de la app)."""
    if not usa_app():
        return
    for f in glob.glob(APP + '/*/*/local_*.json'):
        if alcances is not None and '/'.join(f.split('/')[-3:-1]) not in alcances:
            continue
        try:
            d = json.load(open(f, encoding='utf-8'))
        except (ValueError, OSError):
            continue
        if isinstance(d, dict) and not d.get('isArchived'):
            yield d


def tareas_programadas():
    """Las tareas programadas activas de la app: {scheduledTaskId: displayName}. Sin archivo, o roto, no hay tareas."""
    out = {}
    if not usa_app():
        return out
    for f in sorted(glob.glob(APP + '/*/*/scheduled-tasks.json')):
        try:
            lista = json.load(open(f, encoding='utf-8')).get('scheduledTasks') or []
        except (ValueError, OSError, AttributeError):
            continue
        for x in lista:
            if isinstance(x, dict) and x.get('id') and x.get('enabled'):
                out.setdefault(x['id'], x.get('displayName') or x['id'])
    return out


def sesiones_app():
    """Sesiones vivas de la app, con su id de transcripción."""
    out = []
    for d in archivos_app():
        if not d.get('cliSessionId'):
            continue
        out.append({
            'titulo': d.get('title') or '?',
            'sid': d.get('sessionId') or '',
            'cwd': d.get('cwd') or '',
            'cli': d['cliSessionId'],
            'modelo': d.get('model') or '',
            'fijada': bool(d.get('isStarred')),
            'programada': d.get('scheduledTaskId') or '',
            'enlace': f"claude://claude.ai/epitaxy/{d.get('sessionId', '')}" if d.get('sessionId') else '',
            'ultima_app': dt.datetime.fromtimestamp((d.get('lastActivityAt') or 0) / 1000, dt.timezone.utc),
        })
    return out


VERSION_VISTA = {'version': ''}   # versión de Claude Code de la transcripción más reciente leída en la última pasada
_cache_cli = {}           # ruta → ((mtime, tamaño), título, origen, cwd, entrypoint): no releer transcripciones que no cambiaron


def _extremos(ruta, tam, cuenta=None):
    """Las líneas JSON legibles de la cabeza y de la cola de un archivo (LECTURA_CLI bytes cada una), por separado.
    El corte puede partir una línea: esa no es JSON y se salta; tampoco cuentan las que no son un objeto o no traen
    `type`. `cuenta` (opcional, lo usa --doctor) suma en 'leidas' y 'saltadas' las líneas no vacías de cada lectura."""
    def leer(desde):
        with open(ruta, 'rb') as fh:
            fh.seek(desde)
            crudo = fh.read(LECTURA_CLI)
        out = []
        for raw in crudo.split(b'\n'):
            if not raw.strip():
                continue
            d = None
            if b'"type"' in raw:
                try:
                    d = json.loads(raw)
                except ValueError:
                    pass
            if isinstance(d, dict):
                out.append(d)
            if cuenta is not None:
                cuenta['leidas' if isinstance(d, dict) else 'saltadas'] = cuenta.get('leidas' if isinstance(d, dict) else 'saltadas', 0) + 1
        return out
    cabeza = leer(0)
    return cabeza, (leer(tam - LECTURA_CLI) if tam > LECTURA_CLI else cabeza)


def _ultimo(lineas, tipo, campo):
    return next((d[campo] for d in reversed(lineas) if d.get('type') == tipo and isinstance(d.get(campo), str) and d[campo].strip()), '')


def leer_transcripcion_cli(ruta):
    """(título, origen, cwd, entrypoint, versión de Claude Code) de una transcripción, o None si no se puede leer o no tiene cwd.
    Título: el último `custom-title`, si no el último `ai-title`, si no el nombre de la carpeta del cwd; se busca en la
    cola del archivo y, si ahí no hay, en la cabeza. `origen` es 'custom', 'ai' o 'carpeta'."""
    try:
        st = os.stat(ruta)
        clave = (st.st_mtime, st.st_size)
        if _cache_cli.get(ruta, (None,))[0] == clave:
            return _cache_cli[ruta][1:]
        cabeza, cola = _extremos(ruta, st.st_size)
    except OSError:
        return None
    msgs = [d for d in cabeza + cola if d.get('type') in ('user', 'assistant') and not d.get('isSidechain')]
    cwd = next((c for c in (_txt(d.get('cwd')) for d in msgs) if c), '')
    if not cwd:
        return None
    entry = next((c for c in (_txt(d.get('entrypoint')) for d in msgs) if c), '')
    version = next((v for v in (_txt(d.get('version')).strip() for d in reversed(cola)) if v), '')
    titulo, origen = '', 'carpeta'
    for tipo, campo, o in (('custom-title', 'customTitle', 'custom'), ('ai-title', 'aiTitle', 'ai')):
        titulo = _ultimo(cola, tipo, campo) or _ultimo(cabeza, tipo, campo)
        if titulo:
            origen = o
            break
    if not titulo:
        titulo = os.path.basename(cwd.rstrip('/\\')) or cwd
    _cache_cli[ruta] = (clave, titulo, origen, cwd, entry, version)
    return titulo, origen, cwd, entry, version


def sesiones_cli(sin_app=False):
    """Sesiones a partir de las transcripciones con actividad en las últimas HORAS_VISIBLES, con la misma forma que
    sesiones_app(). Sin `sid`, `programada` ni `enlace` y sin fijar: eso solo lo sabe la app. Los subagentes viven en
    una subcarpeta y `*/*.jsonl` no los alcanza. `sin_app`: salta las de entrypoint `claude-desktop`, que la app ya lista."""
    corte = time.time() - HORAS_VISIBLES * 3600
    out = []
    reciente = (0, '')                            # (mtime, versión) de la transcripción más reciente con versión
    for ruta in glob.glob(PROYECTOS + '/*/*.jsonl'):
        try:
            mtime = os.path.getmtime(ruta)
        except OSError:
            continue
        if mtime < corte:
            continue
        datos = leer_transcripcion_cli(ruta)
        if datos and datos[4] and mtime > reciente[0]:
            reciente = (mtime, datos[4])
        if not datos or (sin_app and datos[3] == 'claude-desktop'):
            continue
        out.append((datos[1], {
            'titulo': datos[0], 'sid': '', 'cwd': datos[2], 'cli': os.path.basename(ruta)[:-len('.jsonl')], 'modelo': '',
            'fijada': False, 'programada': '', 'enlace': '',
            'ultima_app': dt.datetime.fromtimestamp(mtime, dt.timezone.utc),
        }))
    # Tras un /clear (o en cada corrida de una tarea programada) la transcripción nueva hereda el título que se le puso
    # con /rename: misma carpeta y mismo título puesto a mano es la misma sesión, y manda la más reciente.
    # Los títulos generados o el nombre de carpeta no se tocan: ahí varias sesiones se parecen sin ser la misma.
    VERSION_VISTA['version'] = reciente[1]
    recientes = {}
    for origen, s in out:
        if origen == 'custom':
            k = (s['cwd'], s['titulo'])
            if k not in recientes or s['ultima_app'] > recientes[k]['ultima_app']:
                recientes[k] = s
    return [s for origen, s in out if origen != 'custom' or recientes[(s['cwd'], s['titulo'])] is s]


def sesiones_todas():
    """La lista de sesiones: las de la app (si hay) + las transcripciones de la CLI que la app no lista. Una de la CLI
    cuyo uuid ya es el `cliSessionId` de una de la app, o cuyo entrypoint es `claude-desktop` (transcripciones viejas de
    la app tras un /clear), no se repite. Sin app, solo las transcripciones."""
    app = sesiones_app()
    if not usa_app():
        return app + sesiones_cli()
    vistas = {s['cli'] for s in app}
    return app + [s for s in sesiones_cli(sin_app=True) if s['cli'] not in vistas]


def transcripcion(cli):
    hits = glob.glob(f'{PROYECTOS}/*/{cli}.jsonl')
    return hits[0] if hits else None


def parsear_principal(ruta):
    """Lee la transcripción (incremental en --watch) y devuelve el estado de la sesión."""
    st = _cache.get(ruta)
    if st is None:
        st = _cache[ruta] = {
            'offset': 0, 'prompt': '', 'prompt_ts': None, 'ultima_ia': None, 'contexto_k': 0, 'modelo': '',
            'herramienta': '', 'herramienta_ts': None, 'stop': '', 'pendientes': {}, 'encargos': {}, 'eventos': [],
            'respuesta': '', 'respuesta_ts': None,
        }
    try:
        tam = os.path.getsize(ruta)
    except OSError:
        return st
    if tam < st['offset']:            # archivo reescrito
        st.update(offset=0, pendientes={}, encargos={}, eventos=[])
    if tam == st['offset']:
        return st
    with open(ruta, 'rb') as fh:
        fh.seek(st['offset'])
        datos = fh.read()
    # solo líneas completas
    fin = datos.rfind(b'\n')
    if fin < 0:
        return st
    st['offset'] += fin + 1
    for raw in datos[:fin].split(b'\n'):
        if not raw.strip():
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        tipo = d.get('type')
        t = ts(d.get('timestamp'))
        if tipo == 'last-prompt' and _txt(d.get('lastPrompt')):
            st['prompt'] = d['lastPrompt']
            continue
        m = _dict(d.get('message'))
        if not m:
            continue
        cont = m.get('content')
        if tipo == 'user':
            if isinstance(cont, str):
                if not d.get('isMeta') and not cont.startswith('<'):
                    st['prompt'], st['prompt_ts'] = cont, t
                    st['eventos'].append((t, 'pedido', corto(primera_linea(cont), 100)))
            elif isinstance(cont, list):
                for b in cont:
                    b = _dict(b)
                    if b.get('type') == 'tool_result':
                        tid = _txt(b.get('tool_use_id'))
                        st['pendientes'].pop(tid, None)
                        enc = st['encargos'].get(tid)
                        if enc and not enc.get('fin'):
                            enc['fin'] = t
                    elif b.get('type') == 'text' and isinstance(b.get('text'), str) and not d.get('isMeta') and not b['text'].startswith('<'):
                        st['prompt'], st['prompt_ts'] = b['text'], t
                        st['eventos'].append((t, 'pedido', corto(primera_linea(b['text']), 100)))
        elif tipo == 'assistant':
            u = _dict(m.get('usage'))
            total = sum(_num(u.get(k)) for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))
            if total > 0:
                st['contexto_k'] = total / 1000
            st['ultima_ia'] = t or st['ultima_ia']
            st['modelo'] = _txt(m.get('model')) or st['modelo']
            st['stop'] = _txt(m.get('stop_reason')) or st['stop']
            for b in cont if isinstance(cont, list) else []:
                b = _dict(b)
                if b.get('type') == 'tool_use':
                    nombre, entrada = _txt(b.get('name')), _dict(b.get('input'))
                    tid = _txt(b.get('id'))
                    st['herramienta'], st['herramienta_ts'] = resumen_herramienta(nombre, entrada), t
                    st['pendientes'][tid] = (nombre, t)
                    if nombre == 'Agent':
                        agente, descripcion = _txt(entrada.get('subagent_type')), _txt(entrada.get('description'))
                        st['encargos'][tid] = {
                            'agente': agente or 'general-purpose',
                            'tarea': descripcion or corto(primera_linea(entrada.get('prompt')), 80),
                            'inicio': t, 'fin': None, 'fondo': bool(entrada.get('run_in_background', True)),
                        }
                        st['eventos'].append((t, 'encargo', textos.t('encargó a {agente}: {descripcion}', agente=agente or textos.t('un agente'), descripcion=descripcion)))
                elif b.get('type') == 'text' and _txt(b.get('text')).strip():
                    st['respuesta'], st['respuesta_ts'] = b['text'], t
    st['eventos'] = st['eventos'][-MAX_EVENTOS:]
    return st


def subagentes(ruta_principal):
    """Los subagentes de la sesión: tipo, tarea, modelo, inicio, última actividad y estado."""
    carpeta = ruta_principal[:-6] + '/subagents'
    out = []
    for meta in glob.glob(carpeta + '/agent-*.meta.json'):
        try:
            md = _dict(json.load(open(meta, encoding='utf-8')))     # un meta.json que no es un objeto cuenta como vacío
        except (ValueError, OSError):
            continue
        jl = meta[:-10] + '.jsonl'
        inicio = ultimo = None
        herramienta = ''
        llamadas = 0
        termino = False
        try:
            mtime = dt.datetime.fromtimestamp(os.path.getmtime(jl), dt.timezone.utc)
            with open(jl, 'rb') as fh:
                primera = fh.readline()
                fh.seek(0, 2)
                tam = fh.tell()
                fh.seek(max(0, tam - 200_000))
                cola = fh.read().split(b'\n')
            try:
                inicio = ts(_dict(json.loads(primera)).get('timestamp'))
            except ValueError:
                pass
            for raw in cola:
                try:
                    d = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                t = ts(d.get('timestamp'))
                ultimo = t or ultimo
                m = _dict(d.get('message'))
                if d.get('type') == 'assistant' and m:
                    termino = m.get('stop_reason') == 'end_turn'
                    cont = m.get('content')
                    for b in cont if isinstance(cont, list) else []:
                        if isinstance(b, dict) and b.get('type') == 'tool_use':
                            herramienta = resumen_herramienta(b.get('name'), b.get('input'))
                            llamadas += 1
                            termino = False
        except OSError:
            mtime = None
        activo = bool(mtime) and (ahora() - mtime).total_seconds() < ACTIVO_MIN * 60 and not termino
        out.append({
            'id': os.path.basename(meta)[6:-10],
            'agente': _txt(md.get('agentType')) or '?',
            'tarea': _txt(md.get('description')),
            'modelo': _txt(md.get('model')).replace('claude-', ''),
            'inicio': inicio, 'ultimo': ultimo or mtime, 'herramienta': herramienta,
            'estado': 'trabajando' if activo else 'terminó',   # un subagente no se pausa: trabaja o terminó
        })
    out.sort(key=lambda a: a['ultimo'] or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
    # en la tarjeta: los que trabajan y los que terminaron en las últimas 24 h
    return [a for a in out if a['estado'] == 'trabajando' or (a['ultimo'] and (ahora() - a['ultimo']).total_seconds() < 86400)]


# ---------- armado ----------

def estado_de(delegado, activa, pendientes, herramienta, stop):
    """El estado de una sesión en una frase. `delegado`: el primer subagente que trabaja (o None); `pendientes`: hay una
    herramienta en curso; `stop`: cómo terminó la última respuesta del modelo."""
    if delegado:                             # la sesión delega: lo que cuenta es el agente
        return t('esperando a {agente}: {tarea}', agente=delegado['agente'], tarea=delegado['tarea'])
    if activa and pendientes:
        return t('ejecutando {herramienta}', herramienta=herramienta)
    if activa:
        return t('pensando o escribiendo')
    if stop == 'end_turn' or not pendientes:
        return t('esperando a {usuario}', usuario=USUARIO)
    return t('en pausa')


def _sesion(s):
    """(sesión, eventos) de una sesión de la lista, o None si no tiene transcripción o está fuera de la ventana."""
    eventos = []
    ruta = transcripcion(s['cli'])
    if not ruta:
        return None
    st = parsear_principal(ruta)
    mtime = dt.datetime.fromtimestamp(os.path.getmtime(ruta), dt.timezone.utc)
    ultima = st['ultima_ia'] or mtime      # la app toca archivos viejos: manda la última llamada al modelo
    if (ahora() - ultima).total_seconds() > HORAS_VISIBLES * 3600:
        return None
    subs = subagentes(ruta)
    hace_ia = (ahora() - ultima).total_seconds()
    hace_disco = (ahora() - mtime).total_seconds()
    # activa si el modelo habló hace poco, o si hay una herramienta en curso (un Bash largo) y el archivo se mueve
    activa = hace_ia < ACTIVO_MIN * 60 or (bool(st['pendientes']) and hace_disco < ACTIVO_MIN * 60 and hace_ia < 15 * 60)
    trabajando = [a for a in subs if a['estado'] == 'trabajando']
    if trabajando:                           # la sesión delega: lo que cuenta es el agente
        activa = True
    estado = estado_de(trabajando[0] if trabajando else None, activa, st['pendientes'], st['herramienta'], st['stop'])
    producto = os.path.basename(s['cwd'].rstrip('/')) or s['cwd']
    ses = {
        'titulo': s['titulo'], 'producto': producto, 'cwd': s['cwd'], 'cli': s['cli'][:8],
        'modelo': (st['modelo'] or s['modelo']).replace('claude-', ''), 'fijada': s['fijada'],
        'contexto_k': round(st['contexto_k']), 'activa': activa, 'estado': estado,
        'ultima': ultima, 'pedido': corto(primera_linea(st['prompt']), 140),
        'respuesta': corto(primera_linea(st['respuesta']), 140),
        'subagentes': [dict(a, fuera=fuera_de_regla(a['modelo'], modelo_esperado(a['agente'], s['cwd']))) for a in subs],
        'programada': s['programada'],
        'sid': s['sid'],
        'enlace': s['enlace'],
        'historial': [{'cuando': t, 'clase': c, 'texto': x} for t, c, x in reversed(st['eventos']) if t][:MAX_EVENTOS],
        'encargos_activos': sum(1 for a in subs if a['estado'] == 'trabajando'),
    }
    ses['fuera'] = fuera_de_regla(ses['modelo'], MODELO_PROGRAMADA) if ses['programada'] else ''
    for cuando, clase, texto in st['eventos']:
        eventos.append((cuando, s['titulo'], clase, texto))
    for a in subs:
        if a['estado'] == 'terminó' and a['ultimo']:
            eventos.append((a['ultimo'], s['titulo'], 'fin', t('{agente} terminó: {tarea} ({duracion})', agente=a['agente'], tarea=a['tarea'], duracion=duracion(a['inicio'], a['ultimo']))))
    return ses, eventos


def recoger():
    sesiones, eventos = [], []
    for s in sesiones_todas():
        try:
            r = _sesion(s)
        except Exception as e:                                   # red de seguridad: una sesión rara no tumba la pasada
            print(t('sesión {cli} saltada: {tipo}: {error}', cli=str(s.get('cli'))[:8], tipo=type(e).__name__, error=e), file=sys.stderr)
            continue
        if r:
            sesiones.append(r[0])
            eventos += r[1]
    sesiones.sort(key=lambda x: (not x['activa'], -x['ultima'].timestamp()))
    try:
        plan.de_sesiones(sesiones)                               # producto, ROADMAP, ideas/ y git (solo lectura)
    except Exception as e:                                       # el plan es un extra: nunca tumba la oficina
        print('plan:', e, file=sys.stderr)
        for s in sesiones:
            s.setdefault('plan', None)
    for m in (chat_hilo() if CHAT_SESION else []):            # el chat (experimental) también sale en el tablón; sin chat_sesion, nada
        quien = USUARIO if m['de'] == 'usuario' else m['de']
        eventos.append((m['cuando'], t('la oficina'), 'chat', f"{quien}: {corto(primera_linea(m['texto']), 120)}"))
    eventos = [e for e in eventos if e[0]]
    eventos.sort(key=lambda e: e[0], reverse=True)
    return sesiones, eventos[:MAX_EVENTOS]


# ---------- pisos ----------

UN_PISO = [{'nombre': t('Oficina'), 'proyectos': []}]


_ALCANCES = []            # carpetas <cuenta>/<org> que tienen grupos en el sidebar; las rellena grupos_app()


def grupos_app():
    """Grupos del sidebar de la app: ([{id, nombre}] en el orden del sidebar, {sessionId: id de grupo}),
    o None si no hay archivo o grupos. Formato interno de la app (preferencias `epitaxyPrefs`), sin documentar."""
    if not usa_app():
        return None
    try:
        with open(APP_CONFIG, encoding='utf-8') as fh:
            prefs = json.load(fh)['preferences']['epitaxyPrefs']
    except (OSError, ValueError, KeyError, TypeError):
        return None
    secciones = prefs.get('dframe-code-sections') or {}
    grupos, asignados = [], {}
    for alcance, v in (prefs.get('dframe-group-scopes') or {}).items():
        orden = {x.get('id'): x.get('order', 0) for x in (secciones.get(alcance) or {}).get('sections') or []}
        for g in sorted(v.get('groups') or [], key=lambda g: orden.get(g.get('id'), 999)):
            if g.get('id'):
                grupos.append({'id': g['id'], 'nombre': g.get('name') or '?'})
        for clave, gid in (v.get('assignments') or {}).items():
            asignados[clave.split(':', 1)[-1]] = gid            # 'code:local_…' → id de grupo
    _ALCANCES[:] = list(prefs.get('dframe-group-scopes') or {})
    return (grupos, asignados) if grupos else None


def _mayor_menor(v):
    m = re.match(r'(\d+)\.(\d+)', v or '')
    return (int(m.group(1)), int(m.group(2))) if m else None


def aviso_version(vista=None):
    """Aviso para el pie si la versión de Claude Code vista en la última pasada no es la probada (mayor.menor distinto;
    un parche distinto no avisa: sale una versión casi cada día). None si coincide o si no se vio ninguna versión."""
    vista = VERSION_VISTA['version'] if vista is None else vista
    if not vista or (_mayor_menor(vista) is not None and _mayor_menor(vista) == _mayor_menor(PROBADO_CON)):
        return None
    return t('Probado con Claude Code {probado}.x; tienes {vista}: si algo se ve raro, corre `python3 oficina.py --doctor`', probado=PROBADO_CON.rsplit('.', 1)[0], vista=vista)


def etiquetar(pisos):
    """Pone a cada piso su etiqueta del elevador: S bajo el lobby, PB el lobby, 1, 2… arriba."""
    pb = next((i for i, p in enumerate(pisos) if p.get('lobby')), 0)
    for i, p in enumerate(pisos):
        p['etiqueta'] = 'PB' if i == pb else (str(i - pb) if i > pb else ('S' if pb == 1 else f'S{pb - i}'))
    return pisos, pb


def cargar_pisos():
    """Los pisos de abajo arriba, el índice del lobby, la asignación sesión → grupo (o None) y un aviso o None.
    Mandan los grupos del sidebar: sótano = el grupo con SOTANO en el nombre, lobby = programadas, sin grupo y
    LOBBY, un piso por cada otro grupo en el orden del sidebar. Sin grupos: pisos.json (fragmentos de carpeta o
    título); sin archivo, o roto, un solo piso con todo y el aviso para el pie de la página."""
    g = grupos_app()
    if g:
        grupos, asignados = g
        abajo = [{'nombre': t('Sótano · {nombre}', nombre=x['nombre']), 'grupo': x['id'], 'sotano': True} for x in grupos if SOTANO and SOTANO in x['nombre'].lower()]
        arriba = [{'nombre': x['nombre'], 'grupo': x['id']} for x in grupos if not (SOTANO and SOTANO in x['nombre'].lower())]
        pisos, pb = etiquetar(abajo + [{'nombre': t('Lobby'), 'grupo': None, 'lobby': True}] + arriba + [dict(AZOTEA)])
        return pisos, pb, asignados, None
    try:
        with open(PISOS, encoding='utf-8') as fh:
            lista = json.load(fh)['pisos']
        pisos = [{'nombre': str(p.get('nombre') or (t('Piso {n}', n=i) if i else t('Planta baja'))),
                  'proyectos': [str(x) for x in (p.get('proyectos') or [])], 'lobby': i == 0} for i, p in enumerate(lista)]
        if not pisos:
            return etiquetar([dict(UN_PISO[0], lobby=True), dict(AZOTEA)]) + (None, t('pisos.json no tiene pisos'))
        return etiquetar(pisos + [dict(AZOTEA)]) + (None, None)
    except FileNotFoundError:
        return etiquetar([dict(UN_PISO[0], lobby=True), dict(AZOTEA)]) + (None, None)
    except (OSError, ValueError, KeyError, AttributeError, TypeError) as e:
        return etiquetar([dict(UN_PISO[0], lobby=True), dict(AZOTEA)]) + (None, t('pisos.json no se pudo leer: {error}', error=e))


def piso_de(s, pisos, pb, asignados):
    """El piso de una sesión. Con grupos: el de su grupo, salvo programadas y LOBBY, que van al lobby (pb), como
    las que no tienen grupo. Con pisos.json: el primero cuyos fragmentos aparecen en la carpeta del proyecto o en
    el título; si ninguno, el primer piso sin lista (el cajón de sastre); si tampoco, el último."""
    if asignados is not None:
        gid = None if s['programada'] or s['titulo'] in LOBBY else asignados.get(s['sid'])
        return next((i for i, p in enumerate(pisos) if gid and p.get('grupo') == gid), pb)
    claves = (s['producto'].lower(), s['titulo'].lower())
    for i, p in enumerate(pisos):
        if any(f.lower() in c for f in p['proyectos'] for c in claves):
            return i
    for i, p in enumerate(pisos):
        if not p['proyectos'] and not p.get('azotea'):
            return i
    return max(0, len(pisos) - 2)


def vacio(titulo, sid='', enlace=''):
    """Cubículo vacío: la oficina con la luz apagada y sin nadie. Solo se dibuja en el plano; no es una sesión."""
    return {'vacio': True, 'titulo': titulo, 'sid': sid, 'enlace': enlace, 'cli': '', 'programada': '', 'activa': False, 'fria': True,
            'estado': t('sin actividad'), 'modelo': '', 'contexto_k': 0, 'subagentes': [], 'encargos_activos': 0, 'fuera': ''}


def cubiculos(sesiones, pisos, pb, asignados):
    """Lo que se dibuja en cada piso: una lista por piso, en el orden de `pisos`. Con grupos del sidebar cada piso tiene
    un cubículo fijo por sesión suya, trabaje o no (las que no salen de recoger() van vacías), ordenados por título para
    que no se muevan entre refrescos. En el lobby, el cubículo fijo es solo para las fijadas sin grupo y LOBBY (las
    sueltas salen mientras tengan actividad), y una tarea programada ocupa un solo cubículo (su corrida más reciente).
    Con pisos.json, las sesiones tal cual."""
    por_piso = [[s for s in sesiones if s['piso'] == i] for i in range(len(pisos))]
    if asignados is None:
        return por_piso
    vistas, tareas = {s['sid'] for s in sesiones if s['sid']}, tareas_programadas()
    for i, en in enumerate(por_piso):
        if i == pb:                                      # una corrida por tarea: la primera de la lista (activas y más recientes antes)
            hechas, unicas = set(), []
            for s in en:
                if s['programada'] and s['programada'] in hechas:
                    continue
                hechas.add(s['programada'])
                unicas.append(s)
            por_piso[i] = unicas
    ocupadas = {s['programada'] for s in por_piso[pb] if s['programada']}
    for d in archivos_app(set(_ALCANCES)):
        sid = d.get('sessionId') or ''
        if not sid or sid in vistas or d.get('scheduledTaskId'):
            continue
        s = {'programada': '', 'titulo': d.get('title') or '?', 'sid': sid}
        i = piso_de(s, pisos, pb, asignados)
        if i == pb and not d.get('isStarred') and s['titulo'] not in LOBBY:
            continue                                     # en el lobby solo las fijadas y LOBBY tienen cubículo fijo (decisión del autor, 24 oct)
        por_piso[i].append(vacio(s['titulo'], sid, f'claude://claude.ai/epitaxy/{sid}'))
    por_piso[pb] += [vacio(nombre) for tid, nombre in tareas.items() if tid not in ocupadas]
    return [sorted(en, key=lambda s: (s['titulo'].casefold(), s['sid'] or s['cli'])) for en in por_piso]


# ---------- la azotea: los especialistas sin encargo ----------

def tipos_de_agente():
    """La plantilla: el nombre (sin .md) de cada definición en ~/.claude/agents/. Vacía si la carpeta no existe."""
    try:
        return sorted(os.path.basename(f)[:-3] for f in glob.glob(AGENTES_GLOBAL + '/*.md'))
    except OSError:
        return []


def llamadas_por_dia(dias=GYM_DIAS):
    """{AAAA-MM-DD: {tipo de agente: llamadas}} de la bitácora, de hoy hacia atrás (fecha local). Un día sin archivo es {}.
    En la bitácora, `agente` es {id, tipo} para un subagente y null para la sesión principal."""
    hoy, out = dt.date.today(), {}
    for n in range(dias):
        dia = (hoy - dt.timedelta(days=n)).isoformat()
        cuenta = {}
        try:
            with open(os.path.join(bitacora.DIR, dia + '.jsonl'), encoding='utf-8') as fh:
                for linea in fh:
                    try:
                        a = json.loads(linea).get('agente')
                    except ValueError:
                        continue
                    tipo = a.get('tipo') if isinstance(a, dict) else a
                    if tipo:
                        cuenta[tipo] = cuenta.get(tipo, 0) + 1
        except OSError:
            pass
        out[dia] = cuenta
    return out


def azotea(sesiones, tipos=None, llamadas=None):
    """Los agentes de la plantilla que no trabajan en ninguna sesión, cada uno con su actividad en la azotea:
    [{tipo, actividad, porque, minutos, hoy, visto}] por orden de tipo. Prioridad: restroom (terminó hace < RESTROOM_MIN) ·
    durmiendo (el de más llamadas hoy entre los que quedan, si > 0) · gym (sin llamadas en GYM_DIAS días) · el resto,
    uno de OCIO por agente y por hora (crc32, estable entre procesos). Si falta la plantilla o la bitácora, sale con menos."""
    try:
        tipos = tipos_de_agente() if tipos is None else tipos
        llamadas = llamadas_por_dia() if llamadas is None else llamadas
    except Exception as e:                    # extra: nunca tumba la pasada
        print('azotea:', e, file=sys.stderr)
        return []
    ocupados = {a['agente'] for s in sesiones for a in s['subagentes'] if a['estado'] == 'trabajando'}
    termino = {}
    for s in sesiones:
        for a in s['subagentes']:
            if a['estado'] == 'terminó' and a['ultimo'] and (a['agente'] not in termino or a['ultimo'] > termino[a['agente']]):
                termino[a['agente']] = a['ultimo']
    dias = sorted(llamadas, reverse=True)                                # hoy primero
    hoy = llamadas.get(dias[0], {}) if dias else {}
    out = []
    for tipo in tipos:
        if tipo in ocupados:
            continue
        minutos = int((ahora() - termino[tipo]).total_seconds() // 60) if tipo in termino else None
        visto = next((d for d in dias if llamadas[d].get(tipo)), None)
        out.append({'tipo': tipo, 'actividad': None, 'porque': '', 'minutos': minutos, 'hoy': hoy.get(tipo, 0), 'visto': visto})
    for a in out:
        if a['minutos'] is not None and a['minutos'] < RESTROOM_MIN:
            a['actividad'], a['porque'] = 'restroom', t('terminó un encargo hace {min} min (< {limite})', min=a['minutos'], limite=RESTROOM_MIN)
    libres = [a for a in out if not a['actividad'] and a['hoy'] > 0]
    if libres:
        dormido = max(libres, key=lambda a: (a['hoy'], a['tipo']))
        dormido['actividad'], dormido['porque'] = 'durmiendo', t('{n} llamadas hoy, el que más trabajó entre los de la azotea', n=dormido['hoy'])
    hora = dt.datetime.now().strftime('%Y-%m-%d-%H')
    for a in out:
        if a['actividad']:
            continue
        if a['visto'] is None:
            a['actividad'], a['porque'] = 'gym', t('sin llamadas en {n} días ({dias})', n=len(dias), dias=', '.join(sorted(dias)))
        else:
            n = zlib.crc32(f"{a['tipo']}{hora}".encode()) % len(OCIO)
            a['actividad'], a['porque'] = OCIO[n], f"crc32({a['tipo']}+{hora}) % {len(OCIO)} = {n}"
    return out


# ---------- chat con la sesión central ----------

def chat_hilo():
    """El hilo del chat, del más antiguo al más nuevo: [{cuando (datetime), de, texto}]."""
    out = []
    try:
        with open(CHAT_HILO, encoding='utf-8') as fh:
            for linea in fh:
                try:
                    d = json.loads(linea)
                    d['cuando'] = dt.datetime.fromisoformat(d['cuando'])
                    if d.get('de') == 'victor':             # el hilo viejo lo escribía así: hoy es 'usuario'
                        d['de'] = 'usuario'
                    out.append(d)
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        return []
    return out[-CHAT_MAX:]


def chat_anotar(de, texto):
    os.makedirs(CHAT_DIR, exist_ok=True)
    with open(CHAT_HILO, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps({'cuando': ahora().isoformat(), 'de': de, 'texto': texto}, ensure_ascii=False) + '\n')


def chat_destino():
    """La sesión viva de la app titulada CHAT_SESION: (id de transcripción completo, cwd), o None (también sin chat)."""
    if not CHAT_SESION:
        return None
    vivas = [s for s in sesiones_app() if s['titulo'] == CHAT_SESION]
    if not vivas:
        return None
    s = max(vivas, key=lambda x: x['ultima_app'])
    return s['cli'], s['cwd']


def sockets_en(cwd):
    """Bandejas de entrada cuyo proceso tiene ese cwd, según lsof. Si lsof no está o falla, todas:
    el session_id que lleva el mensaje hace de filtro (la sesión descarta los que no son suyos)."""
    import subprocess
    todos = sorted({os.path.realpath(p) for d in SOCKETS for p in glob.glob(os.path.join(d, '*.sock'))})   # /tmp y /private/tmp son el mismo
    mios = []
    for p in todos:
        try:
            pid = int(os.path.basename(p).split('.')[0])
            out = subprocess.run(['lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'],
                                 capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5).stdout
        except (ValueError, OSError, subprocess.SubprocessError):
            return todos
        if any(l[1:] == cwd for l in out.splitlines() if l.startswith('n')):
            mios.append(p)
    return mios


def _responder_cmd():
    """Lo que va entre `python3` y la respuesta en el mensaje al chat: la ruta de responder.py y, si la carpeta de datos no
    es la del código, `--datos <carpeta>` (la sesión que responde no hereda NAVIS_RAID_DATA de este proceso)."""
    ruta = os.path.join(AQUI, 'responder.py')
    return ruta if DATOS == AQUI else f'{ruta} --datos {shlex.quote(DATOS)}'


def chat_enviar(texto):
    """Manda el texto a la bandeja de entrada de CHAT_SESION. Devuelve (enviados, error).
    Formato de la línea: el que imprime el propio binario de Claude Code 2.1.295 como ayuda
    (`{"type":"user","message":{"role":"user","content":...}}`); no está en la documentación."""
    import socket
    if not CHAT_SESION:
        return 0, t('el chat no está configurado (chat_sesion en config.json)')
    destino = chat_destino()
    if not destino:
        return 0, t('no hay ninguna sesión "{sesion}" abierta en la app', sesion=CHAT_SESION)
    cli, cwd = destino
    nombre = config.C['nombre_usuario'].strip()
    cuerpo = (t('[la oficina] {texto}', texto=texto) + '\n\n' +
              t('(Mensaje {de} desde la oficina. Responde solo con texto, con: python3 {ruta} "tu respuesta" — queda en el hilo de la oficina.)',
                de=t('de {nombre}', nombre=nombre) if nombre else t('del usuario'), ruta=_responder_cmd()))
    linea = json.dumps({'type': 'user', 'message': {'role': 'user', 'content': cuerpo}, 'session_id': cli}) + '\n'
    enviados = 0
    for ruta in sockets_en(cwd):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect(ruta)
            s.sendall(linea.encode())
            s.close()
            enviados += 1
        except OSError:
            continue
    if not enviados:
        return 0, t('"{sesion}" no tiene bandeja de entrada abierta (¿sesión cerrada?)', sesion=CHAT_SESION)
    return enviados, None


# ---------- salida ----------

CSS = """
:root{--bg:#f6f4ef;--card:#fff;--ink:#1d1d1b;--mute:#6b6a63;--line:#e4e0d6;--ok:#1f8a4c;--warn:#c47a00;--bad:#b3261e;--acc:#e8622c}
@media(prefers-color-scheme:dark){:root{--bg:#15161a;--card:#1f2127;--ink:#ecebe6;--mute:#9a9992;--line:#2d3038;--ok:#4cc27a;--warn:#e0a238;--bad:#ef6b62}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif}
header{display:flex;justify-content:space-between;align-items:baseline;padding:16px 20px 4px}header h1{font-size:18px;margin:0}header small{color:var(--mute)}
main{display:grid;grid-template-columns:1fr 360px;gap:16px;padding:12px 20px 24px}@media(max-width:900px){main{grid-template-columns:1fr}}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:12px;align-content:start}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.card.activa{border-color:var(--ok);box-shadow:0 0 0 2px color-mix(in srgb,var(--ok) 20%,transparent)}
.card h2{font-size:15px;margin:0 0 2px;display:flex;align-items:center;gap:8px}.card h2 .dot{width:9px;height:9px;border-radius:50%;background:var(--mute)}.card.activa h2 .dot{background:var(--ok)}
.meta{color:var(--mute);font-size:12px;margin-bottom:8px}.estado{font-weight:600;margin:4px 0}
.bar{height:5px;background:var(--line);border-radius:3px;overflow:hidden;margin:6px 0 2px}.bar i{display:block;height:100%;background:var(--ok)}.bar.warn i{background:var(--warn)}.bar.bad i{background:var(--bad)}
.pedido{color:var(--mute);font-size:12.5px;margin:6px 0}.pedido b{color:var(--ink);font-weight:600}
.agentes{list-style:none;margin:8px 0 0;padding:0;border-top:1px dashed var(--line)}.agentes li{padding:6px 0;border-bottom:1px dashed var(--line);font-size:13px}
.agentes .tipo{font-weight:600}.agentes .pill{font-size:11px;padding:1px 7px;border-radius:9px;background:var(--line);color:var(--mute);margin-left:6px}
.agentes li.trabajando .pill{background:color-mix(in srgb,var(--ok) 18%,transparent);color:var(--ok)}
.agentes .sub{color:var(--mute);font-size:12px}
aside{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;align-self:start;max-height:calc(100vh - 90px);overflow:auto}
aside h2{font-size:15px;margin:0 0 8px}aside ol{list-style:none;margin:0;padding:0}aside li{padding:6px 0;border-bottom:1px dashed var(--line);font-size:12.5px}
aside .cuando{color:var(--mute);font-size:11px;float:right}aside .ses{color:var(--acc);font-weight:600}
aside li.encargo::before{content:'→ ';color:var(--acc)}aside li.fin::before{content:'✓ ';color:var(--ok)}aside li.pedido::before{content:'✎ ';color:var(--mute)}
.vacio{color:var(--mute);padding:20px}
"""


def render_html(sesiones, eventos, refresco):
    h = html.escape
    partes = [f'<!doctype html><html lang="{textos.idioma()}"><head><meta charset="utf-8"><title>Navis Raid</title>']
    if refresco:
        partes.append(f'<meta http-equiv="refresh" content="{refresco}">')
    partes.append(f'<meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}</style></head><body>')
    activas = sum(1 for s in sesiones if s['activa'])
    trabajando = sum(s['encargos_activos'] for s in sesiones)
    partes.append(f'<header><h1>Navis Raid</h1><small>'
                  + t('{activas} sesión(es) activa(s) · {trabajando} agente(s) trabajando · generado {hora}', activas=activas, trabajando=trabajando, hora=dt.datetime.now().strftime("%d %b %H:%M:%S"))
                  + (t(' · se refresca cada {n}s', n=refresco) if refresco else '') + '</small></header><main>')
    partes.append('<section class="cards">')
    if not sesiones:
        partes.append('<p class="vacio">' + t('Ninguna sesión con actividad en las últimas 48 h.') + '</p>')
    for s in sesiones:
        k = s['contexto_k']
        clase_bar = 'bad' if k >= UMBRAL_K else ('warn' if k >= UMBRAL_K * 0.8 else '')
        pct = min(100, int(k * 100 / UMBRAL_K))
        partes.append(f'<article class="card{" activa" if s["activa"] else ""}">')
        partes.append(f'<h2><span class="dot"></span>{h(s["titulo"])}{" ★" if s["fijada"] else ""}</h2>')
        partes.append(f'<div class="meta">{h(s["producto"])} · {h(s["modelo"])} · {h(hace(s["ultima"]))} · ' + t('{k}K de {umbral}K', k=k, umbral=UMBRAL_K) + (t(' · fría: no reanudar, sesión nueva con /handoff') if s.get("fria") else "") + '</div>')
        partes.append(f'<div class="bar {clase_bar}"><i style="width:{pct}%"></i></div>')
        partes.append(f'<div class="estado">{h(s["estado"])}</div>')
        if s['pedido']:
            partes.append(f'<div class="pedido"><b>{t("Pedido:")}</b> {h(s["pedido"])}</div>')
        if s['respuesta'] and not s['activa']:
            partes.append(f'<div class="pedido"><b>{t("Último mensaje:")}</b> {h(s["respuesta"])}</div>')
        if s['subagentes']:
            partes.append('<ul class="agentes">')
            for a in s['subagentes'][:8]:
                partes.append(f'<li class="{a["estado"].replace("ó","o").replace(" ","-")}"><span class="tipo">{h(a["agente"])}</span>'
                              f'<span class="pill">{h(t("trabajando") if a["estado"] == "trabajando" else t("terminó"))}</span><br>{h(a["tarea"])}'
                              f'<div class="sub">{h(a["modelo"])}{" (" + t("fuera de regla: {modelo}", modelo=h(a["fuera"])) + ")" if a.get("fuera") else ""} · {t("empezó")} {h(hace(a["inicio"]))}'
                              f'{" · " + h(duracion(a["inicio"], a["ultimo"])) if a["estado"] != "trabajando" else ""}'
                              f'{" · " + h(corto(a["herramienta"], 60)) if a["estado"] == "trabajando" and a["herramienta"] else ""}</div></li>')
            partes.append('</ul>')
        partes.append('</article>')
    partes.append('</section><aside><h2>' + t('Lo que pasa en la oficina') + '</h2><ol>')
    if not eventos:
        partes.append('<li>' + t('Sin eventos todavía.') + '</li>')
    for cuando, ses, clase, texto in eventos:
        partes.append(f'<li class="{clase}"><span class="cuando">{h(hace(cuando))}</span><span class="ses">{h(ses)}</span> {h(texto)}</li>')
    partes.append('</ol></aside></main></body></html>')
    return ''.join(partes)


def _url_fuentes():
    """Dónde busca la página las fuentes (`fuentes/`, que se queda junto al código). Con la página en la misma carpeta
    (o sirviéndola `--serve`) basta la ruta relativa; con la página en otra carpeta de datos, una URL `file://`
    absoluta hacia el código. Sin red en ningún caso."""
    if DATOS == AQUI or SERVIDO:
        return 'fuentes/'
    return pathlib.Path(AQUI).joinpath('fuentes').as_uri() + '/'


SERVIDO = False        # servidor() lo pone en True: entrega /fuentes/ desde el código, así que la ruta relativa sirve

CSS_PIXEL = """
@font-face{font-family:'Press Start 2P';font-style:normal;font-weight:400;font-display:swap;src:url('fuentes/press-start-2p-latin-400-normal.woff2') format('woff2')}
@font-face{font-family:'JetBrains Mono';font-style:normal;font-weight:400;font-display:swap;src:url('fuentes/jetbrains-mono-latin-400-normal.woff2') format('woff2')}
@font-face{font-family:'JetBrains Mono';font-style:normal;font-weight:700;font-display:swap;src:url('fuentes/jetbrains-mono-latin-700-normal.woff2') format('woff2')}
:root{--bg:#efe9df;--panel:#fffaf1;--edge:#8b5a3c;--ink:#2b2420;--dim:#7a6f66;--green:#2f9e5f;--gold:#d9a21b;--cyan:#2d8fbf;--red:#d64545;--line:#e6dccb}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.5 "JetBrains Mono",monospace;
 background-image:linear-gradient(rgba(139,90,60,.06) 1px,transparent 1px),linear-gradient(90deg,rgba(139,90,60,.06) 1px,transparent 1px);background-size:24px 24px}
.px{font-family:"Press Start 2P",monospace}
.win{padding:4px;background:var(--edge);clip-path:polygon(0 8px,4px 8px,4px 4px,8px 4px,8px 0,calc(100% - 8px) 0,calc(100% - 8px) 4px,calc(100% - 4px) 4px,calc(100% - 4px) 8px,100% 8px,100% calc(100% - 8px),calc(100% - 4px) calc(100% - 8px),calc(100% - 4px) calc(100% - 4px),calc(100% - 8px) calc(100% - 4px),calc(100% - 8px) 100%,8px 100%,8px calc(100% - 4px),4px calc(100% - 4px),4px calc(100% - 8px),0 calc(100% - 8px))}
.win>.in{background:var(--panel);padding:12px 14px;height:100%}
header{display:flex;flex-wrap:wrap;gap:10px 24px;align-items:center;margin:0;padding:14px 20px 8px;position:sticky;top:0;z-index:10;background:var(--bg);border-bottom:1px dashed var(--line)}
header h1{font-size:13px;margin:0;color:var(--edge)}header .hud{font-size:8px;color:var(--dim);display:flex;gap:18px;flex-wrap:wrap}header .hud b{color:var(--ink)}header .hud .red{color:var(--red)}
main{display:block;padding:8px 20px 28px}
.piso{display:flex;flex-direction:column;gap:14px;min-width:0}
.mapa-in{padding:6px;overflow:auto;position:relative}
.elev-btn{cursor:pointer}.elev-btn .cara{fill:#fbfaf6}.elev-btn:hover .cara{fill:#ffe9a8}.elev-btn.on .cara{fill:#5fd068}.elev-btn .cuenta{fill:#7a6f66}.elev-btn.on .cuenta{fill:#2b2420}.mapa,.iso{display:block;max-width:100%;height:auto;image-rendering:pixelated;margin:0 auto}
.esquina{position:absolute;top:8px;right:14px;z-index:4;width:340px;max-width:calc(100% - 28px);background:rgba(255,250,241,.93);border:2px solid var(--edge);border-radius:6px;box-shadow:0 2px 0 var(--edge);padding:4px 10px 6px}
.esquina .lista li{grid-template-columns:112px 36px 1fr;gap:3px 8px;padding:3px 0;font-size:10px}.esquina .lista .n,.esquina .lista .k{font-size:6px}
.lista li.grupo{display:block;font-size:6px;color:var(--edge);padding:7px 0 3px;cursor:default;border-top:0}.lista li.grupo+li{border-top:0}
.hoja-roja{animation:parpadeo .8s steps(2) infinite}.relevo{cursor:help}
.esquina .cab{display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:6px;color:var(--edge);padding:4px 0 2px;white-space:nowrap}
.esquina .plegar{cursor:pointer;padding:2px 6px;border:1px solid var(--line);border-radius:4px;color:var(--dim)}.esquina .plegar:hover{color:var(--edge);border-color:var(--edge)}
.esquina.plegada{width:auto;padding-bottom:4px}.esquina.plegada .lista,.esquina.plegada .vermas{display:none}
.dialogo .handoff-btn{position:absolute;right:14px;top:38px;font-size:6px;color:#9fe3a6;cursor:pointer;border:1px solid #5fd068;border-radius:4px;padding:3px 6px}.dialogo .handoff-btn:hover{background:#6b4426}.dialogo .relevo-btn.bajo{top:58px}.dialogo.fria{padding-right:170px}.dialogo .entrada[hidden]{display:none}
.hoja-fria{cursor:help}.fuera{color:#d64545!important}.regla{cursor:help}
.dialogo .relevo-btn{position:absolute;right:14px;top:38px;font-size:6px;color:#ffd35c;cursor:pointer;border:1px solid #e0b64a;border-radius:4px;padding:3px 6px}.dialogo .relevo-btn:hover{background:#6b4426}
.esquina .vermas{font-size:6px;color:var(--edge);text-align:right;padding:6px 0 0;cursor:pointer}.esquina .vermas:hover{color:var(--ink)}
.modal{position:fixed;inset:0;z-index:20;background:rgba(43,36,32,.55);display:flex;align-items:center;justify-content:center}.modal[hidden]{display:none}
.modal .win{width:min(780px,92vw);max-height:84vh;display:flex}.modal .win.feed{width:min(1180px,94vw)}.modal .win.panel{width:min(940px,92vw)}
.tablon{cursor:pointer}.tablon:hover polygon{filter:brightness(1.06)}.modal .in{overflow:auto;width:100%;max-height:84vh}.modal .cab{display:flex;align-items:center;justify-content:space-between;font-size:8px;color:var(--edge);padding:2px 0 8px;border-bottom:1px dashed var(--line);margin-bottom:4px}
.modal .x{border:0;background:transparent;color:var(--dim);cursor:pointer;font-size:14px}.modal .x:hover{color:var(--ink)}
.bob{animation:bob .5s steps(2) infinite}@keyframes bob{to{transform:translateY(.5px)}}
.agente{cursor:help}
.dialogo{position:absolute;left:16px;right:16px;bottom:14px;z-index:7;min-height:112px;background:#5a3a1f;border:3px solid #e0b64a;outline:2px solid #2b2420;border-radius:8px;box-shadow:0 4px 0 rgba(0,0,0,.35);padding:16px 44px 14px 150px;color:#fbfaf6;cursor:pointer}
.dialogo .texto{font-size:10px;line-height:2;min-height:60px;word-break:break-word}.dialogo .texto .c{color:#5fd8ff}.dialogo .texto .m{color:#d29bff}.dialogo .texto .g{color:#ffd35c}
.dialogo .retrato{position:absolute;left:14px;bottom:8px;width:118px;text-align:center}.dialogo .retrato svg{width:96px;height:96px;image-rendering:pixelated;display:block;margin:0 auto -6px;filter:drop-shadow(0 3px 0 rgba(0,0,0,.35))}
.dialogo .placa{display:inline-block;font-size:5.5px;line-height:1.7;padding:4px 7px;background:#2b2420;color:#fbfaf6;border:2px solid #e0b64a;border-radius:4px;max-width:124px;word-break:break-all}
.dialogo .mas{position:absolute;right:16px;bottom:10px;font-size:9px;color:#ffd35c;animation:parpadeo .7s steps(2) infinite}@keyframes parpadeo{to{opacity:0}}
.dialogo .ver{position:absolute;right:14px;top:8px;font-size:6px;color:#e0b64a;text-decoration:none;cursor:pointer}.dialogo .ver:hover{color:#fff}
.dialogo .x{position:absolute;right:14px;top:22px;font-size:6px;color:#b9a27a;cursor:pointer}.dialogo .x:hover{color:#fff}.tip{position:absolute;z-index:6;pointer-events:none;background:var(--panel);border:1px solid var(--edge);box-shadow:0 2px 0 var(--edge);border-radius:6px;padding:6px 9px;max-width:260px;font-size:11px;line-height:1.4}.tip .n{font-size:7px;color:var(--gold);margin-bottom:4px;white-space:nowrap}.tip .d{color:var(--dim);font-size:10px}
.lista{list-style:none;margin:0;padding:0}.lista li{display:grid;grid-template-columns:150px 44px 1fr;gap:4px 10px;align-items:center;padding:5px 0;border-top:1px dashed var(--line);font-size:11px;cursor:pointer}
.lista li.sel{background:#f3ecdd}.lista .b{width:26px;height:24px;border:1px solid var(--line);background:transparent;color:var(--dim);border-radius:4px;font-size:14px;line-height:1;cursor:pointer;padding:0}
.lista .b:hover,.lista .b.on{border-color:var(--edge);color:var(--edge)}.lista li.menu-fila{display:flex;justify-content:flex-end;border-top:0;padding:0 0 6px;cursor:default}
.menu{background:var(--panel);border:1px solid var(--edge);border-radius:6px;padding:4px;width:230px;font-size:11.5px}.menu div{padding:6px 8px;border-radius:4px;cursor:pointer;display:flex;gap:8px}.menu.flot{position:absolute;z-index:5;box-shadow:0 2px 0 var(--edge)}.menu .cab{font-size:7px;color:var(--green);cursor:default;border-bottom:1px dashed var(--line);border-radius:0;margin-bottom:3px}.menu .cab:hover{background:transparent}
.menu div:hover{background:#f3ecdd}.menu small{margin-left:auto;color:var(--dim)}.menu .sep{border-top:1px dashed var(--line);margin-top:3px;padding-top:8px}
.panel .in{padding:0}.panel .cab{display:flex;gap:10px;align-items:center;padding:10px 12px}.panel .cab .n{font-size:7px;color:var(--dim)}.panel .cab .n.on{color:var(--green)}
.panel .meta{font-size:10px;color:var(--dim)}.panel .x{margin-left:auto;border:0;background:transparent;color:var(--dim);cursor:pointer;font-size:14px}
.panel .tabs{display:flex;gap:2px;border-bottom:1px dashed var(--line);padding:0 10px}.panel .tabs span{padding:7px 9px;font-size:11px;color:var(--dim);cursor:pointer}.panel .tabs span.a{color:var(--ink);border-bottom:2px solid var(--edge)}
.panel .cuerpo{padding:10px 12px;font-size:12px}.panel .t{margin:4px 0}.panel .dim{color:var(--dim)}
.panel .crew{list-style:none;margin:0;padding:0}.panel .crew li{display:flex;gap:8px;align-items:center;padding:5px 0;border-top:1px dashed var(--line)}.panel .crew li:first-child{border-top:0}
.panel .crew svg{width:20px;height:20px;image-rendering:pixelated}.panel .crew .n2{font-size:6.5px;color:var(--gold);white-space:nowrap}.panel .crew li.ok .n2{color:var(--green)}.panel .crew li.fin{opacity:.6}
.panel .crew .t2{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.panel .crew .s2{color:var(--dim);font-size:10.5px;white-space:nowrap}
.panel .hist{list-style:none;margin:0;padding:0}.panel .hist li{padding:4px 0;border-top:1px dashed var(--line);font-size:11.5px}.panel .hist .cuando{float:right;color:var(--dim);font-size:10px}
.panel .hist li.encargo::before{content:'→ ';color:var(--gold)}.panel .hist li.fin::before{content:'✓ ';color:var(--green)}.panel .hist li.pedido::before{content:'✎ ';color:var(--dim)}
.panel .datos{border-collapse:collapse;font-size:11.5px}.panel .datos td{padding:3px 12px 3px 0;vertical-align:top}.panel .datos td:first-child{color:var(--dim);white-space:nowrap}.panel .datos .red{color:var(--red)}.panel .datos .gold{color:var(--gold)}.panel .datos .dim{color:var(--dim)}.panel .datos.git{margin-top:12px}.panel .datos.git tr:first-child td{color:var(--dim);border-bottom:1px solid var(--line, #d9d2c2)}.panel .datos.git td:first-child{color:inherit}.panel .ideas{margin:0 0 4px;padding:0;list-style:none}
.lista li:first-child{border-top:0}.lista .n{font-size:7px;color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.lista li.activa .n{color:var(--green)}
.lista .k{font-size:7px;color:var(--green)}.lista .k.gold{color:var(--gold)}.lista .k.red{color:var(--red)}.px.red{color:var(--red)}.px.gold{color:var(--gold)}
.lista .e{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.lista li.espera .e{color:var(--dim)}
.lista .crew,.lista .pd{grid-column:3;font-size:10.5px;color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lista .crew svg{width:16px;height:16px;vertical-align:-4px;image-rendering:pixelated}.lista .crew em{font-style:normal;color:var(--gold);font-family:"Press Start 2P",monospace;font-size:6px;margin:0 4px 0 2px}
.feed h2{font-size:8px;margin:0 0 10px;color:var(--edge)}.feed ol{list-style:none;margin:0;padding:0;columns:3;column-gap:24px}@media(max-width:1100px){.feed ol{columns:2}}@media(max-width:700px){.feed ol{columns:1}}
.feed li{padding:6px 0;border-top:1px dashed var(--line);font-size:11px;break-inside:avoid}
.feed .cuando{float:right;color:var(--dim);font-size:10px}.feed .ses{color:var(--cyan);font-family:"Press Start 2P",monospace;font-size:6.5px;margin-right:6px}
.feed li.encargo::before{content:'→ ';color:var(--gold)}.feed li.fin::before{content:'✓ ';color:var(--green)}.feed li.pedido::before{content:'✎ ';color:var(--dim)}.feed li.chat::before{content:'» ';color:var(--cyan)}
.panel .chat{list-style:none;margin:0;padding:0}.panel .chat li{padding:6px 0;border-top:1px dashed var(--line);font-size:11.5px}.panel .chat li .t{white-space:pre-wrap;word-break:break-word}
.panel .chat li.yo{text-align:right}.panel .chat .cuando{float:right;color:var(--dim);font-size:10px}.panel .chat li.yo .cuando{float:left}.panel .chat .de{display:block;font-size:6px;color:var(--cyan);margin-bottom:3px}.panel .chat li.yo .de{color:var(--gold)}
.dialogo.chat{padding-bottom:42px;padding-right:80px}.dialogo .entrada{position:absolute;left:150px;right:44px;bottom:10px;display:flex;gap:8px;align-items:center;border-top:1px dashed #a37b4c;padding-top:7px;cursor:text}
.dialogo .entrada .pr{color:#ffd35c;font-size:9px;animation:parpadeo .9s steps(2) infinite}.dialogo .entrada input{flex:1;min-width:0;background:transparent;border:0;outline:0;color:#fbfaf6;font-size:8px;caret-color:#ffd35c}
.dialogo .entrada input::placeholder{color:#b9a27a}.dialogo .entrada input:disabled{color:#b9a27a}.dialogo .entrada .estado{font-size:6px;color:#b9a27a;white-space:nowrap;max-width:40%;overflow:hidden;text-overflow:ellipsis}.dialogo .entrada .estado.mal{color:#ff8a7a}
.vacio{color:var(--dim);padding:20px;font-size:9px}
.medidor{margin-left:auto;font-size:8px;line-height:1.4;padding:6px 10px;border:2px solid var(--edge);background:var(--panel);color:var(--ink);border-radius:6px;box-shadow:0 2px 0 var(--edge);cursor:pointer;white-space:nowrap}.medidor:hover{background:#f3ecdd}
.medidor.verde{border-color:var(--green)}.medidor.ambar{border-color:var(--gold)}.medidor.rojo{border-color:var(--red);color:var(--red)}.medidor.gris{border-color:var(--line);color:var(--dim);box-shadow:none}.medidor b{font-weight:400}
.salida{margin-left:0}.salida[hidden]{display:none}
#aviso-salida{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:50;max-width:calc(100vw - 32px);font-size:9px;line-height:1.5;text-align:center;padding:10px 14px;border:2px solid var(--edge);background:var(--panel);color:var(--ink);border-radius:6px;box-shadow:0 2px 0 var(--edge)}#aviso-salida.mal{border-color:var(--red);color:var(--red)}
.pizarron{cursor:pointer}.pizarron:hover polygon{filter:brightness(1.06)}
.modal .win.costo{width:min(1040px,94vw)}.costo h3{font-size:8px;color:var(--edge);margin:14px 0 6px;font-weight:400}.costo h3:first-child{margin-top:4px}.costo h3 small{font-family:"JetBrains Mono",monospace;font-size:10px;color:var(--dim);margin-left:8px}
.costo table{border-collapse:collapse;width:100%;font-size:11.5px}.costo th{font-size:6.5px;font-weight:400;color:var(--dim);text-align:left;padding:3px 10px 3px 0;border-bottom:1px solid var(--line)}.costo td{padding:4px 10px 4px 0;border-top:1px dashed var(--line);vertical-align:top}.costo th+th,.costo td+td{text-align:right}
.costo td small,.costo .dim{color:var(--dim);font-size:10px;font-weight:400}.costo td.t{max-width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left}.costo .verde{color:var(--green)}.costo .ambar{color:var(--gold)}.costo .rojo{color:var(--red)}
.costo .dos{display:grid;grid-template-columns:1fr 1fr;gap:6px 28px}.costo .tres{display:grid;grid-template-columns:repeat(3,1fr);gap:6px 28px}@media(max-width:900px){.costo .dos,.costo .tres{grid-template-columns:1fr}}
.costo .grande{font-size:12px;margin:2px 0 4px}.costo p{margin:3px 0;font-size:11px}.costo .vacio{padding:6px 0;font-size:8px}
footer{color:var(--dim);font-size:7px;text-align:center;padding:0 0 18px}
"""


def datos_vivos(sesiones, eventos, escala=None):
    """Lo que la página necesita para pintarse: el plano (SVG), los símbolos, las sesiones y el feed."""
    import oficina_iso
    simbolos = {}

    def simbolo(clave, cuerpo, raw=False):
        if clave not in simbolos:
            simbolos[clave] = cuerpo if raw else f'<symbol id="{clave}" viewBox="0 0 32 32">{cuerpo}</symbol>'
        return clave

    pisos, pb, asignados, aviso = cargar_pisos()
    aviso = ' · '.join(a for a in (aviso, aviso_version()) if a) or None      # pisos.json y versión: si hay los dos, salen los dos
    try:
        relevos = afk.leer_relevos() if afk else {}
    except Exception as e:                    # extra: nunca tumba la pasada
        print('relevos:', e, file=sys.stderr)
        relevos = {}
    for s in sesiones:
        s['piso'] = piso_de(s, pisos, pb, asignados)
        espera = (ahora() - s['ultima']).total_seconds() if s['ultima'] else 0
        s['fria'] = s['contexto_k'] >= UMBRAL_K and not s['activa'] and espera >= FRIA_S   # regla B: no reanudar, sesión nueva + /handoff
        s['relevada'] = afk.relevada(s, relevos, s['ultima']) if afk else False    # «afk»: /checkpoint hecho, falta /clear
        if s['relevada']:
            s['estado'] = t('relevada: /clear y /handoff antes de escribir')
    contadores = (sum(1 for s in sesiones if s['activa']), sum(s['encargos_activos'] for s in sesiones))
    nombres = [(p['nombre'], p['etiqueta']) for p in pisos]
    mapas, meta = [], []
    sala = cubiculos(sesiones, pisos, pb, asignados)           # lo que se dibuja por piso: con grupos, cubículos fijos (los sin actividad, vacíos)
    ocio = azotea(sesiones)                                    # los especialistas sin encargo, con su actividad
    for i, p in enumerate(pisos):                              # un plano por piso; sala y cocina en el lobby, ocio en la azotea, descanso en los vacíos
        en = sala[i]
        arriba = bool(p.get('azotea'))
        sotano = bool(p.get('sotano')) or p['nombre'].startswith('Sótano')            # el garaje: otro estilo y su rincón en vez del descanso
        extras = OCIO_ZONAS if arriba else (('sala', 'cocina') if i == pb else (('rincon',) if sotano else (('descanso',) if not en else ())))
        mapas.append(oficina_iso.render_piso(en, simbolo, cols=2 if arriba else 4, escala=escala or ESCALA, extras=extras, contadores=contadores,
                                             pisos=nombres, ocio=ocio if arriba else None, estilo='sotano' if sotano else None))
        meta.append({'nombre': p['nombre'], 'etiqueta': p['etiqueta'], 'n': sum(1 for s in sesiones if s['piso'] == i), 'activas': sum(1 for s in sesiones if s['piso'] == i and s['activa'])})
    ses = []
    for s in sesiones:
        d = dict(s)
        d['ultima'] = hace(s['ultima'])
        d['espera_s'] = int((ahora() - s['ultima']).total_seconds()) if s['ultima'] else 0
        d['subagentes'] = [dict(a, inicio=hace(a['inicio']), ultimo=hace(a['ultimo']), duracion=duracion(a['inicio'], a['ultimo'])) for a in s['subagentes']]
        d['historial'] = [dict(e, cuando=hace(e['cuando'])) for e in s['historial']]
        d['crew_svg'] = {a['agente']: simbolo('ag-' + ''.join(c if c.isalnum() else '-' for c in a['agente']), sprites.agente(a['agente'], 'feliz')) for a in s['subagentes']}
        d['corto'] = {a['agente']: sprites.corto(a['agente']) for a in s['subagentes']}
        ses.append(d)
    return {
        'generado': dt.datetime.now().strftime('%d %b %H:%M:%S'),
        'activas': sum(1 for s in sesiones if s['activa']),
        'trabajando': sum(s['encargos_activos'] for s in sesiones),
        'simbolos': ''.join(simbolos.values()), 'mapas': mapas, 'pisos': meta, 'lobby': pb, 'aviso': aviso,
        'sesiones': ses,
        'textos': textos.para_js(),                # las traducciones del JS (vacío en español)
        'usuario': USUARIO, 'zona': {'nombre': (config.zona() or (0, None))[1], 'etiqueta': ZONA_ETIQUETA},
        'costo': costo.resumen(UMBRAL_K),          # medidor y pizarrón de costo; memo de 60 s, None si falla
        'eventos': [{'cuando': hace(t), 'hace_s': int((ahora() - t).total_seconds()) if t else None, 'sesion': s_, 'clase': c, 'texto': x} for t, s_, c, x in eventos],
        'chat': {'sesion': CHAT_SESION,
                 'cli': next((s['cli'] for s in sesiones if s['titulo'] == CHAT_SESION), None),
                 'hilo': [{'cuando': hace(m['cuando']), 'id': m['cuando'].isoformat(), 'de': m['de'], 'texto': m['texto']}
                          for m in chat_hilo()]} if CHAT_SESION else None,       # sin chat_sesion: no hay chat
    }


JS = r"""
const $ = (q, el=document) => el.querySelector(q);
const h = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let D = JSON.parse($('#datos').textContent);
let ui = {sel: null, tab: 'pedido', menu: null, piso: null, dialogo: null, modal: null};   // modal: null | 'sesiones' | 'feed' | 'costo' | 'panel'   // dialogo: {cli, agente|null, paginas, pag, pos, escribiendo}   // sel y menu guardan el id de transcripción (cli), único; piso: índice en D.pisos, de abajo arriba (el lobby es D.lobby; null hasta el primer pintado)
const CADA = %CADA%;
// textos: la clave es la frase en español tal cual; D.textos trae las traducciones (vacío en español). {marcador} se cambia por v.marcador
function T(es, v){ const s = (D.textos && D.textos[es]) || es; return v ? s.replace(/\{(\w+)\}/g, (m, k) => k in v ? v[k] : m) : s; }
const ES = T('es-MX') === 'es-MX';
function dec(x, d){ const s = x.toFixed(d); return ES ? s.replace('.', ',') : s; }
function etq(g){ return g === 'Relevo' ? T('Relevo') : g === 'Esperan' ? T('Esperan') : T('Trabajan'); }   // los grupos de la cola se identifican por su código en español
function dur(seg){ return seg < 60 ? T('segundos') : seg < 3600 ? T('{n} min', {n: Math.floor(seg / 60)}) : seg < 86400 ? T('{n} h', {n: (seg / 3600).toFixed(1)}) : T('{n} d', {n: Math.floor(seg / 86400)}); }
function durS(s){ return s.ultima === '—' ? '—' : dur(s.espera_s); }                // cuánto lleva quieta, a partir de los segundos (nunca del texto de hace())

function clase_k(k){ return k >= %UMBRAL% ? 'red' : (k >= %UMBRAL% * 0.8 ? 'gold' : ''); }
function pintar(){
  const G = grupos();
  if (ui.piso == null || !D.mapas[ui.piso]) ui.piso = D.lobby || 0;            // primer pintado, o el piso ya no existe: al lobby
  const P = D.pisos[ui.piso];
  $('#hud').innerHTML = G.map(([t, l]) => `<span>${etq(t).toLowerCase()} <b>${l.length}</b></span>`).join('') + `<span>${T('agentes')} <b>${D.trabajando}</b></span><span>${T('piso')} <b>${h(P.nombre)}</b> ${P.n}</span><span>${h(D.generado)}</span>${CADA?`<span>${T('cada {n}s', {n: CADA})}</span>`:''}${D.aviso?`<span class="red">${h(D.aviso)}</span>`:''}`;
  $('#simbolos').innerHTML = D.simbolos;
  const mapaHtml = D.mapas[ui.piso];
  if ($('#mapa').dataset.v !== mapaHtml.length + '|' + ui.piso){ $('#mapa').innerHTML = mapaHtml; $('#mapa').dataset.v = mapaHtml.length + '|' + ui.piso; }
  // elevador: un botón por piso; se enciende el del piso actual y cada uno muestra sus sesiones activas
  document.querySelectorAll('#mapa .elev-btn').forEach(g => {
    const i = +g.dataset.piso;
    g.classList.toggle('on', i === ui.piso);
    g.querySelector('.cuenta').textContent = D.pisos[i] ? (D.pisos[i].activas || '') : '';
    g.onclick = e => { e.stopPropagation(); ui.piso = i; pintar(); };
  });
  document.querySelectorAll('#mapa [data-elev-piso]').forEach(t => t.textContent = D.pisos[ui.piso].etiqueta);
  // tablón de avisos: clic abre el feed; el contador cuenta los eventos de los últimos 15 min
  const recientes = D.eventos.filter(e => e.hace_s != null && e.hace_s < 960).length;
  document.querySelectorAll('#mapa .tablon').forEach(g => { g.onclick = e => { e.stopPropagation(); ui.modal = 'feed'; pintar(); }; g.querySelector('[data-tablon-cuenta]').textContent = recientes ? `+${recientes}` : ''; });
  // pizarrón de la sala: el % semanal estimado en grande; clic abre el modal de costo (como el tablón abre el feed)
  const cp = cuotaPct();
  document.querySelectorAll('#mapa .pizarron').forEach(g => {
    g.onclick = e => { e.stopPropagation(); ui.modal = 'costo'; pintar(); };
    const t = g.querySelector('[data-pizarron-pct]'); if (t){ t.textContent = cp == null ? '--%' : Math.round(cp) + '%'; t.setAttribute('fill', COL_CUOTA[nivelCuota(cp)]); }
  });
  medidor();
  document.querySelectorAll('#mapa g[data-sesion]').forEach(g => { g.style.cursor='pointer'; g.onclick = e => { e.stopPropagation(); hablar(g.dataset.sesion, null); }; });
  document.querySelectorAll('#mapa g[data-vacia]').forEach(g => { if (!g.dataset.enlace) return; g.style.cursor = 'pointer'; g.onclick = e => { e.stopPropagation(); location.href = g.dataset.enlace; }; });   // cubículo vacío: abre la sesión en la app
  // agentes de pie: tooltip propio (nombre, tarea, herramienta) y clic → pestaña Agentes de su sesión
  document.querySelectorAll('#mapa .agente').forEach(u => {
    u.onmouseenter = e => tip(u, e); u.onmousemove = e => tip(u, e); u.onmouseleave = () => tip(null);
    u.onclick = e => { e.stopPropagation(); tip(null); hablar(u.dataset.sesion, u.dataset.agente); };
  });
  // objetos del plan (rotafolio, sobre, marcas de la placa): abren la pestaña Plan
  document.querySelectorAll('#mapa .plan-obj').forEach(g => { g.style.cursor = 'pointer'; g.onclick = e => { e.stopPropagation(); abrir(g.dataset.plan, 'plan'); }; });
  // burbujas del plano: abren el menú flotante
  document.querySelectorAll('#mapa .burbuja').forEach(g => { g.style.cursor = 'pointer'; g.onclick = e => { e.stopPropagation(); ui.menu = (ui.menu === g.dataset.menu) ? null : g.dataset.menu; pintar(); }; });
  menu();
  llenar($('#lista'), G, 10);                                                 // cuadro de la esquina: la cola, 10 filas
  $('#cola-resumen').textContent = G.map(([t, l]) => `${etq(t).toLowerCase()} ${l.length}`).join(' · ');
  const Q = $('#esquina');
  if (!Q.dataset.listo){                                                        // plegar/desplegar, recordado en este navegador
    Q.dataset.listo = '1'; let pleg = false; try { pleg = localStorage.getItem('oficina.esquina') === 'plegada'; } catch (e) {}
    const aplicar = p => { Q.classList.toggle('plegada', p); $('#plegar').textContent = p ? '▸' : '▾'; };
    aplicar(pleg);
    $('#plegar').onclick = e => { e.stopPropagation(); const p = !Q.classList.contains('plegada'); aplicar(p); try { localStorage.setItem('oficina.esquina', p ? 'plegada' : 'abierta'); } catch (e) {} };
  }
  const vm = $('#vermas'); vm.hidden = D.sesiones.length <= 10; vm.textContent = T('ver más ({n}) ▸', {n: D.sesiones.length});
  vm.onclick = e => { e.stopPropagation(); ui.modal = 'sesiones'; modal(); };
  const feed = $('#feed'); feed.innerHTML = D.eventos.length ? '' : '<li>' + T('Sin eventos todavía.') + '</li>';
  for (const e of D.eventos){ const li = document.createElement('li'); li.className = e.clase; li.innerHTML = `<span class="cuando">${h(e.cuando)}</span><span class="ses">${h(e.sesion)}</span>${h(e.texto)}`; feed.appendChild(li); }
  panel();
  modal();
  if (ui.dialogo && ui.dialogo.chat) hablarChat(true);                          // si llegó respuesta, la caja la teclea
}
// la cola: a quién atender primero. Relevo (pasaron de %UMBRAL%K), Esperan (a que los atiendas, la más antigua arriba), Trabajan.
function grupos(){
  const relevo = D.sesiones.filter(s => s.contexto_k >= %UMBRAL%).sort((a, b) => (a.fria - b.fria) || (b.contexto_k - a.contexto_k));   // las frías al final: no se relevan en caliente
  const esperan = D.sesiones.filter(s => s.contexto_k < %UMBRAL% && !s.activa).sort((a, b) => b.espera_s - a.espera_s);
  const trabajan = D.sesiones.filter(s => s.contexto_k < %UMBRAL% && s.activa);
  return [['Relevo', relevo], ['Esperan', esperan], ['Trabajan', trabajan]];
}
function textoFila(grupo, s){
  if (grupo === 'Relevo' && s.fria) return T('fría · no reanudar · {t}', {t: durS(s)});
  if (grupo === 'Relevo') return s.activa ? T('al terminar · {estado}', {estado: s.estado}) : T('espera {t}', {t: durS(s)});
  if (grupo === 'Esperan') return `${s.ultima}`;
  return s.estado;
}
function llenar(lista, G, max=Infinity){
  const filas = []; let n = 0;                                                  // [grupo, sesión] en orden, con tope de filas
  for (const [t, l] of G){ if (!l.length || n >= max) continue; filas.push([t, null]); for (const s of l){ if (n >= max) break; filas.push([t, s]); n++; } }
  const orden = filas.map(([t, s]) => s ? s.cli : '#' + t).join('\n');
  if (lista.dataset.orden !== orden){                                           // solo se reconstruye si cambian las filas
    lista.innerHTML = ''; lista.dataset.orden = orden;
    for (const [t, s] of filas){
      const li = document.createElement('li');
      if (!s){ li.className = 'grupo px'; li.dataset.g = t; lista.appendChild(li); continue; }
      li.dataset.t = s.cli; li.dataset.g = t;
      li.innerHTML = `<span class="n px" title="${h(s.titulo)}">${h(s.titulo)}</span><span class="k px"></span><span class="e"></span>`;
      li.onclick = e => { e.stopPropagation(); abrir(s.cli, ui.sel === s.cli ? ui.tab : 'pedido'); };
      lista.appendChild(li);
    }
  }
  for (const [t, l] of G){ const g = lista.querySelector(`li.grupo[data-g="${t}"]`); if (g) g.textContent = `${etq(t).toUpperCase()} (${l.length})`; }
  for (const [t, s] of filas){                                                  // y los datos se actualizan en sitio
    if (!s) continue;
    const li = lista.querySelector(`li[data-t="${CSS.escape(s.cli)}"]`); if (!li) continue;
    li.className = (s.activa ? 'activa' : 'espera') + (ui.sel === s.cli ? ' sel' : '');
    const k = li.querySelector('.k'); k.textContent = s.contexto_k + 'K'; k.className = 'k px ' + clase_k(s.contexto_k);
    li.querySelector('.e').textContent = textoFila(t, s);
  }
}
// ---- costo de la cuota: medidor de la cabecera, % del pizarrón y modal (A · Cuota, B · Quién gasta, C · Fugas) ----
const COL_CUOTA = {verde: '#2f9e5f', ambar: '#d9a21b', rojo: '#d64545', gris: '#7a6f66'};
function nivelCuota(p){ return p == null ? 'gris' : p >= 90 ? 'rojo' : p >= 70 ? 'ambar' : 'verde'; }   // por el estimado semanal
function cuotaSemanal(){ const v = D.costo && D.costo.ventanas.semanal; return v && !v.vieja ? v : null; }
function cuotaPct(){ const v = cuotaSemanal(); return v ? (v.estimado ?? v.leido) : null; }      // estimado ahora; si no hay escala, lo leído
function haceIso(iso){
  const m = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
  return m < 1 ? T('ahora') : m < 60 ? T('hace {n} min', {n: m}) : m < 1440 ? T('hace {h} h {m} min', {h: Math.floor(m / 60), m: m % 60}) : T('hace {n} d', {n: Math.floor(m / 1440)});
}
function pc(x, d){ return x == null ? '—' : (d ? dec(x, d) : String(Math.round(x))) + ' %'; }
function medidor(){
  const M = $('#medidor'); if (!M) return;
  if (!M.dataset.listo){ M.dataset.listo = '1'; M.onclick = e => { e.stopPropagation(); ui.modal = 'costo'; pintar(); }; }
  const C = D.costo, v = C && C.ventanas.semanal, c5 = C && C.ventanas['5h'];
  if (!v || v.vieja){
    M.className = 'medidor px gris'; M.textContent = v ? T('cuota: lectura vieja') : T('cuota: sin lectura');
    M.title = v ? T('La última lectura ({lectura}) es de una semana ya cerrada. Clic para ver el detalle.', {lectura: v.leido_txt}) : T('Sin lecturas de get_usage: cuota.py anotar --fuente <origen> < usage.json');
    return;
  }
  const ahora = v.estimado ?? v.leido;
  M.className = 'medidor px ' + nivelCuota(ahora);
  M.textContent = T('Semana {pct}', {pct: pc(ahora)}) + (v.cierre != null ? ` → ~${pc(v.cierre)}` : '') + T(' · 5 h {pct}', {pct: c5 && !c5.vieja ? pc(c5.leido) : '—'});
  M.title = T('Última lectura {txt} ({hace}), {leido} % · reinicio {reinicio} ({zona})', {txt: v.leido_txt, hace: haceIso(v.leido_t), leido: v.leido, reinicio: v.reinicio, zona: D.zona.nombre || D.zona.etiqueta}) +
    (v.estimado != null ? T(' · estimado ahora {est} y proyección al reinicio {cierre} al ritmo de las últimas 24 h', {est: pc(v.estimado, 1), cierre: pc(v.cierre, 1)}) : T(' · sin escala todavía: no se estima')) +
    (c5 ? T(' · 5 h: {leido} % leído {hace}', {leido: c5.leido, hace: haceIso(c5.leido_t)}) + (c5.vieja ? T(' (ventana ya reiniciada)') : '') : '') + T(' · clic: detalle');
}
function costo(){
  const C = D.costo, B = $('#costo-cuerpo'); if (!B) return;
  const llave = (C ? C.generado : 'x') + '|' + Math.floor(Date.now() / 60000) + '|' + D.sesiones.map(s => s.cli + s.contexto_k).join(',');
  if (B.dataset.v === llave) return;                                            // el bloque cambia como mucho una vez por minuto
  B.dataset.v = llave;
  if (!C){ B.innerHTML = '<p class="vacio px">' + T('Sin datos de costo. ¿Corrió bitacora.py --reconstruir?') + '</p>'; return; }
  const V = C.ventanas, nombre = s => s.titulo || ('(' + (s.proyecto || s.cli) + ')');
  // A · Cuota
  const fila = (n, v) => {
    if (!v) return `<tr><td>${n}</td><td colspan="5" class="dim">${T('sin lectura')}</td></tr>`;
    const act = v.estimado ?? null, k = nivelCuota(act ?? v.leido);
    return `<tr><td>${n}</td><td>${v.leido} % <small>${haceIso(v.leido_t)}</small></td>` +
      `<td class="${k}">${act != null ? pc(act, 1) : '<small>—</small>'}</td>` +
      `<td>${v.ritmo_dia != null ? dec(v.ritmo_dia, 1) + T(' %/día') : '<small>—</small>'}</td>` +
      `<td class="${nivelCuota(v.cierre)}">${v.cierre != null ? '~' + pc(v.cierre, 0) : '<small>—</small>'}</td>` +
      `<td>${h(v.reinicio)} <small>${v.horas != null ? T('en {h} h', {h: dec(v.horas, 1)}) : v.vieja ? T('ya reiniciada') : ''}</small></td></tr>`;
  };
  const sem = V.semanal;
  const ayuda = !sem ? '' : sem.vieja ? `<p class="dim">${T('La lectura semanal es de una semana ya cerrada: anota una nueva.')}</p>` : sem.estimado == null ? `<p class="dim">${T('Sin escala todavía (hacen falta lecturas con 3 % o más): no se estima.')}</p>` : '';
  const a = `<h3 class="px">${T('A · CUOTA')}<small>${T('reinicio en {zona} · el 5 h solo se lee, aún no se proyecta', {zona: h(D.zona.etiqueta)})}</small></h3>` +
    `<table><tr><th>${T('VENTANA')}</th><th>${T('LEÍDO')}</th><th>${T('ESTIMADO AHORA')}</th><th>${T('RITMO')}</th><th>${T('AL REINICIO')}</th><th>${T('REINICIO')}</th></tr>` +
    fila(T('Semanal · todos los modelos'), V.semanal) + fila(T('Semanal · Fable'), V.fable) +
    (V['5h'] ? `<tr><td>${T('5 horas')}</td><td>${V['5h'].leido} % <small>${haceIso(V['5h'].leido_t)}</small></td><td colspan="3" class="dim">${V['5h'].vieja ? T('la ventana ya se reinició: lectura vieja') : ''}</td><td>${h(V['5h'].reinicio)}</td></tr>` : `<tr><td>${T('5 horas')}</td><td colspan="5" class="dim">${T('sin lectura')}</td></tr>`) +
    `</table>` + ayuda;
  // B · Quién gasta
  const quien = (t, l, total) => `<div><p class="dim">${t}</p><table><tr><th>${T('PROYECTO')}</th><th>${T('% DE LA SEMANA')}</th></tr>` +
    (l.length ? l.map(s => { const det = (s.sesiones || []).map(x => `${x.titulo} ${x.pct == null ? 'US$ ' + x.usd : pc(x.pct, 1)}`).join(' · ');
      return `<tr><td class="t" title="${h(det)}">${h(s.proyecto)}<br><small>${T('{n} ses. · agentes {pct}', {n: (s.sesiones || []).length, pct: s.pct == null ? '—' : pc(s.agentes_pct, 1)})}</small></td><td>${s.pct == null ? 'US$ ' + s.usd : pc(s.pct, 1)}</td></tr>`; }).join('') : `<tr><td colspan="2" class="dim">${T('sin gasto')}</td></tr>`) +
    `</table><p class="dim">${T('top {n}: {top} · total: {total}', {n: l.length, top: pc(l.reduce((x, s) => x + (s.pct || 0), 0), 1), total: pc(total, 1)})}</p></div>`;
  const b = `<h3 class="px">${T('B · QUIEN GASTA')}<small>${T('peso ÷ escala ({escala}) · por proyecto; sus sesiones, al pasar el cursor · los agentes suman a su sesión madre', {escala: C.escala != null ? T('{n} US$ API por 1 %', {n: dec(C.escala, 2)}) : T('sin escala: se muestra US$')})}</small></h3>` +
    `<div class="dos">${quien(T('Esta semana (desde el último reinicio, {reinicio})', {reinicio: sem ? sem.reinicio : T('vie 06:00')}), C.quien.semana, C.quien.total_semana)}${quien(T('Hoy (día local)'), C.quien.hoy, C.quien.total_hoy)}</div>`;
  // C · Fugas
  const F = C.fugas;
  const vivas = F.sobre_umbral.map(f => ({f, s: D.sesiones.find(s => s.cli === f.cli && s.contexto_k >= C.umbral_k)})).filter(x => x.s);
  const c1 = `<div><p class="px dim" style="font-size:7px">${T('1 · VIVAS SOBRE {k}K', {k: C.umbral_k})}</p>` + (vivas.length ?
    `<table><tr><th>${T('SESIÓN')}</th><th>${T('% DE LA SEMANA')}</th></tr>` + vivas.map(({f, s}) => `<tr><td class="t" title="${h(s.titulo)}">${h(s.titulo)}<br><small>${T('{k}K ahora', {k: s.contexto_k})}</small></td><td>${f.pct == null ? 'US$ ' + f.usd : pc(f.pct, 1)}</td></tr>`).join('') + '</table>' : `<p class="dim">${T('Ninguna sesión viva por encima del umbral.')}</p>`) +
    `<p class="dim">${T('peso de sus llamadas hechas con ≥ {k}K de contexto', {k: C.umbral_k})}</p></div>`;
  const fr = F.frias;
  const c2 = `<div><p class="px dim" style="font-size:7px">${T('2 · REANUDACIONES FRIAS')}</p><p class="grande">${T('{n} llamadas · {pct}', {n: fr.n, pct: fr.pct == null ? 'US$ ' + fr.usd : pc(fr.pct, 1)})}</p>` +
    (fr.top.length ? '<table>' + fr.top.map(s => `<tr><td class="t" title="${h(nombre(s))}">${h(nombre(s))}<br><small>${T('{n} llamadas', {n: s.n})}</small></td><td>${s.pct == null ? '' : pc(s.pct, 1)}</td></tr>`).join('') + '</table>' : '') +
    `<p class="dim">${T('pausa de más de 1 h con ≥ 100K de contexto: reescriben la caché')}</p></div>`;
  const op = F.opus;
  const c3 = `<div><p class="px dim" style="font-size:7px">${T('3 · AGENTES EN OPUS FUERA DE REGLA')}</p><p class="grande">${T('{n} llamadas · {pct}', {n: op.n, pct: op.pct == null ? 'US$ ' + op.usd : pc(op.pct, 1)})}</p>` +
    (op.tipos.length ? '<table>' + op.tipos.map(t => `<tr><td class="t">${h(t.tipo)}<br><small>${T('{n} llamadas', {n: t.n})}</small></td><td>${t.pct == null ? '' : pc(t.pct, 1)}</td></tr>`).join('') + '</table>' : `<p class="dim">${T('Ninguno.')}</p>`) +
    `<p class="dim">${T('sin contar security-specialist (la regla permite Opus en auditorías)')}</p></div>`;
  const c = `<h3 class="px">${T('C · FUGAS')}<small>${T('desde el reinicio semanal · % de la cuota semanal · se traslapan, no se suman')}</small></h3><div class="tres">${c1}${c2}${c3}</div>`;
  B.innerHTML = a + b + c + `<p class="dim" style="margin-top:12px">${T('calculado {hace} · se recalcula como mucho cada minuto', {hace: haceIso(C.generado)})}</p>`;
}
function modal(){
  for (const [clave, id] of [['sesiones', '#modal-sesiones'], ['feed', '#modal-feed'], ['costo', '#modal-costo'], ['panel', '#modal-panel']]){
    const M = $(id); M.hidden = ui.modal !== clave;
    if (!M.dataset.listo){ M.dataset.listo = '1'; M.onclick = () => { ui.modal = null; modal(); }; M.querySelector('.win').onclick = e => e.stopPropagation(); const x = M.querySelector('.x'); if (x) x.onclick = () => { ui.modal = null; modal(); }; }
  }
  if (ui.modal === 'sesiones') llenar($('#lista-todo'), grupos());
  if (ui.modal === 'costo') costo();
}
function menu(){
  const cont = $('.mapa-in'); let M = $('#menu');
  if (!M){ M = document.createElement('div'); M.id = 'menu'; M.className = 'menu flot'; cont.appendChild(M); }
  const s = D.sesiones.find(x => x.cli === ui.menu);
  const b = ui.menu && document.querySelector(`#mapa .burbuja[data-menu="${CSS.escape(ui.menu)}"]`);
  if (!s || !b){ M.hidden = true; ui.menu = null; return; }
  const n_act = s.subagentes.filter(a => a.estado === 'trabajando').length;
  // lo que va después de «Abrir sesión»; sin enlace (sesión de la CLI sin app) no hay «Abrir» y el separador pasa al primero
  const cola = (s.fria ? [`<div data-handoff="1">✚ ${T('Sesión nueva')} <small>${T('copia /handoff')}</small></div>`, `<div data-relevo="1">⟲ /checkpoint <small>${T('reescribe {k}K', {k: s.contexto_k})}</small></div>`]
            : s.contexto_k >= %UMBRAL% ? [`<div data-relevo="1">⟲ ${T('Relevo')} <small>${T('copia /checkpoint y abre')}</small></div>`] : []).concat([`<div data-copiar="1">⧉ ${T('Copiar nombre')}</div>`]);
  if (!s.enlace) cola[0] = cola[0].replace('<div ', '<div class="sep" ');
  M.innerHTML = `<div class="cab px">${h(s.titulo)}</div>` +
    (D.chat && s.cli === D.chat.cli ? `<div data-chat="1">» ${T('Hablar')} <small>${T('chat con la central')}</small></div>` : '') +
    `<div data-tab="pedido">✎ ${T('Último pedido')}</div>` +
    `<div data-tab="agentes">⚉ ${T('Agentes')} <small>${n_act === 1 ? T('{n} activo', {n: n_act}) : T('{n} activos', {n: n_act})}</small></div>` +
    `<div data-tab="historial">↺ ${T('Historial')} <small>${s.historial.length}</small></div>` +
    (s.plan ? `<div data-tab="plan">▤ ${T('Plan')} <small>${h(s.plan.producto)}${s.plan.ideas.length ? ' · ✉ ' + s.plan.ideas.length : ''}</small></div>` : '') +
    `<div data-tab="datos">◔ ${T('Contexto y modelo')}</div>` +
    (s.enlace ? `<div class="sep" data-abrir="1">↗ ${T('Abrir sesión')}</div>` : '') + cola.join('');
  M.querySelectorAll('[data-tab]').forEach(el => el.onclick = e => { e.stopPropagation(); ui.menu = null; abrir(s.cli, el.dataset.tab); });
  const mc = M.querySelector('[data-chat]'); if (mc) mc.onclick = e => { e.stopPropagation(); ui.menu = null; pintar(); hablarChat(); };
  const ma = M.querySelector('[data-abrir]'); if (ma) ma.onclick = e => { e.stopPropagation(); ui.menu = null; location.href = s.enlace; pintar(); };
  const mr = M.querySelector('[data-relevo]'); if (mr) mr.onclick = e => { e.stopPropagation(); ui.menu = null; pintar(); relevo(s.cli); };
  const mh = M.querySelector('[data-handoff]'); if (mh) mh.onclick = e => { e.stopPropagation(); ui.menu = null; pintar(); handoff(s.cli); };
  M.querySelector('[data-copiar]').onclick = e => { e.stopPropagation(); ui.menu = null; navigator.clipboard && navigator.clipboard.writeText(s.titulo); pintar(); };
  M.onclick = e => e.stopPropagation();
  M.hidden = false;
  const rb = b.getBoundingClientRect(), rc = cont.getBoundingClientRect();
  let x = rb.right - rc.left + cont.scrollLeft + 4, y = rb.top - rc.top + cont.scrollTop - 6;
  if (x + 240 > cont.clientWidth) x = rb.left - rc.left + cont.scrollLeft - 244;
  M.style.left = Math.max(4, x) + 'px'; M.style.top = Math.max(4, y) + 'px';
}
function tip(u, e){
  const cont = $('.mapa-in'); let T = $('#tip');
  if (!u){ if (T) T.hidden = true; return; }
  if (!T){ T = document.createElement('div'); T.id = 'tip'; T.className = 'tip'; cont.appendChild(T); }
  T.innerHTML = `<div class="n px">${h(u.dataset.agente)}</div><div>${h(u.dataset.tarea) || '<i>' + T('sin descripción') + '</i>'}</div><div class="d">${h(u.dataset.detalle)}</div>`;
  T.hidden = false;
  const rc = cont.getBoundingClientRect();
  let x = e.clientX - rc.left + cont.scrollLeft + 14, y = e.clientY - rc.top + cont.scrollTop + 14;
  if (x + T.offsetWidth + 8 > cont.scrollLeft + cont.clientWidth) x = e.clientX - rc.left + cont.scrollLeft - T.offsetWidth - 10;
  T.style.left = Math.max(4, x) + 'px'; T.style.top = Math.max(4, y) + 'px';
}
function abrir(t, tab){ ui.sel = t; ui.tab = tab || 'pedido'; ui.modal = 'panel'; const s = D.sesiones.find(x => x.cli === t); if (s) ui.piso = s.piso; pintar(); }
function relevo(cli){
  const s = D.sesiones.find(x => x.cli === cli); if (!s) return;
  try { navigator.clipboard && navigator.clipboard.writeText('/checkpoint').catch(() => {}); } catch (e) {}
  document.querySelectorAll('.relevo-btn').forEach(b => b.textContent = T('copiado ✓ pega /checkpoint'));
  if (s.enlace) setTimeout(() => { location.href = s.enlace; }, 150);
}
// sesión fría: no se abre la vieja (reanudarla reescribe todo el contexto); se copia /handoff para una sesión nueva en su carpeta
function handoff(cli){
  const s = D.sesiones.find(x => x.cli === cli); if (!s) return;
  try { navigator.clipboard && navigator.clipboard.writeText('/handoff').catch(() => {}); } catch (e) {}
  const carpeta = (s.cwd || '').split('/').filter(Boolean).pop() || T('su carpeta');
  document.querySelectorAll('.handoff-btn').forEach(b => { b.textContent = T('copiado ✓ nueva en {carpeta}', {carpeta}); b.title = s.cwd || ''; });
}
function cerrar(){ ui.sel = null; ui.menu = null; ui.dialogo = null; ui.modal = null; dialogo(); pintar(); }

// ---- caja de diálogo al pie del plano, como en los RPG de los 90: retrato, placa y texto con máquina de escribir ----
function hablar(cli, agente){
  const s = D.sesiones.find(x => x.cli === cli); if (!s) return;
  if (!agente && D.chat && cli === D.chat.cli){ hablarChat(); return; }          // el héroe de la central conversa
  let seg = [], retrato, nombre;
  if (agente){
    const a = s.subagentes.find(x => x.agente === agente && x.estado === 'trabajando') || s.subagentes.find(x => x.agente === agente);
    if (!a) return;
    retrato = s.crew_svg[agente]; nombre = agente;
    seg = [[T('Soy ')], [agente, 'c'], [T(' y trabajo para ')], [s.titulo, 'c'], [T(' en ')], [a.tarea || T('una tarea sin descripción'), 'm'], ['. ']];
    if (a.estado === 'trabajando') seg.push([T('Ahora mismo: ')], [a.herramienta || T('pensando'), 'g'], [a.duracion ? T('. Llevo {d} en esto.', {d: a.duracion}) : '.']);
    else seg.push([T('Terminé {hace}', {hace: a.ultimo})], [a.duracion ? T(', en {d}.', {d: a.duracion}) : '.']);
    if (a.fuera) seg.push([T(' Corro en ')], [a.modelo, 'g'], [T(' y mi regla dice ')], [a.fuera, 'c'], ['.']);
  } else {
    retrato = s.activa ? 'heroe-feliz' : 'heroe-pensativo'; nombre = s.titulo;
    seg = [[T('Soy la sesión ')], [s.titulo, 'c'], [T('. Estoy ')], [s.estado], [T('. Contexto ')], [`${s.contexto_k}K`, 'g'], [T(' de {u}K, modelo {modelo}. ', {u: %UMBRAL%, modelo: s.modelo})]];
    if (s.fuera) seg.push([T('Soy una tarea programada y corro en ')], [s.modelo, 'g'], [T('; la regla dice ')], [s.fuera, 'c'], ['. ']);
    if (s.fria) seg.push([T('Llevo {t} quieta con ', {t: durS(s)})], [`${s.contexto_k}K`, 'g'], [T(': mi caché ya expiró. Si me reanudas, reescribo todo mi contexto. Mejor una ')], [T('sesión nueva con /handoff'), 'c'], ['; '], [T('/checkpoint aquí'), 'g'], [T(' solo si mi HANDOFF no está al día. ')]);
    if (s.pedido) seg.push([T('Último pedido: ')], [s.pedido, 'm'], ['. ']);
    if (s.plan) seg.push(...decirPlan(s.plan));
  }
  ui.dialogo = {cli, agente, retrato, nombre, seg, paginas: null, pag: 0, pos: 0, timer: null};
  dialogo();
}
// lo que el héroe cuenta de su producto: avance, qué sigue, git y notas en ideas/
function decirPlan(p){
  const seg = [];
  if (p.avance.length) seg.push([T('Voy en ')], [p.avance.map(c => `${c.col} ${c.hechas}/${c.total}`).join(' · '), 'g'], ['. ']);
  else seg.push([p.roadmap === 'sin-roadmap' ? T('Mi producto no tiene ROADMAP en Planning. ') : T('Mi ROADMAP no tiene fila Total en el Marcador. ')]);
  if (p.siguiente) seg.push([T('Sigue: ')], [p.siguiente, 'm'], ['. ']);
  const git = [];
  if (p.sucios) git.push(p.sucios > 1 ? T('{n} archivos sin commitear', {n: p.sucios}) : T('{n} archivo sin commitear', {n: p.sucios}));
  if (p.adelante) git.push(p.adelante > 1 ? T('{n} commits sin subir', {n: p.adelante}) : T('{n} commit sin subir', {n: p.adelante}));
  if (git.length) seg.push([T('Tengo ')], [git.join(T(' y ')), 'g'], ['. ']);
  if (p.ideas.length) seg.push([p.ideas.length > 1 ? T('Hay {n} notas en ', {n: p.ideas.length}) : T('Hay {n} nota en ', {n: p.ideas.length})], ['ideas/', 'c'], [': '], [p.ideas.map(i => i.titulo).join('; '), 'm'], ['. ']);
  if (p.roadmap_viejo) seg.push([T('Mi ROADMAP de Planning es ')], [T('{d} días más viejo', {d: p.desfase_d}), 'g'], [T(' que mi último commit. ')]);
  return seg;
}
// ---- el chat: la misma caja, con una línea de entrada; habla solo con la sesión central (D.chat.sesion) ----
function hablarChat(refresco){
  if (!D.chat) return;
  const s = D.sesiones.find(x => x.cli === D.chat.cli);
  const hilo = D.chat.hilo, ult = hilo[hilo.length - 1];
  const resp = [...hilo].reverse().find(m => m.de !== 'usuario');
  let seg, id;
  if (!s){ seg = [[T('La sesión ')], [D.chat.sesion, 'c'], [T(' no está abierta en la app. Ábrela y vuelve a intentarlo.')]]; id = 'sin'; }
  else if (ult && ult.de === 'usuario'){ seg = [['… ', 'g'], [T('(trabajando en: ')], [ult.texto.length > 70 ? ult.texto.slice(0, 70) + '…' : ult.texto, 'm'], [')']]; id = 'esp|' + ult.texto; }
  else if (resp){ seg = [[resp.texto]]; id = resp.id; }
  else { seg = [[T('Aquí ')], [D.chat.sesion, 'c'], [T('. Dime qué hacemos.')]]; id = 'hola'; }
  if (refresco && (!ui.dialogo || !ui.dialogo.chat || ui.dialogo.id === id)) return;
  const borrador = (ui.dialogo && ui.dialogo.chat && $('#dialogo .entrada input')) ? $('#dialogo .entrada input').value : '';
  ui.dialogo = {cli: D.chat.cli || 'chat', agente: null, retrato: s && s.activa ? 'heroe-feliz' : 'heroe-pensativo', nombre: D.chat.sesion,
                seg, paginas: null, pag: 0, pos: 0, timer: null, chat: true, id, borrador, puede: !!s};
  dialogo();
}
async function chatEnviar(){
  const B = $('#dialogo'); const d = ui.dialogo; if (!B || !d || !d.chat) return;
  const inp = B.querySelector('.entrada input'), est = B.querySelector('.entrada .estado');
  const texto = inp.value.trim(); if (!texto || inp.disabled) return;
  inp.disabled = true; est.className = 'estado px'; est.textContent = T('enviando…');
  try {
    const tok = ($('meta[name="navis-raid-token"]') || {}).content;      // solo la página servida con --serve lo trae
    if (!tok) throw new Error(T('chat apagado: abre la oficina con --serve'));
    const r = await fetch('chat', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Navis-Raid-Token': tok}, body: JSON.stringify({texto})});
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.ok) throw new Error(j.error || ('HTTP ' + r.status));
    inp.value = '';
    D.chat.hilo.push({cuando: T('hace segundos'), id: 'local-' + Date.now(), de: 'usuario', texto});
    hablarChat(true);
    $('#dialogo .entrada .estado').textContent = T('enviado ✓');
  } catch (err) {
    est.className = 'estado px mal'; est.textContent = T('no se pudo: {error}', {error: err.message || err});
  }
  const inp2 = $('#dialogo .entrada input'); if (inp2){ inp2.disabled = false; inp2.focus(); }
}
function paginar(seg, presupuesto){
  const paginas = [[]]; let largo = 0;
  for (const [texto, cls] of seg) for (const palabra of texto.split(/(?<= )/)){
    if (largo + palabra.length > presupuesto && largo > 0){ paginas.push([]); largo = 0; }
    const pag = paginas[paginas.length - 1], ult = pag[pag.length - 1];
    if (ult && ult[1] === cls) ult[0] += palabra; else pag.push([palabra, cls]);
    largo += palabra.length;
  }
  return paginas;
}
function dialogo(){
  const cont = $('.mapa-in'); let B = $('#dialogo'); const d = ui.dialogo;
  if (!d){ if (B){ clearInterval(B._timer); B.remove(); } return; }
  if (!B){
    B = document.createElement('div'); B.id = 'dialogo'; B.className = 'dialogo'; cont.appendChild(B);
    B.innerHTML = `<div class="retrato"></div><div class="texto px"></div><a class="ver px">${T('ver más ↓')}</a><span class="x px">${T('✕ cerrar')}</span><span class="handoff-btn px" hidden>${T('✚ /handoff (nueva)')}</span><span class="relevo-btn px" hidden>${T('⟲ relevo')}</span><span class="mas px" hidden>▼</span>` +
      `<div class="entrada" hidden><span class="pr px">&gt;</span><input class="px" maxlength="4000" placeholder="${T('escribe y Enter')}" aria-label="${T('Mensaje para la sesión central')}"><span class="estado px"></span></div>`;
    B.querySelector('.relevo-btn').onclick = e => { e.stopPropagation(); relevo(ui.dialogo.cli); };
    B.querySelector('.handoff-btn').onclick = e => { e.stopPropagation(); handoff(ui.dialogo.cli); };
    B.onclick = e => { e.stopPropagation(); avanzar(); };
    B.querySelector('.ver').onclick = e => { e.stopPropagation(); const d_ = ui.dialogo; ui.dialogo = null; dialogo(); abrir(d_.cli, d_.chat ? 'chat' : (d_.agente ? 'agentes' : 'pedido')); };
    B.querySelector('.x').onclick = e => { e.stopPropagation(); ui.dialogo = null; dialogo(); };
    const E = B.querySelector('.entrada'), I = E.querySelector('input');
    E.onclick = e => { e.stopPropagation(); I.focus(); };
    I.onkeydown = e => { if (e.key === 'Enter'){ e.preventDefault(); e.stopPropagation(); chatEnviar(); } else if (e.key !== 'Escape') e.stopPropagation(); };
  }
  const clave = d.cli + '|' + (d.agente || '') + '|' + (d.chat ? 'chat|' + d.id : '');
  if (B.dataset.quien !== clave){
    B.dataset.quien = clave;
    B.classList.toggle('chat', !!d.chat);
    const E = B.querySelector('.entrada'), I = E.querySelector('input');
    E.hidden = !d.chat;
    if (d.chat){ I.value = d.borrador || ''; I.disabled = !d.puede; E.querySelector('.estado').textContent = d.puede ? '' : T('sin sesión'); setTimeout(() => I.focus(), 0); }
    const s_ = D.sesiones.find(x => x.cli === d.cli); const rb = B.querySelector('.relevo-btn'); rb.hidden = !(s_ && s_.contexto_k >= %UMBRAL%);
    const fria = !!(s_ && s_.fria && !d.agente && !d.chat), hb = B.querySelector('.handoff-btn');
    hb.hidden = !fria; hb.textContent = T('✚ /handoff (nueva)'); hb.title = T('Copia /handoff para pegarlo en una sesión nueva abierta en la misma carpeta');
    B.classList.toggle('fria', fria);
    rb.classList.toggle('bajo', fria); rb.textContent = fria ? T('⟲ /checkpoint ({k}K)', {k: s_.contexto_k}) : T('⟲ relevo'); rb.title = fria ? T('Reanuda esta sesión: reescribe {k}K de contexto una vez', {k: s_.contexto_k}) : '';
    B.querySelector('.retrato').innerHTML = `<svg viewBox="0 0 32 32" shape-rendering="crispEdges"><use href="#${d.retrato}"/></svg><div class="placa px" title="${h(d.nombre)}">${h(d.nombre)}</div>`;
    const ancho = B.querySelector('.texto').clientWidth || 600;
    d.paginas = paginar(d.seg, Math.max(60, Math.floor(ancho / 10) * 3 - 12));   // ~10 px por carácter, 3 renglones
    d.pag = 0; d.pos = 0;
    clearInterval(B._timer);
    B._timer = setInterval(() => { if (ui.dialogo !== d) return clearInterval(B._timer); if (d.pos < largoPagina(d)){ d.pos += 1; escribir(B, d); } }, 18);
  }
  escribir(B, d);
}
function largoPagina(d){ return d.paginas[d.pag].reduce((n, [t]) => n + t.length, 0); }
function escribir(B, d){
  let resta = d.pos, html = '';
  for (const [t, cls] of d.paginas[d.pag]){ if (resta <= 0) break; const parte = t.slice(0, resta); resta -= parte.length; html += cls ? `<span class="${cls}">${h(parte)}</span>` : h(parte); }
  B.querySelector('.texto').innerHTML = html;
  const fin = d.pos >= largoPagina(d);
  B.querySelector('.mas').hidden = !(fin && d.pag < d.paginas.length - 1);
}
function avanzar(){
  const d = ui.dialogo; if (!d) return;
  if (d.pos < largoPagina(d)) d.pos = largoPagina(d);                      // completar la página de golpe
  else if (d.pag < d.paginas.length - 1){ d.pag += 1; d.pos = 0; }         // siguiente página
  else if (d.chat) return;                                                  // el chat se cierra con ✕ o Esc, no por clic
  else { ui.dialogo = null; dialogo(); return; }                            // última página: cerrar
  escribir($('#dialogo'), d);
}
function tablaPlan(p){
  const fila = (k, v, cls='') => `<tr><td>${k}</td><td class="${cls}">${v}</td></tr>`;
  const fecha = ts => ts ? new Date(ts * 1000).toLocaleDateString(T('es-MX'), {day: 'numeric', month: 'short'}) : '—';
  let t = '<table class="datos">' + fila(T('Producto'), h(p.producto));
  t += fila(T('Avance'), p.avance.length ? p.avance.map(c => `${h(c.col)} <b>${c.hechas}/${c.total}</b>`).join(' · ') + ` <span class="dim">(${p.hechas}/${p.total})</span>`
                                      : (p.roadmap === 'sin-roadmap' ? T('sin ROADMAP en Planning') : T('sin fila Total en el Marcador')), p.avance.length ? '' : 'dim');
  t += fila(T('Qué sigue'), h(p.siguiente) || '—', p.siguiente ? '' : 'dim');
  t += fila(T('Decisiones abiertas'), p.decisiones || '0', p.decisiones ? 'gold' : '');
  t += fila('ROADMAP', `${fecha(p.roadmap_ts)} · ${T('último commit')} ${fecha(p.ultimo_commit_ts)}` + (p.roadmap_viejo ? ` · <b>${T('{d} días más viejo que el código', {d: p.desfase_d})}</b>` : ''), p.roadmap_viejo ? 'red' : '');
  t += fila(T('Notas en ideas/'), p.ideas.length ? '<ul class="ideas">' + p.ideas.map(i => `<li>✉ ${h(i.titulo)} <span class="dim">${h(i.archivo)}</span></li>`).join('') + '</ul><span class="dim">' + T('Al atenderla, la sesión del producto la mueve a ideas/archivo/.') + '</span>' : T('ninguna'), p.ideas.length ? '' : 'dim');
  t += '</table>';
  if (p.git.length){
    t += `<table class="datos git"><tr><td>${T('Repo')}</td><td>${T('Rama')}</td><td>${T('Sin commitear')}</td><td>${T('Sin subir')}</td><td>${T('Último commit')}</td></tr>`;
    for (const g of p.git) t += `<tr><td>${h(g.nombre)}${g.worktree ? ' <span class="dim">worktree</span>' : ''}</td><td>${h(g.rama)}</td>` +
      `<td class="${g.sucios ? 'gold' : 'dim'}">${g.sucios}</td>` +
      `<td class="${g.adelante ? 'gold' : (g.adelante === null ? 'red' : 'dim')}">${!g.remoto ? T('sin remoto') : g.adelante === null ? T('sin upstream') : g.adelante}</td>` +
      `<td>${fecha(g.ultimo_ts)} · ${h(g.ultimo)}</td></tr>`;
    t += '</table>';
  }
  return t;
}
function panel(){
  const P = $('#panel'); const s = D.sesiones.find(x => x.cli === ui.sel);
  if (!s){ if (ui.modal === 'panel') ui.modal = null; return; }
  const tabs = [['pedido',T('Pedido')],['agentes',T('Agentes')],['historial',T('Historial')]].concat(s.plan ? [['plan',T('Plan')]] : [], [['datos',T('Datos')]]);
  if (ui.tab === 'plan' && !s.plan) ui.tab = 'datos';
  if (D.chat && s.cli === D.chat.cli) tabs.unshift(['chat', T('Chat')]);
  let cuerpo = '';
  if (ui.tab === 'chat') cuerpo = D.chat.hilo.length ? '<ol class="chat">' + D.chat.hilo.map(m => `<li class="${m.de==='usuario'?'yo':'el'}"><span class="cuando">${h(m.cuando)}</span><span class="de px">${h(m.de==='usuario'?D.usuario:m.de)}</span><div class="t">${h(m.texto)}</div></li>`).join('') + '</ol>' : '<p class="t dim">' + T('Sin mensajes todavía. Habla desde la burbuja de la central o con clic en su héroe.') + '</p>';
  else if (ui.tab === 'pedido') cuerpo = `<p class="t">${h(s.pedido) || '<i>' + T('sin pedido reciente') + '</i>'}</p>` + (s.respuesta ? `<p class="t dim"><b>${T('Último mensaje:')}</b> ${h(s.respuesta)}</p>` : '');
  else if (ui.tab === 'agentes') cuerpo = s.subagentes.length ? '<ul class="crew">' + s.subagentes.map(a => `<li class="${a.estado==='trabajando'?'ok':'fin'}"><svg viewBox="0 0 32 32" shape-rendering="crispEdges"><use href="#${s.crew_svg[a.agente]}"/></svg><span class="n2 px">${h(s.corto[a.agente])}</span><span class="t2">${h(a.tarea)}</span><span class="s2"><span class="${a.fuera ? 'fuera' : ''}" title="${a.fuera ? T('fuera de regla: {modelo}', {modelo: h(a.fuera)}) : ''}">${h(a.modelo)}${a.fuera ? ' ≠ ' + h(a.fuera) : ''}</span> · ${a.estado==='trabajando' ? h(a.herramienta || T('trabajando')) : h(a.duracion) + ' · ' + h(a.ultimo)}</span></li>`).join('') + '</ul>' : '<p class="t dim">' + T('Sin agentes en las últimas 24 h.') + '</p>';
  else if (ui.tab === 'plan') cuerpo = tablaPlan(s.plan);
  else if (ui.tab === 'historial') cuerpo = s.historial.length ? '<ol class="hist">' + s.historial.map(e => `<li class="${e.clase}"><span class="cuando">${h(e.cuando)}</span>${h(e.texto)}</li>`).join('') + '</ol>' : '<p class="t dim">' + T('Sin historial.') + '</p>';
  else cuerpo = `<table class="datos"><tr><td>${T('Contexto')}</td><td class="px ${clase_k(s.contexto_k)}">${T('{k}K de {u}K', {k: s.contexto_k, u: %UMBRAL%})}</td></tr><tr><td>${T('Modelo')}</td><td class="${s.fuera ? 'fuera' : ''}">${h(s.modelo)}${s.fuera ? ' · ' + T('tarea programada, la regla dice {r}', {r: h(s.fuera)}) : ''}</td></tr><tr><td>${T('Estado')}</td><td>${h(s.estado)}</td></tr><tr><td>${T('Última llamada')}</td><td>${h(s.ultima)}</td></tr><tr><td>${T('Carpeta')}</td><td>${h(s.cwd)}</td></tr><tr><td>${T('Transcripción')}</td><td>${h(s.cli)}…</td></tr></table>`;
  P.innerHTML = `<div class="in"><div class="cab"><span class="n px ${s.activa?'on':''}">${h(s.titulo)}</span><span class="meta">${s.contexto_k}K · ${h(s.modelo)} · ${h(s.ultima)}</span><button class="x" aria-label="${T('Cerrar')}">✕</button></div>` +
    `<div class="tabs">${tabs.map(([k,v]) => `<span class="${ui.tab===k?'a':''}" data-tab="${k}">${v}</span>`).join('')}</div><div class="cuerpo">${cuerpo}</div></div>`;
  P.querySelector('.x').onclick = cerrar;
  P.querySelectorAll('.tabs span').forEach(el => el.onclick = () => { ui.tab = el.dataset.tab; panel(); });
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') cerrar(); else if (e.key === 'Enter' && ui.dialogo) avanzar(); });
document.addEventListener('click', () => { if (ui.menu){ ui.menu = null; pintar(); } if (ui.dialogo){ ui.dialogo = null; dialogo(); } });
async function refrescar(){
  if (CERRADA) return;
  try {
    const r = await fetch('estado.json?' + Date.now(), {cache:'no-store'});
    if (!r.ok) throw new Error(r.status);
    D = await r.json(); pintar();
  } catch (err) {
    if (!CERRADA && !ui.sel && !ui.menu && !ui.modal && !ui.dialogo) location.reload();      // sin servidor (file://): recargar solo si no hay nada abierto
  }
}
// ---- Horario de salida: detiene el servidor de --serve (POST salida, con el mismo token que el chat); en la página de disco no hay botón ----
let CERRADA = false;
function avisoSalida(txt, mal){
  let A = $('#aviso-salida');
  if (!A){ A = document.createElement('div'); A.id = 'aviso-salida'; A.setAttribute('role', 'status'); document.body.appendChild(A); }
  A.className = 'px' + (mal ? ' mal' : ''); A.textContent = txt;
}
async function salir(){
  const tok = ($('meta[name="navis-raid-token"]') || {}).content;
  if (!tok || !confirm(T('¿Cerrar la oficina? Para volver: /navis-raid:start'))) return;
  try {
    const r = await fetch('salida', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Navis-Raid-Token': tok}, body: '{}'});
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.ok) throw new Error(j.error || ('HTTP ' + r.status));
    CERRADA = true; if (PULSO) clearInterval(PULSO);
    avisoSalida(T('La oficina cerró. Para volver: /navis-raid:start o reinicia sesión'));
  } catch (err) {
    avisoSalida(T('no se pudo cerrar: {error}', {error: err.message || err}), true);
  }
}
const BTN_SALIR = $('#salir');
if (BTN_SALIR && (($('meta[name="navis-raid-token"]') || {}).content)){ BTN_SALIR.hidden = false; BTN_SALIR.onclick = e => { e.stopPropagation(); salir(); }; }
pintar();
const PULSO = CADA ? setInterval(refrescar, CADA * 1000) : null;
"""


def css_pixel():
    """CSS_PIXEL con la ruta de las fuentes que corresponde a dónde vive la página (ver `_url_fuentes`)."""
    url = _url_fuentes()
    return CSS_PIXEL if url == 'fuentes/' else CSS_PIXEL.replace("url('fuentes/", "url('" + url)


def render_pixel(sesiones, eventos, refresco):
    """La oficina isométrica, interactiva: lista con botón de acciones, menú, panel de detalle y refresco por JS."""
    datos = datos_vivos(sesiones, eventos)
    js = JS.replace('%CADA%', str(int(refresco or 0))).replace('%UMBRAL%', str(UMBRAL_K))
    datos_json = json.dumps(datos, ensure_ascii=False, default=serializable).replace('<', '\\u003c')   # ningún '<' crudo dentro del <script> de datos
    return (f'<!doctype html><html lang="{textos.idioma()}"><head><meta charset="utf-8"><title>Navis Raid</title>'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">{TOKEN_META}<style>{css_pixel()}</style></head><body>'
            f'<header><h1 class="px">NAVIS RAID</h1><div class="hud px" id="hud"></div><button class="medidor px gris" id="medidor" type="button">{t("cuota: sin lectura")}</button><button class="medidor salida px" id="salir" type="button" hidden>{t("Horario de salida")}</button></header><main>'
            f'<svg width="0" height="0" style="position:absolute"><defs id="simbolos"></defs></svg>'
            f'<section class="piso"><div class="win"><div class="in mapa-in"><div id="mapa"></div>'
            f'<div class="esquina" id="esquina"><div class="cab px"><span id="cola-resumen"></span><span class="plegar" id="plegar" title="{t("Plegar o desplegar la cola")}">▾</span></div><ul class="lista" id="lista"></ul><div class="vermas px" id="vermas" hidden></div></div></div></div>'
            f'<div class="modal" id="modal-sesiones" hidden><div class="win"><div class="in"><div class="cab"><span class="px">{t("TODAS LAS SESIONES")}</span><button class="x" aria-label="{t("Cerrar")}">✕</button></div><ul class="lista" id="lista-todo"></ul></div></div></div>'
            f'<div class="modal" id="modal-feed" hidden><div class="win feed"><div class="in"><div class="cab"><span class="px">{t("LO QUE PASA EN EL RAID")}</span><button class="x" aria-label="{t("Cerrar")}">✕</button></div><ol id="feed"></ol></div></div></div>'
            f'<div class="modal" id="modal-costo" hidden><div class="win costo"><div class="in"><div class="cab"><span class="px">{t("COSTO DE LA CUOTA")}</span><button class="x" aria-label="{t("Cerrar")}">✕</button></div><div id="costo-cuerpo"></div></div></div></div>'
            f'<div class="modal" id="modal-panel" hidden><div class="win panel" id="panel"></div></div></section></main>'
            f'<footer class="px">{html.escape(PIE)}{(t(", salvo lo que hables con {sesion}", sesion=html.escape(CHAT_SESION))) if CHAT_SESION else ""}</footer>'
            f'<script id="datos" type="application/json">{datos_json}</script><script>{js}</script></body></html>')


def serializable(o):
    if isinstance(o, dt.datetime):
        return o.isoformat()
    raise TypeError


def _escribir(nombre, contenido):
    """Escritura atómica: a un archivo temporal y `os.replace`. Con --serve hay varias peticiones a la vez
    (y puede haber dos servidores sobre la misma carpeta); quien esté leyendo el archivo viejo lo sigue
    leyendo entero, nunca una mezcla. Sin esto el navegador recibía trozos del JS como texto suelto."""
    os.makedirs(DATOS, exist_ok=True)         # la carpeta de datos se crea al escribir
    ruta = os.path.join(DATOS, nombre)
    tmp = f'{ruta}.{os.getpid()}.{threading.get_ident()}.tmp'   # por hilo: dos peticiones a la vez no comparten temporal
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(contenido)
    os.replace(tmp, ruta)


def generar(refresco=0, solo_estado=False):
    """Regenera estado.json y, salvo `solo_estado`, también index.html y tabla.html."""
    try:
        bitacora.actualizar()                 # A1: una línea por llamada al modelo (incremental; extra que nunca tumba)
    except Exception as e:
        print(t('bitácora:'), e, file=sys.stderr)
    sesiones, eventos = recoger()
    if not solo_estado:
        _escribir('index.html', render_pixel(sesiones, eventos, refresco))
        _escribir('tabla.html', render_html(sesiones, eventos, refresco))
    _escribir('estado.json', json.dumps(datos_vivos(sesiones, eventos), ensure_ascii=False, default=serializable))
    return sesiones, eventos


# ---------- doctor ----------

DOCTOR_MUESTRA = 20       # transcripciones más recientes que --doctor inspecciona (por la cabeza y la cola)
CAMPO_TITULOS = t('títulos (custom-title / ai-title)')
CAMPOS_DOCTOR = (         # (nombre, qué deja de verse si falta en todas)
    ('type', t('no se distingue quién habla: no hay sesiones ni estado')),
    ('timestamp', t('sin hora no hay actividad, pausas ni eventos')),
    ('cwd', t('sin carpeta de trabajo la sesión no se reconoce ni se agrupa por producto')),
    ('entrypoint', t('no se distinguen las sesiones de la app de las de la terminal')),
    ('version', t('no se puede avisar de cambios de versión')),
    ('message.usage', t('no hay contexto ni costo')),
    ('message.content', t('no hay pedidos, respuestas, herramientas ni encargos a agentes')),
    (CAMPO_TITULOS, t('las sesiones salen con el nombre de su carpeta')),
)


def _campos_de(lineas):
    """Qué campos esperados aparecen en estas líneas (ya son dict)."""
    vistos = set()
    for d in lineas:
        m = d.get('message')
        for nombre, ok in (('type', isinstance(d.get('type'), str)), ('timestamp', ts(d.get('timestamp')) is not None),
                           ('cwd', bool(_txt(d.get('cwd')))), ('entrypoint', bool(_txt(d.get('entrypoint')))),
                           ('version', bool(_txt(d.get('version')))),
                           ('message.usage', isinstance(m, dict) and isinstance(m.get('usage'), dict) and bool(m['usage'])),
                           ('message.content', isinstance(m, dict) and isinstance(m.get('content'), (str, list))),
                           (CAMPO_TITULOS, d.get('type') in ('custom-title', 'ai-title') and bool(_txt(d.get('customTitle')) or _txt(d.get('aiTitle'))))):
            if ok:
                vistos.add(nombre)
    return vistos


def _se_puede_crear(carpeta):
    """¿Se puede escribir en `carpeta`? Si no existe todavía, en la primera carpeta existente de las que la contienen
    (es donde `os.makedirs` la crearía)."""
    while not os.path.isdir(carpeta):
        padre = os.path.dirname(carpeta)
        if padre == carpeta:
            return False
        carpeta = padre
    return os.access(carpeta, os.W_OK | os.X_OK)


def doctor():
    """--doctor: qué encontró la oficina en este equipo y qué no. Solo lectura (no escribe index.html, estado.json ni la
    bitácora) y sin modelo. Una línea por comprobación con ✓ / ⚠ / ✗. Devuelve el código de salida: 1 si no hay projects/
    o ninguna transcripción legible, 0 si no."""
    marcas = {'ok': '✓', 'aviso': '⚠', 'mal': '✗'}
    cuenta = {'ok': 0, 'aviso': 0, 'mal': 0}

    def linea(nivel, texto):
        cuenta[nivel] += 1
        print(f'{marcas[nivel]} {texto}')

    # 0. configuración de la oficina (config.json)
    if config.ARCHIVO:
        linea('ok', t('config.json: {ruta}.', ruta=config.ARCHIVO))
    else:
        linea('ok', t('sin config.json: valores por defecto (copia config.ejemplo.json a config.json para personalizar).'))
    for a in config.AVISOS:
        linea('aviso', t('config: {aviso}', aviso=a))

    # 1. carpeta de configuración
    de_env = bool(os.environ.get('CLAUDE_CONFIG_DIR'))
    origen = t('viene de CLAUDE_CONFIG_DIR') if de_env else t('la de siempre, ~/.claude')
    if os.path.isdir(CONFIG):
        linea('ok', t('Configuración de Claude Code: {ruta} ({origen}).', ruta=CONFIG, origen=origen))
    else:
        linea('mal', t('Configuración de Claude Code: {ruta} ({origen}) no existe: no hay nada que leer. Revisa CLAUDE_CONFIG_DIR.', ruta=CONFIG, origen=origen))

    # 2. projects/
    principales = glob.glob(PROYECTOS + '/*/*.jsonl')
    mtimes = {}
    for r in principales:
        try:
            mtimes[r] = os.path.getmtime(r)
        except OSError:
            pass
    corte = time.time() - HORAS_VISIBLES * 3600
    recientes = sorted((r for r, m in mtimes.items() if m >= corte), key=lambda r: -mtimes[r])
    if not os.path.isdir(PROYECTOS):
        linea('mal', t('projects/: {ruta} no existe; la oficina saldría vacía.', ruta=PROYECTOS))
    elif not mtimes:
        linea('mal', t('projects/: no hay ninguna transcripción (*.jsonl); la oficina saldría vacía.'))
    elif not recientes:
        linea('aviso', t('projects/: {n} transcripciones, ninguna con actividad en las últimas {horas} h: la oficina saldría vacía hasta que haya una sesión.', n=len(mtimes), horas=HORAS_VISIBLES))
    else:
        linea('ok', t('projects/: {n} transcripciones, {recientes} con actividad en las últimas {horas} h (esas son las sesiones que se dibujan).', n=len(mtimes), recientes=len(recientes), horas=HORAS_VISIBLES))

    # 3. formato de las transcripciones más recientes
    muestra = sorted(mtimes, key=lambda r: -mtimes[r])[:DOCTOR_MUESTRA]
    leidas = saltadas = legibles = 0
    por_campo = {nombre: 0 for nombre, _ in CAMPOS_DOCTOR}
    version_vista = ''
    for r in muestra:
        c = {}
        try:
            cabeza, cola = _extremos(r, os.path.getsize(r), c)
        except OSError:
            continue
        leidas += c.get('leidas', 0)
        saltadas += c.get('saltadas', 0)
        if not cabeza and not cola:
            continue
        legibles += 1
        lineas_ = cabeza if cola is cabeza else cabeza + cola
        for nombre in _campos_de(lineas_):
            por_campo[nombre] += 1
        if not version_vista:
            version_vista = next((v for v in (_txt(d.get('version')).strip() for d in reversed(cola)) if v), '')
    if muestra:
        total = leidas + saltadas
        pct = 100 * saltadas // total if total else 0
        texto = t('Formato: de las {n} transcripciones más recientes se leen {legibles}; {leidas} líneas leídas y {saltadas} saltadas ({pct} %; el corte de la cabeza y la cola parte líneas).',
                  n=len(muestra), legibles=legibles, leidas=leidas, saltadas=saltadas, pct=pct)
        linea('ok' if legibles and pct <= 20 else ('aviso' if legibles else 'mal'), texto)
        for nombre, consecuencia in CAMPOS_DOCTOR:
            n = por_campo[nombre]
            if legibles and n == 0:
                linea('mal', t('  sin `{campo}` en ninguna: {consecuencia}.', campo=nombre, consecuencia=consecuencia))
            elif n < legibles:
                linea('ok' if 2 * n >= legibles else 'aviso', t('  `{campo}`: en {n} de {legibles} transcripciones (en las otras no está: {consecuencia}).', campo=nombre, n=n, legibles=legibles, consecuencia=consecuencia))
            elif legibles:
                linea('ok', t('  `{campo}`: en las {legibles}.', campo=nombre, legibles=legibles))

    # 4. versión
    aviso = aviso_version(version_vista)
    if not version_vista:
        linea('aviso', t('Versión de Claude Code: no se vio en las transcripciones (probado con {probado}).', probado=PROBADO_CON))
    elif aviso:
        linea('aviso', t('Versión de Claude Code {vista}, probado con {probado}: cambió mayor.menor, el formato interno puede haber cambiado; si algo se ve raro, avisa.', vista=version_vista, probado=PROBADO_CON))
    else:
        linea('ok', t('Versión de Claude Code {vista} (probado con {probado}; un parche distinto no importa).', vista=version_vista, probado=PROBADO_CON))

    # 5. app de escritorio (solo macOS)
    if SOLO_TERMINAL or sys.platform != 'darwin':
        linea('ok', t('App de escritorio: no se usa ({motivo}); la lista sale de las transcripciones.', motivo=t('modo solo terminal') if SOLO_TERMINAL else t('solo existe en macOS')))
    elif not os.path.isdir(APP or ''):
        linea('ok', t('App de escritorio: no hay carpeta de la app; la lista sale de las transcripciones (sin fijadas, enlaces ni tareas programadas).'))
    else:
        buenos = rotos = 0
        for f in glob.glob(APP + '/*/*/local_*.json'):
            try:
                with open(f, encoding='utf-8') as fh:
                    ok = isinstance(json.load(fh), dict)
            except (ValueError, OSError):
                ok = False
            buenos, rotos = buenos + ok, rotos + (not ok)
        linea('aviso' if rotos else 'ok', t('App de escritorio: {buenos} archivos local_*.json legibles, {rotos} rotos', buenos=buenos, rotos=rotos)
              + (t(' (se saltan: esas sesiones salen sin título de la app).') if rotos else '.'))
        tareas = tareas_programadas() if usa_app() else {}
        archivos_t = glob.glob(APP + '/*/*/scheduled-tasks.json')
        linea('ok' if archivos_t else 'aviso', t('  scheduled-tasks.json: {n} archivos, {tareas} tareas activas', n=len(archivos_t), tareas=len(tareas))
              + ('.' if archivos_t else t(' (sin él no se reconocen las tareas programadas).')))
        g = grupos_app()
        if g:
            linea('ok', t('  grupos del sidebar en claude_desktop_config.json: {grupos} grupos, {n} sesiones asignadas (cada grupo es un piso).', grupos=len(g[0]), n=len(g[1])))
        else:
            linea('aviso', t('  sin grupos del sidebar en claude_desktop_config.json (o con otro formato): los pisos salen de pisos.json.'))

    # 6. agents/
    defs = glob.glob(os.path.join(AGENTES_GLOBAL, '*.md'))
    if defs:
        linea('ok', t('agents/: {n} definiciones en {ruta} (su `model:` es el modelo esperado de cada agente).', n=len(defs), ruta=AGENTES_GLOBAL))
    else:
        linea('aviso', t('agents/: sin definiciones en {ruta}: se espera {modelo} de todos los agentes.', ruta=AGENTES_GLOBAL, modelo=MODELO_GENERICO))

    # 7. carpeta de datos y bitácora
    if not _se_puede_crear(DATOS):
        linea('mal', t('Datos: no se puede escribir en {ruta}: no se guardará la página, el estado ni la bitácora.', ruta=DATOS))
    elif config.DATOS_DE_VARIABLE:
        linea('ok', t('Datos: {ruta} (de NAVIS_RAID_DATA).', ruta=DATOS))
    else:
        linea('ok', t('Datos: {ruta} (junto al script; NAVIS_RAID_DATA no está definida).', ruta=DATOS))
    if os.path.isdir(bitacora.DIR):
        if os.access(bitacora.DIR, os.W_OK):
            linea('ok', t('Bitácora: {ruta} existe y se puede escribir.', ruta=bitacora.DIR))
        else:
            linea('mal', t('Bitácora: {ruta} existe pero no se puede escribir: no se llevará el costo.', ruta=bitacora.DIR))
    elif _se_puede_crear(DATOS):
        linea('ok', t('Bitácora: {ruta} no existe todavía; se creará (se puede escribir en {aqui}).', ruta=bitacora.DIR, aqui=DATOS))
    else:
        linea('mal', t('Bitácora: no existe {ruta} y no se puede escribir en {aqui}: no se llevará el costo.', ruta=bitacora.DIR, aqui=DATOS))

    # 8. servicio de usuario (launchd o systemd), si lo hay
    import servicio
    sv = servicio.leer()
    if sv['instalado']:
        if not sv['script']:
            linea('aviso', t('Servicio: no se pudo leer a qué oficina.py apunta {archivo}.', archivo=sv['archivo']))
        elif not sv['script_existe']:
            linea('mal', t('Servicio: {archivo} apunta a {script}, que ya no existe (¿se actualizó el plugin?). Arréglalo con /navis-raid:start (o `python3 oficina.py --instalar-servicio`).', archivo=sv['archivo'], script=sv['script']))
        elif sv['python_existe'] is not False:
            linea('ok', t('Servicio: {archivo} → {script} (puerto {puerto}: {estado}).', archivo=sv['archivo'], script=sv['script'], puerto=sv['puerto'] or '?',
                          estado=t('algo escucha') if sv['escucha'] else t('nada escucha')))
        if sv['python_existe'] is False:
            linea('mal', t('Servicio: {archivo} usa el intérprete {python}, que ya no existe. Arréglalo con /navis-raid:start (o `python3 oficina.py --instalar-servicio`).', archivo=sv['archivo'], python=sv['python']))
        aviso = servicio.aviso_pendiente(sv)
        if aviso:
            linea('aviso', t('Servicio: nada escucha y servicio.log termina con este aviso: {aviso}', aviso=aviso))

    # 9. Windows: servicio en la carpeta Inicio (E8f-B1) o a mano, y sin chat (E8f-A)
    if sys.platform == 'win32':
        if sv['instalado']:
            linea('aviso', t('Windows: servicio en la carpeta Inicio; no se relanza si se cae (vuelve en el siguiente inicio de sesión o con /navis-raid:start). Sin chat.'))
        else:
            linea('aviso', t('Windows: servicio sin instalar (instálalo con /navis-raid:start, o arranca a mano con `python oficina.py --serve`) y sin chat.'))
        if CHAT_CONFIGURADO:
            linea('aviso', t('Chat: no disponible en Windows'))

    sin_lectura = not os.path.isdir(PROYECTOS) or legibles == 0
    print('\n' + t('{ok} bien, {aviso} avisos, {mal} fallas', **cuenta) + (t(' · no hay nada legible: la oficina saldría vacía.') if sin_lectura else '.'))
    return 1 if sin_lectura else 0



def resumen_terminal(sesiones):
    for s in sesiones:
        print(f"{'●' if s['activa'] else '○'} {s['titulo'][:28]:28} {s['contexto_k']:4d}K  {s['estado'][:60]}", flush=True)
        for a in s['subagentes']:
            if a['estado'] == 'trabajando':
                print(f"    ↳ {a['agente']} · {a['tarea']} · {a['herramienta'][:50]}")


TOKEN_META = '<meta name="navis-raid-token" content="">'    # la página de disco lo lleva vacío; el servidor lo rellena
PAGINAS = {'/': 'index.html', '/index.html': 'index.html', '/tabla.html': 'tabla.html'}   # + /estado.json y /fuentes/<x>.woff2
CHAT_MAX_BYTES = 20000
_GENERAR = threading.Lock()   # --serve: una regeneración a la vez (dos pestañas no se pisan los archivos)


def servidor(puerto, token):
    """El servidor de --serve, sin arrancar: `servidor(...).serve_forever()`. Con puerto 0 elige uno libre
    (`.server_address[1]`). Solo entrega la página y su estado (lista blanca, sin listado de carpetas), solo a quien
    llama por localhost (encabezado Host: contra DNS rebinding) y el POST /chat y el POST /salida (detiene el servidor)
    exigen el token, Content-Type JSON y, si viene, un Origin propio. No responde OPTIONS ni manda Access-Control-*: un sitio ajeno no pasa el preflight."""
    import http.server
    import secrets
    global SERVIDO
    SERVIDO = True       # la página se entrega desde aquí: /fuentes/ sale del código y la ruta relativa de las fuentes sirve

    class H(http.server.BaseHTTPRequestHandler):
        timeout = 10                                 # una conexión lenta no retiene un hilo para siempre

        def _puerto(self):
            return self.server.server_address[1]

        def _host_ok(self):
            p = self._puerto()
            return self.headers.get('Host') in (f'127.0.0.1:{p}', f'localhost:{p}', f'[::1]:{p}')

        def _origen_ok(self, origen):
            p = self._puerto()
            return origen in (f'http://127.0.0.1:{p}', f'http://localhost:{p}', f'http://[::1]:{p}')

        def _responder(self, codigo, datos, tipo):
            self.send_response(codigo)
            self.send_header('Content-Type', tipo)
            self.send_header('Content-Length', str(len(datos)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')                       # nadie la mete en un iframe (clickjacking del chat)
            self.send_header('Content-Security-Policy', "frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(datos)

        def _drenar(self):
            """Consume el cuerpo de una petición que se rechaza (hasta CHAT_MAX_BYTES, con el timeout de la conexión). Sin
            esto, el servidor contestaba 403 y cerraba con el cuerpo sin leer: el cliente que aún escribía recibía
            BrokenPipe (y en TCP un RST que le borra la respuesta). No cambia ninguna decisión: se lee DESPUÉS de rechazar."""
            try:
                n = int(self.headers.get('Content-Length') or 0)
                if 0 < n <= CHAT_MAX_BYTES:
                    self.rfile.read(n)
            except (ValueError, OSError):
                pass

        def _error(self, codigo):
            self._drenar()
            self._responder(codigo, {403: b'403', 404: b'404', 500: b'500'}.get(codigo, b'error'), 'text/plain; charset=utf-8')

        def do_GET(self):
            if not self._host_ok():
                return self._error(403)
            ruta = self.path.split('?', 1)[0]
            try:
                if ruta in ('/', '/index.html'):
                    with _GENERAR:
                        generar(refresco=5)                  # la página se regenera al pedirla
                elif ruta == '/estado.json':
                    with _GENERAR:
                        generar(refresco=5, solo_estado=True)    # el JS lo pide cada 5 s
                if ruta in PAGINAS:
                    with open(os.path.join(DATOS, PAGINAS[ruta]), 'rb') as fh:
                        datos = fh.read()
                    if ruta != '/tabla.html':                # solo la página servida lleva el token
                        datos = datos.replace(TOKEN_META.encode(), TOKEN_META.replace('content=""', f'content="{token}"').encode(), 1)
                    return self._responder(200, datos, 'text/html; charset=utf-8')
                if ruta == '/estado.json':
                    with open(os.path.join(DATOS, 'estado.json'), 'rb') as fh:
                        return self._responder(200, fh.read(), 'application/json; charset=utf-8')
                m = re.fullmatch(r'/fuentes/([A-Za-z0-9._-]+\.woff2)', ruta)
                if m and '..' not in m.group(1):
                    base = os.path.realpath(os.path.join(AQUI, 'fuentes'))
                    archivo = os.path.realpath(os.path.join(base, m.group(1)))
                    if os.path.dirname(archivo) == base and os.path.isfile(archivo):
                        with open(archivo, 'rb') as fh:
                            return self._responder(200, fh.read(), 'font/woff2')
            except OSError:
                return self._error(404)
            except Exception as e:
                print('servidor:', type(e).__name__, e, file=sys.stderr)
                return self._error(500)
            self._error(404)

        def _autorizado(self):
            """Lo que exigen las dos rutas POST (/chat y /salida): token propio (compare_digest), Content-Type JSON y, si viene,
            un Origin propio. El Host ya se comprobó antes."""
            enviado = (self.headers.get('X-Navis-Raid-Token') or '').encode('utf-8', 'replace')
            tipo = (self.headers.get('Content-Type') or '').split(';')[0].strip().lower()
            origen = self.headers.get('Origin')
            return (secrets.compare_digest(enviado, token.encode()) and tipo == 'application/json'
                    and (origen is None or self._origen_ok(origen)))

        def do_POST(self):
            """POST /chat {"texto": ...}: manda el texto a la sesión central y lo anota en el hilo.
            POST /salida: responde 200 y detiene el servidor («Horario de salida»); existe aunque no haya chat."""
            if not self._host_ok():
                return self._error(403)
            if self.path == '/salida':
                if not self._autorizado():
                    return self._error(403)
                self._drenar()
                try:
                    self._responder(200, b'{"ok": true}', 'application/json; charset=utf-8')
                finally:
                    # shutdown() espera a que serve_forever() vuelva: llamado desde este hilo (un hilo del servidor) bloquearía el bucle
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if self.path != '/chat' or not CHAT_SESION:            # sin chat_sesion el chat no existe
                return self._error(404)
            if not self._autorizado():
                return self._error(403)
            try:
                n = int(self.headers.get('Content-Length') or 0)
                texto = '' if n < 0 or n > CHAT_MAX_BYTES else (json.loads(self.rfile.read(n) or b'{}').get('texto') or '').strip()
            except (ValueError, OSError, AttributeError):
                texto = ''
            if not texto or len(texto) > 4000:
                cuerpo, codigo = {'ok': False, 'error': t('mensaje vacío o de más de 4000 caracteres')}, 400
            else:
                enviados, error = chat_enviar(texto)
                if enviados:
                    chat_anotar('usuario', texto)
                cuerpo, codigo = {'ok': not error, 'enviados': enviados, 'error': error}, 200
            self._responder(codigo, json.dumps(cuerpo, ensure_ascii=False).encode(), 'application/json; charset=utf-8')

        def log_message(self, *a):
            pass

        def handle(self):
            try:
                super().handle()
            except (ConnectionResetError, BrokenPipeError):
                pass                      # el navegador cortó una carga (recarga): no es un error

    return http.server.ThreadingHTTPServer(('127.0.0.1', puerto), H)


def main(argv):
    global ESCALA, SOLO_TERMINAL
    if os.environ.get('NAVIS_RAID_SERVICIO') == '1' and (sys.stdout is None or sys.stderr is None):
        import servicio                  # pythonw.exe (el servicio de Windows) no trae stdout ni stderr: su salida va a servicio.log
        servicio.reabrir_flujos()
    if sys.platform == 'win32':          # la consola o el log de Windows usan cp1252 por defecto: ✓ ⚠ ● y los acentos de los títulos no caben
        for flujo in (sys.stdout, sys.stderr):
            try:
                flujo.reconfigure(encoding='utf-8', errors='replace')
            except (AttributeError, ValueError, OSError):
                pass
    if '--solo-terminal' in argv:
        SOLO_TERMINAL = True
        bitacora.SOLO_TERMINAL, bitacora.APP = True, None     # la bitácora tampoco mira la app
    if '--compacto' in argv:
        ESCALA = 1.5
    if '--doctor' in argv or 'doctor' in argv:
        return doctor()
    if '--estado-servicio' in argv:
        import servicio
        return servicio.estado()
    if '--quitar-servicio' in argv:
        import servicio
        return servicio.quitar()
    if '--instalar-servicio' in argv:
        import servicio
        i = argv.index('--instalar-servicio') + 1
        crudo = argv[i] if i < len(argv) and not argv[i].startswith('-') else str(servicio.PUERTO)
        try:
            puerto = int(crudo)
        except ValueError:
            puerto = crudo
        return servicio.instalar(puerto, os.path.abspath(__file__), verificar=True)
    if '--serve' in argv:
        puerto = int(argv[argv.index('--serve') + 1]) if len(argv) > argv.index('--serve') + 1 else 8765
        import errno
        import secrets
        try:
            srv = servidor(puerto, secrets.token_urlsafe(24))
        except OSError as e:
            if e.errno != errno.EADDRINUSE:
                raise
            import servicio
            print(servicio.aviso_puerto_ocupado(puerto), file=sys.stderr)
            # Como servicio, 0: el KeepAlive/SuccessfulExit de launchd (y Restart=on-failure de systemd) no relanza tras un 0.
            return 0 if os.environ.get(servicio.SERVICIO) == '1' else 3
        print(t('http://localhost:{puerto}/  (Ctrl+C para parar)', puerto=srv.server_address[1]))
        import servicio
        con_pid = os.environ.get(servicio.SERVICIO) == '1' and (sys.platform == 'win32' or servicio.sistema() == 'Windows')
        if con_pid:                  # el servicio de Windows se para con taskkill sobre este PID (quitar, reinstalar)
            try:
                servicio.escribir_pid(puerto=srv.server_address[1])
            except OSError:
                con_pid = False
        try:
            srv.serve_forever()      # vuelve cuando POST /salida llama a shutdown(): salida limpia, código 0 (el servicio no se relanza)
        finally:
            if con_pid:
                servicio.borrar_pid()
        srv.server_close()
        return 0
    elif '--watch' in argv:
        cada = int(argv[argv.index('--watch') + 1]) if len(argv) > argv.index('--watch') + 1 else 5
        print(t('regenerando {ruta} cada {cada} s (Ctrl+C para parar)', ruta=os.path.join(DATOS, "index.html"), cada=cada))
        while True:
            sesiones, _ = generar(refresco=cada)
            print('\033[2J\033[H', end='')          # limpiar pantalla sin depender de TERM
            resumen_terminal(sesiones)
            print(f'\n→ {os.path.join(DATOS, "index.html")} · {dt.datetime.now():%H:%M:%S} · ' + t('cada {cada} s', cada=cada), flush=True)
            time.sleep(cada)
    else:
        sesiones, _ = generar()
        resumen_terminal(sesiones)
        print(f'\n→ {os.path.join(DATOS, "index.html")}')


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        pass
