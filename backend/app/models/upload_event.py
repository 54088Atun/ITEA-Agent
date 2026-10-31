"""上传事件表:用于按用户/按日统计配额,避免依赖文件系统"""
from sqlalchemy import Column, BigInteger, String, Integer, DateTime, ForeignKey, func
from app.db.session import Base

BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class UploadEvent(Base):
    __tablename__ = "upload_events"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String(20), nullable=False, default="image", comment="image/audio/file")
    size = Column(Integer, nullable=False, default=0, comment="字节数")
    created_at = Column(DateTime, server_default=func.now(), index=True)
