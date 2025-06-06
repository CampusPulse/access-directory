from typing import Optional
import enum
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, ForeignKey, text, Enum as EnumType, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, with_polymorphic
from datetime import datetime
from helpers import RoomNumber


class ShelterType(enum.Enum):
    INTERIOR = 1
    EXTERIOR = 2
    VESTIBULE = 3

class ButtonActivation(enum.Enum):
    PUSH = 1
    WAVE = 2

class MountSurface(enum.Enum):
    WALL = 1
    POLE = 2

class MountStyle(enum.Enum):
    PROTRUDING = 1
    RECESSED = 2

class PowerSource(enum.Enum):
    HARDWIRED = 1
    BATTERY = 2

class StatusType(enum.Enum):
    UNKNOWN = 0
    BROKEN = 1
    IN_PROGRESS = 2
    FIXED = 3
    VERIFIED = 4

class Base(DeclarativeBase):
    pass

class Building(Base):
    __tablename__ = "building"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str]
    name: Mapped[str]  # Example: "Main Library", "Engineering Hall"
    acronym: Mapped[str]  # acronym Example: "EAS"
    short_name: Mapped[Optional[str]]  # Example: "Eastman"
    address: Mapped[Optional[str]]  # Optional: Full address if needed
    additional_info: Mapped[Optional[str]]  # Example: "Renovated in 2020"
    locations = relationship("Location", backref="building")

    def human_name(self):
        if self.short_name is not None and self.short_name != "":
            return self.short_name
        else:
            return self.acronym
    
    def toJSON(self):
        return {
            "id":self.number,
            "name": self.name,
            "acronym": self.acronym
        }


class Location(Base):
    __tablename__ = "location"
    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("building.id"))
    floor_number: Mapped[int] # negative -> Basement, 0 - any, positive -> floors
    room_number: Mapped[int] # only the room portion
    nickname: Mapped[Optional[str]]  # Example: "Main Library", "Engineering Hall"
    latitude: Mapped[Optional[int]] # northing
    longitude: Mapped[Optional[int]] # easting
    is_outside: Mapped[bool] = mapped_column(server_default='FALSE')
    additional_info: Mapped[Optional[str]]  # Example: "The accessible entrance between X and Y"
    access_points = relationship("AccessPoint", backref="location")

    def human_name(self):
        if self.nickname is not None and self.nickname != "":
            return self.nickname
        else:
            return RoomNumber(self.floor_number, self.room_number).to_string()


class AccessPoint(Base):
    __tablename__ = "access_point"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str]  # e.g., "Elevator", "Accessible Door Button", "Ramp"
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"))
    thumbnail_ref: Mapped[int] = mapped_column(ForeignKey("images.id"), nullable=True)
    remarks: Mapped[str]
    active: Mapped[bool]  # Whether the access point is still in use

    __mapper_args__ = {
        "polymorphic_identity": "access_point",
        "polymorphic_on": "type",
    }


class DoorButton(AccessPoint):
    __tablename__ = "door_button"
    id: Mapped[int] = mapped_column(ForeignKey("access_point.id"), primary_key=True)
    shelter: Mapped[EnumType(ShelterType)] = mapped_column(EnumType(ShelterType), nullable=True )
    activation: Mapped[EnumType(ButtonActivation)] = mapped_column(EnumType(ButtonActivation), nullable=True )
    mount_surface: Mapped[EnumType(MountSurface)] = mapped_column(EnumType(MountSurface), nullable=True )
    mount_style: Mapped[EnumType(MountStyle)] = mapped_column(EnumType(MountStyle), nullable=True )
    powered_by: Mapped[EnumType(PowerSource)] = mapped_column(EnumType(PowerSource), nullable=True )

    __mapper_args__ = {
        "polymorphic_identity": "door_button",
    }

class Elevator(AccessPoint):
    __tablename__ = "elevator"
    id: Mapped[int] = mapped_column(ForeignKey("access_point.id"), primary_key=True)
    floor_min: Mapped[int]
    floor_max: Mapped[int]
    door_count: Mapped[int] = mapped_column(server_default="1" )

    __mapper_args__ = {
        "polymorphic_identity": "elevator",
    }

class Report(Base):
    """
    A central place for information about reported (confirmed) issues.
    """
    __tablename__ = "report"
    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[Optional[str]] # ticket number/reference


class Status(Base):
    """
    Enables the storage of status history for each report.
    Current status can be retrieved by getting the latest item in the table by timestamp
    Notes can be added by updating the status to the same value with a new note
    """
    __tablename__ = "report_status"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("report.id"))
    status: Mapped[str]  # Example: "Operational", "Out of Service", "Maintenance"
    status_type: Mapped[EnumType(StatusType)] = mapped_column(EnumType(StatusType))
    timestamp: Mapped[datetime]  # When the status was recorded
    notes: Mapped[Optional[str]]  # Additional context if needed

    report = relationship("Report")

    def statusInfo(self):
        return (self.status_type, self.status)


class AccessPointReports(Base):
    """
    Mapping between Access Points and Reports
    """
    __tablename__ = "access_point_reports"
    report_id: Mapped[int] = mapped_column(ForeignKey("report.id"), primary_key=True)
    access_point_id: Mapped[int] = mapped_column(ForeignKey("access_point.id"), primary_key=True)



class Image(Base):
    __tablename__ = "images"
    id: Mapped[int] = mapped_column(primary_key=True)
    caption: Mapped[Optional[str]]
    alttext: Mapped[Optional[str]]
    attribution: Mapped[Optional[str]]
    datecreated: Mapped[datetime]
    fullsizehash: Mapped[str]
    naming_version: Mapped[int] = mapped_column(server_default='1')

class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]  # Example: "ADA Compliant", "Automatic Door", "Braille Signage"
    description: Mapped[str]

class AccessPointTag(Base):
    __tablename__ = "access_point_tags"
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    tag: Mapped[Tag] = relationship()
    access_point_id: Mapped[int] = mapped_column(ForeignKey("access_point.id"), primary_key=True)
    access_point: Mapped[AccessPoint] = relationship()

class ImageAccessPointRelation(Base):
    __tablename__ = "access_point_image_relation"
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id"), primary_key=True)
    image: Mapped[Image] = relationship()
    ordering: Mapped[int]
    access_point_id: Mapped[int] = mapped_column(ForeignKey("access_point.id"), primary_key=True)
    access_point: Mapped[AccessPoint] = relationship()

class Feedback(Base):
    __tablename__ = "feedback"
    feedback_id: Mapped[int] = mapped_column(primary_key=True)
    notes: Mapped[str]
    contact: Mapped[str]
    time: Mapped[str]
    access_point_id: Mapped[int] = mapped_column(ForeignKey("access_point.id"))
    access_point: Mapped[AccessPoint] = relationship()

db = SQLAlchemy(model_class=Base)