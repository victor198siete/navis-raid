"""El pizarrón de costo: lo que la oficina muestra de la cuota (medidor de la cabecera y modal "Costo").

Junta tres cosas, todas desde la bitácora y las lecturas de `cuota.py` (solo lectura, cero tokens):
  A · Cuota   por ventana (semanal, Fable, 5 h): lo leído, el estimado de ahora, el ritmo y el cierre proyectado.
  B · Quién   gasta: las 8 sesiones que más pesan desde el reinicio semanal y hoy, en % de la cuota semanal
              (peso ÷ escala US$ por 1 %). El peso de los subagentes se suma a la sesión madre y se separa aparte.
  C · Fugas   desde el reinicio semanal, cada una con su % de la cuota: sesiones por encima del umbral de relevo,
              reanudaciones frías (pausa > 1 h con contexto ≥ 100K) y agentes en Opus fuera de regla.

`resumen()` se calcula como mucho una vez por minuto (memo por tiempo en el proceso): `estado.json` se regenera
cada 5 s y el cálculo no cambia en ese lapso. Las fechas salen en ISO (UTC); el JS calcula el "hace cuánto".
La hora sale de `zona_horaria` del config (desfase fijo, sin horario de verano); sin zona, la hora local de la máquina.

Uso:
  python3 costo.py        imprime el resumen en JSON
"""
import datetime as dt
import json
import sys
import threading
import time

import bitacora
import config
import cuota
import textos

UTC = dt.timezone.utc
_Z = config.zona()
ZONA = dt.timezone(dt.timedelta(hours=_Z[0]), _Z[1]) if _Z else None   # None: hora local de la máquina
MEMO_S = 60                     # el bloque no se recalcula antes
TOP = 8                         # sesiones en "quién gasta"
FRIA_S = config.valor('ttl_cache_s')   # pausa tras la que la caché expiró (TTL)
UMBRAL_K = config.valor('umbral_relevo_k')   # relevo de sesión
FRIA_CTX = 100_000              # por debajo, reescribir la caché no es una fuga que importe
SIN_REGLA_OPUS = set(config.valor('agentes_con_opus_permitido'))   # tipos de agente a los que se permite Opus
DIAS = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom'] if textos.idioma() == 'es' else ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
MESES = (['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'] if textos.idioma() == 'es'
         else ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'])   # por idioma; mar es martes y marzo, por eso no pasan por t()

_memo = {'t': 0.0, 'valor': None}
_candado = threading.Lock()


def _local(t):
    """datetime → hora de la zona configurada redondeada al minuto (el reinicio llega como 10:59:59 y se dice 06:00)."""
    return (t + dt.timedelta(seconds=30)).astimezone(ZONA)


def _dia_hora(t):
    t = _local(t)
    return f'{DIAS[t.weekday()]} {t:%H:%M}'


def _fecha_hora(t):
    t = _local(t)
    return f'{t.day} {MESES[t.month - 1]} {t:%H:%M}'


def _r(x, n=1):
    return None if x is None else round(x, n)


# ---------- A · cuota ----------

def _ventana(clave, ahora):
    r = cuota.proyeccion(clave)
    if not r:
        return None
    l = r['lectura']
    v = {'etiqueta': l['etiqueta'], 'leido': l['pct'], 'leido_t': l['hora'], 'leido_txt': _fecha_hora(bitacora._ts(l['hora'])), 'fuente': l['fuente'],
         'reinicio_t': r['reinicio'].isoformat(), 'reinicio': _dia_hora(r['reinicio']),
         'escala': _r(r['escala_usd_pct'], 3)}
    if r.get('estimado') is not None:
        v.update(estimado=_r(r['estimado']), ritmo_dia=_r(r['ritmo_pct_h'] * 24), cierre=_r(r['cierre']), horas=_r(r['horas']))
    else:
        v['vieja'] = r['reinicio'] <= ahora          # la lectura es de una semana ya cerrada
    return v


def _cinco_horas(ahora):
    lecturas = [l for l in bitacora.leer_cuota() if l.get('ventana') == '5h']
    if not lecturas:
        return None
    l = lecturas[-1]
    fin = bitacora._ts(l['resetsAt'])
    return {'etiqueta': l['etiqueta'], 'leido': l['pct'], 'leido_t': l['hora'], 'leido_txt': _fecha_hora(bitacora._ts(l['hora'])), 'fuente': l['fuente'],
            'reinicio_t': fin.isoformat(), 'reinicio': _fecha_hora(fin), 'vieja': fin <= ahora}


# ---------- B y C · una sola pasada por lo que va de la semana ----------

def _pasada(ahora, umbral_k):
    ini = bitacora.reinicio_semanal() - dt.timedelta(days=7)
    hoy = ahora.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)      # día local de la máquina
    ses = {}
    frias = {'n': 0, 'usd': 0.0}
    opus = {'n': 0, 'usd': 0.0, 'tipos': {}}
    for e in bitacora.leer(ini, ahora):
        p = bitacora.peso(e)
        if not p:
            continue
        s = ses.setdefault(e['cli'], {'titulo': '', 'proyecto': '', 'sem': 0.0, 'sem_ag': 0.0, 'hoy': 0.0, 'hoy_ag': 0.0,
                                      'sobre': 0.0, 'fria_n': 0, 'fria': 0.0})
        if e.get('titulo'):
            s['titulo'] = e['titulo']
        s['proyecto'] = e.get('proyecto') or s['proyecto']
        ag = e.get('agente')
        s['sem'] += p                                  # `sem` y `hoy` ya incluyen a los agentes
        if ag:
            s['sem_ag'] += p
        if e['_t'] >= hoy:
            s['hoy'] += p
            if ag:
                s['hoy_ag'] += p
        if not ag and e.get('ctx', 0) >= umbral_k * 1000:
            s['sobre'] += p
        pausa = e.get('pausa')
        if pausa is not None and pausa > FRIA_S and e.get('ctx', 0) >= FRIA_CTX:
            s['fria_n'] += 1
            s['fria'] += p
            frias['n'] += 1
            frias['usd'] += p
        if ag and 'opus' in (e.get('modelo') or '') and (ag.get('tipo') or '?') not in SIN_REGLA_OPUS:
            t = opus['tipos'].setdefault(ag.get('tipo') or '?', {'n': 0, 'usd': 0.0})
            t['n'] += 1; t['usd'] += p
            opus['n'] += 1; opus['usd'] += p
    return ses, frias, opus


def _pct(usd, escala):
    return _r(usd / escala) if escala else None


PREFIJOS = tuple(config.valor('prefijos_proyecto'))   # en este orden; el primero que coincide se quita


def _nombre_proyecto(carpeta):
    """Con los prefijos del config: `Apps-mi-app` → `mi-app`; `Tools-notas` → `notas`;
    lo que no empieza por ninguno (la carpeta raíz, `Tools`) queda igual."""
    c = carpeta or '?'
    for pre in PREFIJOS:
        if pre and c.startswith(pre):
            return c[len(pre):]
    return c


def _quien(ses, clave, escala):
    """Por proyecto (decisión del autor, 22 oct): una fila por carpeta, con sus sesiones dentro."""
    grupos = {}
    for c, s in ses.items():
        if s[clave] <= 0:
            continue
        g = grupos.setdefault(_nombre_proyecto(s['proyecto']), {'usd': 0.0, 'ag': 0.0, 'sesiones': []})
        g['usd'] += s[clave]; g['ag'] += s[clave + '_ag']
        g['sesiones'].append({'cli': c, 'titulo': s['titulo'] or c[:8], 'pct': _pct(s[clave], escala), 'usd': _r(s[clave], 2)})
    filas = sorted(grupos.items(), key=lambda kv: -kv[1]['usd'])[:TOP]
    return [{'proyecto': n, 'titulo': n, 'usd': _r(g['usd'], 2), 'pct': _pct(g['usd'], escala), 'agentes_pct': _pct(g['ag'], escala),
             'sesiones': sorted(g['sesiones'], key=lambda x: -x['usd'])} for n, g in filas]


def _fugas(ses, frias, opus, escala, umbral_k):
    sobre = sorted(((c, s) for c, s in ses.items() if s['sobre'] > 0), key=lambda kv: -kv[1]['sobre'])
    fr = sorted(((c, s) for c, s in ses.items() if s['fria_n']), key=lambda kv: -kv[1]['fria'])[:3]
    tipos = sorted(opus['tipos'].items(), key=lambda kv: -kv[1]['usd'])
    return {
        # todas las sesiones con llamadas por encima del umbral; el JS deja las vivas (D.sesiones, contexto_k)
        'sobre_umbral': [{'cli': c, 'titulo': s['titulo'], 'proyecto': s['proyecto'], 'pct': _pct(s['sobre'], escala), 'usd': _r(s['sobre'], 2)} for c, s in sobre],
        'frias': {'n': frias['n'], 'pct': _pct(frias['usd'], escala), 'usd': _r(frias['usd'], 2),
                  'top': [{'cli': c, 'titulo': s['titulo'], 'proyecto': s['proyecto'], 'n': s['fria_n'], 'pct': _pct(s['fria'], escala)} for c, s in fr]},
        'opus': {'n': opus['n'], 'pct': _pct(opus['usd'], escala), 'usd': _r(opus['usd'], 2),
                 'tipos': [{'tipo': k, 'n': t['n'], 'pct': _pct(t['usd'], escala)} for k, t in tipos]},
    }


def calcular(umbral_k=UMBRAL_K):
    ahora = dt.datetime.now(UTC)
    ventanas = {'semanal': _ventana('semanal', ahora), 'fable': _ventana('semanal-fable', ahora), '5h': _cinco_horas(ahora)}
    escala = (ventanas['semanal'] or {}).get('escala')
    ses, frias, opus = _pasada(ahora, umbral_k)
    return {
        'generado': ahora.isoformat(timespec='seconds'), 'umbral_k': umbral_k, 'escala': escala,
        'semana_desde': (bitacora.reinicio_semanal() - dt.timedelta(days=7)).isoformat(),
        'ventanas': ventanas,
        'quien': {'semana': _quien(ses, 'sem', escala), 'hoy': _quien(ses, 'hoy', escala),
                  'total_semana': _pct(sum(s['sem'] for s in ses.values()), escala),
                  'total_hoy': _pct(sum(s['hoy'] for s in ses.values()), escala)},
        'fugas': _fugas(ses, frias, opus, escala, umbral_k),
    }


def resumen(umbral_k=UMBRAL_K, memo=True):
    """El bloque `costo` de estado.json. Memo de MEMO_S segundos; None si falla (la oficina no se cae por esto)."""
    with _candado:
        if memo and _memo['valor'] is not None and time.time() - _memo['t'] < MEMO_S:
            return _memo['valor']
        try:
            valor = calcular(umbral_k)
        except Exception as e:                      # un extra: nunca tumba la oficina
            print('costo:', e, file=sys.stderr)
            return _memo['valor']                   # el último bueno, o None
        _memo.update(t=time.time(), valor=valor)
        return valor


if __name__ == '__main__':
    t0 = time.time()
    print(json.dumps(calcular(), ensure_ascii=False, indent=1))
    print(f'{(time.time() - t0) * 1000:.0f} ms', file=sys.stderr)
