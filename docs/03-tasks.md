# 03 — Tarefas (ordem de execução)

Cada marco: escrever os testes (RED) → implementar o mínimo (GREEN) → refatorar → `ruff check`, `ruff format --check`,
`mypy`, `pytest` verdes → commit. Marque `[x]` ao concluir.

## M0 — Especificação e repositório
- [x] Constituição, spec, plano e tarefas (`docs/00..03`).
- [x] `.gitattributes` com `* text=auto eol=lf`.

## M1 — Esqueleto
Alvo: `unit/test_logging.py`, `integration/test_erros_globais.py`, `integration/test_health.py` (liveness)
- [x] `pyproject.toml` (uv, Python 3.14), ruff, mypy, `pytest.ini` com marcador `e2e`.
- [x] `core/config.py` (`Settings` com todas as variáveis da spec §9, `get_settings` em cache).
- [x] `core/contexto.py` (`request_id`, `consulta_id` em `contextvars`) e `core/logging.py` (JSON + filtro de contexto).
- [x] `core/errors.py` (`AppError` e subclasses), `schemas/erro.py`, handlers e middleware de request id em `main.py`.
- [x] `GET /health`.

## M2 — Documento e schemas
Alvo: `unit/test_documento.py`, `unit/test_schemas.py`
- [x] `core/documento.py`: `normalizar`, `validar(documento, tipo, validar_dv)`, `mascarar`; CPF e CNPJ por módulo 11.
- [x] Teste que confirma que `12345678901` é inválido e `12345678909` é válido.
- [x] `schemas/consulta.py`: `ConsultaCreate` (`extra="forbid"`), `ConsultaCriada`, `ConsultaRead`, `PaginaConsultas`.

## M3 — Modelo e migração
Alvo: `infra/test_migrations.py`
- [x] `db/base.py`, `db/session.py`, `models/consulta.py` (enums `StatusConsulta`, `TipoDocumento`).
- [x] Alembic: `env.py` com URL das settings e `disable_existing_loggers=False`; migração inicial revisada.
- [x] Teste: `upgrade head`, `downgrade base` e models sincronizados com a migração.
- [ ] Validar `upgrade`/`downgrade` em Postgres real (coberto pelo E2E do M9).

## M4 — Criação, obtenção e listagem
Alvo: `integration/test_api_criar_consulta.py`, `test_api_obter_consulta.py`, `test_api_listar_consultas.py`
- [x] `ports.py`: `PublicadorDeTarefas` e `FalhaAoPublicar` (o `ClienteExterno` entra no M6, onde é usado).
- [x] `services/consulta_service.py`: `criar`, `obter`, `listar`.
- [x] Routers `v1/consultas.py` e `deps.py` (sessão, publicador).
- [x] Testes: 202 + `Location`; publicação depois do commit; 422 `VALIDATION_ERROR` e `INVALID_DOCUMENT`
      (nada gravado); 503 com consulta `ERROR`; 404; 422 de id; paginação, filtros e ordenação.

## M5 — API externa fake
Alvo: `integration/test_fake_externo.py`
- [ ] `fake_externo/app.py`: `/fake/customer`, `/fake/reset`, `/health`; cenários da spec §8.
- [ ] Teste de cada cenário, incluindo a recuperação após N falhas e o reset.

## M6 — Integração e processamento
Alvo: `unit/test_cliente_http.py`, `unit/test_politica_retry.py`, `integration/test_processar_consulta.py`
- [ ] `ports.py`: `ClienteExterno` e exceções de integração.
- [ ] `adapters/cliente_http.py` (httpx, timeouts, classificação em exceções de integração).
- [ ] `services/politica_retry.py` (`decidir` e `calcular_delay`, com aleatoriedade injetável).
- [ ] `processar_consulta`: claim, chamada fora de transação, sucesso, retry, esgotamento, permanente, idempotência,
      limite já atingido, outro worker finalizou antes.

## M7 — Celery
Alvo: `unit/test_celery_config.py`, `integration/test_task_celery.py`, `integration/test_fluxo_completo.py`
- [ ] `worker/celery_app.py` (configuração da spec e do plano; logging pelo sinal `setup_logging`).
- [ ] `worker/tasks.py` (task fina; `self.retry(countdown=…)`; restaura `request_id`).
- [ ] `adapters/publicador_celery.py` (falha rápida com Redis fora).
- [ ] Fluxo completo em modo eager; logs do worker com `request_id` e `consulta_id`; documento ausente dos logs.

## M8 — Autenticação, rate limit e readiness
Alvo: `integration/test_auth.py`, `integration/test_rate_limit.py`, `integration/test_health.py`
- [ ] `X-API-Key` com `secrets.compare_digest` e esquema de segurança no OpenAPI.
- [ ] `services/rate_limit.py` (janela fixa, `Retry-After`, fail-open).
- [ ] `GET /health/ready` (banco e Redis).

## M9 — Docker e E2E
Alvo: `infra/test_docker_compose.py`, `e2e/test_e2e_compose.py`
- [ ] `Dockerfile` multi-stage com uv e usuário não-root; `.dockerignore`.
- [ ] `docker-compose.yml`: `api`, `worker`, `externo`, `db`, `redis`; healthchecks; sem `.env` obrigatório.
- [ ] E2E: sucesso, recupera após retry, esgota, erro permanente.

## M10 — Entrega
Alvo: `integration/test_openapi.py`
- [ ] OpenAPI revisado (descrições, exemplos, erros no envelope, Authorize).
- [ ] CI (GitHub Actions): lint, format, mypy, testes com cobertura; validação e build do compose.
- [ ] README: objetivo, arquitetura, tecnologias, execução, testes, exemplos, decisões, débitos técnicos.
- [ ] Execução em clone limpo.
