"""Prueba de tolerancia (E2): la oficina no se cae con transcripciones de forma inesperada.

Arma en un directorio temporal un CLAUDE_CONFIG_DIR falso (transcripción buena, una con líneas rotas, una vacía y un
subagente con meta.json que es una lista) y, en subprocesos con esa configuración, corre `oficina.recoger()`,
`oficina.py --doctor` y `bitacora._leer_nuevo` sobre cada archivo. No llama a `bitacora.actualizar()`: escribiría en la
bitácora real (la carpeta `bitacora/` está junto al código, no en CLAUDE_CONFIG_DIR). Por lo mismo, `--doctor` solo se
ejecuta si `oficina.py` lo define; una bandera desconocida regeneraría la página y tocaría la bitácora. Sale con 0 si nada lanzó una excepción y la transcripción buena aparece en `recoger()`.

Uso: python3 pruebas/tolerancia.py
"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CWD = '/nonexistent/proyecto-falso'
BUENA = 'aaaaaaaa-0000-4000-8000-000000000001'
ROTA = 'bbbbbbbb-0000-4000-8000-000000000002'
VACIA = 'cccccccc-0000-4000-8000-000000000003'


def j(**kw):
    return json.dumps(kw, ensure_ascii=False).encode()


def base(tipo, t, **kw):
    return j(type=tipo, timestamp=t, cwd=CWD, entrypoint='cli', version='2.1.299', sessionId='x', **kw)


def armar(raiz):
    """Crea el CLAUDE_CONFIG_DIR falso y devuelve la lista de transcripciones (ruta, es_subagente)."""
    carpeta = os.path.join(raiz, 'projects', '-nonexistent-proyecto-falso')
    os.makedirs(carpeta)
    ahora = dt.datetime.now(dt.timezone.utc)
    t = lambda s: (ahora - dt.timedelta(seconds=s)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    uso = {'input_tokens': 10, 'cache_creation_input_tokens': 20, 'cache_read_input_tokens': 30, 'output_tokens': 5}
    buena = [
        base('user', t(60), message={'role': 'user', 'content': 'hola, prueba buena'}),
        base('assistant', t(50), message={'role': 'assistant', 'model': 'claude-sonnet-5-5', 'id': 'm1', 'stop_reason': 'end_turn',
                                          'usage': uso, 'content': [{'type': 'text', 'text': 'listo'}]}, requestId='r1'),
        j(type='custom-title', customTitle='sesión buena de prueba', sessionId='x'),
    ]
    rota = [
        base('user', t(300), message={'role': 'user', 'content': 'primera línea buena de la rota'}),
        b'[1, 2, 3]', b'"una cadena"', b'42', b'null',
        base('user', t(290), message={'role': 'user', 'content': ['una', 'lista', 'de cadenas']}),
        base('user', t(289), message={'role': 'user', 'content': [{'type': 'text', 'text': None}, 'suelta', 7,
                                                                  {'type': 'tool_result', 'tool_use_id': ['no', 'hashable']}]}),
        base('assistant', t(280), message={'role': 'assistant', 'model': 'claude-sonnet-5-5', 'id': 'm2', 'content': 'texto suelto',
                                           'usage': uso}, requestId='r2'),
        base('assistant', t(270), message={'role': 'assistant', 'model': 'claude-sonnet-5-5', 'id': 'm3', 'content': ['x', None],
                                           'usage': uso}, requestId='r3'),
        base('assistant', t(260), message={'role': 'assistant', 'model': 'claude-sonnet-5-5', 'id': 'm4', 'usage': uso,
                                           'content': [{'type': 'text', 'text': None}, {'type': 'text', 'text': 5}]}, requestId='r4'),
        base('assistant', t(250), message={'role': 'assistant', 'model': 'claude-sonnet-5-5', 'id': 'm5', 'usage': uso,
                                           'content': [{'type': 'tool_use', 'id': 'tu1', 'name': 'Bash', 'input': None},
                                                       {'type': 'tool_use', 'id': 'tu2', 'name': 'Agent', 'input': 'cadena'},
                                                       {'type': 'tool_use', 'id': ['lista'], 'name': 'Read', 'input': ['x']},
                                                       {'type': 'tool_use', 'id': 'tu3', 'name': None, 'input': {'description': 5}}]},
             requestId='r5'),
        base('assistant', t(240), message={'role': 'assistant', 'model': 'claude-sonnet-5-5', 'id': 'm6',
                                           'usage': {'input_tokens': None, 'cache_creation_input_tokens': '12', 'cache_read_input_tokens': 'x',
                                                     'output_tokens': None, 'cache_creation': 'no', 'speed': 7},
                                           'content': [{'type': 'text', 'text': 'usage raro'}]}, requestId='r6'),
        base('assistant', t(230), message={'role': 'assistant', 'model': 99, 'id': ['m7'], 'usage': 'mucho', 'content': []}, requestId=['r7']),
        base('assistant', t(220), message='un mensaje que es cadena'),
        base('user', t(210), message=['lista']),
        j(type='custom-title', customTitle=None, sessionId='x'),
        j(type='ai-title', aiTitle=['no', 'es', 'str'], sessionId='x'),
        j(type='last-prompt', lastPrompt=123),
        j(type=['raro'], timestamp=12345, cwd=5, message={}),
        b'{"type":"user","message":{"role":"user","cont',                      # línea cortada a la mitad
        b'\xff\xfe\x00 bytes que no son UTF-8 "type" "usage" \xc3\x28',
        base('assistant', t(200), message={'role': 'assistant', 'model': 'claude-sonnet-5-5', 'id': 'm8', 'usage': uso,
                                           'content': [{'type': 'text', 'text': 'y sigue después de lo roto'}]}, requestId='r8'),
        j(type='custom-title', customTitle='sesión rota de prueba', sessionId='x'),
    ]
    sub = os.path.join(carpeta, BUENA, 'subagents')
    os.makedirs(sub)
    escribir = lambda ruta, lineas: open(ruta, 'wb').write(b'\n'.join(lineas) + b'\n')
    escribir(os.path.join(carpeta, BUENA + '.jsonl'), buena)
    escribir(os.path.join(carpeta, ROTA + '.jsonl'), rota)
    open(os.path.join(carpeta, VACIA + '.jsonl'), 'wb').close()
    # subagente 1: meta.json es una lista; su transcripción empieza con una lista
    open(os.path.join(sub, 'agent-uno.meta.json'), 'w').write('[]')
    escribir(os.path.join(sub, 'agent-uno.jsonl'), [b'[1]', base('assistant', t(40), message={'role': 'assistant', 'content': 'x'})])
    # subagente 2: meta.json es una cadena JSON; mensajes con forma rara
    open(os.path.join(sub, 'agent-dos.meta.json'), 'w').write('"hola"')
    escribir(os.path.join(sub, 'agent-dos.jsonl'), [base('assistant', t(30), message={'role': 'assistant', 'content': [None, 'x', {'type': 'tool_use', 'name': 'Bash', 'input': 'x'}]})])
    # subagente 3: meta.json bueno, con campos que no son texto
    open(os.path.join(sub, 'agent-tres.meta.json'), 'w').write(json.dumps({'agentType': ['x'], 'description': None, 'model': 5}))
    escribir(os.path.join(sub, 'agent-tres.jsonl'), [base('user', t(20), message={'role': 'user', 'content': 'x'})])
    return [(os.path.join(carpeta, BUENA + '.jsonl'), False), (os.path.join(carpeta, ROTA + '.jsonl'), False),
            (os.path.join(carpeta, VACIA + '.jsonl'), False)] + \
           [(os.path.join(sub, f), True) for f in ('agent-uno.jsonl', 'agent-dos.jsonl', 'agent-tres.jsonl')]


HIJO_RECOGER = """
import sys, json
sys.path.insert(0, %(aqui)r)
import oficina
sesiones, _ = oficina.recoger()
print(json.dumps([s['titulo'] for s in sesiones]))
"""

HIJO_BITACORA = """
import sys, json, datetime as dt
sys.path.insert(0, %(aqui)r)
import bitacora
fallos = []
for ruta, es_sub in json.loads(sys.argv[1]):
    agente = {'id': 'x', 'tipo': None} if es_sub else None
    try:
        bitacora._leer_nuevo(ruta, {'o': 0, 'k': []}, 'abcdef123456', agente, dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc), {})
        if es_sub:
            bitacora._tipo(ruta)
    except Exception as e:
        fallos.append(f'{ruta.split("/")[-1]}: {type(e).__name__}: {e}')
print(json.dumps(fallos))
"""


def correr(codigo, env, *args):
    return subprocess.run([sys.executable, '-c', codigo, *args], env=env, capture_output=True, text=True, timeout=120)


def main():
    fallos = []
    with tempfile.TemporaryDirectory() as raiz:
        archivos = armar(raiz)
        env = dict(os.environ, CLAUDE_CONFIG_DIR=raiz, NAVIS_RAID_SOLO_TERMINAL='1')

        r = correr(HIJO_RECOGER % {'aqui': AQUI}, env)
        if r.returncode != 0:
            fallos.append('recoger() lanzó una excepción:\n' + r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'recoger() falló')
            print(r.stderr.strip()[-1500:], file=sys.stderr)
        else:
            titulos = json.loads(r.stdout.strip().splitlines()[-1])
            if 'sesión buena de prueba' not in titulos:
                fallos.append(f'la transcripción buena no aparece en recoger(): {titulos}')
            print('recoger():', titulos)

        r = correr(HIJO_BITACORA % {'aqui': AQUI}, env, json.dumps(archivos))
        if r.returncode != 0:
            fallos.append('bitacora._leer_nuevo no pudo correr: ' + (r.stderr.strip().splitlines() or ['?'])[-1])
        else:
            malos = json.loads(r.stdout.strip().splitlines()[-1])
            fallos += ['bitacora._leer_nuevo lanzó ' + m for m in malos]
            print('bitacora._leer_nuevo:', 'sin excepciones' if not malos else f'{len(malos)} con excepción')

        # --doctor: solo si existe (si no, correr oficina.py regeneraría index.html con la configuración falsa)
        with open(os.path.join(AQUI, 'oficina.py')) as fh:
            hay_doctor = 'def doctor(' in fh.read()
        if not hay_doctor:
            fallos.append('oficina.py no tiene --doctor')
        else:
            vigilados = ('index.html', 'estado.json', os.path.join('bitacora', '.offsets.json'))   # --doctor no debe tocarlos
            previo = {f: os.path.getmtime(os.path.join(AQUI, f)) for f in vigilados if os.path.exists(os.path.join(AQUI, f))}
            r = subprocess.run([sys.executable, os.path.join(AQUI, 'oficina.py'), '--doctor'], env=env, capture_output=True, text=True, timeout=120)
            if 'Traceback' in r.stderr:
                fallos.append('--doctor lanzó una excepción: ' + r.stderr.strip().splitlines()[-1])
            if r.returncode != 0:
                fallos.append(f'--doctor salió con {r.returncode}')
            if not any(m in r.stdout for m in ('✓', '⚠', '✗')):
                fallos.append('--doctor no imprimió ninguna comprobación')
            ahora = {f: os.path.getmtime(os.path.join(AQUI, f)) for f in previo}
            if ahora != previo:
                fallos.append('--doctor escribió index.html, estado.json o la bitácora (debe ser solo lectura)')
            print('--doctor: salida', r.returncode)

    if fallos:
        print('\nFALLÓ:\n  - ' + '\n  - '.join(fallos))
        return 1
    print('\nOK: nada lanzó una excepción y la transcripción buena aparece en recoger()')
    return 0


if __name__ == '__main__':
    sys.exit(main())
