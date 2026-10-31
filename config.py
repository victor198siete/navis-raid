"""Configuración de Navis Raid: las reglas y los nombres de cada quien, fuera del código.

Se carga una vez al importarse, sin dependencias. La ruta es `$NAVIS_RAID_CONFIG` si está definida; si no,
`config.json` en la carpeta de datos (`DATOS`: `$NAVIS_RAID_DATA`, o la carpeta de este archivo). Sin archivo, todo
toma su valor genérico. Un JSON roto, una clave desconocida o un valor de tipo equivocado no tumban nada: se usa el valor por defecto y el motivo queda en `AVISOS`.

Uso:
  import config
  config.C['umbral_relevo_k']      el dict con todas las claves, ya validadas
  config.idioma()                  'es' o 'en' (la clave `idioma`, o la del sistema si es null)
  config.AVISOS                    lista de cadenas: qué se ignoró y por qué (la muestra `oficina.py --doctor`)
  config.ARCHIVO                   el archivo que se leyó, o None
Las rutas relativas del archivo se resuelven contra su carpeta (`carpeta_planning`); `raiz_proyectos` admite `~`.
Qué es cada clave: `config.ejemplo.json`, en la clave `_ayuda`.
"""
import json
import os
import re
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
# La carpeta de datos: dónde se escribe todo el estado (página, estado.json, bitacora/, chat/) y se lee pisos.json. Es
# `$NAVIS_RAID_DATA` (con `~`, absoluta); sin ella o vacía, la carpeta del código. Los demás módulos la toman de aquí.
DATOS_DE_VARIABLE = bool(os.environ.get('NAVIS_RAID_DATA', '').strip())
DATOS = os.path.abspath(os.path.expanduser(os.environ['NAVIS_RAID_DATA'].strip())) if DATOS_DE_VARIABLE else AQUI
RUTA = os.path.abspath(os.path.expanduser(os.environ.get('NAVIS_RAID_CONFIG') or os.path.join(DATOS, 'config.json')))

# clave → (valor genérico, tipo). Tipos: 'txt' texto, 'txt?' texto o null, 'int' entero positivo, 'lista' lista de
# textos, 'dic_lista' dict de listas de textos, 'zona' {utc_offset_h, nombre} o null.
DEFECTOS = {
    'nombre_usuario': ('', 'txt'),
    'idioma': (None, 'txt?'),
    'umbral_relevo_k': (350, 'int'),
    'ttl_cache_s': (3600, 'int'),
    'horas_visibles': (48, 'int'),
    'modelo_tareas_programadas': ('sonnet', 'txt'),
    'modelo_agentes_sin_definicion': ('sonnet', 'txt'),
    'agentes_con_opus_permitido': ([], 'lista'),
    'zona_horaria': (None, 'zona'),
    'raiz_proyectos': ('~', 'txt'),
    'prefijos_proyecto': ([], 'lista'),
    'pie': ('navis raid · cero tokens', 'txt'),
    'chat_sesion': (None, 'txt?'),
    'lobby': ([], 'lista'),
    'sotano': ('garage', 'txt'),
    'familias_iconos': ({}, 'dic_lista'),
    'carpeta_planning': (None, 'txt?'),
}

AVISOS = []
ARCHIVO = None


def _copia(v):
    return json.loads(json.dumps(v))


def _valido(v, tipo):
    """El valor ya normalizado si tiene la forma esperada; si no, lanza ValueError."""
    if tipo == 'txt' and isinstance(v, str):
        return v
    if tipo == 'txt?' and (v is None or isinstance(v, str)):
        return v or None
    if tipo == 'int' and isinstance(v, int) and not isinstance(v, bool) and v > 0:
        return v
    if tipo == 'lista' and isinstance(v, list) and all(isinstance(x, str) for x in v):
        return v
    if tipo == 'dic_lista' and isinstance(v, dict) and all(
            isinstance(k, str) and isinstance(x, list) and all(isinstance(y, str) for y in x) for k, x in v.items()):
        return v
    if tipo == 'zona':
        if v is None:
            return None
        if isinstance(v, dict):
            h, nombre = v.get('utc_offset_h'), v.get('nombre')
            if isinstance(h, (int, float)) and not isinstance(h, bool) and -14 <= h <= 14 and isinstance(nombre, str) and nombre.strip():
                return {'utc_offset_h': h, 'nombre': nombre.strip()}
    raise ValueError


def _cargar():
    global ARCHIVO
    cfg = {k: _copia(d) for k, (d, _) in DEFECTOS.items()}
    if not os.path.isfile(RUTA):
        if os.environ.get('NAVIS_RAID_CONFIG'):
            AVISOS.append(f'NAVIS_RAID_CONFIG apunta a {RUTA}, que no existe: valores por defecto.')
        return cfg
    try:
        with open(RUTA, encoding='utf-8') as fh:
            datos = json.load(fh)
        if not isinstance(datos, dict):
            raise ValueError('la raíz no es un objeto')
    except (OSError, ValueError) as e:                    # JSON roto, ilegible o que no es un objeto
        AVISOS.append(f'{os.path.basename(RUTA)} no se pudo leer ({e}): valores por defecto.')
        return cfg
    ARCHIVO = RUTA
    for k, v in datos.items():
        if k == '_ayuda' or k.startswith('_'):
            continue
        if k not in DEFECTOS:
            AVISOS.append(f'clave desconocida «{k}»: se ignora.')
            continue
        try:
            cfg[k] = _valido(v, DEFECTOS[k][1])
        except ValueError:
            AVISOS.append(f'«{k}» tiene un valor que no sirve ({json.dumps(v, ensure_ascii=False)[:40]}): se usa el genérico.')
    return cfg


C = _cargar()


def valor(clave):
    return C[clave]


# ---------- derivados que usan varios módulos ----------

def idioma():
    """'es' o 'en': la clave `idioma` si dice es/en (también «es_MX», «EN»…); si es null o no se reconoce, la del
    sistema (LC_ALL, LC_MESSAGES, LANG: que empiece por «es» da 'es'; todo lo demás, 'en')."""
    v = (C['idioma'] or '').strip().lower().replace('-', '_')
    if v[:2] in ('es', 'en'):
        return v[:2]
    for var in ('LC_ALL', 'LC_MESSAGES', 'LANG'):
        sistema = os.environ.get(var, '').strip().lower()
        if sistema:
            return 'es' if sistema.startswith('es') else 'en'
    return 'en'


def nombre():
    """Quien atiende las sesiones, o «ti» si no hay nombre en la configuración."""
    return C['nombre_usuario'].strip() or 'ti'


def codificar_ruta(ruta):
    """Como Claude Code nombra la carpeta de `projects/` para un cwd: todo lo que no es letra o número pasa a `-`."""
    return re.sub(r'[^A-Za-z0-9]', '-', ruta)


def prefijo_proyectos():
    """Lo que se quita de la carpeta codificada para nombrar el proyecto: `raiz_proyectos` codificada, más el guion."""
    raiz = os.path.expanduser(C['raiz_proyectos']).rstrip('/\\')
    return codificar_ruta(raiz) + '-'


def carpeta_planning():
    """Ruta absoluta de `carpeta_planning` (relativa a la carpeta del config.json), o None si no hay plan."""
    c = C['carpeta_planning']
    if not c:
        return None
    base = os.path.dirname(ARCHIVO) if ARCHIVO else AQUI
    return os.path.abspath(os.path.join(base, os.path.expanduser(c)))


def zona():
    """(desfase en horas, nombre) de `zona_horaria`, o None para la hora local de la máquina."""
    z = C['zona_horaria']
    return (z['utc_offset_h'], z['nombre']) if z else None


def etiqueta_zona():
    """Cómo se dice la zona en pantalla: «hora de <zona>», o «hora local» sin zona."""
    z = C['zona_horaria']
    return f"hora de {z['nombre']}" if z else 'hora local'


if __name__ == '__main__':
    print(f'archivo: {ARCHIVO or "(ninguno: valores por defecto)"}')
    print(json.dumps(C, ensure_ascii=False, indent=1))
    for a in AVISOS:
        print('⚠', a, file=sys.stderr)
