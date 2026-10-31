"""Prueba de duplicados: la bitácora no repite una llamada aunque se pierda o se rompa el estado de lectura.

Causa que reproduce (27 oct 2026): una pasada de `bitacora.actualizar()` que no ve ninguna transcripción (carpeta de
configuración ausente, vacía o ilegible) borraba de `.offsets.json` el desplazamiento de todas; la siguiente pasada
releía todo desde cero y lo anotaba otra vez. Lo mismo pasa si `.offsets.json` queda ilegible o se reinicia.

Todo ocurre en un directorio temporal: se reapuntan `DIR`, `OFFSETS`, `CUOTA`, `PROYECTOS` y `APP` del módulo antes de
llamar a `actualizar()`, y la prueba se niega a seguir si `DIR` no quedó dentro de ese directorio (la bitácora real vive
junto al código y no se toca). Comprueba además que el `.offsets.json` real conserva la misma fecha de modificación.

Uso: python3 pruebas/duplicados.py     (sale con 0 si nada se duplica)
"""
import datetime as dt
import json
import os
import sys
import tempfile

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AQUI)
import bitacora   # noqa: E402

REAL = os.path.join(AQUI, 'bitacora', '.offsets.json')
fallos = []


def comprobar(ok, que):
    print(('ok     ' if ok else 'FALLA  ') + que)
    if not ok:
        fallos.append(que)


def llamada(t, i, agente=False):
    return json.dumps({
        'type': 'assistant', 'timestamp': t, 'requestId': f'r{i}',
        'message': {'role': 'assistant', 'model': 'claude-sonnet-5-5', 'id': f'm{i}', 'content': [],
                    'usage': {'input_tokens': 10 + i, 'cache_creation_input_tokens': 20, 'cache_read_input_tokens': 30,
                              'output_tokens': 5}},
    }).encode() + b'\n'


def contar():
    """(líneas, líneas repetidas) de todos los días de la bitácora de prueba."""
    total = rep = 0
    for nombre in os.listdir(bitacora.DIR):
        if len(nombre) == 16 and nombre.endswith('.jsonl') and nombre != 'cuota.jsonl':
            vistas = set()
            for raw in open(os.path.join(bitacora.DIR, nombre)):
                k = json.dumps(json.loads(raw), sort_keys=True)
                total += 1
                rep += k in vistas
                vistas.add(k)
    return total, rep


def main():
    antes = os.path.getmtime(REAL) if os.path.exists(REAL) else None
    with tempfile.TemporaryDirectory() as raiz:
        proyectos = os.path.join(raiz, 'projects')
        carpeta = os.path.join(proyectos, '-Users-ejemplo-Desktop-Workspace-Prueba')
        os.makedirs(carpeta)
        vacio = os.path.join(raiz, 'vacio')
        os.makedirs(vacio)
        bitacora.DIR = os.path.join(raiz, 'bitacora')
        bitacora.OFFSETS = os.path.join(bitacora.DIR, '.offsets.json')
        bitacora.CUOTA = os.path.join(bitacora.DIR, 'cuota.jsonl')
        bitacora.PROYECTOS = proyectos
        bitacora.APP = None
        assert os.path.realpath(bitacora.DIR).startswith(os.path.realpath(raiz)), 'la bitácora de prueba no es temporal'

        ahora = dt.datetime.now(dt.timezone.utc)
        t = lambda s: (ahora - dt.timedelta(seconds=s)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        ruta = os.path.join(carpeta, 'aaaaaaaa-0000-4000-8000-000000000001.jsonl')
        with open(ruta, 'wb') as fh:
            for i in range(30):
                fh.write(llamada(t(600 - i * 10), i))

        n = bitacora.actualizar(reconstruir=True)
        comprobar(n == 30 and contar() == (30, 0), f'reconstruir anota las 30 llamadas una vez (anotó {n}, hay {contar()})')
        n = bitacora.actualizar()
        comprobar(n == 0 and contar() == (30, 0), f'una pasada sin nada nuevo no añade nada (anotó {n})')

        # 1 · una pasada que no ve transcripciones (carpeta vacía) y luego otra con las transcripciones de vuelta
        bitacora.PROYECTOS = vacio
        bitacora.actualizar()
        bitacora.PROYECTOS = proyectos
        n = bitacora.actualizar()
        comprobar(contar() == (30, 0), f'tras una pasada sin transcripciones y otra con ellas no hay repetidas (hay {contar()}, anotó {n})')

        # 2 · .offsets.json ilegible
        with open(bitacora.OFFSETS, 'w') as fh:
            fh.write('{"roto": ')
        n = bitacora.actualizar()
        comprobar(contar() == (30, 0), f'con .offsets.json ilegible no hay repetidas (hay {contar()}, anotó {n})')

        # 3 · .offsets.json reiniciado a vacío
        with open(bitacora.OFFSETS, 'w') as fh:
            fh.write('{}')
        n = bitacora.actualizar()
        comprobar(contar() == (30, 0), f'con .offsets.json vacío no hay repetidas (hay {contar()}, anotó {n})')

        # 4 · lo nuevo sí se anota, una sola vez, y sin perder lo anterior
        with open(ruta, 'ab') as fh:
            for i in range(30, 35):
                fh.write(llamada(t(100 - (i - 30)), i))
        n = bitacora.actualizar()
        comprobar(n == 5 and contar() == (35, 0), f'5 llamadas nuevas se anotan una vez (anotó {n}, hay {contar()})')
        n = bitacora.actualizar()
        comprobar(n == 0 and contar() == (35, 0), f'y la pasada siguiente no repite nada (anotó {n})')

        # 5 · --deduplicar limpia lo que ya estaba repetido (con y sin título), hace copia y deja los desplazamientos
        dia = sorted(f for f in os.listdir(bitacora.DIR) if len(f) == 16 and f != 'cuota.jsonl')[0]
        archivo = os.path.join(bitacora.DIR, dia)
        lineas = open(archivo).read().splitlines()
        e0 = json.loads(lineas[0])
        sin, con = dict(e0, titulo=''), dict(e0, titulo='con título', pausa=7)
        with open(archivo, 'a') as fh:
            fh.write('\n'.join([json.dumps(sin), json.dumps(con), lineas[1]]) + '\n')
        offsets = open(bitacora.OFFSETS).read()
        antes_n = contar()[0]
        r = bitacora.deduplicar()
        leidas = [json.loads(l) for l in open(archivo)]
        comprobar(r == (antes_n, antes_n - 3) and contar() == (antes_n - 3, 0), f'--deduplicar quita las 3 repetidas ({r}, hay {contar()})')
        comprobar(any(e['t'] == e0['t'] and e['titulo'] == 'con título' for e in leidas), '--deduplicar conserva la línea que tiene título')
        comprobar(os.path.isdir(os.path.join(bitacora.DIR, 'respaldo-dedup')) and open(bitacora.OFFSETS).read() == offsets,
                  '--deduplicar deja copia en respaldo-dedup/ y no toca .offsets.json')
        comprobar(bitacora.deduplicar() is None, '--deduplicar no se repite si ya hay copia')

    despues = os.path.getmtime(REAL) if os.path.exists(REAL) else None
    comprobar(antes == despues, 'el .offsets.json real no se tocó')
    print('\nSALIÓ LIMPIO' if not fallos else f'\n{len(fallos)} FALLO(S)')
    return 1 if fallos else 0


if __name__ == '__main__':
    sys.exit(main())
