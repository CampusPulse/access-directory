FROM python:3.10-slim

# git is needed for getting the repo commit
RUN apt-get update && apt-get install -y git
RUN pip install pipenv


# Set the working directory in the container
# pipenv doesnt want to be run as root
RUN useradd -ms /bin/bash campuspulse
USER campuspulse
WORKDIR /app

# ADD Pipfile.lock Pipfile .
COPY Pipfile.lock Pipfile.lock
COPY Pipfile Pipfile

# Copy requirements file and install dependencies
RUN pipenv install --system --deploy

# Copy the app's source code to the container
COPY . .

# Expose the port the Flask app runs on
EXPOSE 5000

ENV FLASK_APP=app.py

# Run the Flask application
CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]
