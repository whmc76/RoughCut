import asyncio
from sqlalchemy import select
from roughcut.db.session import get_session_factory
from roughcut.db.models import Job
import uuid

async def main():
    async with get_session_factory()() as session:
        job=await session.get(Job, uuid.UUID('653995ce-3399-4f22-ad57-a46259f1b814'))
        print('workflow', job.workflow_template)
        print('enhancement', job.enhancement_modes)
        print('file_hash', job.file_hash)

asyncio.run(main())
