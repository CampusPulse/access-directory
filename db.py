from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, ForeignKey, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass

class Mural(Base):
    __tablename__ = "murals"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    artistknown: Mapped[bool]
    remarks: Mapped[str]
    notes: Mapped[str]
    private_notes: Mapped[str]
    year: Mapped[int]
    location: Mapped[str]
    nextmuralid: Mapped[Optional[int]] = mapped_column(ForeignKey("murals.id"))
    nextmural: Mapped[Optional["Mural"]] = relationship()
    active: Mapped[bool]
    spotify: Mapped[str]

class Artist(Base):
    __tablename__ = "artists"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    notes: Mapped[str]

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
    name: Mapped[str]
    description: Mapped[str]

class ArtistMuralRelation(Base):
    __tablename__ = "artistmuralrelation"
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id"), primary_key=True)
    artist: Mapped[Artist] = relationship()
    mural_id: Mapped[int] = mapped_column(ForeignKey("murals.id"), primary_key=True)
    mural: Mapped[Mural] = relationship()

class ImageMuralRelation(Base):
    __tablename__ = "imagemuralrelation"
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id"), primary_key=True)
    image: Mapped[Image] = relationship()
    mural_id: Mapped[int] = mapped_column(ForeignKey("murals.id"), primary_key=True)
    mural: Mapped[Mural] = relationship()

class MuralTag(Base):
    __tablename__ = "mural_tags"
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    tag: Mapped[Tag] = relationship()
    mural_id: Mapped[int] = mapped_column(ForeignKey("murals.id"), primary_key=True)
    mural: Mapped[Mural] = relationship()

class Feedback(Base):
    __tablename__ = "feedback"
    feedback_id: Mapped[int] = mapped_column(primary_key=True)
    notes: Mapped[str]
    contact: Mapped[str]
    time: Mapped[str]
    mural_id: Mapped[int] = mapped_column(ForeignKey("murals.id"))
    mural: Mapped[Mural] = relationship()

db = SQLAlchemy(model_class=Base)