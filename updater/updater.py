from __future__ import print_function # Python 2/3 compatibility
import boto3
import json
import decimal
import time
from time import sleep
from datetime import datetime
from boto3.dynamodb.conditions import Key, Attr
from subprocess import check_output, call, run

# Helper class to convert a DynamoDB item to JSON.
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            if o % 1 > 0:
                return float(o)
            else:
                return int(o)
        return super(DecimalEncoder, self).default(o)

def timeout():
        raise Exception("TableStatus timeout")

# Set AWS DynamoDB parameters
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
dynamodb_client = boto3.client('dynamodb', region_name='us-east-1')
allScraped_table = dynamodb.Table('allScraped')
updateDoc_table = dynamodb.Table('updateDoc')

# Get the current time for the upcomming update.
now = int(time.mktime(datetime.now().timetuple()))
# Fetch last update time. Use for query.
lastUpdate_file = open("lastUpdate.txt", 'r', encoding="utf-8")
lastUpdate = int(lastUpdate_file.read())
lastUpdate_file.close()

# Wait until table is active.
call = 0
while True:
    response = dynamodb_client.describe_table(TableName='updateDoc')
    if response['Table']['TableStatus'] == 'ACTIVE':
        print("Table status 'updateDoc' : ACTIVE")
        break
    else:
        print("Table status 'updateDoc' : " + response['Table']['TableStatus'] + "\n Waiting...")
        call += 1
        sleep(5) # Time in seconds.
        # Call timeout.
        if call > 6:
            timeout()

print("Update new documents from 'allScraped' into 'updateDoc'.")
# Fetch new documents.
response = allScraped_table.scan(
    IndexName = "last_update-id-index",
    FilterExpression = Key('last_update').between(lastUpdate, now),
    )
"""
print("Documents to update : " + str(len(response['Items'])))
for i in response['Items']:
    result = updateDoc_table.put_item(
        Item = i,
        ConditionExpression='attribute_not_exists(id) AND attribute_not_exists(title)'
    )
    sleep(0.2)
"""

# Update lastUpdate.txt
lastUpdate_file = open("lastUpdate.txt", 'w', encoding="utf-8")
lastUpdate_file.write(str(now))
print("Update time set to : " + str(now))
lastUpdate_file.close()


# Update CloudSearch
print("Create JSON file.")
# JOSNify
batch = []
for i in response['Items']:
    # Build doc
    doc = {}

    doc['id'] = i['id']
    doc['type'] = 'add'
    doc['fields'] = {}

    doc['fields']['title'] = i['title']
    doc['fields']['authors'] = i['authors']
    doc['fields']['abstract'] = i['abstract']
    #doc['fields']['fulltext'] = i['fulltext']
    doc['fields']['release_date'] = i['release_date']
    doc['fields']['article_type'] = i['article_type']
    doc['fields']['file_url'] = i['file_url']
    doc['fields']['keywords'] = i['keywords']
    #doc['fields']['topics'] = i['topics']
    doc['fields']['last_update'] = int(i['last_update'])

    batch.append(doc)

# Create file
updateCloudSearch_file = open("updateCloudSearch.json", 'w', encoding="utf-8")
updateCloudSearch_file.write(json.dumps(batch))
print("Update file complete.")
updateCloudSearch_file.close()

# Call upload
docEd = 'https://endpoint.cloudsearch.amazonaws.com'
updateFile = 'updateCloudSearch.json'
run(["aws", "cloudsearchdomain", "--endpoint-url", docEd, "upload-documents", "--content-type", "application/json", "--documents", updateFile])

# Empty updateDoc
