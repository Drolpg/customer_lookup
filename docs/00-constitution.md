# 00 — Constituição do projeto

Princípios que valem para todas as decisões. Em caso de dúvida, volte aqui.

## 1. Objetivo
Serviço intermediário de consultas de clientes: recebe a solicitação por API, registra, processa de forma assíncrona
contra um serviço externo instável e permite acompanhar status e resultado. Qualidade suficiente para operar em
ambiente real: falhas previsíveis, diagnóstico por logs e execução simples com Docker.

## 2. Método: SDD + TDD
| Fase | Artefato |
|---|---|
| Especificar | `docs/01-spec.md` |
| Planejar | `docs/02-plan.md` |
| Quebrar em tarefas | `docs/03-tasks.md` |
| RED (testes que falham) | `tests/**` |
| GREEN (implementação mínima) | `src/**` |
| REFACTOR | `src/**`, com testes verdes |

Regras:
1. Mudou o comportamento? Muda a spec primeiro, depois o teste, depois o código.
2. Teste é critério de aceite: não se altera teste para "fazer passar".
3. Cada requisito da spec tem pelo menos um teste (matriz na seção 11 da spec).
4. Cada teste precisa poder falhar por um bug real; teste que só repete a implementação não entra.

## 3. Princípios de engenharia
- **Não bloquear**: a API responde na hora (`202`); trabalho lento e incerto vai para o worker.
- **Falhar de forma previsível**: todo erro tem código estável, status HTTP correto e log com contexto.
  O cliente nunca vê stack trace nem mensagem crua de framework.
- **Idempotência**: a fila entrega "pelo menos uma vez"; processar a mesma mensagem duas vezes não corrompe nada
  e estados finais nunca são sobrescritos.
- **Proteger o serviço externo**: timeout explícito, retry limitado com backoff e jitter, concorrência baixa.
- **Nenhuma transação aberta durante chamada de rede.**
- **Observabilidade desde o início**: logs JSON, `request_id` de ponta a ponta, `consulta_id` em todo log do domínio.
- **Dados pessoais**: documento nunca aparece em claro nos logs.
- **Segredos fora do código e do git**; banco e Redis não expostos ao host.
- **Simplicidade deliberada**: abstração só onde há fronteira real (serviço externo e fila). Sem repositório,
  sem container de injeção, sem ORM assíncrono. O que ficou de fora está listado como débito técnico.

## 4. Definition of Done
- [ ] Testes da tarefa verdes e suíte completa verde (`uv run pytest`).
- [ ] `uv run ruff check .`, `uv run ruff format --check .` e `uv run mypy` sem erros.
- [ ] Nenhum segredo, documento em claro ou stack trace em log ou resposta.
- [ ] Spec atualizada se o comportamento mudou.

## 5. Convenções
- Python 3.14, gerenciado com uv (`uv.lock` versionado). Type hints em todas as assinaturas.
- Domínio em português (`Consulta`, `documento`, `tentativas`), infraestrutura em inglês (`get_db`, `celery_app`).
  Status em inglês, como no contrato (`PENDING`, `PROCESSING`, `SUCCESS`, `ERROR`). `error.code` em inglês,
  mensagens ao cliente em português.
- Dependências apontam para dentro: `api → services → models`; `services` não importa FastAPI nem Celery,
  só as portas (`ports.py`).
- Commits no padrão Conventional Commits.
