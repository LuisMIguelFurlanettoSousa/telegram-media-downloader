# Guia de Contribuição

Obrigado pelo interesse em contribuir com o **Telegram Media Downloader**! Este guia explica como você pode participar do projeto.

## Como contribuir

### Reportando bugs

1. Verifique se o bug já não foi reportado nas [issues](https://github.com/LuisMIguelFurlanettoSousa/telegram-media-downloader/issues)
2. Abra uma nova issue descrevendo:
   - O que você esperava que acontecesse
   - O que realmente aconteceu
   - Passos para reproduzir o problema
   - Versão do Python e sistema operacional

### Sugerindo melhorias

Abra uma issue com a tag `enhancement` descrevendo sua sugestão e por que ela seria útil.

### Enviando código

1. Faça um fork do repositório
2. Crie uma branch para sua feature ou correção:
   ```bash
   git checkout -b feat/minha-feature
   ```
3. Faça suas alterações seguindo as convenções do projeto
4. Teste suas alterações localmente
5. Faça commit seguindo o padrão de commits semânticos em português:
   ```bash
   git commit -m "feat: adiciona suporte a download de áudios"
   ```
6. Envie um Pull Request

## Convenções

### Commits semânticos

Usamos commits semânticos em português:

- `feat:` — nova funcionalidade
- `fix:` — correção de bug
- `docs:` — alterações na documentação
- `chore:` — tarefas auxiliares (dependências, configs)
- `refactor:` — refatoração sem mudança de comportamento
- `test:` — adição ou correção de testes

### Estilo de código

- Python 3.10+
- Use funções async quando lidar com a API do Telegram
- Mantenha mensagens de interface em português
- Siga as convenções PEP 8

## Ambiente de desenvolvimento

```bash
git clone https://github.com/SEU_USUARIO/telegram-media-downloader.git
cd telegram-media-downloader
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Precisa de ajuda?

Abra uma issue com a tag `question` e teremos prazer em ajudar.
