#!/usr/bin/env python3
"""Interface grafica multiplataforma para o registrador da mufla."""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
import webbrowser

try:
    from serial.tools import list_ports
except ImportError:
    list_ports = None


PASTA_APP = Path(__file__).resolve().parent
SCRIPT_GRAVADOR = PASTA_APP / "registrar_firebase.py"
ARQUIVO_CONFIG = PASTA_APP / "configuracao.json"
URL_PAINEL_PADRAO = ""

COR_FUNDO = "#0b1011"
COR_CARTAO = "#151c1d"
COR_CARTAO_SUAVE = "#101617"
COR_LINHA = "#2a3433"
COR_TEXTO = "#f3f6f3"
COR_MUTED = "#93a09e"
COR_VERDE = "#7fd4b5"
COR_LARANJA = "#ff9a62"
COR_AMARELO = "#f3c76b"
COR_VERMELHO = "#ff7657"


def fonte_padrao() -> str:
    if sys.platform == "darwin":
        return "Helvetica Neue"
    if os.name == "nt":
        return "Segoe UI"
    return "DejaVu Sans"


class MonitoramentoMufla:
    def __init__(self, raiz: tk.Tk) -> None:
        self.raiz = raiz
        self.fonte = fonte_padrao()
        self.processo: subprocess.Popen[str] | None = None
        self.fila_saida: queue.Queue[tuple[str, object]] = queue.Queue()
        self.mapa_portas: dict[str, str] = {}
        self.inicio_registro: float | None = None
        self.encerrar_janela_ao_parar = False
        self.simulacao_detectada = False
        self.ultima_pasta_dados = PASTA_APP / "dados"

        self.porta_selecionada = tk.StringVar()
        self.estado_principal = tk.StringVar(value="Pronto para iniciar")
        self.estado_firebase = tk.StringVar(value="Aguardando")
        self.estado_sensor = tk.StringVar(value="Sem leitura")
        self.temperatura = tk.StringVar(value="—")
        self.amostra = tk.StringVar(value="—")
        self.tempo_ensaio = tk.StringVar(value="00:00:00")
        self.arquivo_atual = tk.StringVar(value="Nenhum arquivo criado")

        self._configurar_janela()
        self._configurar_estilos()
        self._montar_interface()
        self.atualizar_portas()
        self._processar_fila()
        self._atualizar_relogio()
        self.raiz.protocol("WM_DELETE_WINDOW", self._ao_fechar)

    def _configurar_janela(self) -> None:
        self.raiz.title("Monitoramento térmico — Mufla 01")
        self.raiz.geometry("980x720")
        self.raiz.minsize(820, 620)
        self.raiz.configure(bg=COR_FUNDO)

    def _configurar_estilos(self) -> None:
        estilo = ttk.Style(self.raiz)
        try:
            estilo.theme_use("clam")
        except tk.TclError:
            pass

        estilo.configure("App.TFrame", background=COR_FUNDO)
        estilo.configure("Card.TFrame", background=COR_CARTAO)
        estilo.configure("Soft.TFrame", background=COR_CARTAO_SUAVE)
        estilo.configure(
            "Titulo.TLabel",
            background=COR_FUNDO,
            foreground=COR_TEXTO,
            font=(self.fonte, 23, "bold"),
        )
        estilo.configure(
            "Subtitulo.TLabel",
            background=COR_FUNDO,
            foreground=COR_MUTED,
            font=(self.fonte, 10),
        )
        estilo.configure(
            "Secao.TLabel",
            background=COR_CARTAO,
            foreground=COR_TEXTO,
            font=(self.fonte, 12, "bold"),
        )
        estilo.configure(
            "Rotulo.TLabel",
            background=COR_CARTAO,
            foreground=COR_MUTED,
            font=(self.fonte, 9),
        )
        estilo.configure(
            "Valor.TLabel",
            background=COR_CARTAO,
            foreground=COR_TEXTO,
            font=(self.fonte, 11, "bold"),
        )
        estilo.configure(
            "Rodape.TLabel",
            background=COR_FUNDO,
            foreground=COR_MUTED,
            font=(self.fonte, 9),
        )
        estilo.configure(
            "Accent.TButton",
            background=COR_VERDE,
            foreground="#07110e",
            bordercolor=COR_VERDE,
            focusthickness=0,
            font=(self.fonte, 11, "bold"),
            padding=(18, 12),
        )
        estilo.map(
            "Accent.TButton",
            background=[("disabled", "#3f5650"), ("active", "#9ce5ca")],
            foreground=[("disabled", "#82928e")],
        )
        estilo.configure(
            "Stop.TButton",
            background="#39201c",
            foreground="#ffd4ca",
            bordercolor="#60352d",
            focusthickness=0,
            font=(self.fonte, 11, "bold"),
            padding=(18, 12),
        )
        estilo.map(
            "Stop.TButton",
            background=[("disabled", "#252929"), ("active", "#4b2822")],
            foreground=[("disabled", "#66706e")],
        )
        estilo.configure(
            "Secondary.TButton",
            background=COR_CARTAO_SUAVE,
            foreground=COR_TEXTO,
            bordercolor=COR_LINHA,
            focusthickness=0,
            font=(self.fonte, 9),
            padding=(12, 8),
        )
        estilo.map(
            "Secondary.TButton",
            background=[("active", "#202929")],
            bordercolor=[("active", "#465452")],
        )
        estilo.configure(
            "Porta.TCombobox",
            fieldbackground=COR_CARTAO_SUAVE,
            background=COR_CARTAO_SUAVE,
            foreground=COR_TEXTO,
            arrowcolor=COR_TEXTO,
            bordercolor=COR_LINHA,
            padding=8,
        )
        estilo.map(
            "Porta.TCombobox",
            fieldbackground=[("readonly", COR_CARTAO_SUAVE)],
            foreground=[("readonly", COR_TEXTO)],
        )

    def _montar_interface(self) -> None:
        principal = ttk.Frame(self.raiz, style="App.TFrame", padding=(28, 24, 28, 18))
        principal.pack(fill="both", expand=True)
        principal.columnconfigure(0, weight=1)
        principal.rowconfigure(2, weight=1)

        cabecalho = ttk.Frame(principal, style="App.TFrame")
        cabecalho.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        cabecalho.columnconfigure(0, weight=1)
        ttk.Label(cabecalho, text="Monitoramento térmico", style="Titulo.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            cabecalho,
            text="Mufla 01 · registro local e supervisão Firebase",
            style="Subtitulo.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.indicador_execucao = tk.Label(
            cabecalho,
            text="●  PARADO",
            bg="#18201f",
            fg=COR_MUTED,
            padx=14,
            pady=8,
            font=(self.fonte, 9, "bold"),
        )
        self.indicador_execucao.grid(row=0, column=1, rowspan=2, sticky="e")

        resumo = ttk.Frame(principal, style="App.TFrame")
        resumo.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        resumo.columnconfigure(0, weight=11)
        resumo.columnconfigure(1, weight=9)

        cartao_controle = ttk.Frame(resumo, style="Card.TFrame", padding=22)
        cartao_controle.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        cartao_controle.columnconfigure(0, weight=1)
        ttk.Label(cartao_controle, text="Controle do ensaio", style="Secao.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(
            cartao_controle,
            text="Selecione a porta USB do ESP32",
            style="Rotulo.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(18, 7))

        self.combo_portas = ttk.Combobox(
            cartao_controle,
            textvariable=self.porta_selecionada,
            state="readonly",
            style="Porta.TCombobox",
        )
        self.combo_portas.grid(row=2, column=0, sticky="ew", padx=(0, 8))
        self.botao_atualizar = ttk.Button(
            cartao_controle,
            text="Atualizar",
            command=self.atualizar_portas,
            style="Secondary.TButton",
        )
        self.botao_atualizar.grid(row=2, column=1, sticky="e")

        botoes_principais = ttk.Frame(cartao_controle, style="Card.TFrame")
        botoes_principais.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        botoes_principais.columnconfigure(0, weight=1)
        botoes_principais.columnconfigure(1, weight=1)
        self.botao_iniciar = ttk.Button(
            botoes_principais,
            text="Iniciar registro",
            command=self.iniciar_registro,
            style="Accent.TButton",
        )
        self.botao_iniciar.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.botao_parar = ttk.Button(
            botoes_principais,
            text="Parar e salvar",
            command=self.parar_registro,
            style="Stop.TButton",
            state="disabled",
        )
        self.botao_parar.grid(row=0, column=1, sticky="ew", padx=(5, 0))

        atalhos = ttk.Frame(cartao_controle, style="Card.TFrame")
        atalhos.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        atalhos.columnconfigure(0, weight=1)
        atalhos.columnconfigure(1, weight=1)
        ttk.Button(
            atalhos,
            text="Abrir painel remoto",
            command=self.abrir_painel,
            style="Secondary.TButton",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ttk.Button(
            atalhos,
            text="Abrir pasta dos CSV",
            command=self.abrir_pasta_dados,
            style="Secondary.TButton",
        ).grid(row=0, column=1, sticky="ew", padx=(5, 0))

        cartao_leitura = ttk.Frame(resumo, style="Card.TFrame", padding=22)
        cartao_leitura.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        cartao_leitura.columnconfigure(0, weight=1)
        ttk.Label(cartao_leitura, text="Leitura atual", style="Secao.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        temperatura_linha = tk.Frame(cartao_leitura, bg=COR_CARTAO)
        temperatura_linha.grid(row=1, column=0, sticky="w", pady=(16, 10))
        tk.Label(
            temperatura_linha,
            textvariable=self.temperatura,
            bg=COR_CARTAO,
            fg=COR_TEXTO,
            font=(self.fonte, 40, "bold"),
        ).pack(side="left")
        tk.Label(
            temperatura_linha,
            text=" °C",
            bg=COR_CARTAO,
            fg=COR_LARANJA,
            font=(self.fonte, 16, "bold"),
        ).pack(side="left", anchor="n", pady=(7, 0))

        grade_leitura = ttk.Frame(cartao_leitura, style="Card.TFrame")
        grade_leitura.grid(row=2, column=0, sticky="ew")
        for coluna in range(3):
            grade_leitura.columnconfigure(coluna, weight=1)
        self._adicionar_metrica(grade_leitura, 0, "Amostra", self.amostra)
        self._adicionar_metrica(grade_leitura, 1, "Tempo", self.tempo_ensaio)
        self._adicionar_metrica(grade_leitura, 2, "Sensor", self.estado_sensor)

        console_card = ttk.Frame(principal, style="Card.TFrame", padding=(18, 16))
        console_card.grid(row=2, column=0, sticky="nsew")
        console_card.columnconfigure(0, weight=1)
        console_card.rowconfigure(2, weight=1)

        topo_console = ttk.Frame(console_card, style="Card.TFrame")
        topo_console.grid(row=0, column=0, sticky="ew")
        topo_console.columnconfigure(0, weight=1)
        ttk.Label(topo_console, text="Atividade", style="Secao.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.rotulo_firebase = tk.Label(
            topo_console,
            textvariable=self.estado_firebase,
            bg=COR_CARTAO,
            fg=COR_MUTED,
            font=(self.fonte, 9, "bold"),
        )
        self.rotulo_firebase.grid(row=0, column=1, sticky="e")

        ttk.Label(
            console_card,
            textvariable=self.arquivo_atual,
            style="Rotulo.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(7, 9))

        self.console = scrolledtext.ScrolledText(
            console_card,
            height=12,
            wrap="word",
            state="disabled",
            bg="#091011",
            fg="#cbd5d2",
            insertbackground=COR_TEXTO,
            selectbackground="#315247",
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=10,
            font=("Menlo" if sys.platform == "darwin" else "Consolas", 9),
        )
        self.console.grid(row=2, column=0, sticky="nsew")

        rodape = ttk.Frame(principal, style="App.TFrame")
        rodape.grid(row=3, column=0, sticky="ew", pady=(13, 0))
        rodape.columnconfigure(0, weight=1)
        ttk.Label(rodape, textvariable=self.estado_principal, style="Rodape.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            rodape,
            text="Mantenha o computador ligado e sem suspensão durante o ensaio.",
            style="Rodape.TLabel",
        ).grid(row=0, column=1, sticky="e")

    def _adicionar_metrica(
        self, pai: ttk.Frame, coluna: int, titulo: str, variavel: tk.StringVar
    ) -> None:
        caixa = ttk.Frame(pai, style="Soft.TFrame", padding=(12, 10))
        caixa.grid(row=0, column=coluna, sticky="nsew", padx=(0 if coluna == 0 else 4, 0))
        ttk.Label(
            caixa,
            text=titulo,
            background=COR_CARTAO_SUAVE,
            foreground=COR_MUTED,
            font=(self.fonte, 8),
        ).pack(anchor="w")
        ttk.Label(
            caixa,
            textvariable=variavel,
            background=COR_CARTAO_SUAVE,
            foreground=COR_TEXTO,
            font=(self.fonte, 10, "bold"),
        ).pack(anchor="w", pady=(4, 0))

    @staticmethod
    def _porta_provavel(item: object) -> bool:
        dispositivo = str(getattr(item, "device", "")).lower()
        descricao = str(getattr(item, "description", "")).lower()
        texto = f"{dispositivo} {descricao}"
        if "bluetooth" in texto or "debug-console" in texto:
            return False
        if os.name == "nt" and dispositivo.startswith("com"):
            return True
        marcadores = ("usb", "acm", "slab", "cp210", "ch340", "wch", "uart")
        return any(marcador in texto for marcador in marcadores)

    def atualizar_portas(self) -> None:
        if list_ports is None:
            self.combo_portas["values"] = []
            self.porta_selecionada.set("")
            self.estado_principal.set("PySerial não instalado. Instale requirements.txt.")
            return

        itens = sorted(list_ports.comports(), key=lambda item: item.device)
        provaveis = [item for item in itens if self._porta_provavel(item)]
        exibidos = provaveis or itens
        selecao_anterior = self.porta_selecionada.get()
        dispositivo_anterior = self.mapa_portas.get(selecao_anterior)
        self.mapa_portas.clear()

        opcoes: list[str] = []
        for item in exibidos:
            descricao = item.description or "dispositivo serial"
            rotulo = f"{item.device}  —  {descricao}"
            self.mapa_portas[rotulo] = item.device
            opcoes.append(rotulo)

        self.combo_portas["values"] = opcoes
        correspondente = None
        if dispositivo_anterior:
            correspondente = next(
                (rotulo for rotulo, porta in self.mapa_portas.items() if porta == dispositivo_anterior),
                None,
            )
            if correspondente:
                self.porta_selecionada.set(correspondente)
        if not correspondente:
            self.porta_selecionada.set(opcoes[0] if opcoes else "")

        if opcoes:
            self.estado_principal.set(
                "ESP32 encontrado. Confira a porta e clique em Iniciar registro."
            )
        else:
            self.estado_principal.set("Nenhuma porta serial encontrada. Conecte o ESP32.")

    def _validar_configuracao(self) -> tuple[dict[str, object], bool]:
        if not SCRIPT_GRAVADOR.is_file():
            raise FileNotFoundError(f"Gravador não encontrado: {SCRIPT_GRAVADOR}")
        if not ARQUIVO_CONFIG.is_file():
            raise FileNotFoundError(
                "configuracao.json não foi encontrado. Crie-o a partir do exemplo."
            )

        try:
            config = json.loads(ARQUIVO_CONFIG.read_text(encoding="utf-8"))
        except json.JSONDecodeError as erro:
            raise ValueError(f"configuracao.json inválido: {erro}") from erro

        firebase = config.get("firebase", {})
        if not isinstance(firebase, dict):
            raise ValueError("Seção firebase inválida em configuracao.json.")
        database_url = str(firebase.get("database_url", "")).strip()
        credencial = Path(str(firebase.get("credencial", "")))
        if not credencial.is_absolute():
            credencial = PASTA_APP / credencial
        firebase_pronto = (
            credencial.is_file()
            and bool(database_url)
            and "SEU-PROJETO" not in database_url
            and "ID_DO_PROJETO" not in database_url
        )

        arquivo = config.get("arquivo", {})
        if isinstance(arquivo, dict):
            pasta = Path(str(arquivo.get("pasta", "dados")))
            self.ultima_pasta_dados = pasta if pasta.is_absolute() else PASTA_APP / pasta
        return config, firebase_pronto

    def abrir_painel(self) -> None:
        """Abre o Hosting indicado na configuração do Firebase."""
        try:
            config = json.loads(ARQUIVO_CONFIG.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            messagebox.showinfo(
                "Painel não configurado",
                "Configure painel_url em configuracao.json antes de abrir o painel.",
            )
            return

        firebase = config.get("firebase", {})
        url = str(firebase.get("painel_url", "")).strip() if isinstance(firebase, dict) else ""
        if not url or "SEU-PROJETO" in url or "ID_DO_PROJETO" in url:
            url = URL_PAINEL_PADRAO
        if not url:
            messagebox.showinfo(
                "Painel não configurado",
                "Configure painel_url em configuracao.json antes de abrir o painel.",
            )
            return
        webbrowser.open(url)

    def iniciar_registro(self) -> None:
        if self.processo and self.processo.poll() is None:
            return
        rotulo_porta = self.porta_selecionada.get()
        porta = self.mapa_portas.get(rotulo_porta)
        if not porta:
            messagebox.showwarning(
                "ESP32 não encontrado",
                "Conecte o ESP32, clique em Atualizar e selecione a porta USB.",
                parent=self.raiz,
            )
            return

        try:
            _, firebase_pronto = self._validar_configuracao()
        except (OSError, ValueError) as erro:
            messagebox.showerror("Configuração incompleta", str(erro), parent=self.raiz)
            return

        comando = [
            sys.executable,
            "-u",
            str(SCRIPT_GRAVADOR),
            "--config",
            str(ARQUIVO_CONFIG),
            "--porta",
            porta,
        ]
        if not firebase_pronto:
            comando.append("--somente-local")
        opcoes: dict[str, object] = {
            "cwd": str(PASTA_APP),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "bufsize": 1,
        }
        if os.name == "nt":
            opcoes["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            opcoes["start_new_session"] = True

        try:
            self.processo = subprocess.Popen(comando, **opcoes)  # type: ignore[arg-type]
        except OSError as erro:
            messagebox.showerror(
                "Não foi possível iniciar",
                f"Falha ao abrir o gravador:\n{erro}",
                parent=self.raiz,
            )
            return

        self.inicio_registro = time.monotonic()
        self.simulacao_detectada = False
        self.temperatura.set("—")
        self.amostra.set("—")
        self.tempo_ensaio.set("00:00:00")
        self.estado_sensor.set("Aguardando")
        self.estado_firebase.set("Conectando...")
        self.rotulo_firebase.configure(fg=COR_AMARELO)
        self.estado_principal.set("Registro iniciado. Aguarde a primeira leitura.")
        self.indicador_execucao.configure(
            text="●  REGISTRANDO", fg=COR_VERDE, bg="#14241f"
        )
        self.botao_iniciar.configure(state="disabled")
        self.botao_parar.configure(state="normal")
        self.combo_portas.configure(state="disabled")
        self.botao_atualizar.configure(state="disabled")
        self._adicionar_log("\n=== NOVO REGISTRO ===\n")

        leitor = threading.Thread(
            target=self._ler_saida_processo,
            args=(self.processo,),
            name="leitor-saida-gravador",
            daemon=True,
        )
        leitor.start()

    def _ler_saida_processo(self, processo: subprocess.Popen[str]) -> None:
        if processo.stdout:
            for linha in processo.stdout:
                self.fila_saida.put(("linha", linha.rstrip("\r\n")))
        codigo = processo.wait()
        self.fila_saida.put(("fim", (processo, codigo)))

    def _processar_fila(self) -> None:
        try:
            while True:
                tipo, conteudo = self.fila_saida.get_nowait()
                if tipo == "linha":
                    self._interpretar_linha(str(conteudo))
                elif tipo == "fim":
                    processo, codigo = conteudo  # type: ignore[misc]
                    self._processo_finalizado(processo, int(codigo))
        except queue.Empty:
            pass
        self.raiz.after(100, self._processar_fila)

    def _interpretar_linha(self, linha: str) -> None:
        if not linha:
            return
        self._adicionar_log(linha + "\n")

        if linha.startswith("Arquivo local:"):
            caminho = linha.split(":", 1)[1].strip()
            self.arquivo_atual.set(caminho)
        elif linha.startswith("Firebase: ativo"):
            self.estado_firebase.set("Firebase configurado")
            self.rotulo_firebase.configure(fg=COR_AMARELO)
        elif linha.startswith("Firebase: desativado"):
            self.estado_firebase.set("● Somente local")
            self.rotulo_firebase.configure(fg=COR_VERDE)
        elif "INFO FIREBASE: conexao ativa" in linha:
            self.estado_firebase.set("●  Firebase conectado")
            self.rotulo_firebase.configure(fg=COR_VERDE)
        elif "AVISO FIREBASE" in linha:
            self.estado_firebase.set("●  Internet indisponível")
            self.rotulo_firebase.configure(fg=COR_AMARELO)
        elif linha.startswith("Falha") or "Falha " in linha:
            self.estado_principal.set(linha)
            self.indicador_execucao.configure(fg=COR_VERMELHO)
        elif "MODO_SIMULACAO=ATIVO" in linha:
            self.simulacao_detectada = True
            self.estado_sensor.set("SIMULAÇÃO")
            self.estado_principal.set(
                "Atenção: firmware em simulação; esta não é uma medição real."
            )
            self.indicador_execucao.configure(
                text="●  SIMULAÇÃO", fg=COR_AMARELO, bg="#2a2415"
            )

        if not linha.startswith("Amostra"):
            return
        partes = [parte.strip() for parte in linha.split("|")]
        if len(partes) != 4:
            return
        numero = partes[0].replace("Amostra", "", 1).strip()
        tempo = partes[1].replace(" s", "").strip()
        temperatura = partes[2].replace(" C", "").strip()
        estado = partes[3]
        self.amostra.set(numero or "—")
        self.estado_sensor.set(f"{estado} · simulado" if self.simulacao_detectada else estado)
        try:
            segundos = float(tempo)
            self.tempo_ensaio.set(self._formatar_duracao(segundos))
        except ValueError:
            pass
        try:
            valor = float(temperatura)
            self.temperatura.set(f"{valor:.2f}".replace(".", ","))
        except ValueError:
            self.temperatura.set("—")
        if self.simulacao_detectada:
            self.estado_principal.set(
                "Simulação em andamento; não utilize estes dados como ensaio real."
            )
        elif estado not in {"OK", "ALERTA_ACIMA_1000_C"}:
            self.estado_principal.set(
                f"Atenção: o sensor informou {estado}; temperatura sem leitura válida."
            )
            self.indicador_execucao.configure(fg=COR_VERMELHO)
        else:
            self.estado_principal.set("Aquisição em andamento; CSV salvo a cada leitura.")
            self.indicador_execucao.configure(fg=COR_VERDE)

    def _adicionar_log(self, texto: str) -> None:
        self.console.configure(state="normal")
        self.console.insert("end", texto)
        self.console.see("end")
        self.console.configure(state="disabled")

    @staticmethod
    def _formatar_duracao(segundos: float) -> str:
        total = max(0, int(segundos))
        horas, resto = divmod(total, 3600)
        minutos, segundos_restantes = divmod(resto, 60)
        return f"{horas:02d}:{minutos:02d}:{segundos_restantes:02d}"

    def _atualizar_relogio(self) -> None:
        if self.processo and self.processo.poll() is None and self.inicio_registro:
            if self.amostra.get() == "—":
                decorrido = time.monotonic() - self.inicio_registro
                self.tempo_ensaio.set(self._formatar_duracao(decorrido))
        self.raiz.after(1000, self._atualizar_relogio)

    def parar_registro(self) -> None:
        processo = self.processo
        if not processo or processo.poll() is not None:
            return
        self.estado_principal.set("Encerrando com segurança e finalizando o CSV...")
        self.botao_parar.configure(state="disabled")
        try:
            if os.name == "nt":
                processo.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(os.getpgid(processo.pid), signal.SIGINT)
        except (OSError, ProcessLookupError):
            processo.terminate()
        self.raiz.after(6000, lambda: self._forcar_encerramento(processo))

    @staticmethod
    def _forcar_encerramento(processo: subprocess.Popen[str]) -> None:
        if processo.poll() is None:
            processo.terminate()

    def _processo_finalizado(
        self, processo: subprocess.Popen[str], codigo: int
    ) -> None:
        if processo is not self.processo:
            return
        self.processo = None
        self.inicio_registro = None
        self.botao_iniciar.configure(state="normal")
        self.botao_parar.configure(state="disabled")
        self.combo_portas.configure(state="readonly")
        self.botao_atualizar.configure(state="normal")
        self.indicador_execucao.configure(text="●  PARADO", fg=COR_MUTED, bg="#18201f")
        self.atualizar_portas()
        if codigo == 0:
            self.estado_principal.set("Registro encerrado com segurança. O CSV foi salvo.")
        else:
            self.estado_principal.set(
                "O registro foi interrompido por um erro. Consulte a área de atividade."
            )
            self.indicador_execucao.configure(fg=COR_VERMELHO)
        if self.encerrar_janela_ao_parar:
            self.raiz.destroy()

    def abrir_pasta_dados(self) -> None:
        try:
            if ARQUIVO_CONFIG.is_file():
                config = json.loads(ARQUIVO_CONFIG.read_text(encoding="utf-8"))
                arquivo = config.get("arquivo", {})
                if isinstance(arquivo, dict):
                    pasta = Path(str(arquivo.get("pasta", "dados")))
                    self.ultima_pasta_dados = pasta if pasta.is_absolute() else PASTA_APP / pasta
            self.ultima_pasta_dados.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(self.ultima_pasta_dados))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self.ultima_pasta_dados)])
            else:
                subprocess.Popen(["xdg-open", str(self.ultima_pasta_dados)])
        except (OSError, ValueError, json.JSONDecodeError) as erro:
            messagebox.showerror(
                "Não foi possível abrir a pasta", str(erro), parent=self.raiz
            )

    def _ao_fechar(self) -> None:
        if self.processo and self.processo.poll() is None:
            confirmar = messagebox.askyesno(
                "Registro em andamento",
                "Deseja parar o registro, salvar o CSV e fechar a janela?",
                parent=self.raiz,
            )
            if not confirmar:
                return
            self.encerrar_janela_ao_parar = True
            self.parar_registro()
            return
        self.raiz.destroy()


def main() -> None:
    raiz = tk.Tk()
    MonitoramentoMufla(raiz)
    raiz.mainloop()


if __name__ == "__main__":
    main()
