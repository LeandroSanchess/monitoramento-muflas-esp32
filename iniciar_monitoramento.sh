#!/usr/bin/env sh

PASTA_APP=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$PASTA_APP" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 não foi encontrado. Instale Python 3 e tente novamente."
  exit 1
fi

exec python3 monitoramento_gui.py
