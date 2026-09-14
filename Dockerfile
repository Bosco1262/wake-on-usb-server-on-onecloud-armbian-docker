FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py hid.py i18n.py ./
COPY templates ./templates
COPY static ./static
COPY locales ./locales

EXPOSE 8080

# One worker with threads: the HID device is a serial stream, so multiple
# processes would defeat the write lock in hid.py.
#
# 单 worker + 多线程：HID 设备是串行流，多进程会让 hid.py 里的写锁失效
CMD ["gunicorn", "-w", "1", "-k", "gthread", "--threads", "4", "--timeout", "30", "-b", "0.0.0.0:8080", "app:app"]
