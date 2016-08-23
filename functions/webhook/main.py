# -*- coding: utf-8 -*-

# Method for  registering this module

from __future__ import print_function

import boto3
import json

def handle(event, context):
    url = event.data.payload.commits[0]['url']
    url = url.replace( "commit", "archive" ) + ".zip"

    payload = {
        "action": "job",
        "data": {
            "resource_type": "tn",
            "input_format": "html",
            "output_format": "pdf",
            "source": url,
            "callback": "https://amazon.com/html2pdf/callback",
            "options": {
                "page_size": "letter",
                "line_spacing": "120%"
            }
        }
    }

    return payload

    lambda_client = boto3.client('lambda')
    response = lambda_client.invoke(FunctionName='tx-manager_request', Payload=json.dumps(payload))
    payload = json.loads(response['Payload'].read())
    if 'errorMessage' in payload:
        raise Exception(payload)
    else:
        return {'success': True}


