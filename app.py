import os
import io
import subprocess
from flask import Flask, render_template, request, redirect, abort, url_for
import logging
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
import hashlib
import re
from functools import wraps
from random import shuffle
from PIL import Image as PilImage
from PIL.ExifTags import TAGS as EXIF_TAGS
from datetime import datetime, timezone
from db import (
    db,
    func,
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
    AccessPointStatus,
    Image,
    Tag,
    AccessPointTag,
    ImageAccessPointRelation,
    Feedback,
)
from flask_migrate import Migrate, stamp
from s3 import S3Bucket
from typing import Optional
import shutil
import pandas as pd
import json_log_formatter
from pathlib import Path
from dotenv import load_dotenv
from helpers import floor_to_integer, RoomNumber, integer_to_floor


app = Flask(__name__)

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

########################
#
#   Helpers
#
########################

"""
Create a JSON object for a access_point
"""


def access_point_json(access_point: AccessPoint):
    previd = db.session.execute(
        db.select(AccessPoint.id).where(AccessPoint.id == access_point.id)
    ).scalar()

    image_data = db.session.execute(
        db.select(Image)
        .join(ImageAccessPointRelation, Image.id == ImageAccessPointRelation.image_id)
        .where(ImageAccessPointRelation.access_point_id == access_point.id)
        .order_by(Image.ordering)
    ).scalars()
    images = []
    thumbnail = None
    for image in image_data:
        if image.ordering == 0:
            thumbnail = s3_bucket.get_file_s3(image.imghash)
            images.append(image_json(image))
        else:
            images.append(image_json(image))
    # TODO: use marshmallow to serialize
    base_data = {
        "id": access_point.id,
        "building_name": access_point.location.building.name,
        "room": access_point.location.room_number,
        "floor": access_point.location.floor_number,
        "notes": access_point.remarks,
        "active": "checked" if access_point.active else "unchecked",
        "images": images,
        "tags": getTags(access_point.id),
    }

    if thumbnail is not None:
        base_data.update({
            "thumbnail": thumbnail
        })
    if access_point.location.nickname is not None:
        base_data.update({
            "location_nick": access_point.location.nickname
        })

    if isinstance(access_point, Elevator):
        title = f"{access_point.location.building.name}"
        if access_point.location.nickname is not None:
            title += f" - {access_point.location.nickname}"
        base_data.update({
            "title":  title,
            "floor": f"{integer_to_floor(access_point.floor_min)} to {integer_to_floor(access_point.floor_max)}",
            "room": f"_{access_point.location.room_number}"

        })
    return base_data

"""
Create a JSON object for Feedback
"""


def feedback_json(feedback: Feedback):
    feedback = feedback[0]
    dt = datetime.now(timezone.utc)
    dt = dt.replace(tzinfo=None)
    fb_dt = feedback.time
    diff = dt - fb_dt

    return {
        "id": feedback.feedback_id,
        "access_point_id": feedback.access_point_id,
        "notes": feedback.notes,
        "contact": feedback.contact,
        "approxtime": f"{diff.days} days ago",  # approx_time,
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
        "imgurl": s3_bucket.get_file_s3(image.imghash),
        "ordering": image.ordering,
        "caption": image.caption,
        "alttext": image.alttext,
        "attribution": image.attribution,
        "datecreated": image.datecreated,
        "id": image.id,
    }
    if image.fullsizehash != None:
        out["fullsizeimage"] = s3_bucket.get_file_s3(image.fullsizehash)
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


"""
Search all access points given query
"""


def searchAccessPoints(query):
    return list(
        map(
            access_point_json,
            db.session.execute(
                db.select(AccessPoint)
                .where(text("access_point.text_search_index @@ websearch_to_tsquery(:query)"))
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
    b = db.session.execute(
            db.select(Building).order_by(Building.id.asc())
        ).scalars()
    return b

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
                db.select(AccessPoint).where(AccessPoint.year == year).order_by(AccessPoint.id.asc()),
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

    access_points_df["tags"] = access_points_df.apply(lambda x: getTags(x["id"]), axis=1)
    images_select = (
        db.select(
            Image.id, Image.caption, Image.alttext, Image.attribution, Image.datecreated
        )
        .where(Image.ordering != 0)
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
    access_points = db.session.execute(db.select(AccessPoint).order_by(AccessPoint.id.asc())).scalars()

    for m in access_points:
        images = db.session.execute(
            db.select(Image)
            .join(ImageAccessPointRelation, ImageAccessPointRelation.image_id == Image.id)
            .where(ImageAccessPointRelation.access_point_id == m.id)
            .filter(Image.ordering != 0)
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
    access_point = db.session.execute(db.select(AccessPoint).where(AccessPoint.id == id)).scalar()

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

    return db.session.execute(db.select(AccessPoint).where(AccessPoint.id == id)).scalar() != None


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
                .where(Image.ordering != 0)
                .order_by(func.random())
                .limit(count)
            ).scalars(),
        )
    )
    shuffle(images)
    return images


########################
#
#   Pages
#
########################


@app.route("/")
def home():
    return render_template(
        "home.html",
        pageTitle="RIT's Overlooked Art Museum",
        accessPointHighlights=getRandomImages(8),
    )


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/catalog?q=<query>")
@app.route("/catalog")
def catalog():
    query = request.args.get("q")
    if query == None:
        return render_template(
            "catalog.html", q=query, accessPoints=getAccessPointsPaginated(0), tags=getAllTags()
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
Get next page of access points
"""


@app.route("/page?p=<page>")
@app.route("/page")
def paginated():
    page = int(request.args.get("p"))
    if page == None:
        # print("No page")
        return render_template("404.html"), 404
    else:
        return render_template(
            "paginated.html", page=(page + 1), accessPoints=getAccessPointsPaginated(page)
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
Page for specific year
"""


@app.route("/year/<year>")
def year(year):
    if checkYearExists(year):
        if year == "0":
            readableYear = "Unknown Date"
        else:
            readableYear = year
        return render_template(
            "filtered.html",
            pageTitle=f"AccessPoints from {readableYear}",
            subHeading=None,
            accessPoints=getAllAccessPointsFromYear(year),
        )
    else:
        return render_template("404.html"), 404


"""
Generic error handler
"""


@app.errorhandler(HTTPException)
def not_found(e):
    logger.error(e)
    return render_template("404.html"), 404


########################
#
#   Management
#
########################

########################
# Helpers
########################


def debug_only(f):
    @wraps(f)
    def wrapped(**kwargs):
        if app.config["DEBUG"]:
            return f(**kwargs)
        return abort(404)

    return wrapped


def make_thumbnail(access_point_id, file):

    with PilImage.open(file) as im:
        if im.width == 256 or im.height == 256:
            # Already a thumbnail
            # print("Already a thumbnail...")
            return False
        im = crop_center(im, min(im.size), min(im.size))
        im.thumbnail((256, 256))

        im = im.convert("RGB")
        im.save(file + ".thumbnail", "JPEG")

    with open(file + ".thumbnail", "rb") as tb:

        file_hash = hashlib.md5(tb.read()).hexdigest()
        tb.seek(0)

        # Upload thumnail version
        s3_bucket.upload_file(file_hash, tb, (file + ".thumbnail"))

        img = Image(imghash=file_hash, ordering=0)
        db.session.add(img)
        db.session.flush()

        img_id = img.id
        db.session.add(
            ImageAccessPointRelation(image_id=img_id, access_point_id=access_point_id)
        )
        db.session.commit()


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
    db.session.execute(
        db.delete(ImageAccessPointRelation).where(ImageAccessPointRelation.access_point_id == id)
    )
    db.session.execute(db.delete(AccessPointTag).where(AccessPointTag.access_point_id == id))
    db.session.execute(db.delete(Feedback).where(Feedback.access_point_id == id))

    m = db.session.execute(db.select(AccessPoint).where(AccessPoint.id == id)).scalar_one()

    db.session.query(AccessPoint).filter_by(nextid=id).update(
        {"nextid": m.nextid}
    )
    db.session.execute(db.delete(AccessPoint).where(AccessPoint.id == id))
    for image in images:
        s3_bucket.remove_file(image.imghash)
        db.session.execute(db.delete(Image).where(Image.id == image.id))

    db.session.commit()


"""
Upload fullsize and resized image, add relation to access point given ID
"""


def uploadImageResize(file, access_point_id, count, caption=None, alttext=None, attribution=None):
    file_obj = io.BytesIO(file.read())
    fullsizehash = hashlib.md5(file.read()).hexdigest()
    file.seek(0)

    # Upload full size img to S3
    s3_bucket.upload_file(fullsizehash, file)

    file_obj.seek(0)

    with PilImage.open(file_obj) as im:
        exif = im.getexif()
        width = (im.width * app.config["MAX_IMG_HEIGHT"]) // im.height

        (width, height) = (width, app.config["MAX_IMG_HEIGHT"])
        # print(width, height)
        im = im.resize((width, height))
        for k,v in exif.items():
            if EXIF_TAGS.get(k,k) == "ImageWidth":
                exif[k] = width
            elif EXIF_TAGS.get(k,k) == "ImageLength":
                exif[k] = height

        im = im.convert("RGB")
        im.save(fullsizehash + ".resized.jpg", "JPEG", exif=exif)

    with open((fullsizehash + ".resized.jpg"), "rb") as rs:

        file_hash = hashlib.md5(rs.read()).hexdigest()
        rs.seek(0)

        s3_bucket.upload_file(file_hash, rs, filename=fullsizehash + ".resized.jpg")

        # print(s3_bucket.get_file_s3(file_hash))

        img = Image(
            fullsizehash=fullsizehash,
            ordering=count,
            caption=caption,
            alttext=alttext,
            attribution=attribution,
            imghash=file_hash,
            datecreated=datetime.now(),
        )
        db.session.add(img)
        db.session.flush()
        img_id = img.id
        db.session.add(
            ImageAccessPointRelation(image_id=img_id, access_point_id=access_point_id)
        )
    db.session.commit()


########################
#   Pages
########################

"""
Route to edit access point page
"""


@app.route("/edit/<id>")
@debug_only
def edit(id):
    return render_template(
        "edit.html",
        accessPointDetails=getAccessPoint(id),
        accessPointFeedback=getAccessPointFeedback(id),
        tags=getAllTags(),
    )


"""
Route to the admin panel
"""


@app.route("/admin")
@debug_only
def admin():
    return render_template(
        "admin.html", tags=getAllTags(), accessPoints=getAllAccessPoints(), buildings=getAllBuildings()
    )


########################
#   Form submissions
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
    m = db.session.execute(db.select(AccessPoint).where(AccessPoint.id == id)).scalar_one()

    # Remove existing tag relationships
    db.session.execute(db.delete(AccessPointTag).where(AccessPointTag.access_point_id == m.id))

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
    if request.form["remarks"]  not in ("None", ""):
        m.remarks = request.form["remarks"]
    if request.form["location-nick"]  not in ("None", ""):
        m.location.nickname = request.form["location-nick"]
    if request.form["location"] not in ("None", ""):
        m.location = request.form["location"]
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
    m = db.session.execute(db.select(AccessPoint).where(AccessPoint.id == id)).scalar_one()
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

    # Delete references to current thumbnail
    curr_thumbnail = db.session.execute(
        db.select(Image)
        .join(ImageAccessPointRelation, ImageAccessPointRelation.image_id == Image.id)
        .where(ImageAccessPointRelation.access_point_id == access_point_id)
        .filter(Image.ordering == 0)
    ).scalar_one()

    db.session.execute(
        db.delete(ImageAccessPointRelation).where(
            ImageAccessPointRelation.image_id == curr_thumbnail.id
        )
    )
    db.session.execute(db.delete(Image).where(Image.id == curr_thumbnail.id))

    # Remove file from S3
    remove_file(s3_bucket, curr_thumbnail.imghash)

    # Download base photo, turn it into thumbnail
    image = db.session.execute(
        db.select(Image).where(Image.id == image_id)
    ).scalar_one()
    newfilename = f"/tmp/{image.id}.thumb"

    s3_bucket.get_file(image.imghash, newfilename)
    make_thumbnail(access_point_id, newfilename)

    return redirect(f"/edit/{access_point_id}")


"""
Route to delete image
"""


@app.route("/deleteimage/<id>", methods=["POST"])
@debug_only
def deleteImage(id):
    images = db.session.execute(db.select(Image).where(Image.id == id)).scalars()

    for image in images:
        s3_bucket.remove_file(image.imghash)
        db.session.execute(
            db.delete(ImageAccessPointRelation).where(ImageAccessPointRelation.image_id == id)
        )
        db.session.execute(db.delete(Image).where(Image.id == id))
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
    stmt = db.select(Building).where(Building.short_name == request.form["building"])
    building = db.session.execute(stmt).scalar_one_or_none()

    if not building:
        raise ValueError(f"Building with short name {request.form['building']} not found.")

    # Step 2: Find or create the location
    # for now we consider elevators as being "located" on "all" floors using the special floor number "0" (we are following the american standard where 1 is ground)
    floor, room = RoomNumber.from_string(request.form["room"]).integers()

    stmt = db.select(Location).where(
        Location.building_id == building.id,
        Location.floor_number == 0,
        Location.room_number == room,
        Location.is_outside is False # elevators should not be outside
    )
    location = db.session.execute(stmt).scalar_one_or_none()

    if not location:
        location = Location(
            building_id=building.id,
            floor_number=0,
            room_number=room,
            nickname=request.form["location-nick"],
            additional_info=request.form["location"]
        )
        db.session.add(location)
        db.session.flush()  # Get the location ID

    # Step 3: Insert the elevator access point
    elevator = Elevator(
        floor_min=floor_to_integer(request.form["min_floor"]),
        floor_max=floor_to_integer(request.form["max_floor"]),
        location_id=location.id,
        remarks=request.form["notes"],
        active=request.form["active"] == "true"
    )
    db.session.add(elevator)

    # Commit the transaction
    db.session.commit()

    # Count is the order in which the images are shown
    #   0 is the thumbnail (only shown on access point card)
    #   All other values denote the order shown in the image carousel
    count = 0
    for f in request.files.items(multi=True):
        filename = secure_filename(f[1].filename)
        # print(f[1].filename)

        fullsizehash = hashlib.md5(f[1].read()).hexdigest()
        f[1].seek(0)

        # Check if image is already used in DB
        count = db.session.execute(
            db.select(func.count()).where(Image.imghash == fullsizehash)
        ).scalar()
        if count > 0:
            # print(fullsizehash)
            return render_template("404.html"), 404

        # Begin creating thumbnail version
        if count == 0:
            with open(fullsizehash, "wb") as file:
                f[1].seek(0)
                f[1].save(file)

            with PilImage.open(fullsizehash) as im:
                if im.width == 256 or im.height == 256:
                    # Already a thumbnail
                    # print("Already a thumbnail...")
                    continue
                im = crop_center(im, min(im.size), min(im.size))
                im.thumbnail((256, 256))

                im = im.convert("RGB")
                im.save(fullsizehash + ".thumbnail", "JPEG")

            with open(fullsizehash + ".thumbnail", "rb") as tb:

                file_hash = hashlib.md5(tb.read()).hexdigest()
                tb.seek(0)

                # Upload thumnail version
                s3_bucket.upload_file(file_hash, tb, (fullsizehash + ".thumbnail"))
                img = Image(imghash=file_hash, ordering=0)
                db.session.add(img)
                db.session.flush()
                img_id = img.id
                db.session.add(
                    ImageAccessPointRelation(image_id=img_id, access_point_id=elevator.id)
                )

            db.session.commit()
            count += 1

        # Begin adding full size to database
        f[1].seek(0)

        uploadImageResize(f[1], access_point_id, count)

        count += 1

    db.session.commit()

    return redirect(f"/edit/{access_point_id}")


if __name__ == "__main__":
    # TODO: figure out how to accept this via CLI arg:
    # with app.app_context():
    #     db.create_all()
    #     stamp(directory="migrations")
    if not app.config["DEBUG"]:
        app.run(host="0.0.0.0", port=8080)
    else:
        app.run()
