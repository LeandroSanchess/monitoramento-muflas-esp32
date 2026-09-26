#!/bin/zsh

PASTA_APP="$(cd "$(dirname "$0")" && pwd)"
cd "$PASTA_APP" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 não foi encontrado. Instale Python 3 e tente novamente."
  read -r "?Pressione Enter para fechar."
  exit 1
fi

python3 monitoramento_gui.py

if [ "$?" -ne 0 ]; then
  echo
  echo "Não foi possível abrir o aplicativo."
  echo "Instale as dependências com: python3 -m pip install -r requirements.txt"
  read -r "?Pressione Enter para fechar."
fi
