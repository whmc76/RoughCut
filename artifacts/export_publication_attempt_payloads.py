import asyncio
import json

from sqlalchemy import select

from roughcut.db.models import PublicationAttempt
from roughcut.db.session import get_session_factory

JOB_ID = "334be3ca-b2fb-470a-8135-c31e2e30ec38"


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        attempts = (
            await session.execute(select(PublicationAttempt).where(PublicationAttempt.job_id == JOB_ID))
        ).scalars().all()
        payloads = []
        for attempt in attempts:
            request = dict(attempt.request_payload or {})
            payloads.append(
                {
                    "id": attempt.id,
                    "platform": attempt.platform,
                    "status": attempt.status,
                    "title": request.get("title"),
                    "body": request.get("body"),
                    "hashtags": request.get("hashtags"),
                    "cover_path": request.get("cover_path"),
                    "media_items": request.get("media_items"),
                    "scheduled_publish_at": request.get("scheduled_publish_at"),
                    "collection": request.get("collection"),
                    "category": request.get("category"),
                    "response_result": (attempt.response_payload or {}).get("task", {}).get("result", {}),
                }
            )
        print(json.dumps(payloads, ensure_ascii=False, indent=2, default=str))


asyncio.run(main())
