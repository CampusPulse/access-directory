from sqlalchemy import select, func, text, cast, String
from sqlalchemy.orm import with_polymorphic

from db import AccessPoint, Location, Building, db



def searchAccessPoints(query):
    """
    Search all access points given query
    """

    # with_polymorphic automatically joins subclass tables (door_button, elevator, etc.)
    poly = with_polymorphic(AccessPoint, "*")

    # Combine text fields from AccessPoint, Location, and Subclasses
    # Cast non-string types (like Enums, Integers) to String for text indexing
    searchable_document = func.to_tsvector(
        'english',
        func.coalesce(Location.nickname, '') + ' ' +
        func.coalesce(Building.name, '') + ' ' +
        func.coalesce(Building.short_name, '') + ' ' +
        func.coalesce(Building.acronym, '') + ' ' +
        func.coalesce(cast(poly.DoorButton.shelter, String), '') + ' ' +
        func.coalesce(cast(poly.DoorButton.activation, String), '') + ' '
    )

    # Build the SQLAlchemy 2.0 select statement
    stmt = (
        select(poly)
        .outerjoin(Location, poly.location_id == Location.id)
        .outerjoin(Building, Location.building_id == Building.id)
        .where(
            searchable_document.op('@@')(
                func.websearch_to_tsquery('english', query)
            )
        )
        .order_by(poly.id)
        .limit(150)
    )

    return db.session.scalars(stmt).all()
