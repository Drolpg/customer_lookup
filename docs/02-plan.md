# 02 — Plano técnico

## 1. Arquitetura
Camadas com duas portas nas fronteiras externas (serviço de clientes e fila). Sem repositório: o `Session` do
SQLAlchemy já é a unidade de trabalho.

```
HTTP ─▶ api/ (routers, auth, rate limit) ─▶ services/ (regras) ─▶ models/ (SQLAlchemy) ─▶ PostgreSQL
                                                │
                                                ├─▶ ports.PublicadorDeTarefas ◀── adapters/publicador_celery.py ─▶ Redis
                                                └─▶ ports.ClienteExterno      ◀── adapters/cliente_http.py (httpx) ─▶ API fake

Redis ─▶ worker/tasks.py (casca fina) ─▶ services/processamento.processar_consulta
```
- `api/` só traduz HTTP ⇄ services. `services/` não importa FastAPI, Celery nem httpx: depende de `ports.py`.
- `adapters/` implementam as portas; são os únicos módulos que conhecem Celery (publicação) e httpx.
- `worker/` monta as dependências reais, chama o service e traduz a decisão de retry em `self.retry(countdown=…)`.
- `fake_externo/` é uma aplicação FastAPI independente, sem dependência do restante do pacote.

## 2. Estrutura de diretórios
```
src/customer_lookup/
  main.py                    # app, middleware de request id, handlers de erro, routers
  ports.py                   # Protocols ClienteExterno, PublicadorDeTarefas + exceções de integração
  api/        deps.py  health.py  v1/consultas.py
  core/       config.py  contexto.py  documento.py  errors.py  logging.py
  db/         base.py  session.py
  models/     consulta.py
  schemas/    consulta.py  erro.py
  services/   consulta_service.py  processamento.py  politica_retry.py  rate_limit.py
  adapters/   cliente_http.py  publicador_celery.py
  worker/     celery_app.py  tasks.py
  fake_externo/ app.py
migrations/   alembic
tests/        conftest.py  unit/  integration/  infra/  e2e/
```

## 3. Decisões que afetam o código
| Decisão | Motivo |
|---|---|
| SQLAlchemy 2 síncrono + psycopg 3; endpoints `def` | O worker Celery é síncrono; API e worker usam o mesmo service. |
| UUID gerado na aplicação | Não enumerável; o id existe antes do INSERT. |
| Schema valida a forma; o service valida o documento (`INVALID_DOCUMENT`) | Separa `VALIDATION_ERROR` de `INVALID_DOCUMENT` e respeita `DOCUMENTO_VALIDAR_DV`. |
| Commit antes de publicar; falha na publicação ⇒ `ERROR` + `503` | O worker nunca recebe id inexistente; nada fica `PENDING` órfão. |
| Claim e finalização por `UPDATE … WHERE status IN (…)` verificando `rowcount` | Idempotência e concorrência sem lock explícito. |
| Decisão de retry em função pura (`politica_retry.decidir`) | Testável sem Celery; a task só aplica a decisão. `autoretry_for` sozinho não grava o `ERROR` final. |
| Celery: `acks_late`, `task_reject_on_worker_lost`, serializer JSON, nome de task fixo, `rate_limit`, `prefetch_multiplier=1` | Entrega "pelo menos uma vez" e proteção do serviço externo. |
| Publicação sem retry interno do Celery (`retry=False`) e com timeout de conexão curto | Com Redis fora, o `POST` deve falhar rápido com `503`, não travar. |
| `request_id` viaja como argumento da task; `contextvars` no worker | Correlação API ⇄ worker nos logs. |
| `resultado` em `JSON().with_variant(JSONB, "postgresql")` | JSONB no Postgres, JSON nos testes em SQLite. |
| Log JSON com `logging` da stdlib; filtro injeta o contexto; só o logger `customer_lookup` é configurado | Sem dependência extra; não quebra `caplog`. |
| Rate limit: `INCR` + `EXPIRE` em pipeline, chave `rl:{hash da api key}:{janela}` | Atômico e simples; a chave de API nunca vai em claro para o Redis. |
| Fake com `async def` e `asyncio.sleep` | A lentidão simulada não bloqueia outras requisições do fake. |
| Alembic é o único que cria tabelas; `fileConfig(..., disable_existing_loggers=False)` | Padrão de produção; não desligar os loggers da aplicação. |
| Compose sem `.env` obrigatório (`${VAR:-padrão}`) | `docker compose up` sem configuração adicional. |

## 4. Estratégia de testes
| Nível | O que cobre | Infra |
|---|---|---|
| unit | documento, política de retry, cliente httpx (`MockTransport`), schemas, logging, configuração Celery | nenhuma |
| integration | API (TestClient) + service + SQLite em arquivo + fakes das portas; fake externo; task em modo eager | nenhuma |
| infra | compose, Dockerfile, migrações (upgrade/downgrade, sincronia com models) | nenhuma |
| e2e (`-m e2e`) | fluxo real com `docker compose up` | Docker |

Fakes: `PublicadorFake` (registra ids e o momento em relação ao commit; pode simular falha) e `ClienteExternoFake`
(roteiro de respostas e exceções). Rate limit testado com `fakeredis`.

## 5. Pontos de atenção
| Ponto | Tratamento |
|---|---|
| `fileConfig` do Alembic desliga loggers | `disable_existing_loggers=False` |
| Celery substitui o logging do worker | conectar `configure_logging` ao sinal `setup_logging` |
| Datas naive (SQLite) vs aware (Postgres) | normalizar para UTC na leitura; `refresh` antes de comparar nos testes |
| CRLF quebra scripts no container | `.gitattributes` com `* text=auto eol=lf` |
| Demonstração lenta com backoff padrão | `RETRY_BASE_SEGUNDOS` e `RETRY_TETO_SEGUNDOS` configuráveis |

## 6. Débitos técnicos e melhorias
Registro do que foi simplificado conscientemente. A versão final vai para o README.

| Débito | Por que foi aceito | Risco | Melhoria |
|---|---|---|---|
| Sem outbox transacional | Falha de publicação já vira `ERROR` + `503` (sem órfão) | Cliente precisa reenviar quando a fila cai | Outbox na mesma transação + publicador dedicado |
| Sem circuit breaker | Backoff, jitter e concorrência baixa já limitam a carga | Com o externo fora, cada consulta ainda gasta suas tentativas | Abrir o circuito após N falhas seguidas e adiar novas chamadas |
| Chamada externa duplicada possível entre workers | Resultado final é o mesmo e só um grava | Uma chamada extra ao externo | `SELECT … FOR UPDATE SKIP LOCKED` ou lock no Redis |
| Paginação por offset | Simples e com total | Lenta em páginas profundas | Paginação por cursor (keyset) |
| Fake com estado em memória | Suficiente para demonstração | Contadores somem ao reiniciar | Estado em Redis |
| Sem `Idempotency-Key` no `POST` | Fora do escopo pedido | Reenvio do cliente cria consulta duplicada | Header `Idempotency-Key` com unicidade no banco |
| API key única, sem rotação nem escopos | Enunciado dispensa autenticação sofisticada | Vazamento exige troca manual | Várias chaves com hash no banco, ou OAuth2/JWT |
| Rate limit por janela fixa | Simples e atômico | Rajada na virada da janela | Janela deslizante ou token bucket |
| Sem métricas nem tracing | Logs estruturados cobrem o diagnóstico pedido | Sem visão agregada | Prometheus + OpenTelemetry |
| Sem HTTPS | Ambiente local | Chave trafega em claro fora de localhost | Proxy reverso com TLS |
| Sem retenção de consultas antigas | Volume pequeno | Crescimento da tabela | Job de expurgo por idade |
| CNPJ alfanumérico não suportado | Regra nova, fora do escopo | Rejeição de CNPJs novos | Estender `core/documento.py` |
| Sem DLQ | Erros são gravados na própria consulta | Mensagem malformada só aparece no log | Fila de mensagens mortas |
| Consulta presa em `PROCESSING` se o broker cair durante o agendamento do retry | Janela muito pequena | Consulta sem desfecho | Reconciliação periódica de `PROCESSING` antigas |
