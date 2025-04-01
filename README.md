# CampusPulse Access
An interactive catalog of accessibility devices on RIT's campus by maintenance status

This is a fork of [TunnelVision](https://github.com/wilsonmcdade/tunnelvision)



## Running Locally
(Reach out to a maintainer of this repo for credentials for the dev database)


* Fork the repo and run the following commands in that directory:
* `pip install pipenv --user` (if you dont already have it installed)
* `pipenv install`
<!-- * `cp sample.env .env` -->
* `podman compose up` (this starts up the database and minio for S3, docker should also work well too)
* `pipenv run python3 app.py` (this runs the app in development mode)

## Database Schema
This project uses SQLAlchemy to access a PostgresQL database. The DB schema is defined in `db.py`

This project also uses flask-migrate to allow for database schema revisions

to create a new revision:
`pipenv run flask db revision --autogenerate -m "[message]"`

to upgrade your schema:
`pipenv run flask db upgrade`

## Docker Infrastructure:
The docker compose config in this repository is intended to provide a small/simple suite of services for TunnelVision to rely on. This is for development and testing purposes.

To use this suite:

1. create a file called `compose.env` in the root of the repository. Use the following template to get started:

```
MINIO_ROOT_USER=
MINIO_ROOT_PASSWORD=
POSTGRES_USER=
POSTGRES_PASSWORD=
```
2. fill in appropriate values
3. `docker compose up`
4. navigate to http://localhost:9001, log in with the root credentials for minio specified above, add create a bucket for TunnelVision
5. while still in the minio console, navigate to "access keys" on the left and create an access key and secret for tunnelvision to use.
6. Provide the the information to TunnelVision
   - S3 url: `http://localhost:9000`
   - the s3 secret and key you generated
   - S3 bucket name: whatever you created
   - database host: `localhost`
   - DB user and password: whatever you set in `compose.env` for postgres
   - DB name: should match the db user by default
