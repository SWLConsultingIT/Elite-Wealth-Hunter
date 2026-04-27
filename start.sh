#!/bin/bash
pip install -r requirements.txt
gunicorn instagram_scraper:app --bind 0.0.0.0:$PORT --workers 1 --timeout 300
