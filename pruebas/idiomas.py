"""Prueba de idiomas (E4a): Navis Raid habla español o inglés según `config.idioma`, y en español nada cambia.

Corre en subprocesos con `NAVIS_RAID_CONFIG` apuntando a un archivo temporal. Arma la página en memoria con
`oficina.recoger()` y `oficina.render_pixel()`; no llama a `generar()` ni a `bitacora.actualizar()` (escriben en disco).
Comprueba:
  1. todo literal de `t('…')` en los cinco `.py` (oficina, oficina_iso, costo, escena, plan) tiene entrada en `EN`
     con los mismos {marcadores}, y ninguna llamada a `t()` recibe algo que no sea un literal (el escáner no la vería);
  2. con `{"idioma": "en"}`: el estado de una sesión sale en inglés (`estado_de` con cada rama y los estados reales de
     `recoger()`), `hace()`, `<html lang>`, los días y meses del modal Costo y los títulos del dibujo;
  3. `oficina.py --doctor` en inglés no deja ninguna palabra suelta en español;
  4. con `{"idioma": "es"}` los mismos textos salen como siempre;
  5. el JS de la página (E4b): `node --check` en los dos idiomas; cada `T('…')` tiene entrada en `EN_JS` con los mismos
     {marcadores} y ninguna llamada a `T()` recibe algo que no sea un literal; fuera de las claves de `T()` y de los
     comentarios no quedan palabras visibles en español; el JS ya no interpreta el texto de `hace()` (usa `hace_s` y
     `espera_s`, numéricos) y `dur()` da lo mismo que `hace()` en los dos idiomas.

Uso: python3 pruebas/idiomas.py
"""
import ast
import json
import os
import re
import string
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AQUI)
FUENTES = ('oficina.py', 'oficina_iso.py', 'costo.py', 'escena.py', 'plan.py', 'servicio.py')
PALABRAS_JS = ('esperando', 'sesión', 'sesiones', 'encargo', 'relevo', 'semana', 'reinicio', 'cuota')
PROHIBIDAS_EN_DOCTOR = ('esperando', 'transcripciones', 'sesiones', 'piso', 'bitácora')
SPANISH_ESTADOS = ('esperando', 'pensando', 'ejecutando', 'en pausa', 'relevada')

# Se ejecuta en el subproceso: imprime un JSON con lo que hay que comprobar.
CODIGO = r'''
import datetime as dt, json, re, sys
sys.path.insert(0, %r)
import config, oficina, oficina_iso, costo, textos
ahora = dt.datetime.now(dt.timezone.utc)
sesiones, eventos = oficina.recoger()
EVENTOS = [(ahora - dt.timedelta(minutes=5), 'ses', 'encargo', 'x')]
pagina = oficina.render_pixel([], EVENTOS, 0)
datos_pagina = json.loads(re.search(r'<script id="datos" type="application/json">(.*?)</script>', pagina, re.S).group(1))
vacio = oficina.vacio('x')
print(json.dumps({
    'idioma': textos.idioma(),
    'estados': [s['estado'] for s in sesiones],
    'ramas': [oficina.estado_de(a, activa, pend, 'Bash', stop) for a, activa, pend, stop in (
        ({'agente': 'qa', 'tarea': 'probar'}, True, True, ''), (None, True, True, ''), (None, True, False, ''),
        (None, False, False, 'end_turn'), (None, False, True, 'tool_use'))],
    'hace': [oficina.hace(ahora - dt.timedelta(seconds=10)), oficina.hace(ahora - dt.timedelta(minutes=5)),
             oficina.hace(ahora - dt.timedelta(hours=3)), oficina.hace(ahora - dt.timedelta(days=2))],
    'lang': re.search(r'<html lang="(\w+)"', pagina).group(1),
    'lang_tabla': re.search(r'<html lang="(\w+)"', oficina.render_html([], [], 0)).group(1),
    'usuario': oficina.USUARIO, 'vacio': vacio['estado'], 'ocio': list(oficina.OCIO),
    'dias': costo.DIAS, 'meses': costo.MESES, 'zona': oficina.ZONA_ETIQUETA,
    'para_js': textos.para_js(),
    'js': re.search(r'<script>(.*)</script></body>', pagina, re.S).group(1),
    'textos_pagina': datos_pagina.get('textos'), 'eventos_hace_s': [e.get('hace_s') for e in datos_pagina['eventos']],
    'sotano': [p['nombre'] for p in oficina.cargar_pisos()[0]],
    'aviso': oficina.aviso_version('0.1.0'),
}, ensure_ascii=False))
''' % AQUI


def correr(ruta_config, *args):
    env = dict(os.environ, NAVIS_RAID_CONFIG=ruta_config)
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, env=env, timeout=180)


def datos(ruta_config):
    p = correr(ruta_config, '-c', CODIGO)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip().splitlines()[-1] if p.stderr.strip() else f'salió con {p.returncode}')
    return json.loads(p.stdout.splitlines()[-1])


def marcadores(texto):
    return {c[1] for c in string.Formatter().parse(texto) if c[1]}


def literales_t(archivo):
    """([literales de t('…')], [líneas de t() con algo que no es un literal]) de un .py."""
    with open(os.path.join(AQUI, archivo), encoding='utf-8') as fh:
        arbol = ast.parse(fh.read())
    ok, mal = [], []
    for n in ast.walk(arbol):
        if isinstance(n, ast.Call) and ((isinstance(n.func, ast.Name) and n.func.id == 't')
                                        or (isinstance(n.func, ast.Attribute) and n.func.attr == 't' and getattr(n.func.value, 'id', '') == 'textos')):
            if n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                ok.append(n.args[0].value)
            else:
                mal.append(n.lineno)
    return ok, mal


def literales_js(js):
    """[(texto, es_clave_T, tiene_expresion)] de los literales ('…', "…", `…`) del JS, sin comentarios ni regex.
    Las plantillas se parten en sus trozos fijos; los `${…}` se recorren como código."""
    out, pila, i, n, prev = [], [], 0, len(js), ''

    def cadena(i, q):
        j, buf = i + 1, []
        while j < n and js[j] != q:
            if js[j] == '\\':
                buf.append(js[j:j + 2]); j += 2
            else:
                buf.append(js[j]); j += 1
        return ''.join(buf), j + 1

    def plantilla(i):
        j, buf = i, []
        while j < n:
            if js[j] == '\\':
                buf.append(js[j:j + 2]); j += 2; continue
            if js[j] == '`':
                return ''.join(buf), j + 1, False
            if js[j] == '$' and js[j + 1:j + 2] == '{':
                return ''.join(buf), j + 2, True
            buf.append(js[j]); j += 1
        return ''.join(buf), j, False

    def es_t(i):
        return bool(re.search(r'(?<![\w$.])T\(\s*$', js[:i]))

    while i < n:
        c = js[i]
        if js.startswith('//', i):
            i = js.find('\n', i); i = n if i < 0 else i; continue
        if js.startswith('/*', i):
            i = js.find('*/', i) + 2; continue
        if c == '/' and (prev == '' or prev in '(,=:[!&|?{};'):              # literal de regex
            j, clase = i + 1, False
            while j < n and (js[j] != '/' or clase):
                if js[j] == '\\': j += 1
                elif js[j] == '[': clase = True
                elif js[j] == ']': clase = False
                j += 1
            i, prev = j + 1, 'x'; continue
        if c in '\'"':
            txt, j = cadena(i, c); out.append((txt, es_t(i), False)); i, prev = j, 'x'; continue
        if c == '`':
            txt, j, expr = plantilla(i + 1); out.append((txt, es_t(i), expr))
            if expr: pila.append('p')
            i, prev = j, ('(' if expr else 'x'); continue
        if c == '{':
            pila.append('b')
        elif c == '}' and pila and pila.pop() == 'p':
            txt, j, expr = plantilla(i + 1); out.append((txt, False, expr))
            if expr: pila.append('p')
            i, prev = j, ('(' if expr else 'x'); continue
        if not c.isspace():
            prev = c
        i += 1
    return out


def main():
    fallos = []
    res = {}

    def comprobar(ok, texto):
        print(('✓ ' if ok else '✗ ') + texto)
        if not ok:
            fallos.append(texto)

    # 1 · cada literal tiene traducción con los mismos marcadores
    try:
        import textos_en
        en = textos_en.EN
    except ImportError as e:
        comprobar(False, f'existe textos_en.EN ({e})')
        en = None
    if en is not None:
        total = 0
        for f in FUENTES:
            ok, mal = literales_t(f)
            total += len(ok)
            comprobar(not mal, f'{f}: toda llamada a t() lleva un literal (fallan las de las líneas {mal})')
            sin = sorted({x for x in ok if x not in en})
            comprobar(not sin, f'{f}: {len(ok)} literales, todos con entrada en EN (faltan {len(sin)}: {sin[:3]})')
            raros = sorted({x for x in ok if x in en and marcadores(x) != marcadores(en[x])})
            comprobar(not raros, f'{f}: los {{marcadores}} coinciden entre español e inglés ({raros[:3]})')
        comprobar(total > 100, f'se escanearon {total} llamadas a t() (más de 100)')
        sobran = sorted(k for k in en if not any(k in literales_t(f)[0] for f in FUENTES))
        comprobar(not sobran, f'EN no trae claves que nadie use ({len(sobran)}: {sobran[:3]})')

    tmp = tempfile.mkdtemp(prefix='raid-idiomas-')
    ruta_en, ruta_es = os.path.join(tmp, 'en.json'), os.path.join(tmp, 'es.json')
    for ruta, idioma in ((ruta_en, 'en'), (ruta_es, 'es')):
        with open(ruta, 'w', encoding='utf-8') as fh:
            json.dump({'idioma': idioma}, fh)

    # 2 · en inglés
    try:
        r = res['en'] = datos(ruta_en)
        comprobar(r['idioma'] == 'en', 'con idioma "en", textos.idioma() es en')
        comprobar(r['ramas'] == ['waiting for qa: probar', 'running Bash', 'thinking or writing', 'waiting for you', 'paused'],
                  f'los estados de sesión salen en inglés ({r["ramas"]})')
        comprobar(not any(re.search('|'.join(SPANISH_ESTADOS), e) for e in r['estados']),
                  f'los {len(r["estados"])} estados de recoger() no traen estados en español')
        comprobar(r['hace'] == ['seconds ago', '5 min ago', '3.0 h ago', '2 d ago'], f'hace() en inglés ({r["hace"]})')
        comprobar(r['lang'] == 'en' and r['lang_tabla'] == 'en', f'<html lang> es en ({r["lang"]}, {r["lang_tabla"]})')
        comprobar(r['usuario'] == 'you' and r['vacio'] == 'no activity', f'«ti» pasa a «you» ({r["usuario"]}, {r["vacio"]})')
        comprobar(r['dias'][0] == 'Mon' and r['meses'][9] == 'Oct', f'días y meses del modal Costo en inglés ({r["dias"][:2]}, {r["meses"][9]})')
        comprobar(r['zona'] == 'local time' or r['zona'].endswith(' time'), f'la etiqueta de zona en inglés ({r["zona"]})')
        comprobar(r['aviso'] and r['aviso'].startswith('Tested with'), f'aviso_version en inglés ({r["aviso"]})')
        comprobar(isinstance(r['para_js'], dict), 'para_js() devuelve un dict en inglés')
        comprobar(not any(re.search(r'\bSótano\b|\bPiso\b|\bPlanta baja\b', n) for n in r['sotano']), f'los nombres de piso en inglés ({r["sotano"]})')
    except Exception as e:
        comprobar(False, f'la página en inglés se arma sin error ({e})')

    p = correr(ruta_en, os.path.join(AQUI, 'oficina.py'), '--doctor')
    for palabra in PROHIBIDAS_EN_DOCTOR:
        n = len(re.findall(r'\b%s\b' % palabra, p.stdout, re.I))
        comprobar(n == 0, f'--doctor en inglés no contiene «{palabra}» ({n} veces)')
    comprobar('transcripts' in p.stdout and p.stdout.count('\n') > 10, '--doctor en inglés imprime sus líneas (mínimo 10)')

    # 3 · en español nada cambia
    try:
        r = res['es'] = datos(ruta_es)
        comprobar(r['ramas'] == ['esperando a qa: probar', 'ejecutando Bash', 'pensando o escribiendo', 'esperando a ti', 'en pausa'],
                  f'con idioma "es" los estados son los de siempre ({r["ramas"]})')
        comprobar(r['hace'] == ['hace segundos', 'hace 5 min', 'hace 3.0 h', 'hace 2 d'], f'hace() en español ({r["hace"]})')
        comprobar(r['lang'] == 'es' and r['usuario'] == 'ti' and r['dias'][0] == 'lun' and r['meses'][9] == 'oct'
                  and r['ocio'][0] == 'videojuegos' and r['para_js'] == {}, 'lang, usuario, días, meses, ocio y para_js() en español')
    except Exception as e:
        comprobar(False, f'la página en español se arma sin error ({e})')

    # 4 · el JS de la página (E4b)
    try:
        import textos_en
        en_js = textos_en.EN_JS
    except ImportError as e:
        comprobar(False, f'existe textos_en.EN_JS ({e})')
        en_js = {}
    for idioma in ('en', 'es'):
        js = res.get(idioma, {}).get('js')
        if js is None:
            comprobar(False, f'hay JS de la página en {idioma}')
            continue
        archivo = os.path.join(tmp, f'pagina-{idioma}.js')
        with open(archivo, 'w', encoding='utf-8') as fh:
            fh.write(js)
        try:
            p = subprocess.run(['node', '--check', archivo], capture_output=True, text=True, timeout=60)
            comprobar(p.returncode == 0, f'node --check del JS generado en {idioma} ({p.stderr.strip()[:200]})')
        except (OSError, subprocess.TimeoutExpired) as e:
            comprobar(False, f'node --check del JS generado en {idioma} ({e})')
    js = res.get('es', {}).get('js') or ''
    lits = literales_js(js)
    claves = [t_ for t_, es_clave, _ in lits if es_clave]
    llamadas = re.findall(r'(?<![\w$.])(?<!function )T\(\s*(.)', js)
    comprobar(len(claves) > 150, f'se escanearon {len(claves)} claves de T() en el JS (más de 150)')
    comprobar(all(c in '\'"`' for c in llamadas), f'toda llamada a T() lleva un literal ({len(llamadas)} llamadas, {len(claves)} literales)')
    comprobar(not [t_ for t_, es_clave, expr in lits if es_clave and expr], 'ninguna clave de T() es una plantilla con ${…}')
    sin = sorted({c for c in claves if c not in en_js})
    comprobar(not sin, f'cada clave de T() tiene entrada en EN_JS (faltan {len(sin)}: {sin[:3]})')
    raros = sorted({c for c in claves if c in en_js and marcadores(c) != marcadores(en_js[c])})
    comprobar(not raros, f'los {{marcadores}} de EN_JS coinciden con los de la clave ({raros[:3]})')
    sobran = sorted(k for k in en_js if k not in claves)
    comprobar(not sobran, f'EN_JS no trae claves que nadie use ({len(sobran)}: {sobran[:3]})')
    patron = re.compile(r'(?<![\w\-.#])(%s)(?![\w\-])' % '|'.join(PALABRAS_JS), re.I)
    sueltas = sorted({m.group(0).lower() + ' en «' + t_.strip()[:40] + '»' for t_, es_clave, _ in lits if not es_clave
                      and re.search(r'\s', t_.strip()) for m in patron.finditer(t_)})
    comprobar(not sueltas, f'el JS no deja palabras visibles en español fuera de T() ({len(sueltas)}: {sueltas[:3]})')
    comprobar(not re.search(r"/segundos/|\^hace|replace\('hace |\.ultima\.replace", js), 'el JS ya no interpreta el texto de hace()')
    r_en = res.get('en', {})
    comprobar(isinstance(r_en.get('textos_pagina'), dict) and r_en['textos_pagina'] == r_en.get('para_js') and r_en['textos_pagina'],
              'la página en inglés lleva D.textos (el diccionario de EN_JS)')
    comprobar(res.get('es', {}).get('textos_pagina') == {}, 'la página en español lleva D.textos vacío')
    hs = r_en.get('eventos_hace_s') or [None]
    comprobar(hs[0] is not None and 298 <= hs[0] <= 330, f'cada evento lleva hace_s numérico ({hs})')
    # dur() y T() de la página, corridos con node: lo mismo que hace() en cada idioma
    esperado = {'en': ['seconds', '5 min', '3.0 h', '2 d'], 'es': ['segundos', '5 min', '3.0 h', '2 d']}
    for idioma in ('en', 'es'):
        js_i = res.get(idioma, {}).get('js') or ''
        funcs = '\n'.join(l for l in js_i.splitlines() if re.match(r'(function (T|dur|dec)\(|const ES\b)', l))
        textos_i = res.get(idioma, {}).get('textos_pagina') or {}
        prog = 'let D = {textos: %s};\n%s\nconsole.log(JSON.stringify([dur(10), dur(300), dur(10800), dur(172800)]));' % (json.dumps(textos_i), funcs)
        try:
            p = subprocess.run(['node', '-e', prog], capture_output=True, text=True, timeout=60)
            salida = json.loads(p.stdout) if p.returncode == 0 else p.stderr.strip()[-200:]
        except (OSError, subprocess.TimeoutExpired, ValueError) as e:
            salida = str(e)
        comprobar(salida == esperado[idioma], f'dur() de la página en {idioma} ({salida})')

    print('\n' + ('TODO BIEN' if not fallos else f'{len(fallos)} FALLOS'))
    return 1 if fallos else 0


if __name__ == '__main__':
    sys.exit(main())
