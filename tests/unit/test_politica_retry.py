"""Política de retry (RN-06): função pura, testável sem Celery."""

import pytest

from customer_lookup.services.politica_retry import PoliticaRetry, Retentar

SEM_JITTER = 0.5  # aleatorio() = 0,5 → fator 1,0


def _politica(**kwargs: object) -> PoliticaRetry:
    padrao: dict[str, object] = {
        "max_tentativas": 5,
        "base_segundos": 2.0,
        "teto_segundos": 60.0,
        "aleatorio": lambda: SEM_JITTER,
    }
    return PoliticaRetry(**{**padrao, **kwargs})  # type: ignore[arg-type]


@pytest.mark.parametrize(("tentativa", "esperado"), [(1, 2.0), (2, 4.0), (3, 8.0), (4, 16.0)])
def test_backoff_dobra_a_cada_tentativa(tentativa: int, esperado: float):
    assert _politica().calcular_delay(tentativa) == esperado


def test_backoff_respeita_o_teto():
    politica = _politica(teto_segundos=10.0)

    assert politica.calcular_delay(3) == 8.0
    assert politica.calcular_delay(4) == 10.0
    assert politica.calcular_delay(30) == 10.0  # sem overflow nem crescimento depois do teto


@pytest.mark.parametrize(("sorteio", "fator"), [(0.0, 0.5), (0.25, 0.75), (0.999, 1.499)])
def test_jitter_multiplica_por_fator_entre_meio_e_um_e_meio(sorteio: float, fator: float):
    politica = _politica(aleatorio=lambda: sorteio)

    assert politica.calcular_delay(3) == pytest.approx(8.0 * fator)


def test_jitter_padrao_espalha_os_delays():
    politica = PoliticaRetry(max_tentativas=5, base_segundos=2.0, teto_segundos=60.0)

    delays = [politica.calcular_delay(2) for _ in range(200)]

    assert all(2.0 <= d <= 6.0 for d in delays)
    assert len(set(delays)) > 100  # não é constante: tentativas não sincronizam


def test_erro_transitorio_com_tentativas_restantes_pede_retry():
    decisao = _politica().decidir(retentavel=True, tentativa=1)

    assert decisao == Retentar(delay_s=2.0)


def test_erro_transitorio_na_ultima_tentativa_finaliza():
    assert _politica(max_tentativas=5).decidir(retentavel=True, tentativa=4) == Retentar(delay_s=16.0)
    assert _politica(max_tentativas=5).decidir(retentavel=True, tentativa=5) is None


def test_erro_permanente_nunca_pede_retry():
    assert _politica().decidir(retentavel=False, tentativa=1) is None


def test_max_uma_tentativa_desliga_o_retry():
    assert _politica(max_tentativas=1).decidir(retentavel=True, tentativa=1) is None


def test_politica_a_partir_das_settings():
    from customer_lookup.core.config import Settings

    settings = Settings(api_key="x", retry_max_tentativas=3, retry_base_segundos=1.0, retry_teto_segundos=5.0)

    politica = PoliticaRetry.de_settings(settings)

    assert (politica.max_tentativas, politica.base_segundos, politica.teto_segundos) == (3, 1.0, 5.0)
