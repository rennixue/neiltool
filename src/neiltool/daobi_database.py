import logging
from textwrap import dedent

import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine

from .models.operation import OrderFileRemote, OrderInfo

logger = logging.getLogger(__name__)


class DaobiDatabase:
    def __init__(self, url: str) -> None:
        self._engine = create_async_engine(url, pool_size=2, pool_recycle=600)

    async def is_healthy(self) -> bool:
        try:
            async with self._engine.connect() as conn:
                cursor = await conn.execute(sqlalchemy.text("SELECT 1"))
                assert cursor.scalar_one() == 1
        except Exception as exc:
            logger.error("fail to connect to daobi_database: %r", exc)
            return False
        else:
            return True

    async def fetch_order_info(self, order_id: int) -> OrderInfo | None:
        async with self._engine.connect() as conn:
            cursor = await conn.execute(
                sqlalchemy.text(
                    dedent("""
                        SELECT
                            c.id order_id, c.order_no order_name,
                            o.`type` order_type, o.course_code, o.course_name,
                            su.name univ_name,
                            u.username student_name
                        FROM stud_course c
                        JOIN stud_purchase_order o ON c.id = o.course_id
                        LEFT JOIN sys_university su ON o.university_id = su.id
                        LEFT JOIN stud_user u ON c.user_id = u.user_id
                        WHERE c.id = :order_id
                        LIMIT 1
                    """)
                ),
                {"order_id": order_id},
            )
            row = cursor.one_or_none()
            if row is None:
                return None
            info = OrderInfo.model_validate(row, from_attributes=True)
            cursor = await conn.execute(
                sqlalchemy.text(
                    dedent("""
                        SELECT
                            o.remark, o.oper_remark, o.special_offer_remark,
                            o.seller_demand_desc, o.description, o.general_client_message,
                            cc.first_lesson_needs, cc.other_needs, cc.order_requirements
                        FROM stud_purchase_order o
                        LEFT JOIN stud_course_customized cc ON cc.course_id = o.course_id
                        WHERE o.course_id = :order_id
                        LIMIT 1
                    """)
                ),
                {"order_id": order_id},
            )
            row = cursor.one_or_none()
            if row is None:
                needs = {}
            else:
                needs = {k: v for k, v in row._asdict().items() if v and v != "[]"}  # pyright: ignore[reportPrivateUsage]
        if needs:
            info.needs = needs
        return info

    async def fetch_order_files(self, order_id: int) -> list[OrderFileRemote]:
        async with self._engine.connect() as conn:
            cursor = await conn.execute(
                sqlalchemy.text(
                    dedent("""
                        SELECT w.id file_id, w.cd_id order_id, w.name, w.url
                        FROM stud_courseware w
                        WHERE w.delete_flag = 0 AND w.is_hide = 0
                        AND w.cd_id = :order_id
                        /* AND w.group_id IN (5, 6, 7, 9, 21, 22, 23, 24, 26) */
                        AND w.name RLIKE '.zip$|.rar$|.pdf$|.docx$|.doc$|.pptx$|.ppt$|.png$|.jpg$|.jpeg$|.webp$|.txt$'
                        AND w.url <> ''
                        ORDER BY w.id
                        LIMIT 100
                    """)
                ),
                {"order_id": order_id},
            )
            rows = cursor.all()
        return [OrderFileRemote.model_validate(row, from_attributes=True) for row in rows]
