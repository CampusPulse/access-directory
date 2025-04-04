import os

DBNAME = os.getenv("DBNAME", default="tunnelvision")
DBUSER = os.getenv("DBUSER", default="")
DBPWD =  os.getenv("DBPWD", default="")
DBHOST = os.getenv("DBHOST", default="postgres.csh.rit.edu")
DBPORT = os.getenv("DBPORT", default="5432")

JSON_LOGS = os.getenv("JSON_LOGS", default=True)

S3_URL = os.getenv("S3_URL", default="s3.csh.rit.edu")
S3_KEY = os.getenv("S3_KEY", default="")
S3_SECRET = os.getenv("S3_SECRET", default="")
BUCKET_NAME = os.getenv("BUCKET_NAME", default="tunnelvision")
ITEMSPERPAGE = 18

WEBHOOK_CREDENTIAL = os.getenv("WEBHOOK_CREDENTIAL", default="")

DEBUG = os.getenv("DEBUG", default=False)