import asyncio, json
from sqlalchemy import select
from roughcut.db.session import get_session_factory
from roughcut.db.models import Timeline
import uuid

async def main():
    async with get_session_factory()() as session:
        job_id=uuid.UUID('653995ce-3399-4f22-ad57-a46259f1b814')
        res=await session.execute(
            select(Timeline).where(Timeline.job_id==job_id, Timeline.timeline_type=='render_plan').order_by(Timeline.version.desc())
        )
        for tl in res.scalars():
            print('\nversion', tl.version)
            print(json.dumps(tl.data_json.get('avatar_commentary', {}) , ensure_ascii=False, indent=2))

asyncio.run(main())
