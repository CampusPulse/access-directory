from sqlalchemy import select, func, text, cast, String
from sqlalchemy.orm import with_polymorphic

from db import AccessPoint, Location



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
        func.coalesce(poly.remarks, '') + ' ' +
        func.coalesce(Location.name, '') + ' ' +
        func.coalesce(Location.building_code, '') + ' ' +
        func.coalesce(cast(poly.DoorButton.shelter, String), '') + ' ' +
        func.coalesce(cast(poly.DoorButton.activation, String), '') + ' ' +
        func.coalesce(poly.Elevator.manufacturer, '')
    )

    # Build the SQLAlchemy 2.0 select statement
    stmt = (
        select(poly)
        .outerjoin(poly.location)  # Join Location model/relationship
        .where(
            searchable_document.op('@@')(
                func.websearch_to_tsquery('english', query)
            )
        )
        .order_by(poly.id)
        .limit(150)
    )

    scalars = db.session.scalars(stmt).all()

    return list(
        map(
            access_point_json,
            scalars,
        )
    )
