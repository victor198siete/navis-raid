#!/usr/bin/env python3
"""Respuesta de la sesión central al chat de la oficina.

Uso:
    python3 responder.py "texto de la respuesta"
    echo "texto" | python3 responder.py
    python3 responder.py --datos <carpeta> "texto"    (la carpeta de datos de la oficina, si no es la del código)

Anota {cuando, de: claude-agent, texto} en chat/hilo.jsonl de la carpeta de datos: la que dice `--datos`, si no
`$NAVIS_RAID_DATA`, y si tampoco, la carpeta de este archivo (la misma regla que `config.DATOS`). La oficina lo lee
en su siguiente refresco y lo teclea en la caja de diálogo; también sale en la pestaña Chat y en el tablón. Solo texto.
"""
import datetime as dt
import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
DE = 'claude-agent'


def carpeta_de_datos(argv):
    """(carpeta de datos, argumentos restantes). `--datos <carpeta>` manda; si no, `config.DATOS`."""
    args = list(argv)
    if args and args[0] == '--datos':
        if len(args) < 2 or not args[1].strip():
            sys.exit('--datos necesita la carpeta de datos de la oficina')
        return os.path.abspath(os.path.expanduser(args[1].strip())), args[2:]
    sys.path.insert(0, AQUI)
    import config
    return config.DATOS, args


def main():
    datos, args = carpeta_de_datos(sys.argv[1:])
    texto = ' '.join(args).strip() or (sys.stdin.read().strip() if not sys.stdin.isatty() else '')
    if not texto:
        sys.exit('falta el texto de la respuesta')
    os.makedirs(os.path.join(datos, 'chat'), exist_ok=True)
    with open(os.path.join(datos, 'chat', 'hilo.jsonl'), 'a') as fh:
        fh.write(json.dumps({'cuando': dt.datetime.now(dt.timezone.utc).isoformat(), 'de': DE, 'texto': texto},
                            ensure_ascii=False) + '\n')
    print(f'anotado en el hilo de la oficina ({len(texto)} caracteres)')


if __name__ == '__main__':
    main()
