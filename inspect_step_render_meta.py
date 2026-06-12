import asyncio, json
from sqlalchemy import select
from roughcut.db.session import get_session_factory
from roughcut.db.models import JobStep
import uuid

async def main():
    async with get_session_factory()() as session:
        job_id=uuid.UUID('653995ce-3399-4f22-ad57-a46259f1b814')
        res=await session.execute(select(JobStep).where(JobStep.job_id==job_id, JobStep.step_name=='render'))
        step=res.scalar_one()
        print('status', step.status)
        print('error', step.error_message)
        print('metadata detail', step.metadata_.get('detail'))
        print('metadata keys', list(step.metadata_.keys()))
        if step.metadata_:
            for k,v in step.metadata_.items():
                if k in ('progress',):
                    print('  ',k,v)
        print('started', step.started_at, step.finished_at)

asyncio.run(main())
