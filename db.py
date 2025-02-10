from typing import Optional
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, ForeignKey, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from datetime import datetime

class Base(DeclarativeBase):
    pass

class Building(Base):
    __tablename__ = "buildings"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str]
    name: Mapped[str]  # Example: "Main Library", "Engineering Hall"
    address: Mapped[Optional[str]]  # Optional: Full address if needed
    additional_info: Mapped[Optional[str]]  # Example: "Renovated in 2020"

    # Relationship to Access Points
    access_points = relationship("AccessPoint", back_populates="building")

class AccessPoint(Base):
    __tablename__ = "access_points"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str]  # e.g., "Elevator", "Accessible Door Button", "Ramp"
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id"))
    location_details: Mapped[str]  # Example: "Main entrance", "Hallway near room 205"
    status_history = relationship("AccessPointStatus", back_populates="access_point", order_by="AccessPointStatus.timestamp")    remarks: Mapped[str]

class AccessPointStatus(Base):
    __tablename__ = "access_point_status"
    id: Mapped[int] = mapped_column(primary_key=True)
    access_point_id: Mapped[int] = mapped_column(ForeignKey("access_points.id"))
    status: Mapped[str]  # Example: "Operational", "Out of Service", "Maintenance"
    timestamp: Mapped[datetime]  # When the status was recorded
    notes: Mapped[Optional[str]]  # Additional context if needed

    # Relationship to AccessPoint
    access_point = relationship("AccessPoint", back_populates="status_history")


class AccessPointMetadata(Base):
    """
    Stores custom key-value metadata for each access point type.
    Example:
      - Elevator: {"capacity": "1000 lbs", "manufacturer": "Otis"}
      - Door Button: {"height": "40 inches", "power_source": "Battery"}
    """
    __tablename__ = "access_point_metadata"
    access_point_id: Mapped[int] = mapped_column(ForeignKey("access_points.id"), primary_key=True)
    key: Mapped[str] = mapped_column(primary_key=True)  # Example: "capacity", "height"
    value: Mapped[str]  # Example: "1000 lbs", "40 inches"
    access_point: Mapped[AccessPoint] = relationship()

class Image(Base):
    __tablename__ = "images"
    id: Mapped[int] = mapped_column(primary_key=True)
    caption: Mapped[str]
    alttext: Mapped[str]
    ordering: Mapped[int]
    imghash: Mapped[str]
    attribution: Mapped[str]
    datecreated: Mapped[datetime]
    fullsizehash: Mapped[Optional[str]]

class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]  # Example: "ADA Compliant", "Automatic Door", "Braille Signage"
    description: Mapped[str]

class AccessPointTag(Base):
    __tablename__ = "access_point_tags"
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    tag: Mapped[Tag] = relationship()
    access_point_id: Mapped[int] = mapped_column(ForeignKey("access_points.id"), primary_key=True)
    access_point: Mapped[AccessPoint] = relationship()

class AccessPointImageRelation(Base):
    __tablename__ = "access_point_image_relation"
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id"), primary_key=True)
    image: Mapped[Image] = relationship()
    access_point_id: Mapped[int] = mapped_column(ForeignKey("access_points.id"), primary_key=True)
    access_point: Mapped[AccessPoint] = relationship()

class Feedback(Base):
    __tablename__ = "feedback"
    feedback_id: Mapped[int] = mapped_column(primary_key=True)
    notes: Mapped[str]
    contact: Mapped[str]
    time: Mapped[str]
    access_point_id: Mapped[int] = mapped_column(ForeignKey("access_points.id"))
    access_point: Mapped[AccessPoint] = relationship()

db = SQLAlchemy(model_class=Base)