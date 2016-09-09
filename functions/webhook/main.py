# -*- coding: utf-8 -*-

# Sample webhook client for receiving a payload from Gogs to process the job. This currently works with
# an English OBS repo

from __future__ import print_function

# Python libraries
import os
import tempfile
import boto3
import requests
import json

# Functions from Python libraries
from shutil import copyfile
from glob import glob
from datetime import datetime

# Functions from unfoldingWord libraries
from general_tools.file_utils import unzip, add_file_to_zip, make_dir, write_file
from general_tools.url_utils import download_file


def handle(event, context):
    data = event['data']

    commit_id = data['after']
    commit = None
    for commit in data['commits']:
        if commit['id'] == commit_id:
            break

    commit_url = commit['url']
    commit_message = commit['message']

    if 'https://git.door43.org/' not in commit_url and 'http://test.door43.org:3000/' not in commit_url:
        raise Exception('Currently only git.door43.org repositories are supported.')

    pre_convert_bucket = event['pre_convert_bucket']
    cdn_bucket = event['cdn_bucket']
    gogs_user_token = event['gogs_user_token']
    api_url = event['api_url']
    repo_name = data['repository']['name']
    repo_owner = data['repository']['owner']['username']
    compare_url = data['compare_url']

    if 'pusher' in data:
        pusher = data['pusher']
    else:
        pusher = {'username': commit['author']['username']}
    pusher_username = pusher['username']

    # The following sections of code will:
    # 1) download and unzip repo files
    # 2) massage the repo files by creating a new directory and file structure
    # 3) zip up the massages filed
    # 4) upload massaged files to S3 in zip file

    # 1) Download and unzip the repo files
    repo_zip_url = commit_url.replace('commit', 'archive') + '.zip'
    repo_zip_file = os.path.join(tempfile.gettempdir(), repo_zip_url.rpartition('/')[2])
    repo_dir = tempfile.mkdtemp(prefix='repo_')
    try:
        print('Downloading {0}...'.format(repo_zip_url), end=' ')
        if not os.path.isfile(repo_zip_file):
            download_file(repo_zip_url, repo_zip_file)
    finally:
        print('finished.')

    # Unzip the archive
    try:
        print('Unzipping {0}...'.format(repo_zip_file), end=' ')
        unzip(repo_zip_file, repo_dir)
    finally:
        print('finished.')

    # 2) Massage the content to just be a directory of MD files in alphabetical order as they should be compiled together in the converter
    content_dir = os.path.join(repo_dir, repo_name, 'content')
    md_files = glob(os.path.join(content_dir, '*.md'))
    massaged_files_dir = tempfile.mktemp(prefix='files_')
    make_dir(massaged_files_dir)
    print('Massaging content from {0} to {1}...'.format(content_dir, massaged_files_dir), end=' ')
    for md_file in md_files:
        copyfile(md_file, os.path.join(massaged_files_dir, os.path.basename(md_file)))
    # want front matter to be before 01.md and back matter to be after 50.md
    copyfile(os.path.join(content_dir, '_front', 'front-matter.md'), os.path.join(massaged_files_dir, '00_front-matter.md'))
    copyfile(os.path.join(content_dir, '_back', 'back-matter.md'), os.path.join(massaged_files_dir, '51_back-matter.md'))
    print('finished.')

    # 3) Zip up the massaged files
    zip_filename = context.aws_request_id+'.zip' # context.aws_request_id is a unique ID for this lambda call, so using it to not conflict with other requests
    zip_filepath = os.path.join(tempfile.gettempdir(), zip_filename)
    md_files = glob(os.path.join(massaged_files_dir, '*.md'))
    print('Zipping files from {0} to {1}...'.format(massaged_files_dir, zip_filepath), end=' ')
    for md_file in md_files:
        add_file_to_zip(zip_filepath, md_file, os.path.basename(md_file))
    print('finished.')

    # 4) Upload zipped file to the S3 bucket (you may want to do some try/catch and give an error if fails back to Gogs)
    print('Uploading {0} to {1}...'.format(zip_filepath, pre_convert_bucket), end=' ')
    s3_client = boto3.client('s3')
    s3_client.upload_file(zip_filepath, pre_convert_bucket, zip_filename)
    print('finished.')

    # Send job request to tx-manager
    source_url = 'https://s3-us-west-2.amazonaws.com/'+pre_convert_bucket+'/'+zip_filename # we use us-west-2 for our s3 buckets
    tx_manager_job_url = api_url+'/tx/job'
    identifier = "{0}/{1}/{2}".format(repo_owner, repo_name, commit_id[:10])  # The way to know which repo/commit goes to this job request
    payload = {
        "identifier": identifier,
        "user_token": gogs_user_token,
        "username": pusher_username,
        "resource_type": "obs",
        "input_format": "md",
        "output_format": "html",
        "source": source_url,
        "callback": api_url+'/sampleclient/callback'
    }
    headers = {"content-type": "application/json"}

    print('Making request to tx-Manager URL {0} with payload:'.format(tx_manager_job_url))
    print(payload)
    print('...', end=' ')
    response = requests.post(tx_manager_job_url, json=payload, headers=headers)
    print('finished.')

    # for testing
    print('tx-manager response:')
    print(response)
    json_data = json.loads(response.text)
    print("json:")
    print(json_data)

    build_log_json = {
        'job_id': json_data['job']['job_id'],
        'repo_name': repo_name,
        'repo_owner': repo_owner,
        'commit_id': commit_id,
        'committed_by': pusher_username,
        'commit_url': commit_url,
        'compare_url': compare_url,
        'commit_message': commit_message,
        'request_timestamp': datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        'eta_timestamp': json_data['job']['eta'],
        'success': None,
        'status': 'started',
        'message': 'Conversion in progress...'
    }

    if 'errorMessage' in json_data:
        build_log_json['status'] = 'failed'
        build_log_json['message'] = json_data['errorMessage']

    # Make a build_log.json file with this repo and commit data for later processing, upload to S3
    s3_project_key = 'u/{0}'.format(identifier)
    s3_resource = boto3.resource('s3')
    bucket = s3_resource.Bucket(cdn_bucket)
    for obj in bucket.objects.filter(Prefix=s3_project_key):
        s3_resource.Object(bucket.name, obj.key).delete()
    build_log_file = os.path.join(tempfile.gettempdir(), 'build_log_request.json')
    write_file(build_log_file, build_log_json)
    bucket.upload_file(build_log_file, s3_project_key+'/build_log.json', ExtraArgs={'ContentType': 'application/json'})
    print('Uploaded the following content from {0} to {1}/build_log.json'.format(build_log_file, s3_project_key))
    print(build_log_json)

    # If there was an error, in order to trigger a 400 error in the API Gateway, we need to raise an
    # exception with the returned 'errorMessage' because the API Gateway needs to see 'Bad Request:' in the string
    if 'errorMessage' in json_data:
        raise Exception(json_data['errorMessage'])

    return build_log_json
