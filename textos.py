"""Los textos de Navis Raid en español o inglés, según `idioma` del config (`config.idioma()`).

Cómo se usa (estilo gettext): la clave es la frase en español tal cual, con {marcadores} para lo variable.
    from textos import t
    t('esperando a {agente}: {tarea}', agente=..., tarea=...)   → «esperando a qa: probar» / «waiting for qa: probar»
En español devuelve la frase; en inglés, su traducción de `textos_en.EN`, y si falta, el español. Sin argumentos no
formatea, así que un texto con llaves literales se queda como está. Los datos de la persona usuaria (títulos de sesión,
pedidos, nombres de grupo) no pasan por aquí. Los códigos internos (`trabajando`, `terminó`, `durmiendo`...) tampoco:
se traducen solo al mostrarlos.

Para el JS de la página (E4b): `para_js()` da el diccionario del idioma activo, o {} en español; sus claves viven en
`textos_en.EN_JS`, que la E4b rellena. Los textos hechos en Python no van ahí.

Vocabulario fijo del inglés (mantenerlo entre Python y JS):
    relevo → handoff            cubículo → desk             piso → floor              lobby → lobby
    sótano → basement           azotea → rooftop            encargo → task            bitácora → log
    cuota → quota               reanudación fría → cold resume
Inglés natural y corto: es interfaz, no una traducción palabra por palabra.

La prueba `pruebas/idiomas.py` exige que todo `t('…')` de los .py tenga entrada en EN con los mismos {marcadores}.
"""
import config
from textos_en import EN, EN_JS


def idioma():
    """'es' o 'en'."""
    return config.idioma()


def t(texto_es, **kw):
    """La frase en el idioma activo, con `.format(**kw)` si hay argumentos."""
    texto = EN.get(texto_es, texto_es) if idioma() == 'en' else texto_es
    return texto.format(**kw) if kw else texto


def para_js():
    """Las traducciones que necesita el JS de la página: el diccionario del inglés, o {} en español."""
    return dict(EN_JS) if idioma() == 'en' else {}
