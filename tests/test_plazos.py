"""Criterio 5: plazos en días hábiles con festivos colombianos, fines de semana, hora de corte y suspensión."""
from datetime import date, datetime, time

from core import plazos
from core.reloj import TZ


def test_festivos_colombia_2026():
    for d in [date(2026, 1, 1), date(2026, 1, 12), date(2026, 3, 23), date(2026, 4, 2), date(2026, 4, 3),
              date(2026, 5, 1), date(2026, 7, 20), date(2026, 8, 7), date(2026, 10, 12), date(2026, 12, 8), date(2026, 12, 25)]:
        assert not plazos.es_habil(d), d


def test_fines_de_semana_no_son_habiles():
    assert not plazos.es_habil(date(2026, 10, 17))  # sábado
    assert not plazos.es_habil(date(2026, 10, 18))  # domingo
    assert plazos.es_habil(date(2026, 10, 16))       # viernes


def test_radicacion_antes_y_despues_de_hora_corte():
    antes = datetime(2026, 10, 15, 16, 59, tzinfo=TZ)
    despues = datetime(2026, 10, 15, 17, 1, tzinfo=TZ)
    assert plazos.fecha_radicacion(antes, time(17, 0)) == date(2026, 10, 15)
    assert plazos.fecha_radicacion(despues, time(17, 0)) == date(2026, 10, 16)


def test_radicacion_fin_de_semana_y_festivo_pasa_al_siguiente_habil():
    sabado = datetime(2026, 10, 17, 10, 0, tzinfo=TZ)
    assert plazos.fecha_radicacion(sabado) == date(2026, 10, 19)
    viernes_noche = datetime(2026, 10, 9, 18, 0, tzinfo=TZ)  # lunes 12 de octubre es festivo
    assert plazos.fecha_radicacion(viernes_noche) == date(2026, 10, 13)


def test_vencimiento_15_dias_salta_festivo():
    # Radicada el martes 13/10/2026; festivo 2/11 (Todos los Santos)
    v = plazos.fecha_vencimiento(date(2026, 10, 13), 15)
    assert v == date(2026, 11, 4)
    assert plazos.dias_habiles_entre(date(2026, 10, 13), v) == 15


def test_vencimiento_semana_santa():
    # Radicada el lunes 30/03/2026: jueves y viernes santos (2 y 3 de abril) no cuentan
    assert plazos.fecha_vencimiento(date(2026, 3, 30), 5) == date(2026, 4, 8)


def test_festivo_extra_de_la_empresa():
    extra = frozenset({date(2026, 10, 14)})
    assert plazos.fecha_vencimiento(date(2026, 10, 13), 1) == date(2026, 10, 14)
    assert plazos.fecha_vencimiento(date(2026, 10, 13), 1, extra) == date(2026, 10, 15)


def test_suspension_reinicia_termino():
    rad = date(2026, 9, 1)
    ven = plazos.fecha_vencimiento(rad, 15)
    nueva, susp = plazos.reanudar_tras_suspension(rad, ven, date(2026, 9, 8), date(2026, 9, 15), 15)
    assert nueva == plazos.sumar_habiles(date(2026, 9, 15), 15)
    assert susp == 5


def test_suspension_reanuda_dias_restantes():
    rad = date(2026, 9, 1)
    ven = plazos.fecha_vencimiento(rad, 15)
    restantes = plazos.dias_habiles_entre(date(2026, 9, 8), ven)
    nueva, _ = plazos.reanudar_tras_suspension(rad, ven, date(2026, 9, 8), date(2026, 9, 15), 15, "reanudar")
    assert plazos.dias_habiles_entre(date(2026, 9, 15), nueva) == restantes


def test_prorroga_maxima_y_validacion():
    rad = date(2026, 10, 1)
    ven = plazos.fecha_vencimiento(rad, 15)
    maximo = plazos.max_fecha_prorroga(rad, 15, None)
    assert plazos.dias_habiles_entre(rad, maximo) == 30
    assert plazos.validar_prorroga(ven, ven, maximo, maximo) is None
    assert "posterior" in plazos.validar_prorroga(rad, ven, ven, maximo)
    assert "supera" in plazos.validar_prorroga(rad, ven, plazos.sumar_habiles(maximo, 1), maximo)
    assert "venció" in plazos.validar_prorroga(plazos.sumar_habiles(ven, 1), ven, maximo, maximo)


def test_semaforo_niveles_y_texto():
    rad = date(2026, 10, 1)
    ven = plazos.fecha_vencimiento(rad, 10)
    assert plazos.semaforo(rad, ven, rad).nivel == "verde"
    assert plazos.semaforo(rad, ven, plazos.sumar_habiles(rad, 5)).nivel == "amarillo"
    assert plazos.semaforo(rad, ven, plazos.sumar_habiles(rad, 9)).nivel == "rojo"
    hoy = plazos.semaforo(rad, ven, ven)
    assert (hoy.nivel, hoy.texto) == ("rojo", "Vence hoy")
    v = plazos.semaforo(rad, ven, plazos.sumar_habiles(ven, 2))
    assert v.nivel == "negro" and "Vencida hace 2 días hábiles" in v.texto
    assert plazos.semaforo(rad, ven, rad, "PENDIENTE_INFO").nivel == "pausa"
    assert plazos.semaforo(rad, ven, rad, "CERRADA").nivel == "cerrado"
    s = plazos.semaforo(rad, ven, rad)
    assert s.icono and "Vence en" in s.texto  # nunca solo color
