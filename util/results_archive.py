import boto3,json, sys, time
from config import Config
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

#update item in dynamoDB
def update_item(jobid, archiveID):

	try:
		dynamoDB=boto3.resource('dynamodb', region_name=Config.AWS_REGION_NAME)
	except ClientError as e:
		print(" error: 500, fail to connect to dynamoDB: "+str(e))
		return 0

	try:
		ann_table=dynamoDB.Table(Config.AWS_DYNAMODB_ANNOTATIONS_TABLE)
	except ClientError as e:
		print("error: 404, Table not found: "+str(e))
		return 0

	try:
		response=ann_table.query(KeyConditionExpression=Key('job_id').eq(jobid))
	except ClientError as e:
		print("error: 500, "+str(e))
		return 0

	status=0
	if len(response['Items'])>0:
		status=response['Items'][0]['job_status']

	# https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb.html#DynamoDB.Client.update_item
	try:
		ann_table.update_item(
		    Key={'job_id': jobid},
		    UpdateExpression="SET results_file_archive_id = :ad",
		    ExpressionAttributeValues={':ad' : archiveID},
		  ConditionExpression='attribute_not_exists(results_file_archive_id)'
		)
	except ClientError as e:
		print("error: 500, fail to update job status in the target table: "+str(e))
		return 0
	return 1

def archive_results(file_key, job_id):

	succeed=0 # indicator

	# connect to s3 and glacier client 
	try:
		s3_resource=boto3.resource('s3', region_name=Config.AWS_REGION_NAME)
	except ClientError as e:
		print("error: 500, "+str(e))
		return succeed

	try:
		glacier_client=boto3.client('glacier', region_name=Config.AWS_REGION_NAME)
	except ClientError as e:
		print("error: 500, "+str(e))
		return succeed

	# read result file from s3
	try:
		bucket=s3_resource.Bucket(Config.AWS_S3_RESULTS_BUCKET)
	except ClientError as e:
		print("error: 500, "+str(e))
		return succeed

	try:
		obj = s3_resource.Object(Config.AWS_S3_RESULTS_BUCKET, file_key)
	except ClientError as e:
		print("error: 500, "+str(e))
		return succeed

	result_file=obj.get()['Body'].read()

	# upload file to glacier
	# https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glacier.html#Glacier.Client.upload_archive
	try:
		response = glacier_client.upload_archive(
			vaultName=Config.AWS_GLACIER_VAULT,
			archiveDescription='upload results of FREE USERS',
			body=result_file
			)
		succeed=succeed+1
		print("upload archives succeed")
	except ClientError as e:
		print("fail to upload file to glacier")
		return succeed

	# update DynamoDB
	suc=update_item(job_id, response['archiveId'])
	print("DB updated!")
	succeed=succeed+suc

	if succeed==2:
		try:
			del_response=obj.delete()
			print("Object in results bucket deleted!")
			succeed=succeed+1
		except ClientError as e:
			print("fail to delete result file in S3 RESULTS BUCKET")
			return succeed
	return succeed

# main function
if __name__ == '__main__':

	while True:

		try:
			client=boto3.client('sqs', region_name=Config.AWS_REGION_NAME)
		except ClientError as e:
			print("error: 500, "+str(e))
			continue

		try:
			qURL_free=client.get_queue_url(QueueName=Config.AWS_SQS_ARCHIVE_COMPLETE)['QueueUrl']
		except ClientError as e:
			print("error: 500, "+str(e))
			continue

		try:
			response_free=client.receive_message(QueueUrl=qURL_free,WaitTimeSeconds=Config.AWS_SCANNING_TIME,MaxNumberOfMessages=1)
		except ClientError as e:
			print("error: 500, "+str(e))
			continue

		# check the user role and time after completion
		try:
			dynamoDB=boto3.resource('dynamodb', region_name=Config.AWS_REGION_NAME)
		except ClientError as e:
			print(" error: 500, fail to connect to dynamoDB: "+str(e))
			continue

		try:
			ann_table=dynamoDB.Table(Config.AWS_DYNAMODB_ANNOTATIONS_TABLE)
		except ClientError as e:
			print("error: 404, Table not found: "+str(e))
			continue
		
		# move results of FREE USERS to Glacier 
		if len(response_free)>1:

  			for m in response_free['Messages']:
  				info_free=json.loads(json.loads(m['Body'])['Message'])

  				try:
  					response_table=ann_table.query(KeyConditionExpression=Key('job_id').eq(info_free['job_id']))
  				except ClientError as e:
  					print("error: 500, "+str(e))
  					continue

  				if response_table['Items'][0]['user_role']=='premium_user':

  					try:
  						client.delete_message(QueueUrl=qURL_free, ReceiptHandle=m['ReceiptHandle'])
  						print('Archive Message deleted!')
  					except ClientError as e:
  						print("error: 500, "+str(e))
  						continue


  				# double check if more than 10min has passed
  				if int(time.time())-response_table['Items'][0]['complete_time']<Config.FREE_USER_DATA_RETENTION:
  					continue

  				try:
  					succeed=archive_results(info_free['s3_key_result_file'], info_free['job_id'])
  				except:
  					print('information missing!')
  					try:
  						client.delete_message(QueueUrl=qURL_free, ReceiptHandle=m['ReceiptHandle'])
  						print('Bad Message deleted')
  					except ClientError as e:
  						print("error: 500, "+str(e))

  				# if read and update both succeed, delete result file in s3 results bucket
  				if succeed==3:
  					try:
  						client.delete_message(QueueUrl=qURL_free, ReceiptHandle=m['ReceiptHandle'])
  						print('Archive Message deleted!')
  					except ClientError as e:
  						print("error: 500, "+str(e))