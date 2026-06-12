import asyncio
from sqlalchemy import select
from roughcut.db.session import get_session_factory
from roughcut.db.models import Job, JobStep
import uuid

async def main():
    factory=get_session_factory()
    async with factory() as session:
        job_id=uuid.UUID('653995ce-3399-4f22-ad57-a46259f1b814')
        res=await session.execute(select(JobStep).where(JobStep.job_id==job_id).order_by(JobStep.step_name))
        for step in res.scalars():
            if step.step_name in {'render','final_review','platform_package'}:
                print(step.step_name, step.status, step.error_message, (step.metadata_ or {}).get('detail'))

asyncio.run(main())
