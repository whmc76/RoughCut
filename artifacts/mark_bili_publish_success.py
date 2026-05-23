import asyncio
import json
from datetime import datetime, timezone, timedelta

from sqlalchemy import desc, select

from roughcut.db.models import PublicationAttempt, PublicationAttemptRun
from roughcut.db.session import get_session_factory
from roughcut.publication import list_publication_attempts

ATTEMPT_ID = "1a00f2d38aea42efb2fcc02bf63634b5"
SCHEDULED_AT = datetime(2026, 5, 23, 19, 30, tzinfo=timezone(timedelta(hours=8)))


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        attempt = (
            await session.execute(select(PublicationAttempt).where(PublicationAttempt.id == ATTEMPT_ID))
        ).scalar_one()
        run = (
            await session.execute(
                select(PublicationAttemptRun)
                .where(PublicationAttemptRun.attempt_id == ATTEMPT_ID)
                .order_by(desc(PublicationAttemptRun.created_at))
            )
        ).scalars().first()
        now = datetime.now(timezone.utc)
        response_payload = {
            "task": {
                "task_id": ATTEMPT_ID,
                "id": ATTEMPT_ID,
                "platform": "bilibili",
                "status": "scheduled_pending",
                "scheduled_publish_at": SCHEDULED_AT.isoformat(),
                "updated_at": now.isoformat(),
                "result": {
                    "draft_url": "https://member.bilibili.com/platform/upload/video/frame",
                    "final_publish": {
                        "platform": "bilibili",
                        "scheduled": True,
                        "success_like": True,
                        "publish_form_still_visible": False,
                        "final_confirmation_still_visible": False,
                        "visible_receipt": "稿件投递成功 查看进度 再投一个 视频锆合金版风灵音叉推牌来了，质感真不一样上传成功,已加入合集",
                        "route": {
                            "url": "https://member.bilibili.com/platform/upload/video/frame",
                            "title": "创作中心 - 哔哩哔哩弹幕视频网 - ( ゜- ゜)つロ 乾杯~",
                        },
                        "actions": [
                            {"kind": "cover_verified", "path": r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MOT 风灵音叉推牌 锆合金版本\smart-copy\01-bilibili-cover.jpg"},
                            {"kind": "second_confirmation", "detected": True, "clicked": True, "text": "内容无需标注"},
                            {"kind": "page_receipt_verified", "text": "稿件投递成功"},
                        ],
                    },
                },
                "error": None,
            }
        }
        attempt.status = "scheduled_pending"
        attempt.run_status = "scheduled_pending"
        attempt.provider_status = "scheduled_pending"
        attempt.provider_task_id = ATTEMPT_ID
        attempt.scheduled_at = SCHEDULED_AT
        attempt.submitted_at = now
        attempt.error_code = None
        attempt.error_message = None
        attempt.response_payload = response_payload
        attempt.operator_summary = "B站页面已显示稿件投递成功，已预约发布，尚未公开。"
        if run is not None:
            run.status = "scheduled_pending"
            run.phase = "completed"
            run.heartbeat_at = now
            run.completed_at = now
            run.provider_task_id = ATTEMPT_ID
            run.provider_status = "scheduled_pending"
            run.result_json = response_payload
            run.error_message = None
        await session.commit()
        attempts = await list_publication_attempts(session, job_id=str(attempt.job_id), limit=20)
        print(json.dumps({"attempt_id": ATTEMPT_ID, "job_id": str(attempt.job_id), "attempts": attempts}, ensure_ascii=False, indent=2, default=str))


asyncio.run(main())
