# 📥 Telegram Media Downloader

**Baixe vídeos, fotos e arquivos de grupos/canais do Telegram direto pelo terminal.**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Telethon](https://img.shields.io/badge/Telethon-MTProto_API-orange.svg)](https://github.com/LonamiWebs/Telethon)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

Script Python leve e interativo que usa a API oficial do Telegram (MTProto) para listar seus grupos/canais e baixar toda a mídia com barra de progresso, resumo de tamanho e suporte a retomada de downloads interrompidos. Sem precisar do app instalado.

---

## Sumário

- [Funcionalidades](#-funcionalidades)
- [Início Rápido](#-início-rápido)
- [Como Usar](#-como-usar)
- [Estrutura do Projeto](#-estrutura-do-projeto)
- [Segurança](#-segurança)
- [FAQ](#-faq)
- [Tecnologias](#-tecnologias)
- [Contribuindo](#-contribuindo)
- [Licença](#-licença)

---

## ✨ Funcionalidades

- 🔐 **Autenticação via API oficial** — sem bots, sem gambiarras, sem Telegram Desktop
- 📋 **Lista todos os seus grupos e canais** automaticamente
- 🎬 **Filtra por tipo**: vídeos, fotos, documentos ou tudo de uma vez
- 📊 **Mostra o tamanho total** antes de iniciar o download (quantidade de arquivos + tamanho estimado)
- 📁 **Organiza por pasta** — cada grupo/canal tem sua própria pasta
- ⏸️ **Retomada automática** — interrompeu? Execute novamente e ele continua de onde parou
- 📊 **Barra de progresso por download** em tempo real, com porcentagem, tamanho, velocidade (taxa) e ETA de cada arquivo
- 🗑️ **Limpeza automática** — arquivos incompletos são removidos ao cancelar (Ctrl+C)
- 💾 **Credenciais salvas localmente** — configure uma vez, use sempre
- 🚀 **Instalação automática** — o script configura tudo para você

---

## 🚀 Início Rápido

### Pré-requisitos

- **Python 3.10+** instalado
- Uma conta no Telegram

### 1. Clone o repositório

```bash
git clone https://github.com/LuisMIguelFurlanettoSousa/telegram-media-downloader.git
cd telegram-media-downloader
```

### 2. Execute

```bash
./run.sh
```

Na primeira execução, o script:
1. ✅ Cria o ambiente virtual e instala as dependências (com sua confirmação)
2. ✅ Pede suas credenciais da API do Telegram (com instruções de como obter)
3. ✅ Faz login na sua conta (número + código de verificação)

Tudo é salvo localmente — **nas próximas vezes, é só rodar `./run.sh`**.

### Obtendo credenciais da API

1. Acesse [my.telegram.org](https://my.telegram.org)
2. Faça login com seu número de telefone
3. Clique em **"API development tools"**
4. Crie um aplicativo (qualquer nome serve)
5. Copie o `api_id` e o `api_hash`

---

## 🎮 Como Usar

```
==================================================
  TELEGRAM GROUP DOWNLOADER
==================================================
  Logado como: João (@joao123)
==================================================

🔄 Carregando seus grupos/canais...

    1. [Canal] Curso de Python (5420 membros)
    2. [Grupo] Família
    3. [Canal] Tech News (12000 membros)

    0. Sair

👉 Escolha o número do grupo: 1

Que tipo de mídia deseja baixar?

  1. Apenas vídeos
  2. Apenas fotos
  3. Apenas documentos/arquivos
  4. Tudo (vídeos + fotos + documentos)

👉 Escolha (1-4): 1

📊 Calculando tamanho do grupo... OK!

  =============================================
  RESUMO DO GRUPO
  =============================================
  🎬 Vídeos:     47
  📦 Total:      47 arquivos
  💾 Tamanho:    ~2.3 GB
  =============================================

👉 Deseja continuar com o download? (s/n): s

⬇  [1/47] [VIDEO] aula-01.mp4 (52.3 MB)
  [██████████████████████████████] 100.0% (52.3 MB/52.3 MB)
⬇  [2/47] [VIDEO] aula-02.mp4 (48.1 MB)
  [█████████████░░░░░░░░░░░░░░░░░] 43.2% (20.8 MB/48.1 MB)
```

---

## 📁 Estrutura do Projeto

```
telegram-media-downloader/
├── run.sh                  # Script de inicialização (execute este)
├── telegram_downloader.py  # Script principal
├── requirements.txt        # Dependências Python
├── README.md               # Este arquivo
├── CONTRIBUTING.md          # Guia de contribuição
├── LICENSE                  # Licença MIT
└── .gitignore              # Arquivos ignorados pelo git
```

Após a primeira execução, serão criados:

```
├── venv/                   # Ambiente virtual (automático)
├── config.json             # Suas credenciais da API (local)
├── telegram_session.session # Sessão do Telegram (local)
└── downloads/              # Mídia baixada
    └── Nome do Grupo/
        ├── video_1.mp4
        ├── foto_123.jpg
        └── documento_456.pdf
```

---

## 🔒 Segurança

- Suas credenciais ficam **apenas no seu computador** (`config.json`)
- A sessão do Telegram é armazenada localmente (`telegram_session.session`)
- Nenhum dado é enviado para terceiros — comunicação direta com a API do Telegram
- Para revogar o acesso: Telegram > Configurações > Dispositivos > encerre a sessão

---

## ❓ FAQ

**Posso baixar de grupos que não sou membro?**
Não. Você só consegue acessar grupos/canais dos quais participa.

**O download parou no meio. Perdi tudo?**
Não! Execute novamente e ele continua de onde parou. Arquivos já baixados são pulados automaticamente.

**Funciona no Windows?**
O script principal (`telegram_downloader.py`) sim. Basta criar o venv manualmente:
```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python telegram_downloader.py
```

**Qual a ordem de download?**
Das mensagens mais antigas para as mais recentes (de cima para baixo no chat).

---

## 🛠️ Tecnologias

- [Python 3](https://www.python.org/)
- [Telethon](https://github.com/LonamiWebs/Telethon) — cliente MTProto para a API do Telegram

---

## 🤝 Contribuindo

Contribuições são bem-vindas! Veja o [guia de contribuição](CONTRIBUTING.md) para saber como participar.

---

## 📝 Licença

Este projeto é distribuído sob a licença MIT. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.

---

**⭐ Gostou? Deixe uma estrela!**

Se este projeto te ajudou, considere dar uma ⭐ no repositório. Isso ajuda outras pessoas a encontrá-lo!
