# Helpers that are dependent on the database (to prevent circular imports)
from db import Report, AccessPointReports, AccessPoint, StatusType, Status

from typing import Union


def latest_status_for(session, item: Union[AccessPoint, int]):
    """Fetch the most recent status for the provided item.

    Args:
        session: the database session to use
        item (Union[AccessPoint, int]): The item (in this case AccessPoint) to fetch status for (or its integer ID)

    Returns:
        Status: the status of the access point, or None if none were found
    """
    item_id = item.id if isinstance(item, AccessPoint) else item
    status = (
        session.query(Status)
        .filter(AccessPointReports, AccessPointReports.report_id == Status.report_id)
        .filter(AccessPointReports.access_point_id == item_id)
        .order_by(Status.timestamp.desc())
    ).first()
    
    return status

def highest_report_for(session, item:Union[AccessPoint, int]):
    """Fetch the latest report for the provided item.

    While you can get this using get_item_status and accessing it through the associated report,
    that method can miss scenarios where a report has been created but there is no status yet
    This can happen when associating a ticket before any email has come in yet.

    Args:
        session: the database session to use
        item (Union[AccessPoint, int]): The item (in this case AccessPoint) to fetch the report for (or its integer ID)

    Returns:
        Report: the report of the access point, or None if none were found
    """
    item_id = item.id if isinstance(item, AccessPoint) else item
    report = (
        session.query(Report)
        .filter(AccessPointReports, AccessPointReports.report_id == Report.id)
        .filter(AccessPointReports.access_point_id == item_id)
        .order_by(Report.id.desc())
    ).first()
    
    return report

def link_report_to_access_point(session, report: Union[Report, int], access_point: Union[AccessPoint, int], commit=False):
    """links a report of a problem to its access point

    Args:
        session: the database session to use
        item 
        report (Union[Report, int]): The item (in this case AccessPoint) to fetch the report for (or its integer ID)
        access_point (Union[AccessPoint, int]): The item (in this case AccessPoint) to fetch the report for (or its integer ID)
        commit (bool): whether to commit the transaction once done
    """
    access_point_id = access_point.id if isinstance(access_point, AccessPoint) else access_point
    report_id = report.id if isinstance(report, Report) else report

    # create new association
    association = AccessPointReports(
        report_id=report_id,
        access_point_id=access_point_id
    )
    session.add(association)
    if commit:
        session.commit()


def smart_add_status_report(session, new_status:Status, ticket_number:str, link_to: Union[AccessPoint, int], commit=False):
    """Intelligently decide whether to add a new status value to an existing report or create a new one

    Args:
        session: the database session to use
        new_status (Status): the new status value as a Status() DB object
        ticket_number (str): the ticket number
        link_to (Union[AccessPoint, int]): an access point or integer access point ID to link the report to
        commit (bool): whether to commit the transaction once done
    Returns:
        (report, status): a tuple of the report and status values used.
    """
    # if the ticket number matches, we should always use the same report
    if ticket_number:
        current_report = session.query(Report).filter(Report.ref == ticket_number).first()
        # if no current report for the given ticket number, make one
        if current_report is None:
            # create new report and link status
            new_report = Report(
                ref=ticket_number
            )
            session.add(new_report)
            session.flush() # get the report ID
            new_status.report_id = new_report.id
            current_report = new_report
            
        else:
            new_status.report_id = current_report.id
        
        # TODO: verify existing entry isnt present
        
        session.add(new_status)

        if link_to: #if we have an access point id, we should link it
            link_report_to_access_point(session, current_report, link_to)
        if commit:
            session.commit()
        return current_report, new_status
    elif link_to: # no ticket number, just a linked access point

        current_status = latest_status_for(session, link_to)
        current_report = current_status.report

        # here we use a bit of a hack to compute whether to add to the existing status item
        # we use the value (number) of the enum and do a >= comparison
        # i.e. if the incoming status is the same (in progress only) or greater than the current one, then we reuse the existing one

        allow_matching = current_status.status_type == StatusType.IN_PROGRESS

        if current_status.status_type.value < new_status.status_type.value or (allow_matching and current_status.status_type.value == new_status.status_type.value):
            new_status.report_id = current_report.id

        else:
            # create a new report
            new_report = Report()
            session.add(new_report)
            session.flush() # get the report ID
            new_status.report_id = new_report.id
            current_report = new_report

        session.add(new_status)

        if commit:
            session.commit()
        return current_report, new_status
    
    else:
        # no ticket and no known links
        # we cant really do anything and i cant think of when we would encounter this
        # but since we have a status report,lets insert it at least
        # this requires creating a report for it

        # create a new report
        new_report = Report()
        session.add(new_report)
        session.flush() # get the report ID
        new_status.report_id = new_report.id

        session.add(new_status)

        if commit:
            session.commit()
        return new_report, new_status
