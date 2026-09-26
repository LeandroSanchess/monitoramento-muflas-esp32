/*
  Registrador serial de perfil termico de forno mufla
  Hardware: ESP32 DevKit + MAX31856 + termopar tipo K

  O ESP32 transmite uma amostra por segundo em formato CSV pela USB.
  O computador salva o CSV e envia uma copia periodica ao Firebase.

  Colunas transmitidas:
  amostra;tempo_ms;tempo_s;temperatura_c;estado;dado_bruto_hex;status_hex

  Compatibilidade prevista: Arduino-ESP32 3.x, placa ESP32 Dev Module.
*/

#include <Arduino.h>
#include <math.h>

namespace Config {

constexpr uint8_t PIN_MAX31856_SCK = 26;
constexpr uint8_t PIN_MAX31856_CS  = 27;
constexpr uint8_t PIN_MAX31856_SDO = 25;
constexpr uint8_t PIN_MAX31856_SDI = 33;
constexpr uint8_t PIN_LED_STATUS   = 2;

constexpr uint32_t INTERVALO_AMOSTRA_MS = 1000UL;
constexpr uint32_t INTERVALO_REINICIALIZACAO_MAX31856_MS = 5000UL;
constexpr uint32_t BAUD_SERIAL = 115200UL;

// ATENCAO: deixe true somente durante os testes sem termopar.
// Para medir o forno real, mantenha false e grave o firmware novamente.
constexpr bool MODO_SIMULACAO = false;

// O Brasil usa rede de 60 Hz. Altere para true somente se o ambiente usar 50 Hz.
constexpr bool FILTRO_REDE_50HZ = false;

}  // namespace Config

enum class EstadoTermopar : uint8_t {
  OK,
  SATURADO,
  ABERTO,
  JUNTA_FRIA_FORA_FAIXA,
  ENTRADA_FORA_FAIXA,
  QUADRO_INVALIDO,
};

struct LeituraTermopar {
  uint32_t dadoBruto;
  uint8_t status;
  float temperaturaC;
  EstadoTermopar estado;
};

uint32_t proximaAmostraMs = 0;
uint32_t contadorAmostras = 0;
uint32_t ultimoMillis32 = 0;
uint64_t epocaMillis64 = 0;
uint64_t instanteInicialMs = 0;

uint64_t millis64() {
  const uint32_t agora32 = millis();
  if (agora32 < ultimoMillis32) {
    epocaMillis64 += (1ULL << 32);
  }
  ultimoMillis32 = agora32;
  return epocaMillis64 + agora32;
}

const char* textoEstado(EstadoTermopar estado) {
  switch (estado) {
    case EstadoTermopar::OK:
      return "OK";
    case EstadoTermopar::SATURADO:
      return "SATURADO";
    case EstadoTermopar::ABERTO:
      return "TERMOPAR_ABERTO";
    case EstadoTermopar::JUNTA_FRIA_FORA_FAIXA:
      return "JUNTA_FRIA_FORA_FAIXA";
    case EstadoTermopar::ENTRADA_FORA_FAIXA:
      return "ENTRADA_FORA_FAIXA";
    case EstadoTermopar::QUADRO_INVALIDO:
      return "COMUNICACAO_INVALIDA";
  }
  return "ESTADO_DESCONHECIDO";
}

bool leituraTemTemperatura(EstadoTermopar estado) {
  return estado == EstadoTermopar::OK ||
         estado == EstadoTermopar::SATURADO;
}

namespace Max31856 {

constexpr uint8_t REG_CR0 = 0x00;
constexpr uint8_t REG_CR1 = 0x01;
constexpr uint8_t REG_MASK = 0x02;
constexpr uint8_t REG_TEMP_MSB = 0x0C;

constexpr uint8_t CR0_CONVERSAO_CONTINUA = 0x80;
constexpr uint8_t CR0_DETECCAO_ABERTO = 0x10;
constexpr uint8_t CR0_FILTRO_50HZ = 0x01;

constexpr uint8_t TIPO_TERMOPAR_K = 0x03;

constexpr uint8_t STATUS_JUNTA_FRIA_FORA_FAIXA = 0x80;
constexpr uint8_t STATUS_TERMOPAR_FORA_FAIXA = 0x40;
constexpr uint8_t STATUS_SOBRETENSAO_SUBTENSAO = 0x02;
constexpr uint8_t STATUS_TERMOPAR_ABERTO = 0x01;

}  // namespace Max31856

bool max31856Inicializado = false;
uint32_t proximaTentativaMax31856Ms = 0;

uint8_t valorCr0Max31856() {
  const uint8_t filtro = Config::FILTRO_REDE_50HZ
                             ? Max31856::CR0_FILTRO_50HZ
                             : 0x00U;
  return static_cast<uint8_t>(Max31856::CR0_CONVERSAO_CONTINUA |
                              Max31856::CR0_DETECCAO_ABERTO | filtro);
}

uint8_t transferirByteMax31856(uint8_t enviado) {
  uint8_t recebido = 0;

  // SPI modo 1: SCK em repouso baixo, dado amostrado na descida.
  for (uint8_t mascara = 0x80; mascara != 0; mascara >>= 1) {
    digitalWrite(Config::PIN_MAX31856_SDI,
                 (enviado & mascara) != 0 ? HIGH : LOW);
    digitalWrite(Config::PIN_MAX31856_SCK, HIGH);
    delayMicroseconds(1);
    digitalWrite(Config::PIN_MAX31856_SCK, LOW);
    delayMicroseconds(1);

    recebido <<= 1;
    if (digitalRead(Config::PIN_MAX31856_SDO) == HIGH) {
      recebido |= 0x01U;
    }
  }

  return recebido;
}

void escreverRegistroMax31856(uint8_t endereco, uint8_t valor) {
  digitalWrite(Config::PIN_MAX31856_CS, LOW);
  delayMicroseconds(2);
  transferirByteMax31856(static_cast<uint8_t>(endereco | 0x80U));
  transferirByteMax31856(valor);
  digitalWrite(Config::PIN_MAX31856_CS, HIGH);
}

void lerRegistrosMax31856(uint8_t endereco, uint8_t* destino, uint8_t quantidade) {
  digitalWrite(Config::PIN_MAX31856_CS, LOW);
  delayMicroseconds(2);
  transferirByteMax31856(static_cast<uint8_t>(endereco & 0x7FU));

  for (uint8_t i = 0; i < quantidade; ++i) {
    destino[i] = transferirByteMax31856(0x00U);
  }

  digitalWrite(Config::PIN_MAX31856_CS, HIGH);
}

uint8_t lerRegistroMax31856(uint8_t endereco) {
  uint8_t valor = 0;
  lerRegistrosMax31856(endereco, &valor, 1);
  return valor;
}

bool configuracaoMax31856Valida() {
  uint8_t registros[2] = {0, 0};
  lerRegistrosMax31856(Max31856::REG_CR0, registros, sizeof(registros));
  return registros[0] == valorCr0Max31856() &&
         registros[1] == Max31856::TIPO_TERMOPAR_K;
}

bool configurarMax31856() {
  const uint8_t filtro = Config::FILTRO_REDE_50HZ
                             ? Max31856::CR0_FILTRO_50HZ
                             : 0x00U;

  // Configura primeiro em modo normalmente desligado; a conversao continua
  // somente depois que o tipo e o filtro estao definidos.
  escreverRegistroMax31856(
      Max31856::REG_CR0,
      static_cast<uint8_t>(Max31856::CR0_DETECCAO_ABERTO | filtro));
  escreverRegistroMax31856(Max31856::REG_CR1, Max31856::TIPO_TERMOPAR_K);
  escreverRegistroMax31856(Max31856::REG_MASK, 0x00U);

  // O MAX31856 nao possui registrador de identificacao. A leitura de volta
  // do tipo K detecta pinos SDI/SDO trocados ou CS incorreto antes da aquisicao.
  if ((lerRegistroMax31856(Max31856::REG_CR1) & 0x0FU) !=
      Max31856::TIPO_TERMOPAR_K) {
    return false;
  }

  escreverRegistroMax31856(Max31856::REG_CR0, valorCr0Max31856());
  delay(200);
  return configuracaoMax31856Valida();
}

uint32_t lerQuadroMax31856(uint8_t& status) {
  uint8_t bytes[4] = {0, 0, 0, 0};
  lerRegistrosMax31856(Max31856::REG_TEMP_MSB, bytes, sizeof(bytes));

  status = bytes[3];
  return (static_cast<uint32_t>(bytes[0]) << 16) |
         (static_cast<uint32_t>(bytes[1]) << 8) |
         static_cast<uint32_t>(bytes[2]);
}

LeituraTermopar lerTermoparSimulado();

LeituraTermopar lerTermopar() {
  if (Config::MODO_SIMULACAO) {
    return lerTermoparSimulado();
  }

  LeituraTermopar leitura{};
  leitura.dadoBruto = 0;
  leitura.status = 0;
  leitura.temperaturaC = NAN;

  if (!max31856Inicializado) {
    const uint32_t agoraMs = millis();
    if (static_cast<int32_t>(agoraMs - proximaTentativaMax31856Ms) >= 0) {
      max31856Inicializado = configurarMax31856();
      proximaTentativaMax31856Ms =
          millis() + Config::INTERVALO_REINICIALIZACAO_MAX31856_MS;
    }
    if (!max31856Inicializado) {
      leitura.estado = EstadoTermopar::QUADRO_INVALIDO;
      return leitura;
    }
  }

  // O registrador CR0 volta ao valor de reset quando o MAX perde alimentacao.
  // Esta leitura impede que SDO flutuando seja interpretado como 0,00 graus.
  if (!configuracaoMax31856Valida() && !configuracaoMax31856Valida()) {
    max31856Inicializado = false;
    proximaTentativaMax31856Ms =
        millis() + Config::INTERVALO_REINICIALIZACAO_MAX31856_MS;
    leitura.estado = EstadoTermopar::QUADRO_INVALIDO;
    return leitura;
  }

  leitura.dadoBruto = lerQuadroMax31856(leitura.status);

  if ((leitura.status & Max31856::STATUS_TERMOPAR_ABERTO) != 0U) {
    leitura.estado = EstadoTermopar::ABERTO;
    return leitura;
  }

  if ((leitura.status & Max31856::STATUS_SOBRETENSAO_SUBTENSAO) != 0U) {
    leitura.estado = EstadoTermopar::ENTRADA_FORA_FAIXA;
    return leitura;
  }

  if ((leitura.status & Max31856::STATUS_JUNTA_FRIA_FORA_FAIXA) != 0U) {
    leitura.estado = EstadoTermopar::JUNTA_FRIA_FORA_FAIXA;
    return leitura;
  }

  int32_t codigoTemperatura = static_cast<int32_t>(leitura.dadoBruto >> 5);
  if ((leitura.dadoBruto & 0x00800000UL) != 0UL) {
    codigoTemperatura |= ~0x7FFFF;
  }
  leitura.temperaturaC = static_cast<float>(codigoTemperatura) * 0.0078125F;

  if ((leitura.status & Max31856::STATUS_TERMOPAR_FORA_FAIXA) != 0U) {
    leitura.estado = EstadoTermopar::SATURADO;
  } else {
    leitura.estado = EstadoTermopar::OK;
  }

  return leitura;
}

LeituraTermopar lerTermoparSimulado() {
  const double tempoS = static_cast<double>(millis64() - instanteInicialMs) / 1000.0;
  double temperatura = 25.0;

  // Perfil curto para validar rapidamente o painel remoto.
  if (tempoS < 60.0) {
    temperatura = 25.0 + (180.0 - 25.0) * (tempoS / 60.0);
  } else if (tempoS < 180.0) {
    temperatura = 180.0 + (450.0 - 180.0) * ((tempoS - 60.0) / 120.0);
  } else if (tempoS < 360.0) {
    temperatura = 450.0 + (700.0 - 450.0) * ((tempoS - 180.0) / 180.0);
  } else if (tempoS < 480.0) {
    temperatura = 700.0 + (900.0 - 700.0) * ((tempoS - 360.0) / 120.0);
  } else {
    temperatura = 900.0 + 3.0 * sin((tempoS - 480.0) * 0.20);
  }

  temperatura += 1.5 * sin(tempoS * 0.70);
  if (temperatura < 0.0) temperatura = 0.0;
  if (temperatura > 1372.0) temperatura = 1372.0;

  int32_t codigoTemperatura =
      static_cast<int32_t>(temperatura / 0.0078125 + 0.5);
  if (codigoTemperatura > 0x3FFFF) codigoTemperatura = 0x3FFFF;

  LeituraTermopar leitura{};
  leitura.dadoBruto =
      (static_cast<uint32_t>(codigoTemperatura) & 0x7FFFFU) << 5;
  leitura.status = 0;
  leitura.temperaturaC = static_cast<float>(codigoTemperatura) * 0.0078125F;
  leitura.estado = EstadoTermopar::OK;
  return leitura;
}

size_t montarLinhaCsv(char* destino, size_t capacidade,
                      uint32_t amostra, uint64_t tempoMs,
                      const LeituraTermopar& leitura) {
  const double tempoS = static_cast<double>(tempoMs) / 1000.0;

  if (leituraTemTemperatura(leitura.estado)) {
    return static_cast<size_t>(snprintf(
        destino, capacidade, "%lu;%llu;%.3f;%.2f;%s;0x%06lX;0x%02X\n",
        static_cast<unsigned long>(amostra),
        static_cast<unsigned long long>(tempoMs),
        tempoS,
        static_cast<double>(leitura.temperaturaC), textoEstado(leitura.estado),
        static_cast<unsigned long>(leitura.dadoBruto),
        static_cast<unsigned int>(leitura.status)));
  }

  return static_cast<size_t>(snprintf(
      destino, capacidade, "%lu;%llu;%.3f;;%s;0x%06lX;0x%02X\n",
      static_cast<unsigned long>(amostra),
      static_cast<unsigned long long>(tempoMs),
      tempoS, textoEstado(leitura.estado),
      static_cast<unsigned long>(leitura.dadoBruto),
      static_cast<unsigned int>(leitura.status)));
}

void configurarPinos() {
  pinMode(Config::PIN_MAX31856_CS, OUTPUT);
  pinMode(Config::PIN_MAX31856_SCK, OUTPUT);
  pinMode(Config::PIN_MAX31856_SDI, OUTPUT);
  // Mantem a entrada em zero quando o conversor esta desconectado ou sem energia.
  pinMode(Config::PIN_MAX31856_SDO, INPUT_PULLDOWN);
  pinMode(Config::PIN_LED_STATUS, OUTPUT);

  digitalWrite(Config::PIN_MAX31856_CS, HIGH);
  digitalWrite(Config::PIN_MAX31856_SCK, LOW);
  digitalWrite(Config::PIN_MAX31856_SDI, LOW);
  digitalWrite(Config::PIN_LED_STATUS, LOW);
}

void setup() {
  configurarPinos();

  Serial.begin(Config::BAUD_SERIAL);
  delay(300);

  Serial.println("# Registrador de perfil termico - ESP32 + MAX31856");
  if (Config::MODO_SIMULACAO) {
    Serial.println("# MODO_SIMULACAO=ATIVO; termopar real nao esta sendo lido");
  } else {
    max31856Inicializado = configurarMax31856();
    if (!max31856Inicializado) {
      Serial.println("# ERRO: MAX31856 nao respondeu; verifique SDI, SDO, CS e SCK");
      proximaTentativaMax31856Ms =
          millis() + Config::INTERVALO_REINICIALIZACAO_MAX31856_MS;
    }
  }
  Serial.println("amostra;tempo_ms;tempo_s;temperatura_c;estado;dado_bruto_hex;status_hex");

  ultimoMillis32 = millis();
  instanteInicialMs = millis64();
  proximaAmostraMs = millis();
}

void loop() {
  const uint32_t agoraMs = millis();

  if (static_cast<int32_t>(agoraMs - proximaAmostraMs) >= 0) {
    do {
      proximaAmostraMs += Config::INTERVALO_AMOSTRA_MS;
    } while (static_cast<int32_t>(agoraMs - proximaAmostraMs) >= 0);

    const LeituraTermopar leitura = lerTermopar();
    const uint64_t tempoDecorridoMs = millis64() - instanteInicialMs;

    char linha[160];
    const size_t tamanho = montarLinhaCsv(
        linha, sizeof(linha), contadorAmostras, tempoDecorridoMs, leitura);

    if (tamanho > 0 && tamanho < sizeof(linha)) {
      Serial.print(linha);
    } else {
      Serial.println("# ERRO: buffer da linha CSV insuficiente");
    }

    digitalWrite(Config::PIN_LED_STATUS,
                 leitura.estado == EstadoTermopar::OK ? LOW : HIGH);

    ++contadorAmostras;
  }

  delay(1);
}
