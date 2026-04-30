"""Tests para _make_progress_writer: barra simple de progreso a stderr (sin deps)."""
import io
import sys

from smv_peru.client import _make_progress_writer


def test_no_op_si_total_es_uno():
    # No tiene sentido una barra para una sola llamada → siempre no-op
    tick = _make_progress_writer(1, "label")
    # Llamarlo no debe romper ni escribir nada
    tick()


def test_no_op_si_stderr_no_es_tty(monkeypatch):
    # En pytest stderr normalmente no es TTY → la barra debe no-op silenciosamente
    fake = io.StringIO()
    monkeypatch.setattr(sys, "stderr", fake)
    tick = _make_progress_writer(10, "label")
    for _ in range(10):
        tick()
    assert fake.getvalue() == ""  # nada escrito


def test_escribe_a_stderr_si_es_tty(monkeypatch):
    # Forzamos isatty=True y verificamos que se escribe la barra
    class FakeTTY(io.StringIO):
        def isatty(self):
            return True

    fake = FakeTTY()
    monkeypatch.setattr(sys, "stderr", fake)
    tick = _make_progress_writer(3, "test")
    tick()
    tick()
    tick()
    output = fake.getvalue()
    assert "test" in output
    assert "1/3" in output
    assert "2/3" in output
    assert "3/3" in output
    assert output.endswith("\n")  # libera la línea al terminar
