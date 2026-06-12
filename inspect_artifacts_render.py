import asyncio
from sqlalchemy import select
from roughcut.db.session import get_session_factory
from roughcut.db.models import Artifact
import uuid

async def main():
    async with get_session_factory()() as session:
        job_id=uuid.UUID('653995ce-3399-4f22-ad57-a46259f1b814')
        rs=await session.execute(
            select(Artifact).where(Artifact.job_id==job_id).order_by(Artifact.created_at.desc())
        )
        for art in rs.scalars():
            if 'render' in art.artifact_type or 'packaging' in art.artifact_type or 'avatar' in art.artifact_type or 'cover' in art.artifact_type or art.artifact_type=='render_outputs':
                print(art.created_at, art.artifact_type, art.storage_path)

asyncio.run(main())
