import asyncio

from sqlalchemy import select

from roughcut.db.models import PublicationAttempt
from roughcut.db.session import get_session_factory

BLOCKERS = {
    "85cf232ad90a414d9f41342bbfe88779": (
        "youtube_final_schedule_button_disabled",
        "YouTube 已读写标题、说明、缩略图和 2026-05-23 20:00 时间，且检查通过；但最终“预定”按钮由平台组件重新置为禁用，未出现预约回执，不能判定发布成功。",
    ),
    "80e6c37b127e4b38a393e9561274d076": (
        "xiaohongshu_schedule_and_cover_not_verified",
        "小红书已读到视频、标题和正文，但封面仍显示默认第一帧提示，定时发布未读到具体时间回执，不能点击最终发布。",
    ),
    "3af0d21581b74456b2e4576b11e9d4d5": (
        "kuaishou_publish_form_reset",
        "快手发布页当前回到上传入口，未读到已上传视频、标题、正文、封面和定时设置，不能点击最终发布。",
    ),
    "a73d739e918f46f4bd9daa72c662cc1d": (
        "toutiao_video_form_not_available",
        "头条视频发布页当前未加载可用上传/编辑控件，未读到视频草稿和字段，不能点击最终发布。",
    ),
}


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        for attempt_id, (code, message) in BLOCKERS.items():
            attempt = (
                await session.execute(select(PublicationAttempt).where(PublicationAttempt.id == attempt_id))
            ).scalar_one_or_none()
            if not attempt:
                continue
            attempt.status = "needs_human"
            attempt.run_status = "needs_human"
            attempt.provider_status = "needs_human"
            attempt.error_code = code
            attempt.error_message = message
            attempt.operator_summary = f"最终发布未完成：{message}"
        await session.commit()


asyncio.run(main())
