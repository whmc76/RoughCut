import asyncio
from sqlalchemy import select
from roughcut.db.session import get_session_factory
from roughcut.db.models import Timeline
import uuid

async def main():
    async with get_session_factory()() as session:
        job_id=uuid.UUID('653995ce-3399-4f22-ad57-a46259f1b814')
        res=await session.execute(
            select(Timeline).where(Timeline.job_id==job_id, Timeline.timeline_type=='render_plan').order_by(Timeline.version.asc())
        )
        rows=list(res.scalars())
        print('count', len(rows))
        for tl in rows:
            print('version', tl.version, 'id', tl.id, 'created', tl.created_at)
            plan=tl.data_json
            print('  avatar', bool(plan.get('avatar_commentary')), 'mode', (plan.get('avatar_commentary') or {}).get('mode'))
            print('  manual', plan.get('manual_editor',{}))
            print('  enhancement', bool(plan.get('cover') or plan.get('music') or plan.get('watermark') or plan.get('insert') or plan.get('intro') or plan.get('outro')))

asyncio.run(main())
