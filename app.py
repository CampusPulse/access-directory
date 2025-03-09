import os
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
    AccessPointImageRelation,
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

with app.app_context():
    db.create_all()
    stamp(directory="migrations")

########################
#
#   Helpers
#
########################

"""
Create a JSON object for a mural
"""


def mural_json(mural: AccessPoint):
    artists = []
    if mural.artistknown:
        artists = list(
            map(
                artist_json,
                db.session.execute(
                    db.select(Artist)
                    .join(
                        ArtistMuralRelation, Artist.id == ArtistMuralRelation.artist_id
                    )
                    .where(ArtistMuralRelation.access_point_id == mural.id)
                ).scalars(),
            )
        )

    prevmuralid = db.session.execute(
        db.select(AccessPoint.id).where(AccessPoint.nextmuralid == mural.id)
    ).scalar()

    image_data = db.session.execute(
        db.select(Image)
        .join(ImageAccessPointRelation, Image.id == ImageAccessPointRelation.image_id)
        .where(ImageAccessPointRelation.access_point_id == mural.id)
        .order_by(Image.ordering)
    ).scalars()
    images = []
    thumbnail = None
    for image in image_data:
        if image.ordering == 0:
            thumbnail = s3_bucket.get_file_s3(image.imghash)
        else:
            images.append(image_json(image))

    return {
        "id": mural.id,
        "title": mural.title,
        "year": mural.year,
        "location": mural.location,
        "remarks": mural.remarks,
        "notes": mural.notes,
        "prevmuralid": prevmuralid,
        "nextmuralid": mural.nextmuralid,
        "private_notes": mural.private_notes,
        "active": "checked" if mural.active else "unchecked",
        "thumbnail": thumbnail,
        "artists": artists,
        "images": images,
        "spotify": mural.spotify,
        "tags": getTags(mural.id),
    }


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
Create a JSON object for an artist
"""


def artist_json(artist: Artist):
    return {"id": artist.id, "name": artist.name, "notes": artist.notes}


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
Search all murals given query
"""


def searchAccessPoints(query):
    return list(
        map(
            mural_json,
            db.session.execute(
                db.select(AccessPoint)
                .where(text("murals.text_search_index @@ websearch_to_tsquery(:query)"))
                .order_by(AccessPoint.id)
                .limit(150),
                {"query": query},
            ).scalars(),
        )
    )


"""
Get murals in list, paginated
"""


def getAccessPointsPaginated(page_num):
    return list(
        map(
            mural_json,
            db.session.execute(
                db.select(AccessPoint)
                .where(AccessPoint.active == True)
                .order_by(AccessPoint.title.asc())
                .offset(page_num * app.config["ITEMSPERPAGE"])
                .limit(app.config["ITEMSPERPAGE"])
            ).scalars(),
        )
    )


"""
Get all murals
"""


def getAllAccessPoints():
    return list(
        map(
            mural_json,
            db.paginate(
                db.select(AccessPoint).order_by(AccessPoint.title.asc()),
                per_page=200,
            ).items,
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
Get all murals from year
"""


def getAllAccessPointsFromYear(year):
    return list(
        map(
            mural_json,
            db.paginate(
                db.select(AccessPoint).where(AccessPoint.year == year).order_by(AccessPoint.title.asc()),
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
Get all murals from artist given artist ID
"""


def getAllAccessPointsFromArtist(id):
    return list(
        map(
            mural_json,
            db.paginate(
                db.select(AccessPoint)
                .join(
                    ArtistMuralRelation, AccessPoint.id == ArtistMuralRelation.access_point_id
                )
                .where(ArtistMuralRelation.artist_id == id)
                .order_by(AccessPoint.id.asc()),
                per_page=150,
            ).items,
        )
    )


"""
Get artist details
"""


def getArtistDetails(id):
    return artist_json(
        db.session.execute(db.select(Artist).where(Artist.id == id)).scalar_one()
    )


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
        mural_select = db.select(
            AccessPoint.id,
            AccessPoint.title,
            AccessPoint.notes,
            AccessPoint.remarks,
            AccessPoint.year,
            AccessPoint.location,
            AccessPoint.spotify,
        ).order_by(AccessPoint.id.asc())
    else:
        mural_select = db.select(
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

    murals_df = pd.read_sql(mural_select, db.engine)

    murals_df["tags"] = murals_df.apply(lambda x: getTags(x["id"]), axis=1)
    murals_df["artists"] = murals_df.apply(lambda x: getArtists(x["id"]), axis=1)

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

    murals_df.to_csv(dir + "murals.csv")
    images_df.to_csv(dir + "images.csv")


"""
Exports images to <path>/images
"""


def export_images(path):
    murals = db.session.execute(db.select(AccessPoint).order_by(AccessPoint.id.asc())).scalars()

    for m in murals:
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
Get mural details
"""


def getAccessPoint(id):
    mural = db.session.execute(db.select(AccessPoint).where(AccessPoint.id == id)).scalar()

    if mural == None:
        logging.warning("DB Response was None")
        logging.warning(f"ID was '{id}'")
        return None

    muralInfo = mural_json(mural)
    logging.debug(muralInfo)
    return muralInfo


def checkYearExists(year):
    if not year.isdigit():
        return False

    integer_pattern = r"^[+-]?\d+$"

    # Use re.match to check if the variable matches the integer pattern
    if not re.match(integer_pattern, year):
        return False

    return True


def checkArtistExists(id):
    if not id.isdigit():
        return False

    return db.session.execute(db.select(Artist).where(Artist.id == id)).scalar() != None


def checkAccessPointExists(id):
    # Check id is not bad
    if not id.isdigit():
        return False

    return db.session.execute(db.select(AccessPoint).where(AccessPoint.id == id)).scalar() != None


"""
Get all murals with given tag
"""


def getAccessPointsTagged(tag):
    return list(
        map(
            mural_json,
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
Get all tags / Get all tags on certain mural
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
Get artist names for given mural
"""


def getArtists(access_point_id):
    return list(
        db.session.execute(
            db.select(Artist.name)
            .join(ArtistMuralRelation, Artist.id == ArtistMuralRelation.artist_id)
            .where(ArtistMuralRelation.access_point_id == access_point_id)
        ).scalars()
    )


"""
Get all artist IDs
"""


def getAllArtists():
    return list(map(artist_json, db.session.execute(db.select(Artist)).scalars()))


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
        muralHighlights=getRandomImages(8),
    )


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/open-canvas")
def openCanvas():
    # TODO: Use a random image of the Open Canvas instead of a random mural image
    return render_template("open-canvas.html", canvasHighlight=getRandomImages(1)[0])


@app.route("/catalog?q=<query>")
@app.route("/catalog")
def catalog():
    query = request.args.get("q")
    if query == None:
        return render_template(
            "catalog.html", q=query, murals=getAccessPointsPaginated(0), tags=getAllTags()
        )
    else:
        return render_template(
            "filtered.html",
            pageTitle=f"Query - {query}",
            subHeading="Search Query",
            q=query,
            murals=searchAccessPoints(query),
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
            murals=getAccessPointsTagged(tag),
        )


"""
Get next page of murals
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
            "paginated.html", page=(page + 1), murals=getAccessPointsPaginated(page)
        )


"""
Page for specific mural details
"""


@app.route("/murals/<id>")
def mural(id):
    if checkAccessPointExists(id):
        return render_template(
            "mural.html", muralDetails=getAccessPoint(id), spotify=getAccessPoint(id)["spotify"]
        )
    else:
        return render_template("404.html"), 404


"""
Page for specific artist
"""


@app.route("/artist/<id>")
def artist(id):
    if checkArtistExists(id):
        return render_template(
            "filtered.html",
            pageTitle=f"Artist: {getArtistDetails(id)['name']}",
            subHeading=getArtistDetails(id)["notes"],
            murals=getAllAccessPointsFromArtist(id),
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
            murals=getAllAccessPointsFromYear(year),
        )
    else:
        return render_template("404.html"), 404


"""
Generic error handler
"""


@app.errorhandler(HTTPException)
def not_found(e):
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
        upload_file(s3_bucket, file_hash, tb, (file + ".thumbnail"))

        img = Image(imghash=file_hash, ordering=0)
        db.session.add(img)
        db.session.flush()

        img_id = img.id
        db.session.add(
            ImageAccessPointRelation(image_id=img_id, access_point_id=access_point_id)
        )
        db.session.commit()


"""
Delete artist and all relations from DB
"""


def deleteArtistGivenID(id):
    db.session.execute(
        db.delete(ArtistMuralRelation).where(ArtistMuralRelation.artist_id == id)
    )
    db.session.execute(db.delete(Artist).where(Artist.id == id))
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
Delete mural entry, all relations, and all images from DB and S3
"""


def deleteAccessPointEntry(id):
    # Get all images relating to this mural from the DB
    images = db.paginate(
        db.select(Image)
        .join(ImageAccessPointRelation, Image.id == ImageAccessPointRelation.image_id)
        .where(ImageAccessPointRelation.access_point_id == id),
        per_page=150,
    ).items
    db.session.execute(
        db.delete(ImageAccessPointRelation).where(ImageAccessPointRelation.access_point_id == id)
    )
    db.session.execute(
        db.delete(ArtistAccessPointRelation).where(ArtistAccessPointRelation.access_point_id == id)
    )
    db.session.execute(db.delete(AccessPointTag).where(AccessPointTag.access_point_id == id))
    db.session.execute(db.delete(Feedback).where(Feedback.access_point_id == id))

    m = db.session.execute(db.select(AccessPoint).where(AccessPoint.id == id)).scalar_one()

    db.session.query(AccessPoint).filter_by(nextmuralid=id).update(
        {"nextmuralid": m.nextmuralid}
    )
    db.session.execute(db.delete(AccessPoint).where(AccessPoint.id == id))
    for image in images:
        s3_bucket.remove_file(image.imghash)
        db.session.execute(db.delete(Image).where(Image.id == image.id))

    db.session.commit()


"""
Upload fullsize and resized image, add relation to mural given ID
"""


def uploadImageResize(file, access_point_id, count):
    fullsizehash = hashlib.md5(file.read()).hexdigest()
    file.seek(0)

    # Upload full size img to S3
    s3_bucket.upload_file(fullsizehash, file)

    with PilImage.open(file) as im:
        width = (im.width * app.config["MAX_IMG_HEIGHT"]) // im.height

        (width, height) = (width, app.config["MAX_IMG_HEIGHT"])
        # print(width, height)
        im = im.resize((width, height))

        im = im.convert("RGB")
        im.save(fullsizehash + ".resized", "JPEG")

    with open((fullsizehash + ".resized"), "rb") as rs:

        file_hash = hashlib.md5(rs.read()).hexdigest()
        rs.seek(0)

        s3_bucket.upload_file(file_hash, rs, filename=fullsizehash + ".resized")

        # print(s3_bucket.get_file_s3(file_hash))

        img = Image(
            fullsizehash=fullsizehash,
            ordering=count,
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
Route to edit mural page
"""


@app.route("/edit/<id>")
@debug_only
def edit(id):
    return render_template(
        "edit.html",
        muralDetails=getAccessPoint(id),
        muralFeedback=getAccessPointFeedback(id),
        tags=getAllTags(),
        artists=getAllArtists(),
    )


"""
Route to the admin panel
"""


@app.route("/admin")
@debug_only
def admin():
    return render_template(
        "admin.html", tags=getAllTags(), murals=getAllAccessPoints(), artists=getAllArtists()
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
            access_point_id=request.form["muralid"],
        )
    )
    db.session.commit()

    return redirect("/catalog")


"""
Route to delete artist
"""


@app.route("/deleteArtist/<id>", methods=["POST"])
@debug_only
def deleteArtist(id):
    if checkArtistExists(id):
        deleteArtistGivenID(id)
        return redirect("/admin")
    else:
        return render_template("404.html"), 404


@app.route("/deleteTag/<name>", methods=["POST"])
@debug_only
def deleteTag(name):
    deleteTagGivenName(name)
    return redirect("/admin")


"""
Route to delete mural entry
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
Route to edit mural details
Sets all fields based on http form
"""


@app.route("/editmural/<id>", methods=["POST"])
@debug_only
def editAccessPoint(id):
    m = db.session.execute(db.select(AccessPoint).where(AccessPoint.id == id)).scalar_one()

    # Remove existing tag relationships
    db.session.execute(db.delete(AccessPointTag).where(AccessPointTag.access_point_id == m.id))

    # Relate mural and submitted tags
    if "tags" in request.form:
        if "No Tags" not in request.form.getlist("tags"):
            for tag in request.form.getlist("tags"):
                tag_id = db.session.execute(
                    db.select(Tag.id).where(Tag.name == tag)
                ).scalar()

                rel = AccessPointTag(tag_id=tag_id, access_point_id=m.id)
                db.session.add(rel)

    # Remove existing artist relationships
    # (If artists is not in the form submission, the multiselect was blank)
    db.session.execute(
        db.delete(ArtistMuralRelation).where(
            ArtistMuralRelation.access_point_id == m.id
        )
    )

    if "artists" in request.form:
        # Relate mural and submitted artists
        for artist_id in request.form.getlist("artists"):
            rel = ArtistMuralRelation(artist_id=int(artist_id), access_point_id=m.id)
            db.session.add(rel)

    m.active = True if "active" in request.form else False

    if request.form["notes"] != "None":
        m.notes = request.form["notes"]
    if request.form["remarks"] != "None":
        m.remarks = request.form["remarks"]
    if request.form["year"] != "None":
        m.year = int(request.form["year"])
    if request.form["location"] != "None":
        m.location = request.form["location"]
    if request.form["private_notes"] != "None":
        m.private_notes = request.form["private_notes"]
    if request.form["spotify"] != "None":
        m.spotify = request.form["spotify"]
    if request.form["nextmuralid"] != "None":
        m.nextmuralid = request.form["nextmuralid"]
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
Route to edit Artist notes
"""


@app.route("/editArtist/<id>", methods=["POST"])
@debug_only
def edit_artist(id):
    a = db.session.execute(db.select(Artist).where(Artist.id == id)).scalar_one()
    a.notes = request.form["notes"]
    db.session.commit()
    return ("", 204)


"""
Route to edit mural title
Sets mural title based on http form
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
Replaces mural thumbnail with selected image
Route:
    /makethumbnail?muralid=m_id&imageid=i_id
"""


@app.route("/makethumbnail", methods=["POST"])
@debug_only
def makeThumbnail():
    access_point_id = request.args.get("muralid", None)
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
Add artist with blank notes
"""


@app.route("/addArtist", methods=["POST"])
@debug_only
def add_artist():
    artist = Artist(name=request.form["name"], notes="")

    db.session.add(artist)
    db.session.commit()

    return redirect("/admin")


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
Route to add new mural entry
"""


@app.route("/upload", methods=["POST"])
@debug_only
def upload():
    artistKnown = True if "artistKnown" in request.form else False
    if not (request.form["year"].isdigit()):
        return render_template("404.html"), 404

    mural = AccessPoint(
        title=request.form["title"],
        artistknown=artistKnown,
        notes=request.form["notes"],
        year=request.form["year"],
        location=request.form["location"],
        active=False,
    )
    db.session.add(mural)
    db.session.flush()
    access_point_id = mural.id

    # Count is the order in which the images are shown
    #   0 is the thumbnail (only shown on mural card)
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
                    ImageAccessPointRelation(image_id=img_id, access_point_id=access_point_id)
                )

            db.session.commit()
            count += 1

        # Begin adding full size to database
        f[1].seek(0)

        uploadImageResize(f[1], access_point_id, count)

        count += 1

    if artistKnown:
        artists = request.form["artists"].split(",")
        for artist in artists:
            count = db.session.execute(
                db.select(func.count()).where(Artist.name == artist)
            ).scalar()
            artist_id = None
            if count > 0:
                artist_id = db.session.execute(
                    db.select(Artist.id).where(Artist.name == artist)
                ).scalar()
            else:
                artist_obj = Artist(name=artist)
                db.session.add(artist_obj)
                db.session.flush()
                artist_id = artist_obj.id

            rel = ArtistAccessPointRelation(
                artist_id=artist_id, access_point_id=access_point_id
            )
            db.session.add(rel)

    db.session.commit()

    return redirect(f"/edit/{access_point_id}")


if __name__ == "__main__":
    if not app.config["DEBUG"]:
        app.run(host="0.0.0.0", port=8080)
    else:
        app.run()
