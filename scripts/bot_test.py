"""End-to-end bot handler test with a mocked Telegram API.

Run: python -m scripts.bot_test
"""

import asyncio
import datetime as dt
import sys

from aiogram import Bot, Dispatcher
from aiogram.methods import (
    AnswerCallbackQuery,
    CopyMessage,
    EditMessageReplyMarkup,
    EditMessageText,
    GetMe,
    SendDocument,
    SendMessage,
)
from aiogram.types import (
    CallbackQuery,
    Chat,
    Document,
    Message,
    MessageId,
    PhotoSize,
    Update,
    User,
)


class MockBot(Bot):
    def __init__(self) -> None:
        super().__init__("123456:TEST-dummy-token-for-local-import-check")
        self.calls: list[str] = []
        self.sent_texts: list[str] = []

    async def __call__(self, method, request_timeout=None):  # type: ignore[override]
        name = method.__class__.__name__
        self.calls.append(name)
        now = dt.datetime.now()
        chat_id = getattr(method, "chat_id", 42) or 42

        def make_message(text="") -> Message:
            return Message(
                message_id=len(self.calls),
                date=now,
                chat=Chat(id=chat_id, type="private"),
                text=text,
            )

        if isinstance(method, GetMe):
            return User(id=1, is_bot=True, first_name="TGBed", username="testbot")
        if isinstance(method, SendMessage):
            self.sent_texts.append(method.text)
            return make_message(method.text)
        if isinstance(method, CopyMessage):
            return MessageId(message_id=len(self.calls))
        if isinstance(method, SendDocument):
            return Message(
                message_id=len(self.calls),
                date=now,
                chat=Chat(id=chat_id, type="private"),
                document=Document(
                    file_id="DOCFILEID",
                    file_unique_id="DOCUNIQ",
                    file_name="upload.png",
                    mime_type="image/png",
                    file_size=2048,
                ),
            )
        if isinstance(method, EditMessageText):
            return make_message(method.text)
        if isinstance(method, EditMessageReplyMarkup):
            return make_message()
        if isinstance(method, AnswerCallbackQuery):
            return True
        return True


def _photo_message(uid: int) -> Message:
    return Message(
        message_id=10,
        date=dt.datetime.now(),
        chat=Chat(id=uid, type="private"),
        from_user=User(id=uid, is_bot=False, first_name="Uploader"),
        photo=[
            PhotoSize(file_id="PHOTOFILE", file_unique_id="PHOTOUNIQ", width=800, height=600, file_size=5000)
        ],
    )


async def main() -> int:
    from app.bot import admin, common, deletion, info, upload
    from app.bot.middlewares import ContextMiddleware
    from app.config import settings
    from app.db import SessionLocal, init_db
    from app.services import find_user_images

    await init_db()
    settings.storage_chat_id = -1001234567890  # ensure archive step runs in test

    bot = MockBot()
    info.set_bot_username("testbot")
    dp = Dispatcher()
    dp.update.middleware(ContextMiddleware())
    dp.include_router(common.router)
    dp.include_router(info.router)
    dp.include_router(upload.router)
    dp.include_router(deletion.router)
    dp.include_router(admin.router)

    uid = 555000111
    seq = 0

    async def feed(update: Update) -> None:
        await dp.feed_update(bot, update)

    msg = 100

    def update_with_message(m: Message) -> Update:
        nonlocal seq
        seq += 1
        return Update(update_id=seq, message=m)

    # /start
    seq += 1
    await feed(
        Update(
            update_id=seq,
            message=Message(
                message_id=msg, date=dt.datetime.now(),
                chat=Chat(id=uid, type="private"),
                from_user=User(id=uid, is_bot=False, first_name="Uploader"),
                text="/start",
            ),
        )
    )

    # send a photo -> expect SendMessage with a link and DB row
    seq += 1
    await feed(Update(update_id=seq, message=_photo_message(uid)))

    async with SessionLocal() as session:
        images = await find_user_images(session, uid)
        assert len(images) == 1, f"expected 1 image, got {len(images)}"
        image_id = images[0].id
        # archive copy must record the storage chat (regression: copy_message -> MessageId)
        assert images[0].storage_chat_id == settings.storage_chat_id, images[0].storage_chat_id
        assert images[0].storage_message_id is not None

    # trigger delete callback
    seq += 1
    cb = CallbackQuery(
        id="cb1",
        from_user=User(id=uid, is_bot=False, first_name="Uploader"),
        chat_instance="ci",
        data=f"delyes:{image_id}",
        message=Message(message_id=msg, date=dt.datetime.now(), chat=Chat(id=uid, type="private")),
    )
    await feed(Update(update_id=seq, callback_query=cb))

    async with SessionLocal() as session:
        images = await find_user_images(session, uid)
        assert len(images) == 0, "image should be soft-deleted"

    # /id in private chat -> returns Chat ID / user ID
    seq += 1
    await feed(
        Update(
            update_id=seq,
            message=Message(
                message_id=msg, date=dt.datetime.now(),
                chat=Chat(id=uid, type="private"),
                from_user=User(id=uid, is_bot=False, first_name="Uploader"),
                text="/id",
            ),
        )
    )
    assert any("Chat ID" in t for t in bot.sent_texts), "private /id should return Chat ID"

    # @mention in a group -> returns group Chat ID
    group_id = -100777888999
    before = len(bot.sent_texts)
    seq += 1
    await feed(
        Update(
            update_id=seq,
            message=Message(
                message_id=msg, date=dt.datetime.now(),
                chat=Chat(id=group_id, type="supergroup", title="My Group"),
                from_user=User(id=uid, is_bot=False, first_name="Uploader"),
                text="@testbot 查一下 ID",
            ),
        )
    )
    assert len(bot.sent_texts) == before + 1, "group mention should get exactly one reply"
    assert str(group_id) in bot.sent_texts[-1], "reply should include group chat id"

    assert "SendMessage" in bot.calls, bot.calls
    assert "CopyMessage" in bot.calls, bot.calls
    assert "EditMessageText" in bot.calls, bot.calls
    print("BOT_TEST_OK", bot.calls)
    await bot.session.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
