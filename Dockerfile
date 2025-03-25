FROM python:3.10-slim

# git is needed for getting the repo commit
RUN apt-get update && apt-get install -y git libmagic1
RUN pip install pipenv


# Set the working directory in the container
# pipenv doesnt want to be run as root
RUN useradd -ms /bin/bash campuspulse
USER campuspulse
WORKDIR /app

# needed because we changed users
RUN git config --global --add safe.directory /app

# ADD Pipfile.lock Pipfile .
COPY Pipfile.lock Pipfile.lock
COPY Pipfile Pipfile

# Copy requirements file and install dependencies
RUN pipenv install --system --deploy

# Copy the app's source code to the container
COPY . .

# Expose the port the Flask app runs on
EXPOSE 5000


# Run the Flask application
CMD python3 -m gunicorn --workers 1 --bind 0.0.0.0:5000 app:app
