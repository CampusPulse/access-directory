import os
import io
import subprocess
from dateutil import parser
from enum import Enum
from flask import Flask, render_template, request, redirect, abort, url_for, make_response
import logging
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
import hashlib
import re
from functools import wraps
from random import shuffle
from PIL import Image as PilImage
from relative_datetime import DateTimeUtils
from PIL.ExifTags import TAGS as EXIF_TAGS, Base as ExifBase
from datetime import datetime, timezone
from db import (
    db,
    func,
    text,
    inspect,
    with_polymorphic,
    ShelterType,
    ButtonActivation,
    MountSurface,
    MountStyle,
    PowerSource,
    Building,
    Location,
    AccessPoint,
    DoorButton,
    Elevator,
    AccessPointReports,
    Report,
    Status,
    Image,
    Tag,
    AccessPointTag,
    ImageAccessPointRelation,
    Feedback,
    StatusType
)
from flask_migrate import Migrate, stamp, upgrade
from flask_cors import CORS, cross_origin
from s3 import S3Bucket
from typing import Optional
import shutil
import pandas as pd
import json_log_formatter
from pathlib import Path
from dotenv import load_dotenv
from helpers import floor_to_integer, RoomNumber, integer_to_floor, MapLocation, ServiceNowStatus, ServiceNowUpdateType


app = Flask(__name__)
CORS(app,origins=["*" if app.config["DEBUG"] else "https://*.campuspulse.app"], allow_headers=[
    "Accept", "Authorization", "Content-Type"])

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# loading variables from .env file
load_dotenv()


logging.info("Starting up...")

configpath = Path("config.py")
if configpath.exists():
    app.config.from_pyfile(configpath)
else:
    app.config.from_pyfile(Path("config.env.py"))


if app.config["JSON_LOGS"] is True:
    formatter = json_log_formatter.JSONFormatter()
    json_handler = logging.StreamHandler()
    json_handler.setFormatter(formatter)
    logger.addHandler(json_handler)

logging.info("Starting up...")

git_cmd = ["git", "rev-parse", "--short", "HEAD"]
app.config["GIT_REVISION"] = subprocess.check_output(git_cmd).decode("utf-8").rstrip()

logging.info(f"Connecting to S3 Bucket {app.config['BUCKET_NAME']}")

s3_bucket = S3Bucket(
    app.config["BUCKET_NAME"],
    app.config["S3_KEY"],
    app.config["S3_SECRET"],
    app.config["S3_URL"],
)

app.config["SQLALCHEMY_DATABASE_URI"] = (
    f'postgresql://{app.config["DBUSER"]}:{app.config["DBPWD"]}@{app.config["DBHOST"]}:{app.config["DBPORT"]}/{app.config["DBNAME"]}'
)

logging.info(f"Connecting to DB {app.config['DBNAME']}")
db.init_app(app)

migrate = Migrate(app, db)

with app.app_context():
    # detect if database is empty
    # if so create and stamp it
    insp = inspect(db.engine)
    if not insp.get_table_names():
        logger.info("No database tables found. Creating Database")
        db.create_all()
        stamp(directory="migrations")
    else:
        # if database wasnt empty, attempt to upgrade the db
        # This should do nothing if its already up to date
        logger.info("Checking for database schema upgrades...")
        upgrade(directory="migrations")

########################
#
# region Helpers
#
########################

class ImageType(Enum):
    THUMB = "thumb"
    RESIZED = "resized"
    ORIGINAL = "original"

def get_latest_naming_version():
    return 1

def path_for_image(file_hash:str, image_type: ImageType, naming_version=0) -> str:
    if file_hash is None:
        return None

    if naming_version == 0:
        return file_hash
    elif naming_version == 1:
        return f"{file_hash}_{image_type.value}.jpg"

"""
Create a JSON object for a access_point
"""


def access_point_json(access_point: AccessPoint):

    image_data = db.session.execute(
        db.select(Image)
        .join(ImageAccessPointRelation, Image.id == ImageAccessPointRelation.image_id)
        .where(ImageAccessPointRelation.access_point_id == access_point.id)
        .order_by(ImageAccessPointRelation.ordering)
    ).scalars()
    images = [image_json(i) for i in image_data]
    thumbnail = get_item_thumbnail(access_point)
    naming_version = thumbnail.naming_version if thumbnail is not None else None
    thumbnail = thumbnail.fullsizehash if thumbnail is not None else None
    thumbnail = s3_bucket.get_file_s3(path_for_image(thumbnail, ImageType.THUMB, naming_version=naming_version))

    rn = RoomNumber(access_point.location.floor_number, access_point.location.room_number)

    status = get_item_status(access_point)
    status_style = None
    statusUpdated = "No Data"
    if status is None:
        status_style = statusDataToStyle(StatusType.UNKNOWN, "No Data")
    else:
        status_style = statusDataToStyle(status.status_type, status.status, f"Ticket Number: {status.report.ref}")
        relative_time, direction = DateTimeUtils.relative_datetime(status.timestamp.astimezone())
        statusUpdated = relative_time + " ago" if direction == "past" else " from now"

    # TODO: use marshmallow to serialize
    base_data = {
        "id": access_point.id,
        "thumbnail_ref": access_point.thumbnail_ref or "",
        "building_name": access_point.location.building.name,
        "room": access_point.location.room_number,
        "floor": access_point.location.floor_number,
        "notes": access_point.remarks,
        "active": "checked" if access_point.active else "unchecked",
        "status": status_style,
        "status_updated": statusUpdated,
        "images": images,
        "tags": getTags(access_point.id),
        "report_url": f"https://report.campuspulse.app/elevator?room={rn.to_string()}+{access_point.location.nickname}&campuspulse_id={access_point.id}&building={access_point.location.building.number}:{access_point.location.building.human_name()}"
    }

    if thumbnail is not None:
        base_data.update({"thumbnail": thumbnail})
    if access_point.location.nickname is not None:
        base_data.update({"location_nick": access_point.location.nickname})

    if access_point.location.additional_info is not None:
        base_data.update({"location_info": access_point.location.additional_info})

    if access_point.location.latitude is not None and access_point.location.longitude:
        base_data.update({"coordinates": MapLocation.to_string(access_point.location.latitude, access_point.location.longitude)})

    if isinstance(access_point, Elevator):
        title = access_point.location.building.human_name()
        title += f" - "
        title += access_point.location.human_name()

        base_data.update(
            {
                "title": title,
                "room": rn.to_string(),
                "door_count": access_point.door_count
            }
        )

        if access_point.floor_min != access_point.floor_max:
            base_data.update({ 
                "floor": f"{integer_to_floor(access_point.floor_min)} to {integer_to_floor(access_point.floor_max)}",
            })
    return base_data


"""
Creates a geojson for map feature
"""

def map_features_geojson(access_point: AccessPoint):
    if access_point.location.latitude is None or access_point.location.longitude is None:
        return
    
    status = get_item_status(access_point)

    if status is None:
        status = (StatusType.UNKNOWN, "No Data")
    else: 
        status = status.statusInfo()
    # TODO: use marshmallow to serialize
    base_data = {
        "type": "Feature",
        "properties":{
            "id": access_point.id,
            "building_name": access_point.location.building.name,
            "room": access_point.location.room_number,
            "status": status[0].value,
        },
        "geometry":{
            "coordinates": [access_point.location.latitude, access_point.location.longitude],
            "type": "Point"
        }
    }

    return base_data



"""
Create a JSON object for Feedback
"""


def feedback_json(feedback: Feedback):
    feedback = feedback[0]
    fb_dt = parser.parse(feedback.time)

    relative_time, direction = DateTimeUtils.relative_datetime(fb_dt)

    return {
        "id": feedback.feedback_id,
        "access_point_id": feedback.access_point_id,
        "notes": feedback.notes,
        "contact": feedback.contact,
        "approxtime": relative_time + " ago" if direction == "past" else " from now",
        "exacttime": fb_dt,
    }


"""
Create a JSON object for a tag
"""


def tag_json(tag: Tag):
    return {"name": tag.name, "description": tag.description}


"""
Create a JSON object for an image
"""


def image_json(image: Image):
    out = {
        "imgurl": s3_bucket.get_file_s3(path_for_image(image.fullsizehash, ImageType.RESIZED, naming_version=image.naming_version)),
        "caption": image.caption or "",
        "alttext": image.alttext or "",
        "attribution": image.attribution or "Anonymous",
        "datecreated": image.datecreated,
        "id": image.id,
    }
    if image.fullsizehash != None:
        out["fullsizeimage"] = s3_bucket.get_file_s3(path_for_image(image.fullsizehash, ImageType.ORIGINAL, naming_version=image.naming_version))
    return out


"""
Crop a given image to a centered square
"""


def crop_center(pil_img, crop_width, crop_height):
    img_width, img_height = pil_img.size
    return pil_img.crop(
        (
            (img_width - crop_width) // 2,
            (img_height - crop_height) // 2,
            (img_width + crop_width) // 2,
            (img_height + crop_height) // 2,
        )
    )



def limit_height(pil_img, height_limit):
    """
    Scale an image such that the height is equal to the height limit and the aspect ratio remains the same
    """
    # scale width proportionally to height
    width = (pil_img.width * height_limit) // pil_img.height
    (width, height) = (width, height_limit)
    # set new dimensions
    return pil_img.resize((width, height))


"""
Search all access points given query
"""


def searchAccessPoints(query):
    return list(
        map(
            access_point_json,
            db.session.execute(
                db.select(AccessPoint)
                .where(
                    text(
                        "access_point.text_search_index @@ websearch_to_tsquery(:query)"
                    )
                )
                .order_by(AccessPoint.id)
                .limit(150),
                {"query": query},
            ).scalars(),
        )
    )


"""
Get access points in list, paginated
"""


def getAccessPointsPaginated(page_num):
    return list(
        map(
            access_point_json,
            db.session.execute(
                db.select(AccessPoint)
                .where(AccessPoint.active)
                .order_by(AccessPoint.id.asc())
                .offset(page_num * app.config["ITEMSPERPAGE"])
                .limit(app.config["ITEMSPERPAGE"])
            ).scalars(),
        )
    )


"""
Get all access points
"""


def getAllAccessPoints():
    return list(
        map(
            access_point_json,
            db.paginate(
                db.select(AccessPoint).order_by(AccessPoint.id.asc()),
                per_page=200,
            ).items,
        )
    )


"""
Get all access points
"""


def getAllBuildings():
    b = db.session.execute(db.select(Building).order_by(Building.id.asc())).scalars()
    return b


def getMapFeatures():
    return list(
        map(
            map_features_geojson,
            db.session.execute(
                db.select(AccessPoint)
                .where(AccessPoint.active)
            ).scalars(),
        )
    )

"""
Get all tags
"""


def getAllTags():
    return list(db.session.execute(db.select(Tag)).scalars())


"""
Get Feedback for a AccessPoint
"""


def getAccessPointFeedback(access_point_id):
    return list(
        map(
            feedback_json,
            db.session.execute(
                db.select(Feedback).where(Feedback.access_point_id == access_point_id)
            ),
        )
    )


"""
Get all access points from year
"""


def getAllAccessPointsFromYear(year):
    return list(
        map(
            access_point_json,
            db.paginate(
                db.select(AccessPoint)
                .where(AccessPoint.year == year)
                .order_by(AccessPoint.id.asc()),
                per_page=150,
            ).items,
        )
    )


"""
Get all tags
"""


def getAllTags():
    return list(db.session.execute(db.select(Tag.name)).scalars())


"""
Get Tag details
"""


def getTagDetails(name):
    return tag_json(
        db.session.execute(db.select(Tag).where(Tag.name == name)).scalar_one()
    )


"""
Exports database tables to CSV files
Stores in provided directory
"""


def export_database(dir, public):
    if public:
        access_point_select = db.select(
            AccessPoint.id,
            AccessPoint.notes,
            AccessPoint.remarks,
            AccessPoint.year,
            AccessPoint.location,
            AccessPoint.spotify,
        ).order_by(AccessPoint.id.asc())
    else:
        access_point_select = db.select(
            AccessPoint.id,
            AccessPoint.title,
            AccessPoint.private_notes,
            AccessPoint.notes,
            AccessPoint.remarks,
            AccessPoint.year,
            AccessPoint.location,
            AccessPoint.spotify,
        ).order_by(AccessPoint.id.asc())

        feedback_select = db.select(Feedback).order_by(Feedback.feedback_id.asc())
        feedback_df = pd.read_sql(feedback_select, db.engine)
        feedback_df.to_csv(dir + "feedback.csv")

    access_points_df = pd.read_sql(access_point_select, db.engine)

    access_points_df["tags"] = access_points_df.apply(
        lambda x: getTags(x["id"]), axis=1
    )
    images_select = (
        db.select(
            Image.id, Image.caption, Image.alttext, Image.attribution, Image.datecreated
        )
        .join(
            ImageAccessPointRelation, ImageAccessPointRelation.image_id == Image.id
        )
        .where(ImageAccessPointRelation.ordering != 0)
        .order_by(Image.id.asc())
    )

    images_df = pd.read_sql(images_select, db.engine)

    if not Path(dir).exists():
        Path(dir).mkdir()

    access_points_df.to_csv(dir + "access_points.csv")
    images_df.to_csv(dir + "images.csv")


"""
Exports images to <path>/images
"""


def export_images(path):
    access_points = db.session.execute(
        db.select(AccessPoint).order_by(AccessPoint.id.asc())
    ).scalars()

    for m in access_points:
        # TODO: migrate this to download the images
        images = db.session.execute(
            db.select(Image)
            .join(
                ImageAccessPointRelation, ImageAccessPointRelation.image_id == Image.id
            )
            .where(ImageAccessPointRelation.access_point_id == m.id)
            .filter(ImageAccessPointRelation.ordering != 0)
        ).scalars()

        basepath = path + "images/" + str(m.id) + "/"

        if not Path(basepath).exists():
            Path(basepath).mkdir()

        for i in images:
            s3_bucket.get_file(i.fullsizehash, basepath + str(i.ordering) + ".jpg")


"""
Imports data export into database, S3
"""


def import_data(file):
    return


"""
Get access point details
"""


def getAccessPoint(id):
    access_point = db.session.execute(
        db.select(AccessPoint).where(AccessPoint.id == id)
    ).scalar()

    if access_point == None:
        logging.warning("DB Response was None")
        logging.warning(f"ID was '{id}'")
        return None

    accessPointInfo = access_point_json(access_point)
    logging.debug(accessPointInfo)
    return accessPointInfo


def checkYearExists(year):
    if not year.isdigit():
        return False

    integer_pattern = r"^[+-]?\d+$"

    # Use re.match to check if the variable matches the integer pattern
    if not re.match(integer_pattern, year):
        return False

    return True


def checkAccessPointExists(id):
    # Check id is not bad
    if not id.isdigit():
        return False

    return (
        db.session.execute(db.select(AccessPoint).where(AccessPoint.id == id)).scalar()
        != None
    )


"""
Get all access points with given tag
"""


def getAccessPointsTagged(tag):
    return list(
        map(
            access_point_json,
            db.session.execute(
                db.select(AccessPoint)
                .select_from(AccessPointTag)
                .join(Tag, AccessPointTag.tag_id == Tag.id)
                .join(AccessPoint, AccessPoint.id == AccessPointTag.access_point_id)
                .where(Tag.name == tag)
            ).scalars(),
        )
    )


"""
Get all tags / Get all tags on certain access point
(logic based on whether access_point_id is passed in)
"""


def getTags(access_point_id=None):
    if access_point_id == None:
        return db.session.execute(db.select(Tag.name)).scalars()
    else:
        return list(
            db.session.execute(
                db.select(Tag.name)
                .join(AccessPointTag, AccessPointTag.tag_id == Tag.id)
                .where(AccessPointTag.access_point_id == access_point_id)
            ).scalars()
        )


"""
Get a random assortment of images from DB, excluding thumbnails
"""


def getRandomImages(count):
    images = list(
        map(
            image_json,
            db.session.execute(
                db.select(Image)
                .join(
                    ImageAccessPointRelation, ImageAccessPointRelation.image_id == Image.id
                )
                .where(ImageAccessPointRelation.ordering != 0)
                .order_by(func.random())
                .limit(count)
            ).scalars(),
        )
    )
    shuffle(images)
    return images


def detachAllImagesFromItem(item_id: int, keep_files=False):
    """De-associates or deletes all images from the database given the id of the item to detach from
    If images are used more than once, they are kept, and only the reference is removed. If image has no other references, its deletion is determined by `keep_files` 

    Args:
        item_id (int): the id of the item to remove the images from
        keep_files (bool, optional): Whether to keep files when they would otherwise be deleted. Defaults to False.
    """

    image_refs = db.session.execute(
        db.select(ImageAccessPointRelation).where(ImageAccessPointRelation.access_point_id == item_id)
    ).scalars()
    
    for image_ref in image_refs:
        detachImageByRef(image_ref)


def detachImageByID(image_id: int, item_id: int, keep_files=False):
    """De-associates or deletes images from the database given the id of an image and the item to detach it from
    If images are used more than once, they are kept, and only the reference is removed. If image has no other references, its deletion is determined by `keep_files` 

    Args:
        image_id (int): the id of the image to remove
        item_id (int): the id of the item to remove the images from
        keep_files (bool, optional): Whether to keep files when they would otherwise be deleted. Defaults to False.
    """

    image = db.session.execute(
        db.select(Image).where(Image.id == image_id)
    ).scalars().first()

    image_ref = db.session.execute(
        db.select(ImageAccessPointRelation).where(ImageAccessPointRelation.image_id == image_id, ImageAccessPointRelation.access_point_id == item_id )
    ).scalars().first()

    detachImageByRef(image_ref)
    

def detachImageByRef(image_ref, keep_files=False):

    image = image_ref.image

    # check how many total references to this image exist
    total_ref_count = db.session.execute(
        db.select(func.count()).where(
            Image.fullsizehash == image.fullsizehash
        )
    ).scalar()

    #if theres only this one reference, remove all three images from S3 and remove it from the database
    if total_ref_count <= 1:
        s3_bucket.remove_file(path_for_image(image.fullsizehash, ImageType.ORIGINAL, naming_version=image.naming_version))
        s3_bucket.remove_file(path_for_image(image.fullsizehash, ImageType.RESIZED, naming_version=image.naming_version))
        s3_bucket.remove_file(path_for_image(image.fullsizehash, ImageType.THUMB, naming_version=image.naming_version))  

        db.session.delete(image)

    # remove the reference to this image
    db.session.delete(image_ref)


def statusDataToStyle(statustype: StatusType, message:str, context:str=None):
    """return a JSON block of style information for a given status configuration

    Args:
        type (StatusType): The type of status
        message (str): the message to display in the status
        hovertext (str, optional): Text to display on hover. Defaults to None.

    Returns:
        dict: a dict of style info to pass to a template 
    """

    bgcolor = "#b3b3b3" # default gray
    textcolor = "#000"
    border = True
    bordercolor = "#000"

    if statustype == StatusType.BROKEN:
        bgcolor = "#ff4d4d" #65% red
        # textcolor = ""
        border = False
    elif statustype == StatusType.IN_PROGRESS:
        bgcolor = "yellow"
        # textcolor = ""
        border = False
    elif statustype == StatusType.FIXED:
        bgcolor = "green"
        textcolor = "#fff"
        border = False
    elif statustype == StatusType.VERIFIED:
        bgcolor = "#6666ff" #70% blue
        textcolor = "#fff"
        border = False

    data = {
        "text_color": textcolor,
        "background_color": bgcolor,
        "border": border,
        "message": message
    }

    if border:
        data.update({
            "border_color": bordercolor
        })
    if context is not None:
        data.update({
            "title": context
        })

    return data
    


########################
#
# region Pages
#
########################


@app.route("/")
def home():
    return redirect("/catalog", code=302)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/map")
def map_page():
    return render_template(
        "map.html",
        mapFeatures = getMapFeatures(),
        )


@app.route("/catalog")
def catalog():
    query = request.args.get("q")
    page = request.args.get("p")
    if query == None:
        if page is None:
            return render_template(
            "catalog.html",
            q=query,
            page=1,
            accessPoints=getAccessPointsPaginated(0),
            tags=getAllTags(),
        )
        else:
            page = int(page)
            return render_template(
                "paginated.html", 
                page=(page+1),
                murals=getAccessPointsPaginated(page)
            )
    else:
        return render_template(
            "filtered.html",
            pageTitle=f"Query - {query}",
            subHeading="Search Query",
            q=query,
            accessPoints=searchAccessPoints(query),
        )


@app.route("/tags?t=<tag>")
@app.route("/tags")
def tags():
    tag = request.args.get("t")
    if tag == None:
        return render_template("404.html"), 404
    else:
        return render_template(
            "filtered.html",
            pageTitle=f"Tag - {tag}",
            subHeading=getTagDetails(tag)["description"],
            accessPoints=getAccessPointsTagged(tag),
        )


"""
Page for specific access point details
"""


@app.route("/access_points/<id>")
def access_point(id):
    if checkAccessPointExists(id):
        return render_template(
            "access_point.html", accessPointDetails=getAccessPoint(id)
        )
    else:
        return render_template("404.html"), 404

"""
Generic error handler
"""


@app.errorhandler(HTTPException)
def not_found(e):
    app.logger.error(e)
    return render_template("404.html"), 404



########################
#
# region Decorators
#
########################

def debug_only(f):
    @wraps(f)
    def wrapped(**kwargs):
        if app.config["DEBUG"]:
            return f(**kwargs)
        return abort(404)

    return wrapped



########################
#
# region Ingest
#
########################


@app.route("/email_webhook", methods=["POST"])
def email_webhook():
    webhook_credential = app.config["WEBHOOK_CREDENTIAL"]

    # check to make sure that the POST came from an authorized source (NFSN) and not some random person POSTing stuff to this endpoint
    if request.args.get("token") != webhook_credential:
        return ("Unauthorized", 401)

   

    from_addr = request.form.get("From")
    app.logger.info(from_addr)
    # check to make sure the email is FROM RIT's system

    if not from_addr.endswith("<help@rit.edu>"):
        app.logger.warning("invalid email address - skipping")
        return ("", 200)

    subject = request.form.get("Subject")
    app.logger.info(subject)

    # ensure this is not a ticket about a door button (we dont have those in the DB yet)
    if "WOT" not in subject:
        app.logger.warning("Subject indicates this is not an FMS work order update email - skipping")
        return ("", 200)

    # Log POST fields (headers and body)
    # POST fields: From, To, Subject, Date, and Message-ID
    # The main message body as "Body" (also POST)
    for key, value in request.form.items():
        app.logger.debug(f"POST: {key} => {value}")
    
    html_body = None

    for key, file in request.files.items(multi=True):
        if file.mimetype == 'text/html':
            html_body = file.read()

    if html_body is None:
        app.logger.error("Email sent via webhook did not have an HTML component to the multipart body")
        return ("", 200)

    statusUpdate = ServiceNowStatus.from_email(from_addr, subject, html_body)

    report = db.session.execute(
        db.select(Report).where(Report.ref == statusUpdate.ref)
    ).scalar()

    if report is None:
        # create new report and status
        report = Report(
            ref=statusUpdate.ref
        )

        db.session.add(report)
        db.session.flush()
    
    statusMap = {
        ServiceNowUpdateType.NEW: (StatusType.BROKEN, "Filed"),
        ServiceNowUpdateType.RESOLVED:  (StatusType.FIXED , "Fixed"),
        ServiceNowUpdateType.IN_PROGRESS:  (StatusType.IN_PROGRESS, "In Progress"),
        ServiceNowUpdateType.UNKNOWN:  (StatusType.UNKNOWN, "Unknown")
    }

    status_type, status = statusMap[statusUpdate.status_type]


    statusNotes = ""
    if statusUpdate.comment is not None and statusUpdate.comment != "":
        statusNotes = statusUpdate.comment
    else:
        statusNotes = subject

    # create new status
    status = Status(
        report_id=report.id,
        status=status,
        status_type=status_type,
        timestamp=statusUpdate.timestamp,
        notes=statusNotes
    )
    db.session.add(status)

    
    db.session.commit()

    return ("", 200)


@app.route("/add_ticket/<item_id>", methods=["POST"])
@debug_only
def add_ticket(item_id):
    if not checkAccessPointExists(item_id):
        return "Not found", 404

    ticket_ref = request.form.get("ticket_ref")
    if ticket_ref is None or ticket_ref == "" or not ticket_ref.startswith("WOT"):
        return "invalid ticket number", 400

    report = db.session.execute(
        db.select(Report).where(Report.ref == ticket_ref)
    ).scalar()

    if report is None:
        # create new report and status
        report = Report(
            ref=ticket_ref
        )

        db.session.add(report)
        db.session.flush()
    
    # create new association
    association = AccessPointReports(
        report_id=report.id,
        access_point_id=item_id
    )
    db.session.add(association)
    
    db.session.commit()

    return ("", 200)

########################
#
# region Management Helpers
#
########################

def make_thumbnail(input_file, output_file, raise_if_already=True):
    """
    Given an input file (as a filename to an image), downscale it to a thumbnail and store it in the (file or string filepath) represented by output_file
    """

    with PilImage.open(input_file) as im:
        if im.width == 256 or im.height == 256:
            if raise_if_already:
                raise ValueError("Thumbnail requested from image that is already thumbnail size.")
        im = crop_center(im, min(im.size), min(im.size))
        im.thumbnail((256, 256))
        exif = im.getexif()
        exif[ExifBase.ImageWidth.value] = im.width
        exif[ExifBase.ImageLength.value] = im.height

        im = im.convert("RGB")
        im.save(output_file, "JPEG", exif=exif)

   
def set_thumbnail(item, image):

    item.thumbnail_ref = image.id
    # db.session.commit()

def get_item_thumbnail(item):
    """Fetch the thumbnail image for the provided item.
    This first checks the item's `thumbnail_ref` column for a reference to the Image that should be used. If it cant find one, it grabs the first image associated with that item sorted by the image's `ordering` column.

    Args:
        item (AccessPoint): The item (in this case AccessPoint) to fetch an image for

    Returns:
        Image: The image representing the thumbnail (or None if no images could be found by either method)
    """

    thumbnail = None

    if item.thumbnail_ref is not None:
        # theres probably a better, more "sqlalchemy" way to do this tbh
        thumbnail = db.session.execute(
            db.select(Image)
            .where(Image.id == item.thumbnail_ref)
        ).scalars().first()
    
    if thumbnail is None:

        # else lookup the related images and get the first one by order
        thumbnail = db.session.execute(
            db.select(Image)
            .join(ImageAccessPointRelation, Image.id == ImageAccessPointRelation.image_id)
            .where(ImageAccessPointRelation.access_point_id == item.id)
            .order_by(ImageAccessPointRelation.ordering.asc())
        ).scalars().first()

    return thumbnail

def associate_thumbnail(file_hash, thumbnail_file, item_identifier):
    """
    associate a thumbnail from S3 with a particular item in the database
    """
    thumbnail_file.seek(0)
    created = creationTimeFromFileExif(thumbnail_file)


    img = Image(
        fullsizehash=file_hash,
        ordering=0,
        datecreated=created
    )
    db.session.add(img)
    db.session.flush()
    img_id = img.id
    db.session.add(
        ImageAccessPointRelation(
            image_id=img_id, access_point_id=item_identifier
        )
    )

    db.session.commit()


def get_item_status(item):
    """Fetch the status for the provided item.

    Args:
        item (AccessPoint): The item (in this case AccessPoint) to fetch status for

    Returns:
        Status: the status of the access point, or None if none were found
    """

    status = db.session.execute(
        db.select(Status)
        .join(AccessPointReports, AccessPointReports.report_id == Status.report_id)
        .where(AccessPointReports.access_point_id == item.id)
        .order_by(Status.timestamp.desc())
    ).scalars().first()
    
    return status


"""
Delete tag and all relations from DB
"""


def deleteTagGivenName(name):
    t = db.session.execute(db.select(Tag).where(Tag.name == name)).scalar_one()
    db.session.execute(db.delete(AccessPointTag).where(AccessPointTag.tag_id == t.id))
    db.session.execute(db.delete(Tag).where(Tag.id == t.id))
    db.session.commit()


"""
Delete access point entry, all relations, and all images from DB and S3
"""


def deleteAccessPointEntry(id):
    # Get all images relating to this access point from the DB
    images = db.paginate(
        db.select(Image)
        .join(ImageAccessPointRelation, Image.id == ImageAccessPointRelation.image_id)
        .where(ImageAccessPointRelation.access_point_id == id),
        per_page=150,
    ).items
    # we are deleting the whole access point, so remove all image references
    db.session.execute(
        db.delete(ImageAccessPointRelation).where(
            ImageAccessPointRelation.access_point_id == id
        )
    )
    db.session.execute(
        db.delete(AccessPointTag).where(AccessPointTag.access_point_id == id)
    )
    db.session.execute(db.delete(Feedback).where(Feedback.access_point_id == id))

    # https://docs.sqlalchemy.org/en/21/orm/queryguide/inheritance.html#using-with-polymorphic
    ap_poly = with_polymorphic(AccessPoint, "*")

    m = db.session.execute(
        db.select(ap_poly).where(AccessPoint.id == id)
    ).scalar_one()
    detachAllImagesFromItem(m.id)
    db.session.delete(m)
    db.session.commit()



def creationTimeFromFileExif(file, default=datetime.now()):
    with PilImage.open(file) as im:
        exif = im.getexif()
        try:
            exifdate = exif[ExifBase.DateTime.value]
        except KeyError:
            # No Exif Data available
            return default
        exif_format = "%Y:%m:%d %H:%M:%S"
        return datetime.strptime(exifdate, exif_format)

def scrubGPSFromExif(exif):
    try:
        del exif[ExifBase.GPSInfo.value]
    except KeyError as e:
        print(e)
    return exif



def generateImageHash(file):
    file.seek(0)
    hashvalue = hashlib.md5(file.read()).hexdigest()

    if hashvalue == hashlib.md5("".encode("utf8")).hexdigest():
        raise ValueError("The data to be hashed was empty")

    file.seek(0)
    return hashvalue

"""
Upload fullsize and resized image, add relation to access point given ID
"""


def uploadImageResize(file, access_point_id, count, is_thumbnail=False):
    file_obj = io.BytesIO(file.read())
    fullsizehash = generateImageHash(file_obj)
    file_obj.seek(0)

    name_ver = get_latest_naming_version()

    original_filename = path_for_image(fullsizehash, ImageType.ORIGINAL, naming_version=name_ver)
    resized_filename = path_for_image(fullsizehash, ImageType.RESIZED, naming_version=name_ver)
    thumb_filename = path_for_image(fullsizehash, ImageType.THUMB, naming_version=name_ver)


    # Upload full size img to S3
    s3_bucket.upload_file(original_filename, file_obj, filename=original_filename)

    file_obj.seek(0)
    imageTakenOn = creationTimeFromFileExif(file_obj)
    file_obj.seek(0)

    with PilImage.open(file_obj) as im:
        exif = im.getexif()
        im = limit_height(im, app.config["MAX_IMG_HEIGHT"])
        exif = scrubGPSFromExif(exif)
        exif[ExifBase.ImageWidth.value] = im.width
        exif[ExifBase.ImageLength.value] = im.height
                
        im = im.convert("RGB")

        resized_file = io.BytesIO()
        im.save(resized_file, "JPEG", exif=exif)
        resized_file.seek(0)

        s3_bucket.upload_file(resized_filename, resized_file, filename=resized_filename)

        
        thumbnail_file = io.BytesIO()

        try:
            make_thumbnail(resized_file, thumbnail_file)
        except ValueError as e:
            app.logger.error(f"Exception encountered generating thumbnail: {e}")
        
        thumbnail_file.seek(0)

        s3_bucket.upload_file(thumb_filename, thumbnail_file, filename=thumb_filename)

        img = Image(
            fullsizehash=fullsizehash,
            datecreated=imageTakenOn or datetime.now(),
            naming_version=name_ver
        )
        db.session.add(img)
        db.session.flush()
        img_id = img.id
        db.session.add(
            ImageAccessPointRelation(image_id=img_id, 
            ordering=count,
            access_point_id=access_point_id)
        )

        if is_thumbnail:
            access_point = db.session.execute(
                db.select(AccessPoint).where(AccessPoint.id == access_point_id)
            ).scalar_one()
            if access_point is None:
                print(f"access point not found with id {access_point_id}")
            else:
                set_thumbnail(access_point, img)
    db.session.commit()


########################
# region Admin Pages
########################

"""
Route to edit access point page
"""


@app.route("/edit/<id>")
@debug_only
def edit(id):

    if checkAccessPointExists(id):
        return render_template(
            "edit.html",
            accessPointDetails=getAccessPoint(id),
            accessPointFeedback=getAccessPointFeedback(id),
            tags=getAllTags(),
        )
    else:
        return render_template("404.html"), 404


"""
Route to the admin panel
"""


@app.route("/admin")
@debug_only
def admin():
    return render_template(
        "admin.html",
        tags=getAllTags(),
        accessPoints=getAllAccessPoints(),
        buildings=getAllBuildings(),
    )


########################
# region API
########################


@app.route("/map.geojson")
def mapdata():
    return {
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "id": 99999999,
                    "name": "Nothing to see here",
                    "geometry_id": "99999999",
                    "images": [],
                },
                "geometry": {
                    "coordinates": [-77.6653, 43.08101],  # long/x  # lat/y
                    "type": "Point",
                },
                "id": "02eaa87d832995f670c9ee7c846e6925",
            }
        ],
        "type": "FeatureCollection",
    }

@app.route("/buildings.json")
@cross_origin()
def buildingdata():
    bldgs = db.session.execute(
        db.select(Building)
    ).scalars()
    resp = make_response({
        "buildings": [b.toJSON() for b in bldgs]
    })
    resp.headers['Cache-Control'] = f'public,max-age={int(60 * 10080)}'
    return resp


########################
# region Form submissions
########################

"""
Suggestion/feedback form
"""


@app.route("/suggestion", methods=["POST"])
def submit_suggestion():

    dt = datetime.now(timezone.utc)

    db.session.add(
        Feedback(
            notes=request.form["notes"],
            contact=request.form["contact"],
            time=str(dt),
            access_point_id=request.form["access_point_id"],
        )
    )
    db.session.commit()

    return redirect("/catalog")


"""
Route to delete Tag
"""


@app.route("/deleteTag/<name>", methods=["POST"])
@debug_only
def deleteTag(name):
    deleteTagGivenName(name)
    return redirect("/admin")


"""
Route to delete access point entry
"""


@app.route("/delete/<id>", methods=["POST"])
@debug_only
def delete(id):
    if checkAccessPointExists(id):
        deleteAccessPointEntry(id)
        return redirect("/admin")
    else:
        return render_template("404.html"), 404


"""
Route to edit access point details
Sets all fields based on http form
"""


@app.route("/editaccesspoint/<id>", methods=["POST"])
@debug_only
def editAccessPoint(id):
    m = db.session.execute(
        db.select(AccessPoint).where(AccessPoint.id == id)
    ).scalar_one()

    # Remove existing tag relationships
    db.session.execute(
        db.delete(AccessPointTag).where(AccessPointTag.access_point_id == m.id)
    )

    # Relate access point and submitted tags
    if "tags" in request.form:
        if "No Tags" not in request.form.getlist("tags"):
            for tag in request.form.getlist("tags"):
                tag_id = db.session.execute(
                    db.select(Tag.id).where(Tag.name == tag)
                ).scalar()

                rel = AccessPointTag(tag_id=tag_id, access_point_id=m.id)
                db.session.add(rel)

    m.active = True if "active" in request.form else False

    if request.form["notes"] not in ("None", ""):
        m.notes = request.form["notes"]
    if request.form["remarks"] not in ("None", ""):
        m.remarks = request.form["remarks"]
    if request.form["location-nick"] not in ("None", ""):
        m.location.nickname = request.form["location-nick"]
    if request.form["coords"] not in ("None", ""):
        gpsLocation = MapLocation.from_string(request.form["coords"])

        if gpsLocation is not None:
            lat, long = gpsLocation
            m.location.latitude = lat
            m.location.longitude = long
    
    if request.form["location-info"] not in ("None", ""):
        m.location.additional_info = request.form["location-info"]

    if request.form["door_count"] not in ("None", ""):
        m.door_count = int(request.form["door_count"])
    # if request.form["private_notes"]  not in ("None", ""):
    #     m.private_notes = request.form["private_notes"]
    db.session.commit()
    return ("", 204)


"""
Route to edit tag description
"""


@app.route("/editTag/<name>", methods=["POST"])
@debug_only
def edit_tag(name):
    t = db.session.execute(db.select(Tag).where(Tag.name == name)).scalar_one()
    t.description = request.form["description"]
    db.session.commit()
    return ("", 204)


"""
Route to edit access point title
Sets access point title based on http form
"""


@app.route("/edittitle/<id>", methods=["POST"])
@debug_only
def editTitle(id):
    m = db.session.execute(
        db.select(AccessPoint).where(AccessPoint.id == id)
    ).scalar_one()
    m.title = request.form["title"]
    db.session.commit()
    return ("", 204)


"""
Route to edit image details
Set caption and alttext based on http form
"""


@app.route("/editimage/<id>", methods=["POST"])
@debug_only
def editImage(id):
    image = db.session.execute(db.select(Image).where(Image.id == id)).scalar_one()

    if request.form["caption"].strip() != "":
        image.caption = request.form["caption"]
    if request.form["alttext"].strip() != "":
        image.alttext = request.form["alttext"]
    if request.form["attribution"].strip() != "":
        image.attribution = request.form["attribution"]
    db.session.commit()
    return ("", 204)


"""
Replaces access point thumbnail with selected image
Route:
    /makethumbnail?accesspointid=m_id&imageid=i_id
"""


@app.route("/makethumbnail", methods=["POST"])
@debug_only
def makeThumbnail():
    access_point_id = request.args.get("accesspointid", None)
    image_id = request.args.get("imageid", None)

    # verify both exist
    image = db.session.execute(
        db.select(Image).where(Image.id == image_id)
        ).scalar_one()

    access_point = db.session.execute(
        db.select(AccessPoint).where(AccessPoint.id == access_point_id)
        ).scalar_one()

    if image is None or access_point is None:
        return render_template("404.html"), 404

    set_thumbnail(access_point, image)
    db.session.commit()


    return redirect(f"/edit/{access_point_id}")


"""
Route to delete image
"""


@app.route("/detachimage/<image_id>/from/<item_id>", methods=["POST"])
@debug_only
def detachImageEndpoint(image_id, item_id):

    detachImageByID(image_id, item_id)
    
    db.session.commit()

    return ("", 204)


"""
Route to perform public export
"""


@app.route("/export", methods=["POST"])
@debug_only
def export_data():
    public = bool(int(request.args.get("p")))
    now = datetime.now()
    dir_name = "export" + now.strftime("%d%m%Y")
    basepath = "tmp/"

    export_images(basepath + dir_name + "/")
    export_database(basepath + dir_name + "/", public)

    shutil.make_archive(basepath + dir_name, "zip", basepath + dir_name)

    return send_file(basepath + dir_name + ".zip")


"""
Route to perform data import
"""


@app.route("/import", methods=["POST"])
@debug_only
def import_data():
    return ("", 501)


"""
Add tag with blank description
"""


@app.route("/addTag", methods=["POST"])
@debug_only
def add_tag():
    tag = Tag(name=request.form["name"], description="")

    db.session.add(tag)
    db.session.commit()

    return redirect("/admin")


"""
Route to upload new image
"""


@app.route("/uploadimage/<id>", methods=["POST"])
@debug_only
def uploadNewImage(id):
    count = db.session.execute(
        db.select(func.count()).where(ImageAccessPointRelation.access_point_id == id)
    ).scalar()

    for f in request.files.items(multi=True):
        uploadImageResize(f[1], id, count)
        count += 1

    return redirect(f"/edit/{id}")


"""
Route to add new entry
"""


@app.route("/upload/elevator", methods=["POST"])
@debug_only
def upload():

    # Step 1: Find the building by its number
    stmt = db.select(Building).where(Building.acronym == request.form["building"])
    building = db.session.execute(stmt).scalar_one_or_none()

    if not building:
        raise ValueError(
            f"Building with acronym {request.form['building']} not found."
        )

    # Step 2: Find or create the location
    # for now we consider elevators as being "located" on "all" floors using the special floor number "0" (we are following the american standard where 1 is ground)
    floor, room = RoomNumber.from_string(request.form["room"]).integers()

    stmt = db.select(Location).where(
        Location.building_id == building.id,
        Location.floor_number == floor,
        Location.room_number == room,
        Location.is_outside is False,  # elevators should not be outside
    )
    location = db.session.execute(stmt).scalar_one_or_none()

    if not location:

        locationData = {
            "building_id": building.id,
            "floor_number": floor or 0,
            "room_number": room,
            "nickname": request.form["location-nick"],
            "additional_info": request.form["location"],
        }
        gpsLocation = MapLocation.from_string(request.form["coords"])

        if gpsLocation is not None:
            lat, long = gpsLocation
            locationData.update({
                "latitude": lat,
                "longitude": long
            })

        location = Location(
            **locationData
        )
        db.session.add(location)
        db.session.flush()  # Get the location ID
    
    
    extra_data = {}
    door_count = request.form.get('door_count')
    if door_count is not None:
        try:
            door_count = int(door_count)
            extra_data["door_count"] = door_count
        
        except Exception as e:
            app.logger.error(f"cound not parse door count: {e}")

    # Step 3: Insert the elevator access point
    elevator = Elevator(
        floor_min=floor_to_integer(request.form["min_floor"]),
        floor_max=floor_to_integer(request.form["max_floor"]),
        location_id=location.id,
        remarks=request.form["notes"],
        active=request.form["active"] == "true",
        **extra_data
    )
    db.session.add(elevator)

    # Count is the order in which the images are shown
    count = 1
    for f in request.files.items(multi=True):
        # print(f[1].filename)

        fullsizehash = generateImageHash(f[1])
        f[1].seek(0)

        # Check if image is already used in DB
        usecount = db.session.execute(
            db.select(func.count()).where(Image.fullsizehash == fullsizehash)
        ).scalar()
        if usecount > 0:
            # print(fullsizehash)
            # associate image
            existing_image = db.session.execute(
                db.select(Image).where(Image.fullsizehash == fullsizehash)
            ).scalar()

            db.session.add(
                ImageAccessPointRelation(image_id=existing_image.id, 
                ordering=count,
                access_point_id=elevator.id)
            )
            count += 1
            continue
            # return render_template("404.html"), 404

        # Begin adding full size to database
        f[1].seek(0)

        uploadImageResize(f[1], elevator.id, count, is_thumbnail=(count == 0))

        count += 1

    db.session.commit()

    return redirect(f"/edit/{elevator.id}")


if __name__ == "__main__":
    # TODO: figure out how to accept this via CLI arg:
    # with app.app_context():
    #     db.create_all()
    #     stamp(directory="migrations")
    if not app.config["DEBUG"]:
        app.run(host="0.0.0.0", port=8080)
    else:
        app.run()
else: # prod
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
