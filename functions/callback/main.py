# -*- coding: utf-8 -*-

# Method for receiving a callback from tX Manager, can do something here such as email the user

# Python libraries
import os
import tempfile
import boto3
import json

# Functions from Python libraries
from mimetypes import MimeTypes
from datetime import datetime

# Functions from unfoldingWord libraries
from general_tools.file_utils import unzip, write_file
from general_tools.url_utils import download_file


def handle(event, context):
    # Getting the bucket to where we will unzip the converted files for door43.org. It is different from
    # production and testing, thus it is an environment variable the API Gateway gives us
    if 'cdn_bucket' not in event:
        raise Exception('"cdn_bucket" was not in payload')
    cdn_bucket = event['cdn_bucket']

    # Getting data from payload which is the JSON that was sent from tx-manager
    if 'data' not in event:
        raise Exception('"data" not in payload')
    data = event['data']

    print("data:")
    print(data)

    s3_project_key = 'u/{0}'.format(data['identifier'])  # The identifier is how to know which username/repo/commit this callback goes to

    s3_resource = boto3.resource('s3')
    bucket = s3_resource.Bucket(cdn_bucket)

    # Download the ZIP file of the converted files
    converted_zip_url = data['output']
    converted_zip_file = os.path.join(tempfile.gettempdir(), converted_zip_url.rpartition('/')[2])
    try:
        print('Downloading converted zip file from {0}...'.format(converted_zip_url))
        if not os.path.isfile(converted_zip_file):
            download_file(converted_zip_url, converted_zip_file)
    finally:
        print('finished.')

    # Unzip the archive
    unzip_dir = tempfile.mkdtemp(prefix='unzip_')
    try:
        print('Unzipping {0}...'.format(converted_zip_file))
        unzip(converted_zip_file, unzip_dir)
    finally:
        print('finished.')

    # Upload all files to the cdn_bucket with the key of <user>/<repo_name>/<commit> of the repo
    mime = MimeTypes()
    for root, dirs, files in os.walk(unzip_dir):
        for f in sorted(files):
            path = os.path.join(root, f)
            key = s3_project_key + path.replace(unzip_dir, '')
            mime_type = mime.guess_type(path)[0]
            if not mime_type:
                mime_type = "text/html"
            print('Uploading {0} to {1}, mime_type: {2}'.format(f, key, mime_type))
            bucket.upload_file(path, key, ExtraArgs={'ContentType': mime_type})

    # Now download the existing build_log.json file, update it and upload it back to S3
    s3_file = s3_resource.Object(cdn_bucket, s3_project_key+'/build_log.json')
    build_log_json = json.loads(s3_file.get()['Body'].read())

    build_log_json['start_timestamp'] = data['start_timestamp']
    build_log_json['end_timestamp'] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    build_log_json['success'] = data['success']
    build_log_json['status'] = data['status']
    build_log_json['message'] = data['message']

    if 'log' in data and data['log']:
        build_log_json['log'] = data['log']
    else:
        build_log_json['log'] = []

    if 'warnings' in data and data['warnings']:
        build_log_json['warnings'] = data['warnings']
    else:
        build_log_json['warnings'] = []

    if 'errors' in data and data['errors']:
        build_log_json['errors'] = data['errors']
    else:
        build_log_json['errors'] = []

    build_log_file = os.path.join(tempfile.gettempdir(), 'build_log_finished.json')
    write_file(build_log_file, build_log_json)
    bucket.upload_file(build_log_file, s3_project_key+'/build_log.json', ExtraArgs={'ContentType': 'application/json'})
    print('Uploaded the following content from {0} to {1}/build_log.json'.format(build_log_file, s3_project_key))
    print(build_log_json)

    # Todo: Raw converted files are now in the cdn bucket. Trigger door43.org page rendering here
