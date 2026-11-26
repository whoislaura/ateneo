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

    assert limiter.failures["email:usuario@ateneo.cu"][1] == THREADS
    assert limiter.failures["ip:203.0.113.7"][1] == THREADS
