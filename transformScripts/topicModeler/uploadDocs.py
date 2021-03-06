from __future__ import print_function # Python 2/3 compatibility

import boto3
from boto3.dynamodb.conditions import Key, Attr

import  tarfile
import json, csv

import pandas as pd
from pandas.io.json import json_normalize
from itertools import groupby
from collections import OrderedDict

from unflatten import unflatten

import decimal, time
from time import sleep
from datetime import datetime

from subprocess import check_output, call, run

# Set AWS DynamoDB parameters
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
dynamodb_client = boto3.client('dynamodb', region_name='us-east-1')
allScraped_table = dynamodb.Table('allScraped')

def timeout():
    raise Exception("Waiting table 'allScraped' timeout.")

def extractTopics():
    """
    Extract both file from Comprehend output file.
    output.tar.gz has to be in the same file.
    """

    # Get archive from S3
    output_file = "output.tar.gz"

    # Extract tar
    tar = tarfile.open(output_file)
    tar.extractall()
    tar.close()
    print("Topics extracted in current directory.")

def uploadDocuments():
    """
    Perform a merge between DynamoDB documents and topics form Comprehend.
    Then upload documents on Cloudsearch. Both add new documents and update.
    """

    # Parse CSV
    df = pd.read_csv('doc-topics.csv', dtype={
                "docname" : str,
                "topic" : str,
                "proportion" : float
            })

    df = (df[df.proportion > 0.1])

    # Format document and topics table for easyer merging.
    results = []
    for (docname), bag in df.groupby(["docname"]):
        contents_df = bag.drop(["docname", 'proportion'], axis=1)
        subset = [OrderedDict(row) for i, row in contents_df.iterrows()]
        results.append(OrderedDict([("id", docname),
                                    ("topics", subset)]))
    for result in results:
        topics = []
        for i in result['topics']:
            topics.append(i['topic'])

        result['fields'] = {}
        result['fields']['topics'] = topics
        del result['topics']
        #print(json.dumps(result, indent=4))

    # Create topic file.
    topics_file = open("topicFile.json", 'w', encoding="utf-8")
    topics_file.write(json.dumps(results))
    topics_file.close()
    print('Topics file created.')

    # Fetch all data to reindex
    result_items = []
    response = allScraped_table.scan(
        IndexName = "last_update-id-index",
    )
    result_items.extend(response['Items'])

    # Perform scan through all the table.
    while 'LastEvaluatedKey' in response:
        response = allScraped_table.scan(
            IndexName = "last_update-id-index",
            ExclusiveStartKey = response['LastEvaluatedKey']
        )
        result_items.extend(response['Items'])

    # Format DynamoDB articles.
    batch = []
    for i in result_items:
        # Build doc
        doc = {}

        doc['id'] = i['id']
        doc['type'] = 'add'
        doc['fields'] = {}

        doc['fields']['title'] = i['title']
        doc['fields']['authors'] = i['authors']
        doc['fields']['abstract'] = i['abstract']
        doc['fields']['release_date'] = i['release_date']
        doc['fields']['article_type'] = i['article_type']

        # Prevent optional data to add unwanted object.
        if i['file_url'] != None:
            doc['fields']['file_url'] = i['file_url']

        if i['keywords'] != None:
            doc['fields']['keywords'] = i['keywords']

        if i['fulltext'] != None:
            doc['fields']['fulltext'] = i['fulltext']

        doc['fields']['last_update'] = int(i['last_update'])

        batch.append(doc)

    # Create document file.
    docs_file = open("docFile.json", 'w', encoding="utf-8")
    docs_file.write(json.dumps(batch))
    docs_file.close()
    print('Documents file created.')


    print('Start merging both files.')

    # Open documents
    with open('docFile.json') as f:
        data = json.load(f)
    # Flatten data
    doc_df = json_normalize(data)
    #print("doc_df :\n" + doc_df.head(3).to_string())

    # Open topics
    with open('topicFile.json') as f:
        data = json.load(f)
    # Flatten topics
    topic_df = json_normalize(data)
    #print("topic_df :\n" + topic_df.head(3).to_string())

    # Add topics to data
    results = doc_df.merge(topic_df, how='inner', on='id')
    #print("results :\n" + results.head(3).to_string())

    print('Merging done. Start jsonify.')

    # Reforme json for CloudSearch API.
    docCount = 0
    itemsCount = 0

    result_items = results.to_dict('records')
    batch = []
    for r in result_items:
        item = unflatten(r)

        # Treat NaN cells
        if item['fields']['file_url'] != item['fields']['file_url']:
            del item['fields']['file_url']

        if item['fields']['keywords'] != item['fields']['keywords']:
            del item['fields']['keywords']

        if item['fields']['fulltext'] != item['fields']['fulltext']:
            del item['fields']['fulltext']

        """
        # Test empty keywords list
        if not item['fields']['keywords']:
            del item['fields']['keywords']
        """

        batch.append(item)
        itemsCount += 1

        # Separate upload file in smaller fragments to avoid OS socket exeption.
        if itemsCount > 4000 or r == result_items[len(result_items)-1]:
            # Create file
            updateCloudSearch_file = open("updateTopic_" + str(docCount) + ".json", 'w', encoding="utf-8")
            updateCloudSearch_file.write(json.dumps(batch))
            print("Update file n°" + str(docCount) + " complete with " + str(itemsCount) + " documents.")
            updateCloudSearch_file.close()

            docCount += 1
            itemsCount = 0
            batch = []

    # Start indexing.
    if len(result_items) > 0:
        print("Start indexing.")
        for doc in range(4):
            #print("Upload file n°" + str(doc) + " with " + str(itemsCount) + " documents.")
            # Call upload
            docEd = 'http://doc-micorr-test-yzjuar4kajhkoii2hgziiq5vxy.us-east-1.cloudsearch.amazonaws.com'
            updateFile = "updateTopic_" + str(doc) + ".json"
            run(["aws", "cloudsearchdomain", "--endpoint-url", docEd, "upload-documents", "--content-type", "application/json", "--documents", updateFile])
    else:
        print("Nothing to index.")

### ____ Execution order ____
print('Extract topic from output.tar.gz file.')
extractTopics()

print('Merge files for upload.')
uploadDocuments()
