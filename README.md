# CampusPulse Access
An interactive catalog of accessibility devices on RIT's campus by maintenance status

This is a fork of [TunnelVision](https://github.com/wilsonmcdade/tunnelvision)



## Running Locally

1. Fork the repo, clone it, and run the following commands in the project root directory:

2. [Install `uv`](https://docs.astral.sh/uv/getting-started/installation/) (if you dont already have it installed)

3. `cp sample.env compose.env`

4. Create a garage.toml file by running this command in bash:
```bash
cat > garage.toml <<EOF
metadata_dir = "/tmp/meta"
data_dir = "/tmp/data"
db_engine = "sqlite"

replication_factor = 1

rpc_bind_addr = "[::]:3901"
rpc_public_addr = "127.0.0.1:3901"
rpc_secret = "$(openssl rand -hex 32)"

[s3_api]
s3_region = "garage"
api_bind_addr = "[::]:3900"
root_domain = ".s3.garage.localhost"

[s3_web]
bind_addr = "[::]:3902"
root_domain = ".web.garage.localhost"
index = "index.html"

[k2v_api]
api_bind_addr = "[::]:3904"

[admin]
api_bind_addr = "[::]:3903"
admin_token = "$(openssl rand -base64 32)"
metrics_token = "$(openssl rand -base64 32)"
EOF
```

5. Create the compose.env file in the root project directory:
```
GARAGE_ACCESS_KEY_ID=admin
GARAGE_SECRET_ACCESS_KEY=
POSTGRES_USER=campuspulse
POSTGRES_PASSWORD=
```

6. Create a random pass key and insert it in `compose.env` as the `GARAGE_SECRET_ACCESS_KEY`.

7. Create a test.sh file in the root project directory:
```bash
#!/usr/bin/env bash

export DBNAME=campuspulse
export DBUSER=campuspulse
export DBPWD=DBPWD
export DBHOST=localhost
export S3_URL=http://localhost:3900
export S3_KEY=S3_KEY
export S3_SECRET=S3_SECRET
export BUCKET_NAME=campuspulse
export JSON_LOGS=false

export CPACCESS_SECRET_KEY=CPACCESS_SECRET_KEY
export AUTH0_CLIENT_ID=AUTH0_CLIENT_ID
export AUTH0_CLIENT_SECRET=AUTH0_CLIENT_SECRET
export AUTH0_DOMAIN=mytenant.us.auth0.com
```

8. Create a random string and insert it in `test.sh` as the `CPACCESS_SECRET_KEY`.

9. Create a random pass key and insert it in `compose.env` as the `POSTGRES_PASSWORD` and `DBPWD` in test.sh.

10. `[podman or docker] compose up` (this starts up the database and garage for S3)

11. S3 Key Setup (in another shell)
  * Run `docker exec -it tunnelvision_garage /garage status`.
    * You should see proper status output without any errors.
  
  * Run `docker exec -it tunnelvision_garage /garage layout assign -z dc1 -c 1G <NODE_ID>`.
    * Replace <NODE_ID> with the ID in the previous step which is in the first column of output.
  
  * Run `docker exec -it tunnelvision_garage /garage layout apply --version 1`.
    * This applies the partition assignment.
  
  * Run `docker exec -it tunnelvision_garage /garage bucket create campuspulse-access`.
    * This creates the bucket.
  
  * Run `docker exec -it tunnelvision_garage /garage key create campuspulse-access-key`.
    * This creates the access key.
  
  * The Key ID and Secret Key should be listed in previous step output. Insert the `Key ID` as the `S3_KEY` and the `Secret key` as the `S3_SECRET` in the test.sh file.
  
  * Run `docker exec -it tunnelvision_garage /garage bucket allow  --read  --write  --owner  campuspulse-access  --key campuspulse-access-key`.
    *  This makes it so the bucket allows the key.
  
  * Run `source test.sh` to load the new environment variables.

12. `uv run python3 app.py` (this runs the app in development mode)

13. You should now have the development server running on localhost:8080 now!

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