import asyncio, json
from sqlalchemy import select
from roughcut.db.session import get_session_factory
from roughcut.db.models import RenderOutput, Job
import uuid

async def main():
    async with get_session_factory()() as session:
        job_id=uuid.UUID('653995ce-3399-4f22-ad57-a46259f1b814')
        rs=await session.execute(select(RenderOutput).where(RenderOutput.job_id==job_id).order_by(RenderOutput.created_at.desc()))
        for ro in rs.scalars():
            print('render_output', ro.id, ro.status, ro.progress, ro.output_path)
            print('data_json keys', list((ro.data_json or {}).keys()))
            if ro.data_json:
                print('keys preview', list((ro.data_json or {}).keys())[:10])
            print()

asyncio.run(main())
