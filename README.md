# Monitoramento térmico de fornos

Aplicação para adquirir temperaturas de termopares tipo K ligados a um ESP32 e a um MAX31856. O registro principal é salvo localmente em CSV; opcionalmente, uma cópia é enviada ao Firebase Realtime Database para supervisão remota.

```text
MAX31856 → ESP32 → USB → computador → CSV local
                                  └→ Firebase → painel web
```

O projeto é fornecido como base pública e genérica. Ele não contém credenciais, identificadores de projetos Firebase, históricos experimentais ou arquivos específicos de uma instalação.

## Recursos

- firmware para ESP32 + MAX31856;
- registrador Python com modo local e publicação opcional no Firebase;
- interface gráfica para Windows, macOS e Linux;
- painel web responsivo para Firebase Hosting.

## Estrutura

```text
.
├── firmware/                 # código do ESP32
├── public/                   # painel web do Firebase Hosting
├── configuracao.example.json # modelo sem segredos
├── database.rules.json       # regras com placeholders para editar
├── firebase.json             # configuração do Firebase Hosting/Database
├── monitoramento_gui.py      # interface gráfica
├── registrar_firebase.py     # aquisição serial e envio opcional
└── requirements.txt          # dependências Python
```

## Requisitos

- Python 3.9 ou mais recente;
- `pyserial` e, quando o Firebase for usado, `firebase-admin`;
- Arduino IDE com o pacote oficial **esp32 by Espressif Systems**;
- Node.js LTS e Firebase CLI somente para publicar o painel.

Instale as dependências:

```bash
python3 -m pip install -r requirements.txt
```

No Windows, use `py -m pip install -r requirements.txt`.

## Primeiro teste: somente CSV local

1. Grave `firmware/forno_mufla_esp32_firebase.ino` no ESP32.
2. Duplique `configuracao.example.json` como `configuracao.json`.
3. Para testar sem servidor, execute:

```bash
python3 registrar_firebase.py --somente-local
```

O programa detecta automaticamente uma única porta serial e salva os registros em `dados/`. Se houver mais de uma porta, informe-a explicitamente:

```bash
python3 registrar_firebase.py --somente-local --porta /dev/cu.usbserial-0001
```

No Windows, substitua a porta por algo como `COM5`.

Também é possível abrir a interface gráfica:

- macOS: `Iniciar Monitoramento.command`;
- Windows: `Iniciar Monitoramento.bat`;
- Linux: `./iniciar_monitoramento.sh`.

Feche o Monitor Serial da Arduino IDE antes de iniciar o registrador.

## Configuração opcional do Firebase

1. Crie seu próprio projeto no [Firebase Console](https://console.firebase.google.com/).
2. Ative o Realtime Database em modo bloqueado e o login Google.
3. Copie `configuracao.example.json` para `configuracao.json` e preencha `database_url`, `painel_url` e `forno_id`.
4. Gere uma chave de conta de serviço no Firebase Console e salve-a localmente como `credenciais/service-account.json`.
5. Edite `database.rules.json`, trocando `SEU_EMAIL_AUTORIZADO` e `SEU_EMAIL_ADMIN` pelos e-mails que devem ler e administrar o banco.
6. Publique as regras e o painel:

```bash
npx firebase-tools login
npx firebase-tools deploy --only database,hosting --project SEU_PROJECT_ID
```

Nunca publique `configuracao.json`, a pasta `credenciais/` ou uma chave de conta de serviço. O `.gitignore` já bloqueia esses arquivos, mas confira o conteúdo antes do primeiro `git push`.

## Hardware

| MAX31856 | ESP32 |
|---|---:|
| VIN/VCC | 3V3 |
| GND | GND |
| SCK/CLK | GPIO 26 |
| CS | GPIO 27 |
| SDO/DO/MISO | GPIO 25 |
| SDI/DI/MOSI | GPIO 33 |
| T+ / T− | termopar tipo K |

O firmware possui `MODO_SIMULACAO` para testar o fluxo sem um termopar. Desative esse modo antes de qualquer medição real. Este sistema não substitui controlador, termostato, fusíveis, contatores de segurança ou supervisão humana.

## Dados locais

Os registros gerados pelo aplicativo são salvos localmente em `dados/`. Essa pasta é criada durante o uso e não faz parte da distribuição pública.

## Privacidade e segurança

O projeto público contém somente modelos de configuração. Identificadores de Firebase, e-mails autorizados, chaves privadas, dados experimentais e arquivos de instalação local devem permanecer fora do repositório público.

Se uma chave de conta de serviço já tiver sido publicada em algum repositório, revogue-a no Google Cloud/Firebase e gere outra antes de continuar.

## Licença

O código é distribuído sob a licença MIT. Os dados experimentais, marcas, documentação institucional e hardware podem estar sujeitos a condições adicionais e não estão incluídos nesta licença.
