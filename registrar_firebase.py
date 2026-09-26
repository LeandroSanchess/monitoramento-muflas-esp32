#!/usr/bin/env python3
"""Registra o ESP32 em CSV e publica uma copia no Firebase Realtime Database."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import queue
import re
import sys
import threading
import time
from typing import Any

try:
    import firebase_admin
    from firebase_admin import credentials, db
    import serial
    from serial.tools import list_ports
except ImportError as erro:
    print(
        "Dependencias ausentes. Instale com:\n"
        "python -m pip install -r requirements.txt\n"
        f"Detalhe: {erro}",
        file=sys.stderr,
    )
    raise SystemExit(2)


CABECALHO_ESP32_LEGADO = (
    "amostra;tempo_ms;tempo_s;temperatura_c;estado;dado_bruto_hex"
)
CABECALHO_ESP32 = CABECALHO_ESP32_LEGADO + ";status_hex"
CABECALHOS_ESP32 = {CABECALHO_ESP32_LEGADO, CABECALHO_ESP32}
CABECALHO_ARQUIVO = "data_hora_pc_iso8601;" + CABECALHO_ESP32
PADRAO_FORNO_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ESTADOS_COM_TEMPERATURA = {"OK", "SATURADO", "ALERTA_ACIMA_1000_C"}


class PublicadorFirebase:
    """Publica em thread separada para nunca bloquear o CSV serial."""

    def __init__(self, database_url: str, credencial: Path, forno_id: str) -> None:
        if not database_url.startswith("https://"):
            raise ValueError("firebase.database_url deve comecar com https://")
        if not PADRAO_FORNO_ID.fullmatch(forno_id):
            raise ValueError(
                "firebase.forno_id deve conter apenas letras, numeros, _ ou -"
            )
        if not credencial.is_file():
            raise FileNotFoundError(
                f"Credencial Firebase nao encontrada: {credencial}"
            )

        nome_app = f"registrador-{forno_id}-{id(self)}"
        cred = credentials.Certificate(str(credencial))
        self._app = firebase_admin.initialize_app(
            cred,
            {"databaseURL": database_url.rstrip("/")},
            name=nome_app,
        )
        self._referencia = db.reference(f"fornos/{forno_id}", app=self._app)
        self._fila: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        self._encerrar = threading.Event()
        self._online: bool | None = None
        self._ultimo_aviso = 0.0
        self._thread = threading.Thread(
            target=self._executar,
            name="publicador-firebase",
            daemon=True,
        )
        self._thread.start()

    def publicar(self, campos: list[str]) -> None:
        timestamp_ms = int(time.time() * 1000)
        payload: dict[str, Any] = {
            "amostra": int(campos[0]),
            "tempo_ms": int(campos[1]),
            "tempo_s": float(campos[2]),
            "temperatura_c": float(campos[3]) if campos[3] else None,
            "estado": campos[4],
            "dado_bruto_hex": campos[5],
            "status_hex": campos[6] if len(campos) > 6 else "",
            "timestamp_ms": timestamp_ms,
            "timestamp_iso": datetime.now().astimezone().isoformat(
                timespec="milliseconds"
            ),
        }

        # Em internet lenta, guarda somente a leitura mais recente. O historico
        # completo permanece no CSV local e a memoria nao cresce indefinidamente.
        try:
            self._fila.put_nowait(payload)
        except queue.Full:
            try:
                self._fila.get_nowait()
            except queue.Empty:
                pass
            try:
                self._fila.put_nowait(payload)
            except queue.Full:
                pass

    def fechar(self) -> None:
        self._encerrar.set()
        self._thread.join(timeout=3.0)
        if not self._thread.is_alive():
            firebase_admin.delete_app(self._app)

    def _executar(self) -> None:
        while not self._encerrar.is_set() or not self._fila.empty():
            try:
                payload = self._fila.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                chave = (
                    f"{payload['timestamp_ms']:013d}_"
                    f"{payload['amostra']:010d}"
                )
                # Uma unica operacao atualiza o valor corrente e o historico.
                self._referencia.update(
                    {
                        "atual": payload,
                        f"historico/{chave}": payload,
                    }
                )
                if self._online is not True:
                    print("INFO FIREBASE: conexao ativa.")
                self._online = True
            except Exception as erro:  # Mantem a aquisicao viva em qualquer falha remota.
                agora = time.monotonic()
                if self._online is not False or agora - self._ultimo_aviso >= 60.0:
                    print(
                        "AVISO FIREBASE: envio falhou; CSV local preservado "
                        f"({erro})."
                    )
                    self._ultimo_aviso = agora
                self._online = False


def argumentos() -> argparse.Namespace:
    pasta_script = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Registra o perfil da mufla em CSV e Firebase."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=pasta_script / "configuracao.json",
        help="Arquivo JSON de configuracao.",
    )
    parser.add_argument(
        "--porta",
        help="Sobrescreve a porta configurada, por exemplo COM5.",
    )
    parser.add_argument(
        "--saida",
        type=Path,
        help="Sobrescreve o caminho do arquivo CSV.",
    )
    parser.add_argument(
        "--somente-local",
        action="store_true",
        help="Grava somente o CSV, sem iniciar o Firebase.",
    )
    return parser.parse_args()


def carregar_configuracao(caminho: Path) -> tuple[dict[str, Any], Path]:
    caminho = caminho.expanduser().resolve()
    if not caminho.is_file():
        raise FileNotFoundError(
            f"Configuracao nao encontrada: {caminho}\n"
            "Copie configuracao.example.json para configuracao.json e edite-o."
        )
    try:
        conteudo = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as erro:
        raise ValueError(f"JSON de configuracao invalido: {erro}") from erro
    if not isinstance(conteudo, dict):
        raise ValueError("A raiz de configuracao.json deve ser um objeto JSON.")
    return conteudo, caminho.parent


def escolher_porta(porta_informada: str | None) -> str:
    if porta_informada:
        return porta_informada

    portas = sorted(list_ports.comports(), key=lambda item: item.device)
    if len(portas) == 1:
        print(f"Porta encontrada automaticamente: {portas[0].device}")
        return portas[0].device

    if not portas:
        print(
            "Nenhuma porta serial foi encontrada. Conecte o ESP32.",
            file=sys.stderr,
        )
    else:
        print("Mais de uma porta serial foi encontrada:", file=sys.stderr)
        for item in portas:
            descricao = item.description or "sem descricao"
            print(f"  {item.device} - {descricao}", file=sys.stderr)
        print("Informe a porta em configuracao.json ou com --porta.", file=sys.stderr)
    raise SystemExit(2)


def linha_de_dados_valida(linha: str) -> bool:
    campos = linha.split(";")
    if len(campos) not in (6, 7):
        return False
    try:
        amostra = int(campos[0])
        tempo_ms = int(campos[1])
        tempo_s = float(campos[2])
        if amostra < 0 or tempo_ms < 0 or not math.isfinite(tempo_s):
            return False
        if campos[3]:
            temperatura = float(campos[3])
            if not math.isfinite(temperatura):
                return False
        dado_bruto = int(campos[5], 16)
        if not 0 <= dado_bruto <= 0xFFFFFF:
            return False
        if len(campos) == 7 and campos[6]:
            status = int(campos[6], 16)
            if not 0 <= status <= 0xFF:
                return False
    except (ValueError, OverflowError):
        return False
    estado = campos[4]
    if not estado:
        return False
    return bool(campos[3]) == (estado in ESTADOS_COM_TEMPERATURA)


def normalizar_campos(linha: str) -> list[str]:
    """Acrescenta a coluna de status a linhas de firmwares antigos."""
    campos = linha.split(";")
    if len(campos) == 6:
        campos.append("")
    return campos


def preparar_parametros(
    opcoes: argparse.Namespace,
    config: dict[str, Any],
    pasta_config: Path,
) -> dict[str, Any]:
    serial_config = config.get("serial", {})
    arquivo_config = config.get("arquivo", {})
    firebase_config = config.get("firebase", {})
    if not all(
        isinstance(item, dict)
        for item in (serial_config, arquivo_config, firebase_config)
    ):
        raise ValueError("As secoes serial, arquivo e firebase devem ser objetos.")

    porta_config = str(serial_config.get("porta", "")).strip() or None
    porta = escolher_porta(opcoes.porta or porta_config)
    baud = int(serial_config.get("baud", 115200))
    if baud <= 0:
        raise ValueError("serial.baud deve ser positivo.")

    if opcoes.saida:
        saida = opcoes.saida.expanduser().resolve()
    else:
        pasta_dados = Path(str(arquivo_config.get("pasta", "dados")))
        if not pasta_dados.is_absolute():
            pasta_dados = pasta_config / pasta_dados
        instante = datetime.now().strftime("%Y%m%d_%H%M%S")
        saida = pasta_dados / f"perfil_forno_{instante}.csv"

    resultado: dict[str, Any] = {
        "porta": porta,
        "baud": baud,
        "saida": saida,
        "firebase": None,
    }

    if not opcoes.somente_local:
        database_url = str(firebase_config.get("database_url", "")).strip()
        credencial = Path(str(firebase_config.get("credencial", "")))
        if not credencial.is_absolute():
            credencial = pasta_config / credencial
        forno_id = str(firebase_config.get("forno_id", "mufla-01")).strip()
        intervalo = float(firebase_config.get("intervalo_segundos", 15))
        if intervalo < 1.0:
            raise ValueError("firebase.intervalo_segundos deve ser pelo menos 1.")
        resultado["firebase"] = {
            "database_url": database_url,
            "credencial": credencial.resolve(),
            "forno_id": forno_id,
            "intervalo": intervalo,
        }

    return resultado


def registrar(parametros: dict[str, Any]) -> None:
    destino: Path = parametros["saida"]
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        raise FileExistsError(f"O arquivo nao sera sobrescrito: {destino}")

    publicador = None
    firebase_config = parametros["firebase"]
    if firebase_config:
        publicador = PublicadorFirebase(
            firebase_config["database_url"],
            firebase_config["credencial"],
            firebase_config["forno_id"],
        )

    print(f"Abrindo {parametros['porta']} em {parametros['baud']} baud...")
    print(f"Arquivo local: {destino}")
    if publicador:
        print(
            "Firebase: ativo, envio a cada "
            f"{firebase_config['intervalo']:g} segundos"
        )
    else:
        print("Firebase: desativado; modo somente local")
    print("Pressione Ctrl+C para encerrar com seguranca.\n")

    proximo_envio = 0.0
    try:
        with serial.Serial(
            parametros["porta"], parametros["baud"], timeout=1
        ) as conexao, destino.open("x", encoding="utf-8", newline="") as arquivo:
            # Muitas placas ESP32 reiniciam quando a porta serial e aberta.
            time.sleep(2.0)
            arquivo.write(CABECALHO_ARQUIVO + "\n")
            arquivo.flush()

            while True:
                recebido = conexao.readline()
                if not recebido:
                    continue

                linha = recebido.decode("utf-8", errors="replace").strip()
                if not linha or linha in CABECALHOS_ESP32:
                    continue
                if linha.startswith("#"):
                    print(linha)
                    continue
                if not linha_de_dados_valida(linha):
                    print(f"Linha serial incompleta ignorada: {linha}")
                    continue

                data_hora = datetime.now().astimezone().isoformat(
                    timespec="milliseconds"
                )
                campos = normalizar_campos(linha)
                arquivo.write(f"{data_hora};{';'.join(campos)}\n")
                arquivo.flush()

                temperatura = campos[3] if campos[3] else "sem leitura"
                print(
                    f"Amostra {campos[0]:>6} | {campos[2]:>10} s | "
                    f"{temperatura:>10} C | {campos[4]}"
                )

                agora = time.monotonic()
                if publicador and agora >= proximo_envio:
                    publicador.publicar(campos)
                    proximo_envio = agora + firebase_config["intervalo"]
    finally:
        if publicador:
            publicador.fechar()


def main() -> int:
    try:
        opcoes = argumentos()
        config, pasta_config = carregar_configuracao(opcoes.config)
        parametros = preparar_parametros(opcoes, config, pasta_config)
        registrar(parametros)
    except KeyboardInterrupt:
        print("\nRegistro encerrado. O CSV foi salvo.")
        return 0
    except serial.SerialException as erro:
        print(f"\nFalha na comunicacao serial: {erro}", file=sys.stderr)
        return 1
    except (OSError, TypeError, ValueError) as erro:
        print(f"\nFalha de configuracao ou arquivo: {erro}", file=sys.stderr)
        return 2
    except Exception as erro:
        print(f"\nFalha inesperada: {erro}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
