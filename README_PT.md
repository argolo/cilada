# Cilada

> É uma cilada, Bino!

CLI em Python 3.11+ que lê um contrato OpenAPI online, gera casos de requisição e
executa teste de carga com Locust.

## Instalação

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
```

Copie e ajuste `.cilada.toml`. Segredos podem ser referenciados por variável de
ambiente, por exemplo `Authorization = "Bearer ${CILADA_TOKEN}"`.

Para criar um modelo de configuração comentado:

```bash
cilada config init
```

O comando não sobrescreve um arquivo existente. Para criar em outro local use
`cilada config init --path caminho/.cilada.toml`; use `--force` somente quando
quiser substituir o arquivo de destino.

## Uso

O arquivo `.cilada.toml` é **opcional**. Todas as configurações podem ser informadas diretamente via argumentos de linha de comando ou definidas no arquivo de configuração.

```bash
# Execução utilizando .cilada.toml (se existir no diretório):
cilada run

# Execução direta sem arquivo de configuração, informando a URL via CLI:
cilada run --openapi-url https://sandbox.example.com/openapi.json

# Execução completa informando todos os parâmetros via CLI:
cilada run \
  --openapi-url https://api.example.com/openapi.json \
  --users 20 \
  --spawn-rate 5.0 \
  --run-time 2m \
  -H "Authorization: Bearer meu_token" \
  -H "X-Tenant: meu_tenant" \
  -m GET -m POST \
  --cases-per-operation 3 \
  --timeout-seconds 15

# Valida contrato, seleção e casos sem enviar carga (dry-run):
cilada run --dry-run --openapi-url https://sandbox.example.com/openapi.json

# Modo não-interativo (não solicita valores de headers):
cilada run --non-interactive --openapi-url https://sandbox.example.com/openapi.json
```

### Precedência das Configurações

A ordem de precedência aplicada é: **Argumentos CLI > Arquivo `.cilada.toml` > Valores Padrão (Defaults)**.

Todos os argumentos disponíveis para `cilada run`:
- **API**: `--openapi-url` (`-u`), `--base-url` (`-b`), `--header` (`-H`), `--verify-tls`/`--no-verify-tls`, `--timeout-seconds`
- **Teste**: `--enabled-methods` (`-m`), `--include-paths`, `--exclude-paths`, `--cases-per-operation`, `--failure-status-classes`
- **Locust**: `--users`, `--spawn-rate`, `--run-time`, `--headless`/`--no-headless`, `--web-host`, `--web-port`, `--csv-prefix`, `--html-report`

Em modo interativo, a CLI solicita a URL do OpenAPI e os headers obrigatórios que
estiverem ausentes. A URL é indispensável para carregar o contrato. É possível
recusar um header: nesse caso, a CLI confirma se os testes devem ser executados
sem ele. Com `--non-interactive`, nenhuma interação nem confirmação é solicitada (todos os prompts de valor e confirmação são ignorados); sem uma URL
do OpenAPI configurada, o comando encerra imediatamente com erro. Headers com nome sensível
(`Authorization`, `token` ou `key`) usam entrada oculta no modo interativo. Valores informados
interativamente existem somente durante o processo e não são gravados no TOML.

## Progresso e resultado

O progresso de preparação aparece em três etapas. Durante a carga, a tabela nativa
do Locust apresenta cada endpoint, tempo médio de retorno, volume e falhas, sem um
painel adicional que polua ou pisque no terminal. A coluna `Name` mostra apenas o
último segmento da URL; se isso colidir entre rotas, a CLI acrescenta o menor
contexto necessário para distingui-las. O método HTTP continua na coluna `Type`.

Ao encerrar, a CLI sempre exibe um resumo consolidado com total de requisições e
falhas, tempos mínimo/médio/máximo e os totais por método e código HTTP. As
estatísticas são coletadas mesmo quando o Locust retorna erro. Em execuções curtas,
nas quais o CSV periódico ainda não recebeu dados, a CLI usa uma captura final das
métricas antes de informar que o resumo não pôde ser coletado.
Se o CSV contiver uma métrica não numérica, a CLI preserva o resumo e exibe um
aviso indicando que esse valor foi considerado como zero.

```text
Resumo final do teste de carga
  Requisições: 120
  Falhas: 2
  Tempo de retorno: mínimo 12.0 ms | médio 48.5 ms | máximo 311.0 ms
  Total por método HTTP
    GET: 100 requisições | 0 falhas
    POST: 20 requisições | 2 falhas
  Total por código HTTP
    200: 118 requisições | mín. 12.0 ms | méd. 47.9 ms | máx. 311.0 ms
    500: 2 requisições | mín. 83.0 ms | méd. 94.5 ms | máx. 106.0 ms
    sem resposta: 1 requisição | mín. 30.0 ms | méd. 30.0 ms | máx. 30.0 ms
```

O CSV necessário para o resumo é criado em diretório temporário quando
`locust.csv_prefix` não está configurado e é removido ao fim da execução. Quando
esse prefixo está definido, os arquivos CSV do Locust são mantidos no local
configurado e também alimentam o resumo final. Uma captura final temporária é usada
como fallback para garantir métricas de execuções curtas.

## Seleção e geração dos casos

- `test.enabled_methods` controla explicitamente os verbos executados.
- `include_paths` e `exclude_paths` aceitam padrões glob, como `/patients/*`.
- `cases_per_operation` gera variações com exemplos/defaults/enums, remoção de
  campos opcionais e valores de limite.
- Cada execução escolhe aleatoriamente um caso. Na tabela de estatísticas, os
  casos usam o menor sufixo único da URL e o método fica na coluna `Type`.
- Respostas HTTP 5xx são marcadas como falha; 4xx permanecem visíveis nas
  estatísticas sem mascarar cenários negativos definidos pelo contrato. Ajuste
  `test.failure_status_classes = [4, 5]` para também marcar 4xx como falha.

## Segurança operacional

O exemplo habilita apenas `GET`, `HEAD` e `OPTIONS`. `POST`, `PUT`, `PATCH` e
`DELETE` podem criar, alterar ou apagar dados e devem ser ativados somente em um
ambiente isolado, com dados descartáveis e autorização explícita.

Não versione tokens no `.cilada.toml`. Em CI, injete segredos pelo cofre do
pipeline e use `${NOME_DA_VARIAVEL}`.

## Qualidade

```bash
make unit-test
make lint
make typecheck
```

Use `make install` para instalar as dependências de desenvolvimento, `make build`
para criar artefatos de distribuição e `make format` (ou `make formatter`) para
formatar o projeto.

## Limitações deliberadas

- Referências JSON Schema `$ref` não são expandidas nesta versão inicial.
- O gerador usa `application/json`; multipart/form-data requer um adaptador.
- Autenticações OAuth2 com renovação de token devem ser fornecidas por um hook
  futuro; headers estáticos funcionam para tokens válidos durante o ensaio.
