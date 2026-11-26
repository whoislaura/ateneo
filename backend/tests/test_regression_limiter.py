"""Regresión: los fallos de login concurrentes no deben subcontar el limitador."""

from threading import Barrier, Thread

from app import auth

THREADS = 8


def test_concurrent_fail_counts_every_attempt():
    barrier = Barrier(THREADS)

    def clock():
        barrier.wait(timeout=5)
        return 1000.0

    limiter = auth.LoginLimiter(clock=clock)

    def attempt():
        limiter.fail(" Usuario@Ateneo.cu", "203.0.113.7")

    threads = [Thread(target=attempt) for _ in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert limiter.failures["email:usuario@ateneo.cu|203.0.113.7"][1] == THREADS
    assert limiter.failures["ip:203.0.113.7"][1] == THREADS


def test_account_counter_is_per_ip_and_succeed_clears_only_that_key(monkeypatch):
    monkeypatch.setattr(auth, "LOGIN_MAX_ATTEMPTS", 2)
    limiter = auth.LoginLimiter(clock=lambda: 1000.0)
    for _ in range(5):
        limiter.fail("admin@ateneo.cu", "198.51.100.1")  # atacante
    assert limiter.retry_after("admin@ateneo.cu", "198.51.100.1")
    assert limiter.retry_after("admin@ateneo.cu", "203.0.113.7") == 0  # el admin real no se ve
    limiter.fail("admin@ateneo.cu", "203.0.113.7")
    limiter.succeed("admin@ateneo.cu", "203.0.113.7")
    assert "email:admin@ateneo.cu|203.0.113.7" not in limiter.failures
    assert "email:admin@ateneo.cu|198.51.100.1" in limiter.failures
