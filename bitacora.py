"""La bitácora: una línea por llamada al modelo, para saber en qué se va la cuota.

Diseño aprobado por el autor el 21 oct 2026 (A1, B1, C2):
  - A1 · `bitacora/AAAA-MM-DD.jsonl` (fecha local): hora, sesión, agente, modelo, tokens, contexto y pausa previa.
    Se escribe de forma incremental: `bitacora/.offsets.json` guarda hasta dónde se leyó cada transcripción.
  - B1 · las lecturas reales del plan van en `bitacora/cuota.jsonl` (las anota `cuota.py`).
  - C2 · se guardan las últimas 5 semanas del plan (la actual y las 4 anteriores); lo más viejo se borra al escribir.

Solo lectura de las transcripciones; cero tokens. La carpeta está en `.gitignore`: lleva títulos de sesión.

Uso:
  python3 bitacora.py                 pone la bitácora al día (lo hace también oficina.py en cada pasada)
  python3 bitacora.py --reconstruir   la borra y la rellena hacia atrás con las transcripciones que haya
  python3 bitacora.py --deduplicar    quita las llamadas repetidas de los archivos ya escritos (guarda antes una copia en
                                      bitacora/respaldo-dedup/ y no toca los desplazamientos; ver DISENO.md)
"""
import datetime as dt
import glob
import json
import os
import shutil
import sys
import time

import config

try:
    import fcntl      # candado entre procesos; donde no existe (Windows) la bitácora trabaja sin candado
except ImportError:
    fcntl = None

AQUI = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(config.DATOS, 'bitacora')   # en la carpeta de datos (NAVIS_RAID_DATA; por defecto, junto al código)
OFFSETS = os.path.join(DIR, '.offsets.json')
CUOTA = os.path.join(DIR, 'cuota.jsonl')
# Las rutas viven aquí y oficina.py las toma de aquí. CLAUDE_CONFIG_DIR reemplaza a ~/.claude.
CONFIG = os.path.expanduser(os.environ.get('CLAUDE_CONFIG_DIR') or '~/.claude')
PROYECTOS = os.path.join(CONFIG, 'projects')
SOLO_TERMINAL = os.environ.get('NAVIS_RAID_SOLO_TERMINAL', '').strip().lower() in ('1', 'true', 'si', 'sí', 'yes')   # ignora la app (--solo-terminal)
# La app de escritorio solo se busca en macOS y nunca en modo solo terminal; si no, APP es None y los títulos salen vacíos.
APP = os.path.expanduser('~/Library/Application Support/Claude/claude-code-sessions') if sys.platform == 'darwin' and not SOLO_TERMINAL else None
SEMANAS = 5                      # C2
CLAVES = 20                      # últimas claves (message.id, requestId) por transcripción: los duplicados son consecutivos
UTC = dt.timezone.utc

# Precio de la API en US$ por millón de tokens: (entrada, salida, lectura de caché). Escritura de caché: 1,25× la
# entrada con TTL de 5 min y 2× con TTL de 1 h. Fast mode: 2×. Fuente: skill `claude-api` (tabla del 6 oct 2026),
# consultada el 21 oct. Es el peso relativo entre modelos; la calibración con las lecturas reales fija la escala.
# Gana el prefijo más largo: `claude-opus-5-5` antes que `claude-opus-5`.
PRECIOS = {
    'claude-fable-5-1': (10, 50, 0.25), 'claude-mythos-5-1': (10, 50, 0.25),
    'claude-fable-5': (10, 50, 1.0), 'claude-mythos-5': (10, 50, 1.0),
    'claude-opus-5-5': (4, 20, 0.20),
    'claude-opus-5': (5, 25, 0.50), 'claude-opus-4': (5, 25, 0.50),
    'claude-sonnet-5-5': (2, 10, 0.20), 'claude-sonnet-5': (2, 10, 0.20),
    'claude-sonnet-4': (3, 15, 0.30),
    'claude-haiku-5-5': (0.10, 0.50, 0.01),     # hasta 100K de entrada; más allá, 5× (abajo)
    'claude-haiku-4': (1, 5, 0.10),
}
_PREFIJOS = sorted(PRECIOS, key=len, reverse=True)


def precio(modelo):
    for p in _PREFIJOS:
        if (modelo or '').startswith(p):
            return PRECIOS[p]
    return None


def peso(e):
    """US$ a precio de API de una línea de la bitácora; None si el modelo no tiene precio conocido."""
    p = precio(e.get('modelo'))
    if not p:
        return None
    ent, sal, lec = p
    if e['modelo'].startswith('claude-haiku-5-5') and e.get('ctx', 0) > 100_000:
        ent, sal, lec = ent * 5, sal * 5, lec * 5
    usd = (e.get('in', 0) * ent + e.get('cw5', 0) * ent * 1.25 + e.get('cw1h', 0) * ent * 2
           + e.get('cr', 0) * lec + e.get('out', 0) * sal) / 1e6
    return usd * 2 if e.get('speed') == 'fast' else usd


# ---------- semana del plan ----------

def _dict(x):
    """x si es un dict; si no, {} (los formatos de Claude Code no están documentados: un campo puede venir con otra forma)."""
    return x if isinstance(x, dict) else {}


def _num(x):
    """x si es un número (no bool); si no, 0."""
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else 0


def _txt(x):
    """x si es texto; si no, ''."""
    return x if isinstance(x, str) else ''


def _ts(s):
    try:
        return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
    except (AttributeError, ValueError):
        return None


def reinicio_semanal():
    """Próximo reinicio de la cuota semanal: el `resetsAt` de la última lectura, avanzado de 7 en 7 días hasta
    quedar en el futuro. Sin lecturas: viernes 11:00 UTC (06:00 en UTC-5), lo que dio `get_usage` el 21 oct 2026."""
    r = None
    for l in leer_cuota():
        if l.get('ventana') == 'semanal':
            r = _ts(l.get('resetsAt')) or r
    ahora = dt.datetime.now(UTC)
    if r is None:
        r = ahora.replace(hour=11, minute=0, second=0, microsecond=0) + dt.timedelta(days=(4 - ahora.weekday()) % 7)
    while r <= ahora:
        r += dt.timedelta(days=7)
    while r - dt.timedelta(days=7) > ahora:
        r -= dt.timedelta(days=7)
    return r


def corte():
    """Inicio de lo que se guarda (C2): el arranque de la semana actual menos 4 semanas."""
    return reinicio_semanal() - dt.timedelta(days=7 * SEMANAS)


# ---------- lectura ----------

def leer_cuota():
    try:
        with open(CUOTA, encoding='utf-8') as fh:
            for raw in fh:
                try:
                    yield json.loads(raw)
                except ValueError:
                    continue
    except OSError:
        return


def leer(desde=None, hasta=None):
    """Las líneas de la bitácora con `desde < t <= hasta` (datetimes con zona), en orden de archivo."""
    for f in sorted(glob.glob(os.path.join(DIR, '????-??-??.jsonl'))):
        dia = dt.date.fromisoformat(os.path.basename(f)[:10])
        if desde and dia < (desde.astimezone() - dt.timedelta(days=1)).date():
            continue
        if hasta and dia > (hasta.astimezone() + dt.timedelta(days=1)).date():
            continue
        with open(f, encoding='utf-8') as fh:
            for raw in fh:
                try:
                    e = json.loads(raw)
                except ValueError:            # una línea a medio escribir
                    continue
                t = _ts(e.get('t'))
                if t and (not desde or t > desde) and (not hasta or t <= hasta):
                    e['_t'] = t
                    yield e


# ---------- escritura incremental ----------

_titulos = {'cuando': 0, 'mapa': {}}


def titulos():
    """cliSessionId → título en la app (también las archivadas). Caché de 60 s."""
    if time.time() - _titulos['cuando'] > 60:
        mapa = {}
        for f in glob.glob(APP + '/*/*/local_*.json') if APP else []:
            try:
                d = json.load(open(f, encoding='utf-8'))
            except (ValueError, OSError):
                continue
            if isinstance(d, dict) and isinstance(d.get('cliSessionId'), str) and d['cliSessionId']:
                mapa[d['cliSessionId']] = _txt(d.get('title'))
        _titulos.update(cuando=time.time(), mapa=mapa)
    return _titulos['mapa']


def transcripciones():
    """(ruta, cli de la sesión, agente o None) de cada transcripción principal y de cada subagente."""
    for f in glob.glob(PROYECTOS + '/*/*.jsonl'):
        yield f, os.path.basename(f)[:-6], None
    for f in glob.glob(PROYECTOS + '/*/*/subagents/agent-*.jsonl'):
        # .../<sesión madre>/subagents/agent-<id>.jsonl → la carpeta de la sesión madre es la que está dos niveles arriba
        yield f, os.path.basename(os.path.dirname(os.path.dirname(f))), {'id': os.path.basename(f)[6:-6], 'tipo': None}   # el tipo se lee si hay algo nuevo


def _tipo(ruta):
    try:
        return _txt(_dict(json.load(open(ruta[:-6] + '.meta.json', encoding='utf-8'))).get('agentType')) or '?'
    except (ValueError, OSError):
        return '?'


def _leer_nuevo(ruta, st, cli, agente, desde, mapa):
    """Lee las líneas completas nuevas de una transcripción y devuelve las entradas de la bitácora."""
    with open(ruta, 'rb') as fh:
        fh.seek(st['o'])
        datos = fh.read()
    fin = datos.rfind(b'\n')
    if fin < 0:
        return []
    st['o'] += fin + 1
    out = []
    proyecto = os.path.basename(os.path.dirname(ruta) if not agente else os.path.dirname(os.path.dirname(os.path.dirname(ruta))))
    pre = config.prefijo_proyectos()               # `raiz_proyectos` como la codifica Claude Code, más el guion
    if proyecto.startswith(pre):
        proyecto = proyecto[len(pre):]
    for raw in datos[:fin].split(b'\n'):
        if b'"usage"' not in raw:
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        d = _dict(d)                              # una línea que no es un objeto se salta
        m = _dict(d.get('message'))
        u = _dict(m.get('usage'))
        t = _ts(d.get('timestamp'))
        modelo = _txt(m.get('model'))
        if d.get('type') != 'assistant' or not u or not t or modelo.startswith('<'):
            continue
        clave = f"{m.get('id')}|{d.get('requestId')}"
        if clave in st['k']:                     # el mismo mensaje partido en varias líneas
            continue
        st['k'] = (st['k'] + [clave])[-CLAVES:]
        previo = _ts(st.get('t'))
        st['t'] = t.isoformat()
        if t <= desde:
            continue
        cc = _dict(u.get('cache_creation'))
        cw1h = _num(cc.get('ephemeral_1h_input_tokens'))
        cw = _num(u.get('cache_creation_input_tokens'))
        e = {
            't': t.isoformat(), 'cli': cli[:8], 'titulo': mapa.get(cli, ''),
            'proyecto': proyecto,                 # la carpeta de la sesión, no el cwd del momento (cambia con cada cd)
            'agente': agente, 'modelo': modelo, 'speed': _txt(u.get('speed')) or 'standard',
            'in': _num(u.get('input_tokens')), 'cw5': cw - cw1h, 'cw1h': cw1h,
            'cr': _num(u.get('cache_read_input_tokens')), 'out': _num(u.get('output_tokens')),
        }
        e['ctx'] = e['in'] + cw + e['cr']
        e['pausa'] = round((t - previo).total_seconds()) if previo else None
        out.append(e)
    return out


def _identidad(e):
    """Qué hace única a una llamada: instante, sesión, agente, modelo y tokens. No incluye `titulo` ni `pausa`,
    que cambian si la misma llamada se lee otra vez en otro momento."""
    a = e.get('agente')
    return (e.get('t'), e.get('cli'), a.get('id') if isinstance(a, dict) else None, e.get('modelo'),
            e.get('in'), e.get('cw5'), e.get('cw1h'), e.get('cr'), e.get('out'))


def _identidades(archivo):
    """Las identidades de lo ya anotado en el archivo de un día (vacío si no existe)."""
    ya = set()
    try:
        with open(archivo, encoding='utf-8') as fh:
            for raw in fh:
                try:
                    e = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(e, dict):
                    ya.add(_identidad(e))
    except OSError:
        pass
    return ya


def _podar(limite):
    """C2: borra los días anteriores al corte (y las lecturas de cuota viejas)."""
    dia = limite.astimezone().date()
    for f in glob.glob(os.path.join(DIR, '????-??-??.jsonl')):
        if dt.date.fromisoformat(os.path.basename(f)[:10]) < dia:
            os.remove(f)
    lecturas = list(leer_cuota())
    vigentes = [l for l in lecturas if (_ts(l.get('hora')) or limite) >= limite]
    if len(vigentes) < len(lecturas):
        tmp = CUOTA + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.writelines(json.dumps(l, ensure_ascii=False) + '\n' for l in vigentes)
        os.replace(tmp, CUOTA)


def actualizar(reconstruir=False):
    """Pone la bitácora al día. Devuelve cuántas llamadas nuevas anotó, o None si otro proceso la está escribiendo
    o si todavía no se reconstruyó (la primera pasada lee semanas de transcripciones: se hace a mano)."""
    os.makedirs(DIR, exist_ok=True)
    if not reconstruir and not os.path.exists(OFFSETS):
        return None
    with open(os.path.join(DIR, '.lock'), 'w', encoding='utf-8') as candado:
        try:
            if fcntl:
                fcntl.flock(candado, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None                           # otro servidor de la oficina está escribiendo
        if reconstruir:
            for f in glob.glob(os.path.join(DIR, '????-??-??.jsonl')) + [OFFSETS]:
                if os.path.exists(f):
                    os.remove(f)
            estado = {}
        else:
            try:
                estado = json.load(open(OFFSETS, encoding='utf-8'))
            except (ValueError, OSError):
                estado = {}
        desde = corte()
        mapa = titulos()
        por_dia = {}
        vistas = set()
        cambio = reconstruir
        for ruta, cli, agente in transcripciones():
            vistas.add(ruta)
            try:
                tam = os.path.getsize(ruta)
                mtime = os.path.getmtime(ruta)
            except OSError:
                continue
            st = estado.get(ruta) or {'o': 0, 'k': [], 't': None}
            if tam < st['o']:                     # archivo reescrito: se vuelve a leer desde el principio
                st = {'o': 0, 'k': [], 't': None}
            if tam == st['o']:
                estado[ruta] = st
                continue
            cambio = True
            if st['o'] == 0 and mtime < desde.timestamp():
                st['o'] = tam                     # nada dentro de las 5 semanas: no se lee
                estado[ruta] = st
                continue
            if agente:
                agente['tipo'] = _tipo(ruta)
            for e in _leer_nuevo(ruta, st, cli, agente, desde, mapa):
                por_dia.setdefault(dt.datetime.fromisoformat(e['t']).astimezone().date().isoformat(), []).append(e)
            estado[ruta] = st
        # Sin ninguna transcripción a la vista (carpeta ausente, vacía o ilegible en esta pasada) no se poda: borrar
        # todos los desplazamientos haría que la pasada siguiente lo releyera todo.
        for ruta in [r for r in estado if r not in vistas] if vistas else []:
            del estado[ruta]                      # transcripción borrada
            cambio = True
        if not cambio:
            return 0
        nuevas = 0
        for dia, entradas in sorted(por_dia.items()):
            entradas.sort(key=lambda e: e['t'])
            archivo = os.path.join(DIR, dia + '.jsonl')
            ya = _identidades(archivo)
            with open(archivo, 'a', encoding='utf-8') as fh:
                for e in entradas:
                    ident = _identidad(e)
                    if ident in ya:               # releída tras perderse el estado: ya está anotada
                        continue
                    ya.add(ident)
                    fh.write(json.dumps(e, ensure_ascii=False) + '\n')
                    nuevas += 1
        tmp = OFFSETS + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(estado, fh)
        os.replace(tmp, OFFSETS)
        _podar(desde)
        return nuevas


def deduplicar():
    """Quita de los archivos de cada día las llamadas repetidas (misma `_identidad`), conservando una sola línea por
    llamada —la que tenga título, si alguna lo tiene— y el orden por hora. Antes copia los archivos a
    `bitacora/respaldo-dedup/` (si ya existe, no hace nada). No toca `.offsets.json`. Devuelve (líneas antes, después),
    o None si otro proceso escribe la bitácora o ya hay un respaldo."""
    os.makedirs(DIR, exist_ok=True)
    respaldo = os.path.join(DIR, 'respaldo-dedup')
    with open(os.path.join(DIR, '.lock'), 'w', encoding='utf-8') as candado:
        try:
            if fcntl:
                fcntl.flock(candado, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None
        if os.path.exists(respaldo):
            return None
        archivos = sorted(glob.glob(os.path.join(DIR, '????-??-??.jsonl')))
        os.makedirs(respaldo)
        for f in archivos:
            shutil.copy2(f, respaldo)
        antes = despues = 0
        for f in archivos:
            elegidas = {}
            with open(f, encoding='utf-8') as fh:
                for raw in fh:
                    try:
                        e = json.loads(raw)
                    except ValueError:
                        continue
                    if not isinstance(e, dict):
                        continue
                    antes += 1
                    ident = _identidad(e)
                    if ident not in elegidas or (e.get('titulo') and not elegidas[ident].get('titulo')):
                        elegidas[ident] = e
            lineas = sorted(elegidas.values(), key=lambda e: _txt(e.get('t')))
            despues += len(lineas)
            tmp = f + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                fh.writelines(json.dumps(e, ensure_ascii=False) + '\n' for e in lineas)
            os.replace(tmp, f)
        return antes, despues


if __name__ == '__main__':
    t0 = time.time()
    if '--deduplicar' in sys.argv[1:]:
        r = deduplicar()
        print('sin cambios: otro proceso la está escribiendo, o ya existe bitacora/respaldo-dedup/ (revísalo y bórralo si ya no hace falta)'
              if r is None else f'{r[0]} líneas → {r[1]} ({r[0] - r[1]} repetidas quitadas) · copia en bitacora/respaldo-dedup/ · {time.time() - t0:.1f} s')
        sys.exit(0)
    n = actualizar(reconstruir='--reconstruir' in sys.argv[1:])
    if n is None:
        print('sin cambios: otro proceso la está escribiendo, o falta la primera pasada (--reconstruir)')
    else:
        dias = sorted(glob.glob(os.path.join(DIR, '????-??-??.jsonl')))
        print(f'{n} llamadas nuevas · {len(dias)} días en la bitácora'
              f"{' (' + os.path.basename(dias[0])[:10] + ' → ' + os.path.basename(dias[-1])[:10] + ')' if dias else ''}"
              f' · {time.time() - t0:.1f} s')
