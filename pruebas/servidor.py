"""Prueba del servidor (E6): `--serve` solo entrega la página y su estado, solo a quien le habla por localhost, y el
`POST /chat` exige token. Con `chat_sesion: null` el chat no existe.

Levanta `oficina.servidor(0, token)` en este mismo proceso, en un hilo y en un puerto libre (si el sandbox no deja abrir
puertos, la misma clase de servidor atiende las peticiones por un `socketpair`: mismo manejador, mismos encabezados). NUNCA manda texto real a una
sesión: `oficina.chat_enviar` y `oficina.chat_anotar` se sustituyen por funciones de prueba que solo registran la llamada
(así `chat/hilo.jsonl` tampoco se toca). Los GET de `/` y `/estado.json` llaman a `generar()`, que escribe `index.html` y
`estado.json` y pone la bitácora al día con la configuración real: es lo que hace el servidor de verdad.

Comprueba:
  1. `Host` ajeno (o con otro puerto) → 403, en GET y en POST;
  2. todo lo que no está en la lista blanca → 404 (config.json, bitacora/, chat/hilo.jsonl, oficina.py, encargos/,
     fuentes/../config.json, rutas con %2e%2e); `/estado.json?123` y `/` → 200; el token va en `/`, no en `estado.json`
     ni en el `index.html` de disco; `/fuentes/x.woff2` solo si existe;
  3. `POST /chat`: sin token, con token malo, con `Origin` ajeno o con `Content-Type: text/plain` → 403 y la función de
     prueba no se llama; con token, `Host` y `Origin` correctos → 200 y la función de prueba recibe el texto;
     sin `Origin` (curl) también pasa; el servidor no responde `OPTIONS` ni manda `Access-Control-Allow-*`;
  4. (subproceso, `NAVIS_RAID_CONFIG` con `chat_sesion: null`) `POST /chat` → 404 aun con token bueno; la pasada de
     `recoger()` y `datos_vivos()` no toca `chat_destino()`, `sockets_en()` ni `chat_enviar()`; el tablón no trae
     mensajes del chat; el pie no lo menciona.

  5. (E8e-2b) `POST /salida` detiene el servidor: sin token, con token malo, con `Origin` ajeno, con `Content-Type: text/plain`
     o con `Host` ajeno → 403 y el servidor sigue respondiendo; con todo correcto → 200 y `serve_forever` vuelve en menos
     de 5 s; con `chat_sesion: null` la ruta existe (200) y `POST /chat` sigue en 404; `main(['--serve', '0'])` en un
     subproceso sale con código 0 tras `POST /salida` (por TCP si el sandbox deja hacer bind; si no, por socketpair).

Uso: python3 pruebas/servidor.py
"""
import http.client
import http.server
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = 'token-de-prueba-0123456789'
MARCA = 'meta name="navis-raid-token"'

def levantar(oficina, token):
    """Levanta el servidor de la oficina. Devuelve (servidor, puerto, conectar, parar, modo): `conectar()` da una
    HTTPConnection lista; `modo` es 'tcp' o 'socketpair' (cuando el sandbox no deja hacer bind)."""
    try:
        srv = oficina.servidor(0, token)
    except PermissionError:                               # sin permiso para abrir puertos: el mismo manejador, sin red
        http.server.ThreadingHTTPServer.server_bind = lambda self: None
        http.server.ThreadingHTTPServer.server_activate = lambda self: None
        srv = oficina.servidor(0, token)
        puerto = 40000 + os.getpid() % 20000              # solo un número para los encabezados Host y Origin
        srv.server_address = ('127.0.0.1', puerto)

        def conectar():
            cliente, lado_servidor = socket.socketpair()

            def servir():
                try:
                    srv.finish_request(lado_servidor, ('127.0.0.1', 1))
                finally:
                    lado_servidor.close()
            threading.Thread(target=servir, daemon=True).start()
            c = http.client.HTTPConnection('127.0.0.1', puerto, timeout=60)
            c.sock = cliente
            return c
        return srv, puerto, conectar, srv.server_close, 'socketpair'
    puerto = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def parar():
        srv.shutdown()
        srv.server_close()
    return srv, puerto, lambda: http.client.HTTPConnection('127.0.0.1', puerto, timeout=60), parar, 'tcp'


# Subproceso del caso 4: el mismo servidor, con un config sin chat. Imprime un JSON con lo observado.
CODIGO_SIN_CHAT = r'''
import json, os, sys, tempfile
sys.path[:0] = [%r, %r]
import oficina, servidor as prueba
llamadas = []
def espia(nombre):
    def f(*a, **kw):
        llamadas.append(nombre)
        return 0, 'prueba'
    return f
for n in ('chat_destino', 'sockets_en', 'chat_enviar', 'chat_anotar'):
    setattr(oficina, n, espia(n))
tmp = tempfile.mkdtemp(prefix='raid-hilo-')
hilo = os.path.join(tmp, 'hilo.jsonl')
with open(hilo, 'w') as fh:
    fh.write(json.dumps({'cuando': oficina.ahora().isoformat(), 'de': 'usuario', 'texto': 'mensaje-del-hilo'}) + '\n')
oficina.CHAT_HILO = hilo
sesiones, eventos = oficina.recoger()
datos = oficina.datos_vivos(sesiones, eventos)
pagina = oficina.render_pixel([], [], 0)
srv, puerto, conectar, parar, modo = prueba.levantar(oficina, 'tok')
c = conectar()
c.request('POST', '/chat', body=json.dumps({'texto': 'hola'}),
          headers={'Host': '127.0.0.1:%%d' %% puerto, 'Content-Type': 'application/json', 'X-Navis-Raid-Token': 'tok',
                   'Origin': 'http://127.0.0.1:%%d' %% puerto})
codigo = c.getresponse().status
parar()
print(json.dumps({'codigo': codigo, 'llamadas': llamadas, 'chat': datos['chat'],
                  'en_tablon': [e for e in eventos if e[2] == 'chat' or 'mensaje-del-hilo' in e[3]],
                  'pie_menciona': 'salvo lo que hables' in pagina}))
''' % (AQUI, os.path.join(AQUI, 'pruebas'))


def main():
    fallos = []

    def comprobar(ok, texto):
        print(('✓ ' if ok else '✗ ') + texto)
        if not ok:
            fallos.append(texto)

    sys.path.insert(0, AQUI)
    import oficina
    if not hasattr(oficina, 'servidor'):
        comprobar(False, 'oficina.servidor(puerto, token) existe (el servidor vive aparte de main() para poder probarlo)')
        return fallos

    # el chat de la prueba: nada sale de aquí
    enviados, anotados = [], []
    oficina.chat_enviar = lambda texto: (enviados.append(texto), (1, None))[1]
    oficina.chat_anotar = lambda de, texto: anotados.append((de, texto))
    if not oficina.CHAT_SESION:
        oficina.CHAT_SESION = 'sesion-de-prueba'          # el config de quien corre esto puede no tener chat: el caso 4 cubre ese

    srv, puerto, conectar, parar, modo = levantar(oficina, TOKEN)
    print(f'(servidor de prueba por {modo}, puerto {puerto})')
    yo = f'127.0.0.1:{puerto}'
    origen = f'http://{yo}'

    def pedir(metodo, ruta, host=None, cabeceras=None, cuerpo=None):
        c = conectar()
        h = {'Host': host or yo}
        h.update(cabeceras or {})
        c.request(metodo, ruta, body=cuerpo, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data, r

    try:
        # 1 · Host
        for metodo, ruta in (('GET', '/estado.json'), ('GET', '/'), ('POST', '/chat')):
            for host in ('evil.example', f'evil.example:{puerto}', f'127.0.0.1:{puerto + 1}', '127.0.0.1', ''):
                cab = {'Content-Type': 'application/json', 'X-Navis-Raid-Token': TOKEN} if metodo == 'POST' else None
                c = conectar()
                c.putrequest(metodo, ruta, skip_host=True)
                if host:
                    c.putheader('Host', host)
                for k, v in (cab or {}).items():
                    c.putheader(k, v)
                c.putheader('Content-Length', '15' if metodo == 'POST' else '0')
                c.endheaders(b'{"texto": "hi"}' if metodo == 'POST' else None)
                st = c.getresponse().status
                c.close()
                comprobar(st == 403, f'{metodo} {ruta} con Host «{host}» → 403 (fue {st})')
        for host in (f'localhost:{puerto}', f'[::1]:{puerto}'):
            st, _, _ = pedir('GET', '/estado.json?1', host=host)
            comprobar(st == 200, f'GET /estado.json con Host «{host}» → 200 (fue {st})')

        # 2 · lista blanca
        for ruta in ('/config.json', '/bitacora/', '/bitacora', '/chat/hilo.jsonl', '/oficina.py', '/encargos/', '/',
                     '/fuentes/../config.json', '/fuentes/%2e%2e/config.json', '/fuentes/', '/fuentes/no-existe.woff2',
                     '/fuentes/x.woff2/../../config.json', '/%2e%2e/oficina.py', '/estado.json/../config.json',
                     '/index.html/../config.json', '//config.json', '/pruebas/servidor.py', '/.git/config'):
            if ruta == '/':
                continue
            st, cuerpo, _ = pedir('GET', ruta)
            comprobar(st == 404, f'GET {ruta} → 404 (fue {st})')
            comprobar(b'"nombre_usuario"' not in cuerpo and b'def servidor' not in cuerpo, f'GET {ruta} no entrega contenido propio')
        st, cuerpo_estado, r = pedir('GET', '/estado.json?123')
        comprobar(st == 200 and json.loads(cuerpo_estado).get('sesiones') is not None, f'GET /estado.json?123 → 200 con JSON (fue {st})')
        comprobar(r.getheader('Content-Type', '').startswith('application/json'), 'estado.json sale como application/json')
        comprobar(TOKEN.encode() not in cuerpo_estado, 'el token NO va en estado.json')
        for ruta in ('/', '/index.html'):
            st, cuerpo, r = pedir('GET', ruta)
            comprobar(st == 200 and b'<title>Navis Raid</title>' in cuerpo, f'GET {ruta} → 200, la página (fue {st})')
            comprobar(f'{MARCA} content="{TOKEN}"'.encode() in cuerpo, f'GET {ruta} lleva el token en el <meta>')
            comprobar(r.getheader('Content-Type', '').startswith('text/html'), f'{ruta} sale como text/html')
            comprobar(r.getheader('X-Frame-Options') == 'DENY' and "frame-ancestors 'none'" in (r.getheader('Content-Security-Policy') or ''),
                      f'{ruta} no se deja meter en un iframe (X-Frame-Options y frame-ancestors; auditoría F-001)')
        with open(os.path.join(AQUI, 'index.html'), 'rb') as fh:
            comprobar(TOKEN.encode() not in fh.read(), 'el index.html de disco NO lleva el token (solo la página servida)')
        st, cuerpo, _ = pedir('GET', '/tabla.html')
        comprobar(st == 200 and b'<html' in cuerpo, f'GET /tabla.html → 200 (fue {st})')
        # fuentes: solo si existe; se crea una de prueba y se borra
        carpeta = os.path.join(AQUI, 'fuentes')
        existia = os.path.isdir(carpeta)
        os.makedirs(carpeta, exist_ok=True)
        prueba = os.path.join(carpeta, 'prueba-e6.woff2')
        try:
            with open(prueba, 'wb') as fh:
                fh.write(b'wOF2-de-prueba')
            st, cuerpo, r = pedir('GET', '/fuentes/prueba-e6.woff2')
            comprobar(st == 200 and cuerpo == b'wOF2-de-prueba' and r.getheader('Content-Type') == 'font/woff2',
                      f'GET /fuentes/prueba-e6.woff2 → 200 como font/woff2 (fue {st})')
            st, _, _ = pedir('GET', '/fuentes/prueba-e6.txt')
            comprobar(st == 404, f'GET /fuentes/<otra extensión> → 404 (fue {st})')
        finally:
            if os.path.exists(prueba):
                os.remove(prueba)
            if not existia:
                os.rmdir(carpeta)

        # 3 · POST /chat
        ok_cab = {'Content-Type': 'application/json', 'X-Navis-Raid-Token': TOKEN, 'Origin': origen}
        cuerpo = json.dumps({'texto': 'hola desde la prueba'})

        def malo(nombre, cab, esperado=403, host=None):
            antes = len(enviados)
            st, _, r = pedir('POST', '/chat', host=host, cabeceras=cab, cuerpo=cuerpo)
            comprobar(st == esperado and len(enviados) == antes, f'POST /chat {nombre} → {esperado}, sin enviar (fue {st}, enviados {len(enviados) - antes})')
        malo('sin token', {k: v for k, v in ok_cab.items() if k != 'X-Navis-Raid-Token'})
        malo('con token malo', dict(ok_cab, **{'X-Navis-Raid-Token': TOKEN + 'x'}))
        malo('con token vacío', dict(ok_cab, **{'X-Navis-Raid-Token': ''}))
        malo('con token no ASCII', dict(ok_cab, **{'X-Navis-Raid-Token': 'ñandú'.encode('utf-8').decode('latin-1')}))
        malo('con Origin ajeno', dict(ok_cab, Origin='http://evil.example'))
        malo('con Origin de otro puerto', dict(ok_cab, Origin=f'http://127.0.0.1:{puerto + 1}'))
        malo('con Origin null', dict(ok_cab, Origin='null'))
        malo('con Content-Type text/plain', dict(ok_cab, **{'Content-Type': 'text/plain'}))
        malo('sin Content-Type', {k: v for k, v in ok_cab.items() if k != 'Content-Type'})
        malo('con Host ajeno', ok_cab, host='evil.example')
        st, _, r = pedir('POST', '/otra', cabeceras=ok_cab, cuerpo=cuerpo)
        comprobar(st == 404, f'POST /otra → 404 (fue {st})')

        st, datos, _ = pedir('POST', '/chat', cabeceras=ok_cab, cuerpo=cuerpo)
        comprobar(st == 200 and json.loads(datos).get('ok') is True, f'POST /chat con token, Host y Origin correctos → 200 (fue {st})')
        comprobar(enviados == ['hola desde la prueba'], f'la función de prueba recibió el texto ({enviados})')
        comprobar(anotados == [('usuario', 'hola desde la prueba')], f'y se anotó en el hilo (de prueba): {anotados}')
        st, _, _ = pedir('POST', '/chat', cabeceras={k: v for k, v in ok_cab.items() if k != 'Origin'}, cuerpo=cuerpo)
        comprobar(st == 200, f'POST /chat sin Origin (curl) con token → 200 (fue {st})')
        st, _, _ = pedir('POST', '/chat', cabeceras=dict(ok_cab, **{'Content-Type': 'application/json; charset=utf-8'}), cuerpo=cuerpo)
        comprobar(st == 200, f'POST /chat con «application/json; charset=utf-8» → 200 (fue {st})')
        st, _, _ = pedir('POST', '/chat', cabeceras=ok_cab, cuerpo=json.dumps({'texto': 'x' * 5000}))
        comprobar(st == 400, f'POST /chat con más de 4000 caracteres → 400 (fue {st})')
        antes = len(enviados)
        try:
            st, _, _ = pedir('POST', '/chat', cabeceras=ok_cab, cuerpo=json.dumps({'texto': 'x' * 100000}))
        except (BrokenPipeError, ConnectionResetError):
            st = 'conexión cortada'                       # el servidor no lee un cuerpo enorme: corta antes
        comprobar(st in (400, 413, 'conexión cortada') and len(enviados) == antes, f'POST /chat con un cuerpo enorme se rechaza sin enviar (fue {st})')

        # sin preflight ni CORS
        st, _, r = pedir('OPTIONS', '/chat', cabeceras={'Origin': 'http://evil.example', 'Access-Control-Request-Method': 'POST',
                                                        'Access-Control-Request-Headers': 'x-navis-raid-token'})
        comprobar(st >= 400 and r.getheader('Access-Control-Allow-Origin') is None, f'OPTIONS /chat no se autoriza (fue {st}, sin Access-Control-Allow-*)')
        for ruta in ('/estado.json', '/'):
            st, _, r = pedir('GET', ruta, cabeceras={'Origin': 'http://evil.example'})
            comprobar(not any(k.lower().startswith('access-control-') for k, _ in r.getheaders()), f'GET {ruta} no manda Access-Control-*')
    finally:
        parar()

    # 4 · sin chat_sesion: el chat no existe
    tmp = tempfile.mkdtemp(prefix='raid-servidor-')
    ruta = os.path.join(tmp, 'sin-chat.json')
    with open(ruta, 'w', encoding='utf-8') as fh:
        json.dump({'chat_sesion': None, 'idioma': 'es'}, fh)
    p = subprocess.run([sys.executable, '-c', CODIGO_SIN_CHAT], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180,
                       env=dict(os.environ, NAVIS_RAID_CONFIG=ruta))
    if p.returncode != 0:
        comprobar(False, 'sin chat_sesion: el subproceso corre (' + (p.stderr.strip().splitlines() or ['?'])[-1] + ')')
    else:
        r = json.loads(p.stdout.splitlines()[-1])
        comprobar(r['codigo'] == 404, f'sin chat_sesion: POST /chat con token bueno → 404 (fue {r["codigo"]})')
        comprobar(r['llamadas'] == [], f'sin chat_sesion: no se llamó a chat_destino/sockets_en/chat_enviar/chat_anotar ({r["llamadas"]})')
        comprobar(r['chat'] is None, 'sin chat_sesion: datos_vivos deja chat = null')
        comprobar(r['en_tablon'] == [], 'sin chat_sesion: el tablón no trae mensajes del chat')
        comprobar(r['pie_menciona'] is False, 'sin chat_sesion: el pie no menciona el chat')
    prueba_salida(comprobar)          # 5 · POST /salida (E8e-2b)
    return fallos


def levantar_vigilado(oficina, token):
    """`levantar(...)` más un `threading.Event` que se activa cuando `serve_forever` vuelve. En socketpair el servidor no
    tiene hilo propio (no hay socket de escucha): aquí se le pone uno, porque `shutdown()` solo vuelve si el bucle corre."""
    import types
    salio = threading.Event()

    primera = [True]

    def con_marca(puerto, tok):
        if primera[0] and http.server.ThreadingHTTPServer.server_bind.__name__ == '<lambda>':
            primera[0] = False         # una prueba anterior ya dejó el bind apagado: que levantar() tome su camino de socketpair
            raise PermissionError(1, 'bind apagado por una prueba anterior')
        primera[0] = False
        srv = oficina.servidor(puerto, tok)
        bucle = srv.serve_forever

        def envuelto(*a, **kw):
            try:
                return bucle(*a, **kw)
            finally:
                salio.set()
        srv.serve_forever = envuelto
        return srv
    srv, puerto, conectar, parar, modo = levantar(types.SimpleNamespace(servidor=con_marca), token)
    if modo == 'socketpair':
        threading.Thread(target=srv.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True).start()
    return srv, puerto, conectar, parar, modo, salio


def prueba_salida(comprobar):
    """Caso 5: POST /salida. Un servidor por escenario, porque el que sale bien se apaga."""
    import oficina
    cuerpo_ok = json.dumps({})

    def cliente(conectar, puerto, ruta, cab, cuerpo=cuerpo_ok, host=None):
        c = conectar()
        h = {'Host': host or f'127.0.0.1:{puerto}'}
        h.update(cab)
        c.request('POST' if cuerpo is not None else 'GET', ruta, body=cuerpo, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    # (a) lo rechazado deja el servidor vivo
    srv, puerto, conectar, parar, modo, salio = levantar_vigilado(oficina, TOKEN)
    try:
        origen = f'http://127.0.0.1:{puerto}'
        ok_cab = {'Content-Type': 'application/json', 'X-Navis-Raid-Token': TOKEN, 'Origin': origen}
        casos = (
            ('sin token', {k: v for k, v in ok_cab.items() if k != 'X-Navis-Raid-Token'}, None),
            ('con token malo', dict(ok_cab, **{'X-Navis-Raid-Token': TOKEN + 'x'}), None),
            ('con Origin ajeno', dict(ok_cab, Origin='http://evil.example'), None),
            ('con Content-Type text/plain', dict(ok_cab, **{'Content-Type': 'text/plain'}), None),
            ('con Host ajeno', ok_cab, 'evil.example'),
        )
        for nombre, cab, host in casos:
            st, _ = cliente(conectar, puerto, '/salida', cab, host=host)
            comprobar(st == 403, f'POST /salida {nombre} → 403 (fue {st})')
            st, _ = cliente(conectar, puerto, '/estado.json?1', {}, cuerpo=None)
            comprobar(st == 200 and not salio.is_set(), f'tras POST /salida {nombre} el servidor sigue respondiendo (GET → {st})')

        # (b) todo correcto: 200 y el bucle termina
        st, datos = cliente(conectar, puerto, '/salida', ok_cab)
        comprobar(st == 200 and json.loads(datos) == {'ok': True}, f'POST /salida con token, Host y Origin correctos → 200 {{"ok": true}} (fue {st} {datos!r})')
        comprobar(salio.wait(5), 'tras el 200, serve_forever vuelve en menos de 5 s')
    finally:
        parar()

    # (c) sin chat_sesion: /salida existe y /chat sigue en 404 (subproceso, como el caso 4)
    tmp = tempfile.mkdtemp(prefix='raid-salida-')
    cfg = os.path.join(tmp, 'sin-chat.json')
    with open(cfg, 'w', encoding='utf-8') as fh:
        json.dump({'chat_sesion': None, 'idioma': 'es'}, fh)
    p = subprocess.run([sys.executable, '-c', CODIGO_SALIDA_SIN_CHAT], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180,
                       env=dict(os.environ, NAVIS_RAID_CONFIG=cfg, NAVIS_RAID_DATA=tmp))
    if p.returncode != 0:
        comprobar(False, 'sin chat_sesion (salida): el subproceso corre (' + (p.stderr.strip().splitlines() or ['?'])[-1] + ')')
    else:
        r = json.loads(p.stdout.splitlines()[-1])
        comprobar(r['chat'] == 404, f'sin chat_sesion: POST /chat con token bueno → 404 (fue {r["chat"]})')
        comprobar(r['salida'] == 200 and r['cuerpo'] == {'ok': True}, f'sin chat_sesion: POST /salida con token bueno → 200 (fue {r["salida"]})')
        comprobar(r['salio'] is True, 'sin chat_sesion: tras POST /salida serve_forever vuelve en menos de 5 s')

    # (d) main(['--serve', '0']) sale con 0 tras POST /salida
    salida_main(comprobar)


# Subproceso (c): el mismo servidor con un config sin chat. Imprime un JSON con lo observado.
CODIGO_SALIDA_SIN_CHAT = r'''
import json, sys
sys.path[:0] = [%r, %r]
import oficina, servidor as prueba
srv, puerto, conectar, parar, modo, salio = prueba.levantar_vigilado(oficina, 'tok')
def post(ruta):
    c = conectar()
    c.request('POST', ruta, body='{}', headers={'Host': '127.0.0.1:%%d' %% puerto, 'Content-Type': 'application/json',
              'X-Navis-Raid-Token': 'tok', 'Origin': 'http://127.0.0.1:%%d' %% puerto})
    r = c.getresponse(); d = r.read(); c.close()
    return r.status, d
chat, _ = post('/chat')
salida, cuerpo = post('/salida')
ok = salio.wait(5)
parar()
print(json.dumps({'chat': chat, 'salida': salida, 'cuerpo': json.loads(cuerpo), 'salio': ok}))
''' % (AQUI, os.path.join(AQUI, 'pruebas'))


# Subproceso (d) cuando el sandbox no deja hacer bind: el mismo `main(['--serve', '0'])`, con el servidor atendido por
# socketpair; un hilo manda POST /salida y el proceso debe terminar con el código que devuelve main().
CODIGO_MAIN_SIN_BIND = r'''
import sys, threading
sys.path[:0] = [%r, %r]
import oficina, servidor as prueba
original = oficina.servidor
def servidor_de_prueba(puerto, token):
    # sin bind, levantar() cae a socketpair y no arranca ningún hilo de serve_forever: lo llama main()
    srv, p, conectar, parar, modo = prueba.levantar(type('O', (), {'servidor': staticmethod(original)}), token)
    def mandar():
        c = conectar()
        c.request('POST', '/salida', body='{}', headers={'Host': '127.0.0.1:%%d' %% p, 'Content-Type': 'application/json', 'X-Navis-Raid-Token': token})
        r = c.getresponse(); r.read(); c.close()
    threading.Timer(0.5, mandar).start()
    return srv
oficina.servidor = servidor_de_prueba
guardia = threading.Timer(15, lambda: (print('main() no salió en 15 s tras POST /salida', file=sys.stderr), __import__('os')._exit(97)))
guardia.daemon = True
guardia.start()
sys.exit(oficina.main(['--serve', '0']))
''' % (AQUI, os.path.join(AQUI, 'pruebas'))


def salida_main(comprobar):
    """`main(['--serve', '0'])` en un proceso aparte: tras `POST /salida` sale con código 0. Por TCP si el sandbox deja hacer
    bind; si no (PermissionError), la variante de socketpair de arriba, y lo dice."""
    import re
    import time
    tmp = tempfile.mkdtemp(prefix='raid-main-')
    cfg = os.path.join(tmp, 'sin-chat.json')
    with open(cfg, 'w', encoding='utf-8') as fh:
        json.dump({'chat_sesion': None, 'idioma': 'es'}, fh)
    vacio = os.path.join(tmp, 'claude')
    os.makedirs(vacio)
    env = dict(os.environ, NAVIS_RAID_CONFIG=cfg, NAVIS_RAID_DATA=os.path.join(tmp, 'datos'), CLAUDE_CONFIG_DIR=vacio,
               PYTHONUNBUFFERED='1')
    env.pop('NAVIS_RAID_SERVICIO', None)
    proc = subprocess.Popen([sys.executable, os.path.join(AQUI, 'oficina.py'), '--serve', '0'], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    try:
        fin = time.time() + 60
        linea = ''
        while time.time() < fin and proc.poll() is None and not linea:
            linea = proc.stdout.readline()
        m = re.search(r'localhost:(\d+)/', linea or '')
        if not m:
            err = proc.stderr.read() if proc.poll() is not None else ''
            if 'PermissionError' in err or 'Operation not permitted' in err:
                print('(sin permiso para hacer bind: main(--serve) se prueba con el servidor por socketpair)')
                p = subprocess.run([sys.executable, '-c', CODIGO_MAIN_SIN_BIND], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120, env=env)
                comprobar(p.returncode == 0, f'main([--serve, 0]) tras POST /salida sale con 0 (socketpair; código {p.returncode}'
                          + ('' if p.returncode == 0 else ': ' + (p.stderr.strip().splitlines() or ['?'])[-1]) + ')')
                return
            comprobar(False, 'main([--serve, 0]) imprime su dirección (' + (err.strip().splitlines() or ['sin salida'])[-1] + ')')
            return
        puerto = int(m.group(1))
        c = http.client.HTTPConnection('127.0.0.1', puerto, timeout=60)
        c.request('GET', '/', headers={'Host': f'127.0.0.1:{puerto}'})
        pagina = c.getresponse().read().decode('utf-8')
        c.close()
        tok = re.search(r'name="navis-raid-token" content="([^"]+)"', pagina).group(1)
        c = http.client.HTTPConnection('127.0.0.1', puerto, timeout=60)
        c.request('POST', '/salida', body='{}', headers={'Host': f'127.0.0.1:{puerto}', 'Content-Type': 'application/json', 'X-Navis-Raid-Token': tok})
        st = c.getresponse().status
        c.close()
        try:
            codigo = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            codigo = None
        comprobar(st == 200 and codigo == 0, f'main([--serve, 0]) tras POST /salida sale con 0 (TCP; POST → {st}, código {codigo})')
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        for f in (proc.stdout, proc.stderr):
            f.close()


if __name__ == '__main__':
    f = main()
    print()
    print('TODO EN VERDE' if not f else f'{len(f)} FALLOS')
    sys.exit(1 if f else 0)
