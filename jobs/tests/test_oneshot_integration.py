"""Optional real RabbitMQ/prefork proof of single-delivery settlement."""

import os
from pathlib import Path
import subprocess
import sys
import uuid

from celery import Celery
import pytest


@pytest.mark.skipif(
    not os.getenv("SCHOLENS_TEST_BROKER_URL"), reason="isolated RabbitMQ not configured"
)
def test_real_prefork_worker_acknowledges_only_one_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = "oneshot-" + uuid.uuid4().hex
    broker = os.environ["SCHOLENS_TEST_BROKER_URL"]
    # Other tests initialize the product app; this probe owns both connections.
    monkeypatch.setenv("CELERY_BROKER_URL", broker)
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "cache+memory://")
    (tmp_path / "probe.py").write_text(
        "import os\n"
        "from celery import Celery\n"
        "from src.oneshot import OneShotConsumer\n"
        "app = Celery('probe', broker=os.environ['SCHOLENS_TEST_BROKER_URL'], "
        "task_cls='src.oneshot:OneShotTask')\n"
        "app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, "
        "task_ignore_result=True)\n"
        "app.steps['consumer'].add(OneShotConsumer)\n"
        "@app.task(name='probe.noop')\n"
        "def noop(): return None\n"
    )
    app = Celery("producer", broker=broker)
    env = {
        **os.environ,
        "SCHOLENS_WORKER_ONE_SHOT": "1",
        "PYTHONPATH": os.pathsep.join([str(tmp_path), str(Path.cwd())]),
    }
    with app.connection_for_write() as connection:
        channel = connection.channel()
        channel.queue_declare(queue=queue, durable=True, auto_delete=False)
        try:
            for _ in range(2):
                app.send_task("probe.noop", queue=queue, ignore_result=True)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "celery",
                    "-A",
                    "probe",
                    "worker",
                    "--queues",
                    queue,
                    "--concurrency=1",
                    "--pool=prefork",
                    "--without-gossip",
                    "--without-mingle",
                    "--without-heartbeat",
                    "--loglevel=WARNING",
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=70,
            )
            assert result.returncode == 0, result.stderr[-4000:]
            assert channel.queue_declare(queue=queue, passive=True).message_count == 1
        finally:
            channel.queue_delete(queue=queue)
