# 01 — Especificação

> Fonte da verdade do comportamento. Versão 1.0. Mudou o comportamento? Altere aqui primeiro.

## 1. Visão geral
O cliente envia uma solicitação de consulta (`documento` + `tipo`). A API valida, grava a consulta como `PENDING`,
confirma no banco, publica uma tarefa na fila e responde `202` sem esperar. Um worker consome a tarefa, chama o
serviço externo de clientes (simulado por uma API fake), trata lentidão e falhas com retry limitado e grava o
resultado (`SUCCESS`) ou o erro (`ERROR`). O cliente acompanha por `GET`.

```
Cliente ──POST /api/v1/consultas──▶ API ──valida──▶ grava PENDING ──commit──▶ publica(id) ──▶ 202 {id, status}
                                                                                 │
                                                                     Redis (broker)
                                                                                 │
                                    Worker ──claim (PROCESSING, tentativas+1)──▶ commit
                                       │
                                       ├──POST /fake/customer──▶ API externa fake
                                       │
                                       └──▶ SUCCESS (resultado) | retry com backoff | ERROR (ultimo_erro)
Cliente ──GET /api/v1/consultas[/{id}]──▶ API ──▶ banco
```

## 2. Glossário
| Termo | Significado |
|---|---|
| Consulta | Solicitação de informações de um cliente (pessoa física ou jurídica) no serviço externo. |
| Documento | CPF (11 dígitos) ou CNPJ (14 dígitos), armazenado só com dígitos. |
| Tentativa | Uma chamada ao serviço externo. |
| Erro transitório | Falha que pode desaparecer sozinha (timeout, conexão, 5xx, 408, 429): vale tentar de novo. |
| Erro permanente | Falha que não muda ao repetir (demais 4xx, resposta inválida): não vale tentar de novo. |
| Claim | Marcação atômica da consulta como em processamento, antes de chamar o serviço externo. |

## 3. Requisitos funcionais
| ID | Requisito |
|---|---|
| **RF-01** | `POST /api/v1/consultas` recebe `{"documento", "tipo"}`. Payload inválido na forma (campo ausente, tipo de dado errado, `tipo` fora de `CPF`/`CNPJ`, campo extra, JSON malformado) ⇒ `422 VALIDATION_ERROR`. |
| **RF-02** | Documento inválido segundo RN-01 ⇒ `422 INVALID_DOCUMENT`. Nada é gravado nem publicado. |
| **RF-03** | Consulta válida é gravada com `id` UUID gerado pela aplicação, documento normalizado, `status=PENDING`, `tentativas=0` e o `request_id` da requisição. |
| **RF-04** | A tarefa é publicada **somente depois do commit**. Resposta `202 Accepted` com `{"id", "status": "PENDING"}` e header `Location: /api/v1/consultas/{id}`. |
| **RF-05** | Se a publicação falhar, a consulta passa a `ERROR` com `ultimo_erro = "fila indisponível"` e `processado_em` preenchido, e a API responde `503 QUEUE_UNAVAILABLE` com o `id` em `details`. Nenhum detalhe do broker vaza. |
| **RF-06** | O worker processa a consulta conforme RN-03 a RN-06. |
| **RF-07** | `GET /api/v1/consultas/{id}` ⇒ `200` com `id, documento, tipo, status, tentativas, resultado, ultimo_erro, criado_em, atualizado_em, processado_em`. Id inexistente ⇒ `404 CONSULTA_NOT_FOUND`; id que não é UUID ⇒ `422 VALIDATION_ERROR`. |
| **RF-08** | `GET /api/v1/consultas` ⇒ `200 {items, page, page_size, total}`, ordenado por `criado_em` decrescente. Parâmetros opcionais: `status`, `documento` (aceita máscara, é normalizado), `page` (≥ 1, padrão 1), `page_size` (1 a 100, padrão 20). Parâmetro inválido ⇒ `422 VALIDATION_ERROR`. |
| **RF-09** | API externa fake `POST /fake/customer` com `{"documento"}`, comportamento determinístico da seção 8. |
| **RF-10** | Todas as rotas `/api/v1/*` exigem o header `X-API-Key`. Ausente ou incorreto ⇒ `401 UNAUTHORIZED`. `/health`, `/health/ready`, `/docs`, `/redoc` e `/openapi.json` são públicos. |
| **RF-11** | Rate limit no `POST /api/v1/consultas` por chave de API: no máximo `RATE_LIMIT_POR_MINUTO` requisições por janela fixa de 60 s. Excedeu ⇒ `429 RATE_LIMITED` com header `Retry-After` (segundos até o fim da janela). Se o Redis estiver indisponível, a requisição passa (fail-open) e um log de aviso é emitido. |
| **RF-12** | `GET /health` ⇒ `200 {"status": "ok"}` (liveness, sem dependências). `GET /health/ready` ⇒ `200` se banco e Redis respondem; senão `503 SERVICE_UNAVAILABLE` indicando o componente em falha. |
| **RF-13** | Toda resposta traz `X-Request-ID`: o enviado pelo cliente ou um UUID gerado. |
| **RF-14** | Qualquer erro segue o envelope da seção 6.4. Erro não previsto ⇒ `500 INTERNAL_ERROR` com `request_id`; stack trace só no log. |

## 4. Regras de negócio
- **RN-01 Documento.**
  - Entrada aceita dígitos com ou sem máscara (`.`, `-`, `/`, espaços); qualquer outro caractere torna o documento inválido.
  - CPF: 11 dígitos. CNPJ: 14 dígitos. Tamanho diferente do esperado para o `tipo` ⇒ inválido.
  - Sequências de um único dígito repetido (`11111111111`) ⇒ inválido.
  - Com `DOCUMENTO_VALIDAR_DV=true` (padrão), os dois dígitos verificadores (módulo 11) devem estar corretos.
    Com `false`, valida-se só caracteres e tamanho.
  - Armazenado só com dígitos.
  - Observação: o CPF de exemplo do enunciado do problema, `12345678901`, tem dígitos verificadores inválidos
    (o válido seria `12345678909`) e é rejeitado com a configuração padrão.
- **RN-02 Estados.** `PENDING → PROCESSING → SUCCESS | ERROR`, além de `PENDING → ERROR` (RF-05).
  `SUCCESS` e `ERROR` são terminais: nunca são sobrescritos. `PROCESSING` se repete a cada nova tentativa.
- **RN-03 Claim.** Antes de cada chamada externa, em uma transação curta e atômica:
  `status=PROCESSING, tentativas=tentativas+1` somente se `status ∈ {PENDING, PROCESSING}` e
  `tentativas < RETRY_MAX_TENTATIVAS`. A transação é confirmada **antes** da chamada externa.
  - Consulta inexistente ou terminal ⇒ a tarefa termina sem efeito (log de aviso).
  - Consulta em `PROCESSING` com o limite já atingido ⇒ finalizada como `ERROR` (`"limite de tentativas atingido"`).
- **RN-04 Chamada externa.** Timeout de conexão `EXTERNO_TIMEOUT_CONEXAO_S` e de leitura `EXTERNO_TIMEOUT_LEITURA_S`.
  Nenhuma transação ou conexão de banco fica aberta durante a chamada.
- **RN-05 Classificação do resultado.**
  | Resultado | Classe | Efeito |
  |---|---|---|
  | `200` com corpo válido (`nome`, `score`, `situacao`) | sucesso | `SUCCESS`, `resultado` = corpo, `ultimo_erro` = nulo, `processado_em` |
  | timeout, erro de conexão, `5xx`, `408`, `429` | transitório | grava `ultimo_erro`; se ainda há tentativas, agenda retry (continua `PROCESSING`); senão `ERROR` + `processado_em` |
  | demais `4xx` | permanente | `ERROR` imediato, sem retry |
  | `200` com corpo inválido | permanente | `ERROR` imediato, sem retry |
  A gravação final só ocorre se a consulta ainda estiver `PROCESSING` (outro worker pode ter finalizado antes).
  `ultimo_erro` é uma mensagem curta, sem dados pessoais (ex.: `"serviço externo respondeu HTTP 503"`).
- **RN-06 Retry.** Máximo de `RETRY_MAX_TENTATIVAS` tentativas no total (padrão 5). Espera antes da tentativa n+1:
  `min(RETRY_BASE_SEGUNDOS · 2^(n-1), RETRY_TETO_SEGUNDOS) · U(0,5; 1,5)`, com padrão base 2 s e teto 60 s
  (≈ 2 s, 4 s, 8 s, 16 s antes do jitter). Sem retry infinito.
- **RN-07 Proteção do serviço externo.** Concorrência do worker baixa (`WORKER_CONCORRENCIA`, padrão 2) e limite de
  execução da tarefa (`TAREFA_RATE_LIMIT`, padrão `10/s`), somados ao backoff com jitter.

## 5. Modelo de dados — tabela `consultas`
| Coluna | Tipo | Notas |
|---|---|---|
| `id` | UUID PK | gerado pela aplicação (`uuid4`), não enumerável |
| `documento` | `varchar(14)` | só dígitos; índice |
| `tipo` | `varchar(4)` | `CPF` / `CNPJ` (enum não nativo) |
| `status` | `varchar(10)` | `PENDING` / `PROCESSING` / `SUCCESS` / `ERROR` (enum não nativo) |
| `tentativas` | `integer` | padrão 0 |
| `resultado` | JSONB (JSON no SQLite) | nulo até o sucesso |
| `ultimo_erro` | `text` | nulo; sem dados pessoais |
| `request_id` | `varchar(64)` | nulo; correlação com a requisição de origem |
| `criado_em`, `atualizado_em` | `timestamptz` | UTC; `atualizado_em` muda a cada UPDATE |
| `processado_em` | `timestamptz` | nulo; preenchido ao atingir `SUCCESS` ou `ERROR` |

Índices: `documento`; `(status, criado_em)` para a listagem filtrada.

## 6. Contrato da API
Base `/api/v1`, autenticação por `X-API-Key`.

### 6.1 `POST /api/v1/consultas`
```json
{ "documento": "529.982.247-25", "tipo": "CPF" }
```
`202` (header `Location: /api/v1/consultas/3f1c…`):
```json
{ "id": "3f1c2a52-…", "status": "PENDING" }
```

### 6.2 `GET /api/v1/consultas/{id}`
`200`:
```json
{ "id": "3f1c…", "documento": "52998224725", "tipo": "CPF", "status": "SUCCESS", "tentativas": 1,
  "resultado": { "nome": "Cliente Teste", "score": 742, "situacao": "REGULAR" }, "ultimo_erro": null,
  "criado_em": "2026-10-14T12:00:00Z", "atualizado_em": "2026-10-14T12:00:01Z",
  "processado_em": "2026-10-14T12:00:01Z" }
```

### 6.3 `GET /api/v1/consultas?status=ERROR&documento=529.982.247-25&page=1&page_size=20`
`200`: `{ "items": [ …mesmo formato do 6.2… ], "page": 1, "page_size": 20, "total": 1 }`

### 6.4 Envelope de erro (único formato)
```json
{ "error": { "code": "INVALID_DOCUMENT", "message": "Documento informado é inválido.",
             "details": [ { "field": "documento", "message": "dígitos verificadores inválidos" } ],
             "request_id": "…" } }
```
`details` e `request_id` são opcionais (`request_id` sempre presente no `500`).

| HTTP | `code` | Quando |
|---|---|---|
| 401 | `UNAUTHORIZED` | `X-API-Key` ausente ou incorreta |
| 404 | `CONSULTA_NOT_FOUND` | `GET` de id inexistente |
| 404 | `NOT_FOUND` | rota inexistente |
| 405 | `METHOD_NOT_ALLOWED` | método não suportado |
| 422 | `VALIDATION_ERROR` | payload ou parâmetro inválido; `details[].field` indica o campo |
| 422 | `INVALID_DOCUMENT` | documento reprovado pela RN-01 |
| 429 | `RATE_LIMITED` | limite de requisições excedido; header `Retry-After` |
| 503 | `QUEUE_UNAVAILABLE` | consulta gravada mas a fila falhou (RF-05); `details` traz o `id` |
| 503 | `SERVICE_UNAVAILABLE` | readiness com dependência fora (RF-12) |
| 500 | `INTERNAL_ERROR` | erro não previsto; inclui `request_id` |

## 7. Logs
Uma linha JSON por evento: `timestamp, level, logger, message, request_id, consulta_id` e campos extras.
Documento nunca em claro (só mascarado, ex.: `***.982.247-**`, ou omitido).

| Evento (`message`) | Extras |
|---|---|
| `consulta_criada` | `tipo` |
| `consulta_enfileirada` | |
| `falha_ao_enfileirar` | `erro` (classe da exceção) |
| `processamento_iniciado` | `tentativa` |
| `integracao_tentativa` | `tentativa` |
| `integracao_sucesso` | `tentativa`, `duracao_ms` |
| `integracao_erro` | `tentativa`, `tipo_erro`, `retentavel`, `duracao_ms` |
| `retry_agendado` | `tentativa`, `delay_s` |
| `consulta_finalizada` | `status`, `tentativas`, `duracao_total_ms` (desde `criado_em`) |
| `consulta_ignorada` | `motivo` (inexistente, terminal) |
| `rate_limit_indisponivel` | |
| `erro_inesperado` | stack trace |

## 8. API externa fake
Aplicação separada (`POST /fake/customer`, `POST /fake/reset`, `GET /health`). O comportamento é decidido pelo
**último dígito** do documento:

| Último dígito | Comportamento | Desfecho esperado na consulta |
|---|---|---|
| `0` | `500` sempre | `ERROR` após `RETRY_MAX_TENTATIVAS` tentativas |
| `1` | `503` nas `FAKE_FALHAS_ANTES_DE_RECUPERAR` (padrão 2) primeiras chamadas do documento, depois `200` | `SUCCESS` com 3 tentativas |
| `2` | resposta após `FAKE_LENTIDAO_SEGUNDOS` (padrão 5, acima do timeout de leitura) nas 2 primeiras chamadas, depois `200` | `SUCCESS` com 3 tentativas |
| `3` | `404` (cliente não encontrado) | `ERROR` com 1 tentativa, sem retry |
| demais | `200` `{"nome": "Cliente Teste", "score": 300 + (documento mod 601), "situacao": "REGULAR"}` | `SUCCESS` com 1 tentativa |

Contadores por documento ficam em memória do processo (limitação aceita); `POST /fake/reset` os zera.

Documentos válidos para demonstração:
| Documento | Cenário |
|---|---|
| CPF `529.982.247-25` | sucesso |
| CPF `111.444.781-11` | 503 e recupera no retry |
| CPF `111.444.790-02` | lentidão e recupera no retry |
| CPF `111.444.780-30` | 500, esgota as tentativas |
| CPF `111.444.783-83` | 404, erro permanente |
| CNPJ `11.222.333/0001-81` | 503 e recupera no retry |

## 9. Configuração (variáveis de ambiente)
Todas têm padrão de desenvolvimento; o `docker compose up` funciona sem `.env`.

| Variável | Padrão | Uso |
|---|---|---|
| `DATABASE_URL` | Postgres local | banco |
| `REDIS_URL` | Redis local | broker e rate limit |
| `API_KEY` | (compose fornece chave de desenvolvimento) | RF-10 |
| `RATE_LIMIT_POR_MINUTO` | 60 | RF-11 |
| `DOCUMENTO_VALIDAR_DV` | `true` | RN-01 |
| `EXTERNO_URL` | `http://externo:9000` | RN-04 |
| `EXTERNO_TIMEOUT_CONEXAO_S` / `EXTERNO_TIMEOUT_LEITURA_S` | 2 / 3 | RN-04 |
| `RETRY_MAX_TENTATIVAS` / `RETRY_BASE_SEGUNDOS` / `RETRY_TETO_SEGUNDOS` | 5 / 2 / 60 | RN-06 |
| `WORKER_CONCORRENCIA` / `TAREFA_RATE_LIMIT` | 2 / `10/s` | RN-07 |
| `FAKE_FALHAS_ANTES_DE_RECUPERAR` / `FAKE_LENTIDAO_SEGUNDOS` | 2 / 5 | seção 8 |
| `LOG_LEVEL` | `INFO` | logs |

## 10. Requisitos não funcionais
- **RNF-01 Não bloqueio**: o `POST` não depende do serviço externo.
- **RNF-02 Entrega e idempotência**: a tarefa é confirmada na fila só ao terminar (`acks_late`) e reentregue se o
  worker morrer; reprocessar não altera estado terminal nem passa do limite de tentativas.
- **RNF-03 Observabilidade**: seção 7; `request_id` da requisição chega aos logs do worker.
- **RNF-04 Segurança**: sem stack trace em respostas; chave comparada em tempo constante; nenhuma credencial real no
  repositório; banco e Redis sem portas publicadas no host.
- **RNF-05 Infra**: `docker compose up` sobe `api`, `worker`, `externo`, `db`, `redis` com healthchecks e
  `depends_on: service_healthy`, sem exigir `.env`.
- **RNF-06 Schema versionado**: tabelas criadas somente por migrações Alembic, aplicadas no início do container da API;
  `downgrade` funciona; models e migrações sincronizados.
- **RNF-07 Testabilidade**: suíte principal sem Docker (SQLite + fakes); E2E real opcional (`pytest -m e2e`).
- **RNF-08 Documentação da API**: Swagger em `/docs` com autenticação utilizável, exemplos válidos e todas as
  respostas de erro no envelope real.
- **RNF-09 Qualidade**: ruff (lint e format), mypy e pytest no CI.

## 11. Matriz de rastreabilidade
| Requisito | Testes |
|---|---|
| RN-01, RF-02 | `unit/test_documento.py`, `integration/test_api_criar_consulta.py` |
| RF-01, RF-03, RF-04 | `unit/test_schemas.py`, `integration/test_api_criar_consulta.py` |
| RF-05 | `integration/test_api_criar_consulta.py` (fila indisponível) |
| RN-02, RN-03, RN-05, RNF-02 | `integration/test_processar_consulta.py` |
| RN-04 | `unit/test_cliente_http.py`, `integration/test_processar_consulta.py` (sem transação aberta) |
| RN-06, RN-07 | `unit/test_politica_retry.py`, `unit/test_celery_config.py`, `integration/test_task_celery.py` |
| RF-07 | `integration/test_api_obter_consulta.py` |
| RF-08 | `integration/test_api_listar_consultas.py` |
| RF-09 | `integration/test_fake_externo.py` |
| RF-10, RF-11 | `integration/test_auth.py`, `integration/test_rate_limit.py` |
| RF-12 | `integration/test_health.py` |
| RF-13, RF-14, RNF-03 | `unit/test_logging.py`, `integration/test_erros_globais.py` |
| RNF-04, RNF-05, RNF-06 | `infra/test_docker_compose.py`, `infra/test_migrations.py` |
| RNF-08 | `integration/test_openapi.py` |
| Fluxo completo | `integration/test_fluxo_completo.py`, `e2e/test_e2e_compose.py` |

## 12. Critérios de aceite
1. `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` e `uv run mypy` verdes.
2. Em um clone limpo, `docker compose up --build` sobe sem `.env` e `uv run pytest -m e2e` fica verde.
3. Demonstração manual: os seis documentos da seção 8 chegam aos desfechos esperados.
4. `docker compose stop redis` + `POST` ⇒ `503 QUEUE_UNAVAILABLE`, consulta em `ERROR`, sem detalhe interno.
