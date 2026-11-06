"""Prueba de configuración (E3a): sin config.json la oficina no lleva nada de nadie, y una config rota no la tumba.

Corre en subprocesos, con NAVIS_RAID_CONFIG apuntando a un archivo que no existe (o a uno temporal). Arma la página en
memoria con `oficina.recoger()` y `oficina.render_pixel()`; no llama a `generar()` ni a `bitacora.actualizar()`
(escriben en disco). Comprueba:
  1. sin config: el HTML y el JS no contienen los datos personales de quien la corre (su nombre, su zona, su handle del
     pie y su usuario del sistema; se derivan del config.json local, no están escritos aquí) y los estados de las
     sesiones no nombran a nadie. Se excluye el bloque de datos vivos: lleva títulos y rutas de las sesiones reales.
     Sin config.json local no hay qué buscar, y esas comprobaciones se saltan con un mensaje;
  2. un config.json roto, con una clave desconocida o con valores de tipo equivocado: no revienta, los valores
     vuelven al genérico y `config.AVISOS` no queda vacío;
  3. un config con nombre y zona: el nombre y la etiqueta de zona llegan a la página;
  4. (E3b) sin config la oficina se ve variada (iconos distintos por título, no todo cubos) y sin rotafolios
     (`plan.de_sesiones` deja `plan: None`); un icono desconocido avisa; `carpeta_planning` y `raiz_proyectos` mueven
     las rutas del plan; el umbral llega a `oficina_iso` y a `escena`; con el config local, los iconos de siempre (los de su `familias_iconos`).

El config local es `$NAVIS_RAID_CONFIG` si está definida, o `config.json` junto a `oficina.py` (como en config.py).

Uso: python3 pruebas/configuracion.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_LOCAL = os.path.abspath(os.path.expanduser(os.environ.get('NAVIS_RAID_CONFIG') or os.path.join(AQUI, 'config.json')))


def config_local():
    """El dict del config local, o None si no existe o no se puede leer."""
    try:
        with open(RUTA_LOCAL, encoding='utf-8') as fh:
            datos = json.load(fh)
        return datos if isinstance(datos, dict) else None
    except (OSError, ValueError):
        return None


def datos_personales(cfg):
    """Los textos que no deben aparecer en una página sin config: nombre, zona, handles (@...) del pie y usuario del
    sistema (si tiene 6 letras o más, para no dar falsos positivos). Vacío si no hay config local."""
    if not cfg:
        return []
    valores = [cfg.get('nombre_usuario')]
    zona = cfg.get('zona_horaria')
    valores.append(zona.get('nombre') if isinstance(zona, dict) else None)
    valores += [w.lstrip('@') for w in re.split(r'[\s·]+', cfg.get('pie') or '') if w.startswith('@')]
    usuario = os.path.basename(os.path.expanduser('~'))
    valores.append(usuario if len(usuario) >= 6 else None)
    vistos = []
    for v in valores:
        if isinstance(v, str) and v.strip() and v.strip() not in vistos:
            vistos.append(v.strip())
    return vistos


def familias_a_comprobar(cfg):
    """[(título, icono)] del config local: el primer patrón de cada familia de `familias_iconos`, que debe dar su
    icono. Se omite el patrón que una familia anterior ya reclama (gana la primera familia que casa)."""
    familias = (cfg or {}).get('familias_iconos')
    if not isinstance(familias, dict):
        return []
    pares = []
    for icono, patrones in familias.items():
        if not (isinstance(patrones, list) and patrones and isinstance(patrones[0], str) and patrones[0]):
            continue
        titulo = patrones[0]
        previas = [i for i, p in familias.items() if i != icono and isinstance(p, list) and any(isinstance(k, str) and k.lower() in titulo.lower() for k in p)]
        if not previas or list(familias).index(icono) < list(familias).index(previas[0]):
            pares.append((titulo, icono))
    return pares


CFG = config_local()
PROHIBIDAS = datos_personales(CFG)
FAMILIAS = familias_a_comprobar(CFG)
NOMBRE_LOCAL = ((CFG or {}).get('nombre_usuario') or '').strip()

# Se ejecuta en el subproceso: imprime un JSON con lo que hay que comprobar.
CODIGO = r'''
import json, re, sys
sys.path.insert(0, %r)
import config, oficina, logos, plan, oficina_iso, escena
sesiones, eventos = oficina.recoger()
pagina = oficina.render_pixel([], [], 0)
datos = re.search(r'<script id="datos" type="application/json">(.*?)</script>', pagina, re.S).group(1)
estatica = pagina.replace(datos, '')
ses = [{'cwd': %r, 'titulo': 'x'}]
try:
    plan.de_sesiones(ses)
    plan_sesion = ses[0]['plan']
except Exception as e:
    plan_sesion = 'ERROR ' + str(e)
titulos = ['alfa', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'eta'] + %r
print(json.dumps({'avisos': config.AVISOS, 'umbral': oficina.UMBRAL_K, 'umbral_iso': oficina_iso.UMBRAL_K, 'umbral_escena': getattr(escena, 'UMBRAL_K', None),
                  'iconos': {t: logos.icono(t) for t in titulos}, 'plan_sesion': plan_sesion,
                  'planning': plan.PLANNING, 'productos': plan.PRODUCTOS, 'workspace': plan.WORKSPACE, 'estatica': estatica, 'datos': json.loads(datos.replace('<\\/', '</')),
                  'estados': [s['estado'] for s in sesiones], 'n': len(sesiones)}, ensure_ascii=False))
''' % (AQUI, os.path.dirname(os.path.dirname(AQUI)), [t for t, _ in FAMILIAS])


def correr(ruta_config):
    env = dict(os.environ, NAVIS_RAID_CONFIG=ruta_config)
    p = subprocess.run([sys.executable, '-c', CODIGO], capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, timeout=120)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip().splitlines()[-1] if p.stderr.strip() else f'salió con {p.returncode}')
    return json.loads(p.stdout.splitlines()[-1])


def main():
    fallos = []

    def comprobar(ok, texto):
        print(('✓ ' if ok else '✗ ') + texto)
        if not ok:
            fallos.append(texto)

    tmp = tempfile.mkdtemp(prefix='raid-config-')

    # 1 · sin archivo: genérico
    try:
        r = correr(os.path.join(tmp, 'no-existe.json'))
        if PROHIBIDAS:
            for palabra in PROHIBIDAS:
                comprobar(palabra not in r['estatica'], f'sin config: el HTML y el JS no contienen «{palabra}» ({r["estatica"].count(palabra)} veces)')
        else:
            print(f'- se salta: no hay config local ({RUTA_LOCAL}), así que no hay datos personales que buscar')
        if NOMBRE_LOCAL:
            comprobar(not any(NOMBRE_LOCAL in e for e in r['estados']), 'sin config: ningún estado de sesión nombra al usuario del config local')
        comprobar(r['umbral'] == 350, 'sin config: el umbral de relevo es el genérico (350)')
    except Exception as e:
        comprobar(False, f'sin config: la página se arma sin error ({e})')

    # 2 · config roto / con claves o tipos equivocados: no revienta, avisa
    casos = {
        'JSON roto': '{ "nombre_usuario": "Ana", ',
        'la raíz no es un objeto': '[1, 2, 3]',
        'clave desconocida y tipos equivocados': json.dumps({'clave_rara': 1, 'umbral_relevo_k': 'mucho', 'lobby': 'x',
                                                          'zona_horaria': {'nombre': 'Lima'}, 'horas_visibles': -4}),
    }
    for nombre, contenido in casos.items():
        ruta = os.path.join(tmp, 'roto.json')
        with open(ruta, 'w', encoding='utf-8') as fh:
            fh.write(contenido)
        try:
            r = correr(ruta)
            comprobar(bool(r['avisos']), f'{nombre}: no revienta y config.AVISOS no está vacío ({len(r["avisos"])} avisos)')
            comprobar(r['umbral'] == 350, f'{nombre}: el umbral vuelve al genérico')
            if PROHIBIDAS:
                comprobar(all(p not in r['estatica'] for p in PROHIBIDAS), f'{nombre}: tampoco lleva nombres propios')
        except Exception as e:
            comprobar(False, f'{nombre}: no revienta ({e})')

    # 3 · config con nombre y zona: llegan a la página
    ruta = os.path.join(tmp, 'ana.json')
    with open(ruta, 'w', encoding='utf-8') as fh:
        json.dump({'nombre_usuario': 'Ana', 'zona_horaria': {'utc_offset_h': -3, 'nombre': 'Lima'}, 'umbral_relevo_k': 200,
                   'pie': 'ana · navis raid', 'chat_sesion': 'central',
                   'idioma': 'es'}, fh)       # fijo: sin idioma sale el del sistema y el texto del pie cambiaría (decisión del autor, 27 oct)
    try:
        r = correr(ruta)
        comprobar(r['avisos'] == [], f'config válido: sin avisos ({r["avisos"]})')
        comprobar(r['datos'].get('usuario') == 'Ana', 'config válido: el nombre llega a los datos de la página')
        comprobar((r['datos'].get('zona') or {}).get('nombre') == 'Lima', 'config válido: la zona llega a los datos de la página')
        comprobar('ana · navis raid, salvo lo que hables con central' in r['estatica'], 'config válido: el pie sale del config, con el chat')
        comprobar(r['umbral'] == 200, 'config válido: el umbral sale del config')
    except Exception as e:
        comprobar(False, f'config válido: la página se arma sin error ({e})')

    # 4 · E3b: dibujo y plan salen del config
    try:
        r = correr(os.path.join(tmp, 'no-existe.json'))
        genericos = [r['iconos'][t] for t in ('alfa', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'eta')]
        comprobar(len(set(genericos)) >= 3, f'sin config: al menos 3 iconos distintos entre títulos sin familia ({sorted(set(genericos))})')
        comprobar(set(genericos) != {'cubo'}, 'sin config: la oficina no sale toda de cubos')
        comprobar(r['plan_sesion'] is None, f'sin config: plan.de_sesiones deja plan: None ({str(r["plan_sesion"])[:60]})')
        comprobar(r['umbral_iso'] == 350 and r['umbral_escena'] == 350, 'sin config: el umbral del dibujo es el genérico')
    except Exception as e:
        comprobar(False, f'E3b sin config: se arma sin error ({e})')

    ruta = os.path.join(tmp, 'plan', 'config.json')
    os.makedirs(os.path.dirname(ruta))
    with open(ruta, 'w', encoding='utf-8') as fh:
        json.dump({'carpeta_planning': 'mi-plan', 'raiz_proyectos': '/proyectos/x', 'umbral_relevo_k': 200,
                   'familias_iconos': {'dragon': ['zzz'], 'huella': ['alfa']}}, fh)
    try:
        r = correr(ruta)
        esperado = os.path.join(os.path.dirname(os.path.realpath(ruta)), 'mi-plan')
        comprobar(os.path.realpath(r['planning']) == esperado, f'carpeta_planning: PLANNING es la carpeta relativa al config ({r["planning"]})')
        comprobar(r['productos'] == os.path.join(r['planning'], 'productos.tsv'), 'carpeta_planning: PRODUCTOS cuelga de PLANNING')
        comprobar(r['workspace'] == '/proyectos/x', f'raiz_proyectos: WORKSPACE es la raíz configurada ({r["workspace"]})')
        comprobar(r['iconos']['alfa'] == 'huella', 'familias_iconos: «alfa» toma la familia del config')
        comprobar(any('dragon' in a for a in r['avisos']), 'icono desconocido «dragon»: avisa en config.AVISOS')
        comprobar(r['umbral_iso'] == 200 and r['umbral_escena'] == 200, 'umbral_relevo_k llega a oficina_iso y a escena')
    except Exception as e:
        comprobar(False, f'E3b con config: se arma sin error ({e})')

    # con el config local, si existe: los iconos y el plan de siempre
    if CFG is not None:
        try:
            r = correr(RUTA_LOCAL)
            malos = [f'{t}: {r["iconos"][t]} (esperado {i})' for t, i in FAMILIAS if r['iconos'][t] != i]
            comprobar(bool(FAMILIAS) and not malos,
                      f'config local: los iconos por nombre son los de su familias_iconos ({len(FAMILIAS)} familias comprobadas{"; fallan " + ", ".join(malos) if malos else ""})')
            comprobar(isinstance(r['plan_sesion'], dict), 'config local: la sesión de este repo sí tiene plan')
        except Exception as e:
            comprobar(False, f'config local: se arma sin error ({e})')
    else:
        print(f'- se salta: no hay config local ({RUTA_LOCAL}); sus comprobaciones de iconos y plan no aplican')

    print(f'\n{"FALLÓ" if fallos else "OK"}: {len(fallos)} comprobaciones fallidas')
    return 1 if fallos else 0


if __name__ == '__main__':
    sys.exit(main())
