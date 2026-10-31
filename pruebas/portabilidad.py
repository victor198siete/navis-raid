"""Prueba de portabilidad (E8a): la oficina no depende de `fcntl` y sus `git` no tocan el `.git/index` de otros repos.

  1. Sin `fcntl` (se simula con `sys.modules['fcntl'] = None` antes del import, en un subproceso), `bitacora` importa y
     `actualizar()` anota las llamadas sin candado.
  2. Con `fcntl`, el candado sigue funcionando: si otro descriptor tiene el `.lock`, `actualizar()` devuelve None y no escribe.
  3. `plan._correr` llama a `git --no-optional-locks -C <repo> …` (así `git status` no reescribe el índice del repo).

Todo ocurre en un directorio temporal (la bitácora real vive junto al código y no se toca; se comprueba la fecha de su
`.offsets.json`). No ejecuta git de verdad: sustituye `subprocess.run`.

Uso: python3 pruebas/portabilidad.py     (sale con 0 si todo pasa)
"""
import datetime as dt
import json
import os
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


def main():
    antes = os.path.getmtime(REAL) if os.path.exists(REAL) else None

    # 1 · sin fcntl
    with tempfile.TemporaryDirectory() as raiz:
        proyectos = preparar(raiz)
        p = subprocess.run([sys.executable, '-c', SIN_FCNTL, AQUI, raiz, proyectos], capture_output=True, text=True, timeout=60)
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
            with open(os.path.join(bitacora.DIR, '.lock'), 'w') as otro:
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

    despues = os.path.getmtime(REAL) if os.path.exists(REAL) else None
    comprobar(antes == despues, 'el .offsets.json real no se tocó')
    print('\nSALIÓ LIMPIO' if not fallos else f'\n{len(fallos)} FALLO(S)')
    return 1 if fallos else 0


if __name__ == '__main__':
    sys.exit(main())
