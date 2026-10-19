# Throwaway image for the updater's end-to-end test. Built locally, never pushed.
FROM python:3.11-slim
ARG APP_VERSION=dev
ARG DB_REV=rev0
ARG MIN_DB_REV=
ARG BROKEN=0
ARG DESTRUCTIVE=0
ENV APP_VERSION=${APP_VERSION} DB_REV=${DB_REV} BROKEN=${BROKEN} DESTRUCTIVE=${DESTRUCTIVE} PYTHONUNBUFFERED=1
LABEL org.pinpoint311.app.version=${APP_VERSION} \
      org.pinpoint311.app.db_revision=${DB_REV} \
      org.pinpoint311.app.min_db_revision=${MIN_DB_REV}
COPY fakeapp.py /app/fakeapp.py
ENTRYPOINT ["python", "/app/fakeapp.py"]
CMD ["backend"]
