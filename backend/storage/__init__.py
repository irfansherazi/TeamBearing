"""
vQA Storage — S3 Artifact Persistence Package
===============================================

This package handles all uploads to and reads from AWS S3.

Modules
-------
s3.py
    Upload utilities for screenshots, session videos (``.webm``),
    and HTML audit reports.  All objects are stored under the
    configured S3 prefix (``settings.s3_prefix``).

    Key functions:
    - ``upload_screenshot()`` — PNG screenshot → S3
    - ``upload_video()``      — .webm session recording → S3
    - ``upload_report()``     — HTML audit report → S3
    - ``get_presigned_url()`` — generate temporary download URLs
"""
