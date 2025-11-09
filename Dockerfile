FROM python:3.10-slim

# git is needed for getting the repo commit
RUN apt-get update && apt-get install -y git libmagic1

COPY --from=ghcr.io/astral-sh/uv:0.4.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

ENV UV_PROJECT_ENVIRONMENT=/app/venv


# Set the working directory in the container
# pipenv doesnt want to be run as root
RUN useradd -ms /bin/bash campuspulse
USER campuspulse
WORKDIR /app

# needed because we changed users
RUN git config --global --add safe.directory /app

COPY pyproject.toml pyproject.toml
COPY uv.lock uv.lock
RUN uv sync --locked --no-install-project --no-dev --no-cache

# remove uv binary copied in earlier to hopefully save some space
USER root
RUN rm /bin/uv
USER campuspulse

# Copy the app's source code to the container
COPY . .

# Expose the port the Flask app runs on
EXPOSE 5000

ENV PATH="/app/venv/bin:$PATH"

# Run the Flask application
CMD gunicorn --workers 1 --bind 0.0.0.0:5000 app:app
