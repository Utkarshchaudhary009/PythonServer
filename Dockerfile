FROM python:3.13

# Install FFmpeg (if needed, e.g., for multimedia tasks)
RUN apt-get update && apt-get install -y ffmpeg

RUN pip install uv

# Set working directory
WORKDIR /app

# Copy project files
COPY . /app/

# Set up virtual environment with UV
RUN uv sync

# Make entrypoint executable
RUN chmod +x /app/run.sh

# Expose port (optional, as Railway overrides it)
EXPOSE 8000

# Set entrypoint
ENTRYPOINT ["/app/run.sh"]