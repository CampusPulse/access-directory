# CampusPulse Access
An interactive catalog of accessibility devices on RIT's campus by maintenance status

This is a fork of [TunnelVision](https://github.com/wilsonmcdade/tunnelvision)



## Running Locally
(Reach out to a maintainer of this repo for credentials for the dev database)


* Fork the repo and run the following commands in that directory:
* [Install `uv`](https://docs.astral.sh/uv/getting-started/installation/) (if you dont already have it installed)
* `cp sample.env compose.env`
* `[podman or docker] compose up` (this starts up the database and minio for S3)
* `uv run python3 app.py` (this runs the app in development mode)

## Configuring Auth

1. Create an auth0 tenant
2. create an application (type: Regular Web Application)
3. ensure the domain, client ID, and client secret are in the environment variables (see `sample.env` for the names to store these in)
4. generate a random secret value and store it in the `CPACCESS_SECRET_KEY` variable
5. Set up your callback and logout urls in the application settings of auth0 (default endpoints are `<your domain>/callback` and `<your domain>/logout`)
6. on the "API's" tab enable the auth0 management API
7. drop down the management API and ensure at least `read:users` and `read:roles` are selected
8. Run the app
9. visit the `/login` page. When prompted, sign up with whatever method you choose



## Database Schema
This project uses SQLAlchemy to access a PostgresQL database. The DB schema is defined in `db.py`

This project also uses flask-migrate to allow for database schema revisions

to create a new revision:
`uv run flask db revision --autogenerate -m "[message]"`

to upgrade your schema:
`uv run flask db upgrade`

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



## Running in prod

The app will assume you are using a proxy or some other tool to ensure the application is accessible via HTTPS (https urls are provided as callback and logout urls to auth0)