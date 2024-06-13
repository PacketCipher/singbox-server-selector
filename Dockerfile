# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 80 available to the world outside this container
# EXPOSE 80

# Define environment variables
ENV API_URL ""
ENV BEARER_TOKEN ""
ENV TEST_URL ""
ENV TIMEOUT 5000
ENV RETRIES 60
ENV RETRY_DELAY 10
ENV MIN_UPTIME 90
ENV CHECK_INTERVAL 60
ENV UPDATE_INTERVAL 14400
ENV LIGHTMODE_MAXIMUM_SERVERS 10
ENV PROXY_GROUP_NAME "select"

# Run app.py when the container launches
CMD ["python", "server-selector.py"]
