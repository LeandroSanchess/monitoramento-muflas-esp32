(() => {
  "use strict";

  const FORNOS = [
    { id: "pechini-01", numero: "01", nome: "Forno Pechini", curto: "Pechini", cor: "#ff9a62" },
    { id: "tubular-01", numero: "02", nome: "Forno tubular", curto: "Tubular", cor: "#55c6d9" },
    { id: "mufla-01", numero: "03", nome: "Forno mufla", curto: "Mufla", cor: "#b894ff" },
  ];
  const FORNO_POR_ID = new Map(FORNOS.map((forno) => [forno.id, forno]));
  const HORAS_MAXIMAS = 30;
  const LIMITE_MAXIMO_C = 1372;
  const LIMITE_DESATUALIZADO_MS = 45_000;
  const CHAVE_PREFERENCIAS = "monitoramento-muflas-esp32-selecionados-v1";

  const elementos = {
    app: document.querySelector("#app"),
    loginLayer: document.querySelector("#login-layer"),
    loginFeedback: document.querySelector("#login-feedback"),
    signIn: document.querySelector("#sign-in"),
    signOut: document.querySelector("#sign-out"),
    userEmail: document.querySelector("#user-email"),
    pageTitle: document.querySelector("#page-title"),
    connectionPill: document.querySelector("#connection-pill"),
    connectionLabel: document.querySelector("#connection-label"),
    overviewButton: document.querySelector("#overview-button"),
    backToOverview: document.querySelector("#back-to-overview"),
    overviewSection: document.querySelector("#overview-section"),
    individualSection: document.querySelector("#individual-section"),
    selectionCount: document.querySelector("#selection-count"),
    selectionFeedback: document.querySelector("#selection-feedback"),
    selectorInputs: [...document.querySelectorAll("#furnace-selectors input[type='checkbox']")],
    selectorOpenButtons: [...document.querySelectorAll("[data-open-furnace]")],
    furnaceCards: [...document.querySelectorAll("[data-furnace-card]")],
    onlineCount: document.querySelector("#online-count"),
    fleetAverage: document.querySelector("#fleet-average"),
    alertCount: document.querySelector("#alert-count"),
    individualName: document.querySelector("#individual-furnace-name"),
    individualNumber: document.querySelector("#individual-number"),
    temperatureCard: document.querySelector("#temperature-card"),
    temperature: document.querySelector("#temperature-value"),
    temperatureOrbit: document.querySelector("#temperature-orbit"),
    thermalProgress: document.querySelector("#thermal-progress"),
    sensorState: document.querySelector("#sensor-state"),
    elapsed: document.querySelector("#elapsed-value"),
    trend: document.querySelector("#trend-value"),
    trendDetail: document.querySelector("#trend-detail"),
    updated: document.querySelector("#updated-value"),
    updatedDetail: document.querySelector("#updated-detail"),
    sample: document.querySelector("#sample-value"),
    raw: document.querySelector("#raw-value"),
    statusMax: document.querySelector("#status-value"),
    chartTitle: document.querySelector("#chart-title"),
    chartSubtitle: document.querySelector("#chart-subtitle"),
    chartLegend: document.querySelector("#chart-legend"),
    chart: document.querySelector("#temperature-chart"),
    chartShell: document.querySelector("#chart-shell"),
    chartTooltip: document.querySelector("#chart-tooltip"),
    chartEmpty: document.querySelector("#chart-empty"),
    chartPoints: document.querySelector("#chart-points"),
    chartExtremes: document.querySelector("#chart-extremes"),
    downloadCsv: document.querySelector("#download-csv"),
    rangeButtons: [...document.querySelectorAll("[data-hours]")],
    eventList: document.querySelector("#event-list"),
    eventCount: document.querySelector("#event-count"),
    resetData: document.querySelector("#reset-data"),
    resetDialog: document.querySelector("#reset-dialog"),
    resetTarget: document.querySelector("#reset-target"),
    resetUnderstood: document.querySelector("#reset-understood"),
    resetFeedback: document.querySelector("#reset-feedback"),
    cancelReset: document.querySelector("#cancel-reset"),
    confirmReset: document.querySelector("#confirm-reset"),
  };

  const estado = {
    usuario: null,
    vista: "overview",
    fornoAtivo: "pechini-01",
    selecionados: carregarSelecao(),
    horas: HORAS_MAXIMAS,
    renderPendente: false,
    pontosProjetados: [],
    resetando: false,
    fornos: new Map(
      FORNOS.map((forno) => [forno.id, {
        atual: null,
        pontos: new Map(),
        referenciaAtual: null,
        consultaHistorico: null,
        erroAtual: "",
        erroHistorico: "",
      }])
    ),
  };

  const textosEstado = {
    OK: "Leitura normal",
    ALERTA_ACIMA_1000_C: "Leitura normal (registro antigo)",
    SATURADO: "Conversor fora da faixa",
    TERMOPAR_ABERTO: "Termopar aberto",
    JUNTA_FRIA_FORA_FAIXA: "Junta fria fora da faixa",
    ENTRADA_FORA_FAIXA: "Entrada fora da faixa",
    COMUNICACAO_INVALIDA: "Comunicação inválida",
  };

  function carregarSelecao() {
    try {
      const salvos = JSON.parse(localStorage.getItem(CHAVE_PREFERENCIAS));
      const validos = Array.isArray(salvos) ? salvos.filter((id) => FORNO_POR_ID.has(id)) : [];
      if (validos.length) return new Set(validos);
    } catch (_erro) {
      // Preferências locais são opcionais.
    }
    return new Set(FORNOS.map((forno) => forno.id));
  }

  function salvarSelecao() {
    try {
      localStorage.setItem(CHAVE_PREFERENCIAS, JSON.stringify([...estado.selecionados]));
    } catch (_erro) {
      // O painel segue funcionando quando o armazenamento estiver bloqueado.
    }
  }

  function numeroFinitoOuNulo(valor) {
    if (valor === null || valor === undefined) return null;
    if (typeof valor === "string" && !valor.trim()) return null;
    const numero = Number(valor);
    return Number.isFinite(numero) ? numero : null;
  }

  function formatarTemperatura(valor, casas = 2) {
    const numero = numeroFinitoOuNulo(valor);
    if (numero === null) return "—";
    return numero.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
  }

  function formatarDuracao(segundos) {
    if (!Number.isFinite(segundos)) return "—";
    const total = Math.max(0, Math.floor(segundos));
    const horas = Math.floor(total / 3600);
    const minutos = Math.floor((total % 3600) / 60);
    const segundosRestantes = total % 60;
    return `${String(horas).padStart(2, "0")}:${String(minutos).padStart(2, "0")}:${String(segundosRestantes).padStart(2, "0")}`;
  }

  function formatarHorario(timestamp, incluirSegundos = true) {
    if (!Number.isFinite(timestamp)) return "—";
    return new Intl.DateTimeFormat("pt-BR", {
      hour: "2-digit",
      minute: "2-digit",
      second: incluirSegundos ? "2-digit" : undefined,
    }).format(new Date(timestamp));
  }

  function formatarDataHora(timestamp) {
    if (!Number.isFinite(timestamp)) return "—";
    return new Intl.DateTimeFormat("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(new Date(timestamp));
  }

  function nivelDoSensor(valor) {
    if (!valor) return "waiting";
    if (valor === "OK" || valor === "ALERTA_ACIMA_1000_C") return "normal";
    return "error";
  }

  function statusDoForno(id) {
    const dados = estado.fornos.get(id);
    if (dados.erroAtual) return { nivel: "error", texto: dados.erroAtual, online: false, alerta: true };
    if (!dados.atual) return { nivel: "waiting", texto: "Aguardando", online: false, alerta: false };

    const atraso = Date.now() - Number(dados.atual.timestamp_ms);
    if (!Number.isFinite(atraso) || atraso > LIMITE_DESATUALIZADO_MS) {
      return { nivel: "stale", texto: "Dados atrasados", online: false, alerta: true };
    }

    const nivel = nivelDoSensor(dados.atual.estado);
    if (nivel === "error") return { nivel, texto: "Falha no sensor", online: true, alerta: true };
    if (nivel === "warning") return { nivel, texto: "Alerta térmico", online: true, alerta: true };
    return { nivel: "normal", texto: "Recebendo", online: true, alerta: false };
  }

  function definirConexao(tipo, texto) {
    elementos.connectionPill.dataset.state = tipo;
    elementos.connectionLabel.textContent = texto;
  }

  function pontosVisiveis(id) {
    const limite = Date.now() - estado.horas * 60 * 60 * 1000;
    return [...estado.fornos.get(id).pontos.values()]
      .filter((ponto) => Number(ponto.timestamp_ms) >= limite)
      .sort((a, b) => Number(a.timestamp_ms) - Number(b.timestamp_ms));
  }

  function segmentosValidos(id) {
    const segmentos = [];
    let segmento = [];
    let timestampAnterior = null;

    const concluirSegmento = () => {
      if (segmento.length) segmentos.push(segmento);
      segmento = [];
    };

    pontosVisiveis(id).forEach((ponto) => {
      const temperatura = numeroFinitoOuNulo(ponto.temperatura_c);
      const timestamp = numeroFinitoOuNulo(ponto.timestamp_ms);
      const houveLacuna = timestamp !== null && timestampAnterior !== null &&
        timestamp - timestampAnterior > LIMITE_DESATUALIZADO_MS;

      if (temperatura === null || timestamp === null || houveLacuna) {
        concluirSegmento();
      }
      if (temperatura !== null && timestamp !== null) segmento.push(ponto);
      timestampAnterior = timestamp;
    });
    concluirSegmento();
    return segmentos;
  }

  function pontosValidos(id) {
    return segmentosValidos(id).flat();
  }

  function calcularTendencia(id) {
    const segmentos = segmentosValidos(id);
    const pontos = segmentos.length ? segmentos[segmentos.length - 1] : [];
    if (pontos.length < 2) return { texto: "—", detalhe: "aguardando histórico", direcao: "stable", valor: null };
    const ultimo = pontos[pontos.length - 1];
    const timestampFinal = Number(ultimo.timestamp_ms);
    const alvo = timestampFinal - 5 * 60 * 1000;
    const anteriores = pontos.filter((ponto) => Number(ponto.timestamp_ms) <= alvo);
    const referencia = anteriores.length ? anteriores[anteriores.length - 1] : pontos[0];
    const minutos = (timestampFinal - Number(referencia.timestamp_ms)) / 60_000;
    if (!Number.isFinite(minutos) || minutos < 0.5) {
      return { texto: "—", detalhe: "janela ainda insuficiente", direcao: "stable", valor: null };
    }
    const valor = (Number(ultimo.temperatura_c) - Number(referencia.temperatura_c)) / minutos;
    const estavel = Math.abs(valor) < 0.02;
    return {
      texto: `${valor > 0 ? "+" : ""}${formatarTemperatura(valor)} °C/min`,
      detalhe: `janela de ${Math.round(minutos)} min`,
      direcao: estavel ? "stable" : valor > 0 ? "rising" : "falling",
      valor,
    };
  }

  function fornosDaVista() {
    if (estado.vista === "individual") return [FORNO_POR_ID.get(estado.fornoAtivo)];
    return FORNOS.filter((forno) => estado.selecionados.has(forno.id));
  }

  function renderizarNavegacao() {
    const quantidade = estado.selecionados.size;
    elementos.selectionCount.textContent = String(quantidade);
    elementos.selectionFeedback.textContent = quantidade === 3
      ? "Todos os fornos aparecem na comparação."
      : quantidade === 2
        ? "Dois fornos aparecem na comparação."
        : "Um forno aparece na comparação.";

    elementos.selectorInputs.forEach((input) => {
      input.checked = estado.selecionados.has(input.value);
      const seletor = input.closest(".furnace-selector");
      seletor.classList.toggle("selected", input.checked);
      seletor.classList.toggle("current", estado.vista === "individual" && input.value === estado.fornoAtivo);
    });

    elementos.furnaceCards.forEach((cartao) => {
      cartao.hidden = !estado.selecionados.has(cartao.dataset.furnaceCard);
    });

    const geral = estado.vista === "overview";
    elementos.overviewSection.hidden = !geral;
    elementos.individualSection.hidden = geral;
    elementos.overviewButton.classList.toggle("active", geral);
    elementos.overviewButton.setAttribute("aria-pressed", String(geral));
    elementos.resetData.hidden = !estado.usuario || geral;

    if (geral) {
      elementos.pageTitle.innerHTML = "Central <span>/</span> Fornos";
      elementos.chartTitle.textContent = quantidade === 1 ? "Histórico do forno selecionado" : "Comparativo dos fornos";
      elementos.chartSubtitle.textContent = quantidade === 1
        ? "Curva térmica do forno selecionado."
        : "Curvas dos fornos selecionados no mesmo eixo.";
    } else {
      const forno = FORNO_POR_ID.get(estado.fornoAtivo);
      elementos.pageTitle.innerHTML = `Forno <span>/</span> ${forno.curto}`;
      elementos.chartTitle.textContent = `Curva do ${forno.nome.toLowerCase()}`;
      elementos.chartSubtitle.textContent = "Histórico térmico e evolução do ensaio selecionado.";
    }
  }

  function renderizarResumoGeral() {
    const selecionados = FORNOS.filter((forno) => estado.selecionados.has(forno.id));
    const temperaturas = [];
    let online = 0;
    let alertas = 0;

    selecionados.forEach((forno) => {
      const dados = estado.fornos.get(forno.id);
      const status = statusDoForno(forno.id);
      const temperatura = numeroFinitoOuNulo(dados.atual && dados.atual.temperatura_c);
      if (temperatura !== null) temperaturas.push(temperatura);
      if (status.online) online += 1;
      if (status.alerta) alertas += 1;

      const seletorStatus = document.querySelector(`#selector-status-${forno.id}`);
      seletorStatus.textContent = status.texto;
      seletorStatus.dataset.level = status.nivel;

      const cartao = elementos.furnaceCards.find((item) => item.dataset.furnaceCard === forno.id);
      const tendencia = calcularTendencia(forno.id);
      cartao.dataset.level = status.nivel;
      const statusCartao = cartao.querySelector(".card-status");
      statusCartao.dataset.level = status.nivel;
      statusCartao.lastChild.textContent = status.texto;
      cartao.querySelector(".card-temperature strong").textContent = dados.atual ? formatarTemperatura(dados.atual.temperatura_c) : "—";
      const percentual = temperatura !== null ? Math.min(100, Math.max(0, (temperatura / LIMITE_MAXIMO_C) * 100)) : 0;
      cartao.querySelector(".mini-thermal-track i").style.width = `${percentual}%`;
      const metricas = cartao.querySelectorAll(".card-metrics strong");
      metricas[0].textContent = tendencia.valor === null
        ? "—"
        : `${tendencia.valor > 0 ? "+" : ""}${formatarTemperatura(tendencia.valor, 1)} °C/min`;
      metricas[0].dataset.direction = tendencia.direcao;
      metricas[1].textContent = dados.atual ? formatarHorario(Number(dados.atual.timestamp_ms), false) : "—";
    });

    elementos.onlineCount.textContent = String(online);
    elementos.alertCount.textContent = String(alertas);
    elementos.fleetAverage.textContent = temperaturas.length
      ? `${formatarTemperatura(temperaturas.reduce((soma, valor) => soma + valor, 0) / temperaturas.length, 1)} °C`
      : "—";

    if (!estado.usuario) return;
    if (!navigator.onLine) definirConexao("error", "Sem conexão com a internet");
    else if (alertas > 0) definirConexao("alert", `${alertas} ${alertas === 1 ? "atenção necessária" : "atenções necessárias"}`);
    else if (online === selecionados.length && online > 0) definirConexao("online", `${online} ${online === 1 ? "forno online" : "fornos online"}`);
    else if (online > 0) definirConexao("stale", `${online}/${selecionados.length} online`);
    else definirConexao("waiting", "Aguardando dados");
  }

  function limparDetalhes() {
    elementos.temperature.textContent = "—";
    elementos.thermalProgress.style.width = "0%";
    elementos.temperatureOrbit.style.setProperty("--heat-progress", "0deg");
    elementos.temperatureCard.dataset.level = "waiting";
    elementos.sensorState.textContent = "Sem dados";
    elementos.sensorState.dataset.level = "waiting";
    elementos.elapsed.textContent = "—";
    elementos.trend.textContent = "—";
    elementos.trend.dataset.direction = "stable";
    elementos.trendDetail.textContent = "aguardando histórico";
    elementos.updated.textContent = "—";
    elementos.updatedDetail.textContent = "nenhuma amostra recebida";
    elementos.sample.textContent = "—";
    elementos.raw.textContent = "—";
    elementos.statusMax.textContent = "—";
  }

  function renderizarIndividual() {
    const forno = FORNO_POR_ID.get(estado.fornoAtivo);
    const dados = estado.fornos.get(forno.id);
    elementos.individualName.textContent = forno.nome;
    elementos.individualNumber.textContent = `FORNO ${forno.numero}`;
    elementos.temperatureCard.style.setProperty("--furnace-color", forno.cor);
    elementos.resetTarget.style.setProperty("--furnace-color", forno.cor);
    elementos.resetTarget.querySelector("span").textContent = forno.numero;
    elementos.resetTarget.querySelector("strong").textContent = forno.nome;

    if (!dados.atual) {
      limparDetalhes();
      return;
    }

    const temperatura = numeroFinitoOuNulo(dados.atual.temperatura_c);
    const temTemperatura = temperatura !== null;
    const percentual = temTemperatura ? Math.min(100, Math.max(0, (temperatura / LIMITE_MAXIMO_C) * 100)) : 0;
    const nivel = nivelDoSensor(dados.atual.estado);
    const tendencia = calcularTendencia(forno.id);

    elementos.temperature.textContent = temTemperatura ? formatarTemperatura(temperatura) : "—";
    elementos.thermalProgress.style.width = `${percentual}%`;
    elementos.temperatureOrbit.style.setProperty("--heat-progress", `${percentual * 2.7}deg`);
    elementos.temperatureCard.dataset.level = nivel;
    elementos.sensorState.textContent = textosEstado[dados.atual.estado] || dados.atual.estado || "Estado desconhecido";
    elementos.sensorState.dataset.level = nivel;
    elementos.elapsed.textContent = formatarDuracao(Number(dados.atual.tempo_s));
    elementos.trend.textContent = tendencia.texto;
    elementos.trend.dataset.direction = tendencia.direcao;
    elementos.trendDetail.textContent = tendencia.detalhe;
    elementos.updated.textContent = formatarHorario(Number(dados.atual.timestamp_ms));
    elementos.updatedDetail.textContent = formatarDataHora(Number(dados.atual.timestamp_ms));
    elementos.sample.textContent = Number.isFinite(Number(dados.atual.amostra)) ? Number(dados.atual.amostra).toLocaleString("pt-BR") : "—";
    elementos.raw.textContent = dados.atual.dado_bruto_hex || "—";
    elementos.statusMax.textContent = dados.atual.status_hex || "—";
  }

  function renderizarLegenda(fornos) {
    elementos.chartLegend.replaceChildren();
    fornos.forEach((forno) => {
      const item = document.createElement("span");
      const ponto = document.createElement("i");
      ponto.className = "legend-dot";
      ponto.style.background = forno.cor;
      ponto.style.boxShadow = `0 0 10px ${forno.cor}88`;
      item.append(ponto, document.createTextNode(forno.curto));
      elementos.chartLegend.append(item);
    });
  }

  function agendarRenderizacao() {
    if (estado.renderPendente) return;
    estado.renderPendente = true;
    requestAnimationFrame(() => {
      estado.renderPendente = false;
      renderizarTudo();
    });
  }

  function renderizarTudo() {
    renderizarNavegacao();
    renderizarResumoGeral();
    renderizarIndividual();
    desenharGrafico();
    renderizarEventos();
  }

  function desenharGrafico() {
    const canvas = elementos.chart;
    const caixa = elementos.chartShell.getBoundingClientRect();
    if (!caixa.width || !caixa.height) return;

    const proporcao = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(caixa.width * proporcao);
    canvas.height = Math.round(caixa.height * proporcao);
    canvas.style.width = `${caixa.width}px`;
    canvas.style.height = `${caixa.height}px`;
    const contexto = canvas.getContext("2d");
    contexto.setTransform(proporcao, 0, 0, proporcao, 0, 0);
    contexto.clearRect(0, 0, caixa.width, caixa.height);

    const fornos = fornosDaVista();
    const series = fornos.map((forno) => {
      const segmentos = segmentosValidos(forno.id);
      return { forno, segmentos, pontos: segmentos.flat() };
    });
    const todos = series.flatMap((serie) => serie.pontos.map((ponto) => ({ forno: serie.forno, ponto })));
    renderizarLegenda(fornos);
    elementos.chartPoints.textContent = `${todos.length.toLocaleString("pt-BR")} ${todos.length === 1 ? "ponto" : "pontos"}`;
    elementos.chartEmpty.hidden = todos.length > 0;
    elementos.chartTooltip.hidden = true;
    elementos.downloadCsv.disabled = todos.length === 0;
    estado.pontosProjetados = [];

    if (!todos.length) {
      elementos.chartExtremes.textContent = "mín. — · máx. —";
      canvas.setAttribute("aria-label", "Gráfico sem dados de temperatura");
      return;
    }

    const temperaturas = todos.map(({ ponto }) => Number(ponto.temperatura_c));
    const timestamps = todos.map(({ ponto }) => Number(ponto.timestamp_ms));
    const minimoReal = Math.min(...temperaturas);
    const maximoReal = Math.max(...temperaturas);
    const amplitude = Math.max(6, maximoReal - minimoReal);
    const minimoY = Math.max(-200, minimoReal - amplitude * 0.14);
    const maximoY = Math.max(minimoY + 8, maximoReal + amplitude * 0.14);
    const inicioX = Math.min(...timestamps);
    const fimX = Math.max(inicioX + 1, ...timestamps);
    elementos.chartExtremes.textContent = `mín. ${formatarTemperatura(minimoReal)} °C · máx. ${formatarTemperatura(maximoReal)} °C`;
    canvas.setAttribute("aria-label", `Gráfico com ${todos.length} pontos de ${fornos.length} ${fornos.length === 1 ? "forno" : "fornos"}`);

    const margem = { topo: 22, direita: 18, base: 38, esquerda: caixa.width < 560 ? 43 : 54 };
    const largura = caixa.width - margem.esquerda - margem.direita;
    const altura = caixa.height - margem.topo - margem.base;
    const projetarX = (timestamp) => margem.esquerda + ((timestamp - inicioX) / (fimX - inicioX)) * largura;
    const projetarY = (temperatura) => margem.topo + (1 - (temperatura - minimoY) / (maximoY - minimoY)) * altura;

    contexto.font = `${caixa.width < 560 ? 10 : 11}px Inter, system-ui, sans-serif`;
    contexto.lineWidth = 1;
    contexto.textBaseline = "middle";
    for (let indice = 0; indice <= 4; indice += 1) {
      const fracao = indice / 4;
      const y = margem.topo + fracao * altura;
      const valor = maximoY - fracao * (maximoY - minimoY);
      contexto.strokeStyle = "rgba(232, 240, 238, 0.075)";
      contexto.beginPath();
      contexto.moveTo(margem.esquerda, y);
      contexto.lineTo(margem.esquerda + largura, y);
      contexto.stroke();
      contexto.fillStyle = "rgba(189, 199, 197, 0.58)";
      contexto.textAlign = "right";
      contexto.fillText(`${valor.toFixed(0)}°`, margem.esquerda - 8, y);
    }

    contexto.textBaseline = "top";
    contexto.fillStyle = "rgba(189, 199, 197, 0.58)";
    [inicioX, (inicioX + fimX) / 2, fimX].forEach((timestamp, indice) => {
      contexto.textAlign = indice === 0 ? "left" : indice === 1 ? "center" : "right";
      contexto.fillText(formatarHorario(timestamp, false), margem.esquerda + (indice / 2) * largura, margem.topo + altura + 14);
    });

    const quantidadeSeriesComDados = series.filter((serie) => serie.pontos.length).length;
    series.forEach(({ forno, pontos, segmentos }) => {
      if (!pontos.length) return;
      segmentos.forEach((pontosDoSegmento) => {
        const projetados = pontosDoSegmento.map((ponto) => ({
          x: projetarX(Number(ponto.timestamp_ms)),
          y: projetarY(Number(ponto.temperatura_c)),
          ponto,
          forno,
        }));
        estado.pontosProjetados.push(...projetados);

        if (quantidadeSeriesComDados === 1 && projetados.length > 1) {
          const gradiente = contexto.createLinearGradient(0, margem.topo, 0, margem.topo + altura);
          gradiente.addColorStop(0, `${forno.cor}35`);
          gradiente.addColorStop(1, `${forno.cor}00`);
          contexto.beginPath();
          projetados.forEach(({ x, y }, indice) => indice === 0 ? contexto.moveTo(x, y) : contexto.lineTo(x, y));
          contexto.lineTo(projetados[projetados.length - 1].x, margem.topo + altura);
          contexto.lineTo(projetados[0].x, margem.topo + altura);
          contexto.closePath();
          contexto.fillStyle = gradiente;
          contexto.fill();
        }

        contexto.beginPath();
        projetados.forEach(({ x, y }, indice) => indice === 0 ? contexto.moveTo(x, y) : contexto.lineTo(x, y));
        contexto.strokeStyle = forno.cor;
        contexto.lineWidth = 2.2;
        contexto.lineJoin = "round";
        contexto.lineCap = "round";
        contexto.shadowColor = `${forno.cor}66`;
        contexto.shadowBlur = 9;
        contexto.stroke();
        contexto.shadowBlur = 0;
        if (projetados.length === 1) {
          contexto.beginPath();
          contexto.arc(projetados[0].x, projetados[0].y, 3.5, 0, Math.PI * 2);
          contexto.fillStyle = forno.cor;
          contexto.fill();
        }
      });
    });
  }

  function renderizarEventos() {
    const eventos = [];
    fornosDaVista().forEach((forno) => {
      let anterior = null;
      pontosVisiveis(forno.id).forEach((ponto) => {
        if (ponto.estado && ponto.estado !== anterior) {
          eventos.push({ forno, ponto });
          anterior = ponto.estado;
        }
      });
    });
    eventos.sort((a, b) => Number(b.ponto.timestamp_ms) - Number(a.ponto.timestamp_ms));
    const recentes = eventos.slice(0, 7);
    elementos.eventList.replaceChildren();
    elementos.eventCount.textContent = String(recentes.length);
    elementos.eventCount.setAttribute("aria-label", `${recentes.length} ${recentes.length === 1 ? "evento" : "eventos"}`);
    if (!recentes.length) {
      const vazio = document.createElement("li");
      vazio.className = "empty-event";
      vazio.textContent = "Nenhum evento recebido.";
      elementos.eventList.append(vazio);
      return;
    }
    recentes.forEach(({ forno, ponto }) => {
      const item = document.createElement("li");
      const nivel = nivelDoSensor(ponto.estado);
      item.className = nivel === "normal" ? "" : nivel;
      item.style.setProperty("--event-color", forno.cor);
      const texto = document.createElement("span");
      if (estado.vista === "overview") {
        const nome = document.createElement("small");
        nome.textContent = forno.curto;
        texto.append(nome);
      }
      texto.append(document.createTextNode(textosEstado[ponto.estado] || ponto.estado));
      const horario = document.createElement("time");
      horario.dateTime = ponto.timestamp_iso || "";
      horario.textContent = formatarHorario(Number(ponto.timestamp_ms));
      item.append(texto, horario);
      elementos.eventList.append(item);
    });
  }

  function mostrarTooltip(evento) {
    if (!estado.pontosProjetados.length) return;
    const caixa = elementos.chart.getBoundingClientRect();
    const x = evento.clientX - caixa.left;
    const ponto = estado.pontosProjetados.reduce((melhor, atual) => (
      !melhor || Math.abs(atual.x - x) < Math.abs(melhor.x - x) ? atual : melhor
    ), null);
    if (!ponto) return;
    elementos.chartTooltip.replaceChildren();
    const nome = document.createElement("span");
    nome.textContent = ponto.forno.nome;
    nome.style.color = ponto.forno.cor;
    const valor = document.createElement("strong");
    valor.textContent = `${formatarTemperatura(ponto.ponto.temperatura_c)} °C`;
    const horario = document.createElement("small");
    horario.textContent = formatarDataHora(Number(ponto.ponto.timestamp_ms));
    elementos.chartTooltip.append(nome, valor, horario);
    elementos.chartTooltip.style.left = `${Math.min(caixa.width - 72, Math.max(72, ponto.x))}px`;
    elementos.chartTooltip.style.top = `${Math.max(76, ponto.y)}px`;
    elementos.chartTooltip.hidden = false;
  }

  function valorCsv(valor) {
    if (valor === null || valor === undefined) return "";
    return `"${String(valor).replace(/"/g, '""')}"`;
  }

  function baixarCsvRemoto() {
    const linhas = [];
    fornosDaVista().forEach((forno) => {
      pontosVisiveis(forno.id).forEach((ponto) => linhas.push({ forno, ponto }));
    });
    if (!linhas.length) return;
    linhas.sort((a, b) => Number(a.ponto.timestamp_ms) - Number(b.ponto.timestamp_ms));
    const colunas = ["forno_id", "forno_nome", "amostra", "tempo_ms", "tempo_s", "temperatura_c", "estado", "dado_bruto_hex", "status_hex", "timestamp_ms", "timestamp_iso"];
    const conteudo = linhas.map(({ forno, ponto }) => [
      forno.id,
      forno.nome,
      ponto.amostra,
      ponto.tempo_ms,
      ponto.tempo_s,
      ponto.temperatura_c,
      ponto.estado,
      ponto.dado_bruto_hex,
      ponto.status_hex,
      ponto.timestamp_ms,
      ponto.timestamp_iso,
    ].map(valorCsv).join(";"));
    const csv = `\ufeff${[colunas.join(";"), ...conteudo].join("\r\n")}\r\n`;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    const nome = estado.vista === "individual" ? estado.fornoAtivo : "fornos-selecionados";
    link.href = url;
    link.download = `${nome}_${new Date().toISOString().slice(0, 10)}_${estado.horas}h.csv`;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function abrirVistaGeral(atualizarHash = true) {
    estado.vista = "overview";
    if (atualizarHash && location.hash !== "#visao-geral") history.replaceState(null, "", "#visao-geral");
    agendarRenderizacao();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function abrirForno(id, atualizarHash = true) {
    if (!FORNO_POR_ID.has(id)) return;
    estado.fornoAtivo = id;
    estado.vista = "individual";
    if (!estado.selecionados.has(id)) {
      estado.selecionados.add(id);
      salvarSelecao();
    }
    if (atualizarHash && location.hash !== `#${id}`) history.replaceState(null, "", `#${id}`);
    agendarRenderizacao();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function aplicarHash() {
    const id = location.hash.slice(1);
    if (FORNO_POR_ID.has(id)) abrirForno(id, false);
    else abrirVistaGeral(false);
  }

  function desconectarBanco() {
    estado.fornos.forEach((dados) => {
      if (dados.referenciaAtual) dados.referenciaAtual.off();
      if (dados.consultaHistorico) dados.consultaHistorico.off();
      dados.referenciaAtual = null;
      dados.consultaHistorico = null;
      dados.atual = null;
      dados.pontos.clear();
      dados.erroAtual = "";
      dados.erroHistorico = "";
    });
    agendarRenderizacao();
  }

  function conectarBanco() {
    desconectarBanco();
    const desde = Date.now() - HORAS_MAXIMAS * 60 * 60 * 1000;
    FORNOS.forEach((forno) => {
      const dados = estado.fornos.get(forno.id);
      const raiz = firebase.database().ref(`fornos/${forno.id}`);
      dados.referenciaAtual = raiz.child("atual");
      dados.referenciaAtual.on(
        "value",
        (snapshot) => {
          dados.erroAtual = "";
          dados.atual = snapshot.val();
          agendarRenderizacao();
        },
        () => {
          dados.erroAtual = "Acesso negado";
          agendarRenderizacao();
        }
      );
      dados.consultaHistorico = raiz.child("historico").orderByChild("timestamp_ms").startAt(desde);
      dados.consultaHistorico.on(
        "child_added",
        (snapshot) => {
          dados.erroHistorico = "";
          dados.pontos.set(snapshot.key, snapshot.val());
          agendarRenderizacao();
        },
        () => {
          dados.erroHistorico = "Histórico indisponível";
          agendarRenderizacao();
        }
      );
      dados.consultaHistorico.on("child_removed", (snapshot) => {
        dados.pontos.delete(snapshot.key);
        agendarRenderizacao();
      });
    });
  }

  function abrirConfirmacaoReset() {
    if (!estado.usuario || estado.vista !== "individual" || estado.resetando) return;
    elementos.resetUnderstood.checked = false;
    elementos.confirmReset.disabled = true;
    elementos.cancelReset.disabled = false;
    elementos.resetFeedback.textContent = "";
    elementos.resetFeedback.dataset.state = "";
    elementos.resetDialog.showModal();
    elementos.resetUnderstood.focus();
  }

  function fecharConfirmacaoReset() {
    if (!estado.resetando && elementos.resetDialog.open) elementos.resetDialog.close();
  }

  async function resetarDadosRemotos() {
    if (!estado.usuario || estado.vista !== "individual" || !elementos.resetUnderstood.checked || estado.resetando) return;
    const id = estado.fornoAtivo;
    const forno = FORNO_POR_ID.get(id);
    estado.resetando = true;
    elementos.resetDialog.setAttribute("aria-busy", "true");
    elementos.resetFeedback.dataset.state = "waiting";
    elementos.resetFeedback.textContent = `Apagando os dados do ${forno.nome.toLowerCase()}…`;
    elementos.confirmReset.disabled = true;
    elementos.cancelReset.disabled = true;
    try {
      await firebase.database().ref(`fornos/${id}`).remove();
      const dados = estado.fornos.get(id);
      dados.atual = null;
      dados.pontos.clear();
      agendarRenderizacao();
      elementos.resetFeedback.dataset.state = "success";
      elementos.resetFeedback.textContent = "Reset concluído. Os dados remotos foram apagados.";
      window.setTimeout(() => {
        if (elementos.resetDialog.open) elementos.resetDialog.close();
      }, 1200);
    } catch (erro) {
      const acessoNegado = String(erro && erro.code).toUpperCase().includes("PERMISSION_DENIED");
      elementos.resetFeedback.dataset.state = "error";
      elementos.resetFeedback.textContent = acessoNegado
        ? "A exclusão foi bloqueada. Publique as regras atualizadas do Firebase."
        : "Não foi possível limpar o Firebase. Verifique a conexão e tente novamente.";
      elementos.cancelReset.disabled = false;
      elementos.confirmReset.disabled = !elementos.resetUnderstood.checked;
    } finally {
      estado.resetando = false;
      elementos.resetDialog.removeAttribute("aria-busy");
    }
  }

  elementos.selectorInputs.forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) estado.selecionados.add(input.value);
      else if (estado.selecionados.size === 1) {
        input.checked = true;
        elementos.selectionFeedback.textContent = "Mantenha pelo menos um forno selecionado.";
        return;
      } else estado.selecionados.delete(input.value);

      if (estado.vista === "individual" && input.value === estado.fornoAtivo && !input.checked) {
        estado.vista = "overview";
        history.replaceState(null, "", "#visao-geral");
      }
      salvarSelecao();
      agendarRenderizacao();
    });
  });

  elementos.selectorOpenButtons.forEach((botao) => botao.addEventListener("click", () => abrirForno(botao.dataset.openFurnace)));
  elementos.furnaceCards.forEach((cartao) => cartao.addEventListener("click", () => abrirForno(cartao.dataset.furnaceCard)));
  elementos.overviewButton.addEventListener("click", () => abrirVistaGeral());
  elementos.backToOverview.addEventListener("click", () => abrirVistaGeral());
  elementos.rangeButtons.forEach((botao) => {
    botao.addEventListener("click", () => {
      estado.horas = Number(botao.dataset.hours);
      elementos.rangeButtons.forEach((item) => item.classList.toggle("active", item === botao));
      agendarRenderizacao();
    });
  });
  elementos.downloadCsv.addEventListener("click", baixarCsvRemoto);
  elementos.chart.addEventListener("pointermove", mostrarTooltip);
  elementos.chart.addEventListener("pointerleave", () => { elementos.chartTooltip.hidden = true; });
  window.addEventListener("resize", agendarRenderizacao, { passive: true });
  window.addEventListener("hashchange", aplicarHash);
  window.addEventListener("online", agendarRenderizacao);
  window.addEventListener("offline", () => definirConexao("error", "Sem conexão com a internet"));

  elementos.resetData.addEventListener("click", abrirConfirmacaoReset);
  elementos.cancelReset.addEventListener("click", fecharConfirmacaoReset);
  elementos.resetUnderstood.addEventListener("change", () => {
    elementos.confirmReset.disabled = estado.resetando || !elementos.resetUnderstood.checked;
  });
  elementos.confirmReset.addEventListener("click", resetarDadosRemotos);
  elementos.resetDialog.addEventListener("cancel", (evento) => {
    if (estado.resetando) evento.preventDefault();
  });

  aplicarHash();
  renderizarTudo();
  window.setInterval(() => {
    renderizarResumoGeral();
    if (estado.vista === "individual") renderizarIndividual();
  }, 5000);

  if (!window.firebase || !firebase.apps || !firebase.apps.length) {
    elementos.app.setAttribute("aria-busy", "false");
    elementos.loginLayer.classList.add("hidden");
    elementos.userEmail.textContent = "Prévia local · conecte pelo Firebase Hosting";
    definirConexao("waiting", "Prévia local");
    document.body.classList.add("local-preview");
    return;
  }

  const autenticacao = firebase.auth();
  autenticacao.languageCode = "pt-BR";
  elementos.signIn.disabled = true;
  autenticacao
    .setPersistence(firebase.auth.Auth.Persistence.LOCAL)
    .catch(() => null)
    .finally(() => {
      elementos.signIn.disabled = false;
    });

  elementos.signIn.addEventListener("click", async () => {
    elementos.loginFeedback.textContent = "";
    elementos.signIn.disabled = true;
    try {
      const provedor = new firebase.auth.GoogleAuthProvider();
      provedor.setCustomParameters({ prompt: "select_account" });
      await autenticacao.signInWithPopup(provedor);
    } catch (erro) {
      const mensagens = {
        "auth/popup-closed-by-user": "A janela de login foi fechada antes da conclusão.",
        "auth/popup-blocked": "O navegador bloqueou a janela do Google. Autorize pop-ups para este site e tente novamente.",
        "auth/cancelled-popup-request": "Já existe uma tentativa de login aberta.",
        "auth/network-request-failed": "Falha de conexão durante o login. Verifique a internet e tente novamente.",
        "auth/unauthorized-domain": "Este endereço ainda não está autorizado no Firebase Authentication.",
        "auth/operation-not-supported-in-this-environment": "O navegador não permite este login. Abra o painel no Chrome ou Safari fora do modo privado.",
      };
      elementos.loginFeedback.textContent = mensagens[erro && erro.code]
        || "Não foi possível autenticar. Tente novamente ou abra o painel em outro navegador.";
      elementos.signIn.disabled = false;
    }
  });

  elementos.signOut.addEventListener("click", () => autenticacao.signOut());
  autenticacao.onAuthStateChanged((usuario) => {
    estado.usuario = usuario;
    elementos.app.setAttribute("aria-busy", "false");
    if (usuario) {
      elementos.loginLayer.classList.add("hidden");
      elementos.signOut.hidden = false;
      elementos.userEmail.textContent = usuario.email || "Usuário autenticado";
      conectarBanco();
    } else {
      if (elementos.resetDialog.open) elementos.resetDialog.close();
      desconectarBanco();
      elementos.loginLayer.classList.remove("hidden");
      elementos.signOut.hidden = true;
      elementos.resetData.hidden = true;
      elementos.userEmail.textContent = "Acesso não autenticado";
    }
  });
})();
