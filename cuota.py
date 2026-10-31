"""Lecturas reales de la cuota del plan (B1) y la proyección que sale de calibrar la bitácora con ellas.

Las lecturas las da `mcp__ccd_session_mgmt__get_usage`, que solo puede llamar una sesión de Claude. La sesión
central la llama al abrir (`/handoff`), al cerrar (`/checkpoint`) y al recibir un mensaje de la oficina, y le pasa
a este script el JSON tal cual por la entrada estándar.

Calibración: cada lectura semanal fija la escala US$ (a precio de API, ver `bitacora.PRECIOS`) → 1 % de la semana,
como el peso de la bitácora desde el inicio de la semana dividido entre el % leído. Entre lecturas, el % se estima
sumando el peso nuevo con esa escala, y el cierre se proyecta al ritmo de las últimas 24 h.

Uso:
  python3 cuota.py anotar --fuente handoff < usage.json     anota la lectura y muestra la proyección
  python3 cuota.py                                         muestra la proyección con la última lectura
"""
import datetime as dt
import json
import os
import sys

import bitacora

UTC = dt.timezone.utc
VENTANAS = {'semanal': lambda m: True, 'semanal-fable': lambda m: 'fable' in m or 'mythos' in m}
RITMO_H = 24
MIN_PCT = 3                     # por debajo, la escala sale demasiado ruidosa


def ventana(etiqueta):
    e = etiqueta.lower()
    if '5-hour' in e or '5 h' in e:
        return '5h'
    if 'all models' in e:
        return 'semanal'
    if 'fable' in e:
        return 'semanal-fable'
    return e


def anotar(datos, fuente):
    plan = datos.get('plan', datos)
    if plan.get('status') not in (None, 'ok'):
        sys.exit(f"get_usage no dio lecturas: {plan.get('status')} {plan.get('note') or ''}".strip())
    hora = dt.datetime.now(UTC).isoformat(timespec='seconds')
    lineas = [{'hora': hora, 'fuente': fuente, 'ventana': ventana(w['label']), 'etiqueta': w['label'],
               'pct': w['percentUsed'], 'resetsAt': w['resetsAt']} for w in plan.get('windows', [])]
    if not lineas:
        sys.exit('el JSON no trae plan.windows')
    os.makedirs(bitacora.DIR, exist_ok=True)
    with open(bitacora.CUOTA, 'a') as fh:
        fh.writelines(json.dumps(l, ensure_ascii=False) + '\n' for l in lineas)
    return lineas


def suma(entradas, filtro):
    total = 0.0
    for e in entradas:
        p = bitacora.peso(e) if filtro(e.get('modelo') or '') else None
        total += p or 0
    return total


def proyeccion(clave):
    """Estimación de una ventana semanal: dict con la última lectura, la escala y la proyección; None sin lecturas."""
    filtro = VENTANAS[clave]
    lecturas = [l for l in bitacora.leer_cuota() if l.get('ventana') == clave]
    if not lecturas:
        return None
    ahora = dt.datetime.now(UTC)
    ultima = lecturas[-1]
    t_ult = bitacora._ts(ultima['hora'])
    fin = bitacora._ts(ultima['resetsAt'])
    # la escala, de la lectura más reciente con % suficiente (de esta semana o de una anterior)
    escala = None
    for l in reversed(lecturas):
        if l['pct'] >= MIN_PCT:
            reinicio = bitacora._ts(l['resetsAt'])
            usd = suma(bitacora.leer(reinicio - dt.timedelta(days=7), bitacora._ts(l['hora'])), filtro)
            if usd > 0:
                escala = usd / l['pct']
                break
    r = {'ventana': clave, 'lectura': ultima, 'escala_usd_pct': escala, 'reinicio': fin}
    if escala is None or fin <= ahora:
        return r                                   # sin escala, o la lectura es de una semana ya cerrada
    desde_lectura = suma(bitacora.leer(t_ult, ahora), filtro)
    ritmo = suma(bitacora.leer(ahora - dt.timedelta(hours=RITMO_H), ahora), filtro) / RITMO_H   # US$ por hora
    estimado = ultima['pct'] + desde_lectura / escala
    horas = (fin - ahora).total_seconds() / 3600
    r.update(estimado=estimado, ritmo_pct_h=ritmo / escala, horas=horas, cierre=estimado + ritmo * horas / escala)
    return r


def mostrar():
    bitacora.actualizar()
    vistas = False
    for clave in VENTANAS:
        r = proyeccion(clave)
        if not r:
            continue
        vistas = True
        l = r['lectura']
        hace = (dt.datetime.now(UTC) - bitacora._ts(l['hora'])).total_seconds() / 60
        print(f"{l['etiqueta']}: {l['pct']} % leído hace {hace:.0f} min ({l['fuente']})", end='')
        if r.get('estimado') is None:
            print(' · sin escala todavía' if r['escala_usd_pct'] is None else ' · semana ya cerrada')
            continue
        print(f" · ahora ≈{r['estimado']:.0f} % · ritmo {r['ritmo_pct_h'] * 24:.1f} %/día"
              f" · al reinicio ({r['horas']:.0f} h) ≈{r['cierre']:.0f} %"
              f" · escala {r['escala_usd_pct']:.2f} US$ API por 1 %")
    if not vistas:
        print('sin lecturas: anotar una con `cuota.py anotar --fuente <origen> < usage.json`')


if __name__ == '__main__':
    args = sys.argv[1:]
    if args[:1] == ['anotar']:
        fuente = args[args.index('--fuente') + 1] if '--fuente' in args else 'manual'
        anotar(json.load(sys.stdin), fuente)
    mostrar()
