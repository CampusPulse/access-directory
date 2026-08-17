# CampusPulse Access
An interactive catalog of accessibility devices on RIT's campus by maintenance status

This is a fork of [TunnelVision](https://github.com/wilsonmcdade/tunnelvision)



## Running Locally
(Reach out to a maintainer of this repo for credentials for the dev database)


* Fork the repo and run the following commands in that directory:
* [Install `uv`](https://docs.astral.sh/uv/getting-started/installation/) (if you dont already have it installed)
* run the docker infrastructure (see the [Docker Infrastructure](#docker-infrastructure) section) to run the data storage layers
* if you choose to, [Configure Auth](#configuring-auth). We are working on making this not required
* run `source compose.env` to ensure your application variables are available to the app
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

## Configuring AI Features

This app optionally makes use of an OpenAI API key to provide admins with suggested first-pass alt-text for uploaded images.

To make this work:
1. register for an API key from OpenAI (requires funding the account with at least $5).
2. generate an API key. The minimal permissions you need if you choose a restricted key are
   - list models: Read
   - model capabilities: Request (this will set everything under this section. [Making anything under here more granular breaks things](https://community.openai.com/t/missing-scopes-model-request-on-restricted-api-key/1371602/2))
   - Files: read
3. Provide the API key in the environment variables as `OPENAI_API_KEY`
4. the "generate alt text" button on the edit page should now appear (note this replaces anything that was there before. Its recommended to only use it when theres no existing alt text)

This feature is designed to be very economical, In development, it took 9-10 queries to cost one cent in API credits.

## Database Schema
This project uses SQLAlchemy to access a PostgresQL database. The DB schema is defined in `db.py`

This project also uses flask-migrate to allow for database schema revisions

to create a new revision:
`uv run flask db revision --autogenerate -m "[message]"`

to upgrade your schema:
`uv run flask db upgrade`

## Docker Infrastructure:
The docker compose config in this repository is intended to provide a small/simple suite of services for CampusPulse Access to rely on. This is for development and testing purposes.

To use this suite:

1. create a file called `compose.env` in the root of the repository. To get started you can make a copy of `sample.env`
2. fill in appropriate values for the first section:
   1. create random passwords for `MINIO_ROOT_PASSWORD` (admin ui login) and `POSTGRES_PASSWORD`. We recommend using the [BitWarden Password Generator](https://bitwarden.com/password-generator/)
   2. decide on the name you want to use for your database user (and potentially also the s3 bucket, they dont have to be the same). Something like `campuspulseaccess` works. 
3. `docker compose up`
4. navigate to http://localhost:9001, log in with the root credentials for silo that you specified above.
5. create a bucket for CampusPulse Access named according to what you selected earlier
6. while still in the silo console, navigate to "users" on the left and create a user for the application to use. select `tablesReadWrite` for permissions
7. edit the user you just created and under "Service accounts" create an access key and secret for CampusPulse Access to use.
8. Provide the the information to CampusPulse Access by filling in the middle section of the config
   - S3 url: `http://localhost:9000`
   - the s3 secret and key you generated
   - S3 bucket name: whatever you created
   - database host: `localhost`
   - DB user and password: whatever you set in `compose.env` for postgres
   - DB name: should match the db user by default
9. Leave the `docker compose up` running. This provides the database and S3 for the app to connect to


## Running in prod

The app will assume you are using a proxy or some other tool to ensure the application is accessible via HTTPS (https urls are provided as callback and logout urls to auth0)

In prod, the app runs from docker, so the S3 URL should be  `http://silo:9000` instead of the `localhost` address above.
database host for prod will likely be `db` (the name of that docker service)