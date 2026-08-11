#!/bin/bash

# Слушаем только loopback: наружу сервис отдаёт Nginx Proxy Manager.
uvicorn app.main:app --host 127.0.0.1 --port 8700