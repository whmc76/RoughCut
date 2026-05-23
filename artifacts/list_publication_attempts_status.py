import asyncio
import json

from roughcut.db.session import get_session_factory
from roughcut.publication import list_publication_attempts

JOB_ID = "334be3ca-b2fb-470a-8135-c31e2e30ec38"


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        attempts = await list_publication_attempts(session, job_id=JOB_ID, limit=50)
        keys = [
            "id",
            "platform",
            "platform_label",
            "status",
            "run_status",
            "provider_status",
            "scheduled_at",
            "error_code",
            "error_message",
            "operator_summary",
        ]
        print(json.dumps([{key: attempt.get(key) for key in keys} for attempt in attempts], ensure_ascii=False, indent=2, default=str))


asyncio.run(main())
