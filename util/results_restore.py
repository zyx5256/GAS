import boto3,json, sys
from config import Config
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

# main function
if __name__ == '__main__':

	while True:
		try:
			sqs_client=boto3.client('sqs', region_name=Config.AWS_REGION_NAME)
		except ClientError as e:
			print(str(e))
			continue

		try:
			qURL_restore=sqs_client.get_queue_url(QueueName=Config.AWS_SQS_RESTORE)['QueueUrl']
		except ClientError as e:
			print(str(e))
			continue

		try:
			messages_restore=sqs_client.receive_message(QueueUrl=qURL_restore,WaitTimeSeconds=Config.AWS_SCANNING_TIME,MaxNumberOfMessages=1)
		except ClientError as e:
			print(str(e))
			continue

		# move results of FREE USERS to Glacier 
		if len(messages_restore)>1:

  			# connect to database
  			try:
  				dynamoDB=boto3.resource('dynamodb', region_name=Config.AWS_REGION_NAME)
  			except ClientError as e:
  				print(str(e))
  				continue

  			try:
  				ann_table=dynamoDB.Table(Config.AWS_DYNAMODB_ANNOTATIONS_TABLE)
  			except ClientError as e:
  				print(str(e))
  				continue
  			
  			# connect to glacier
  			try:
  				glacier = boto3.client('glacier', region_name=Config.AWS_REGION_NAME)
  			except ClientError as e:
  				print(str(e))
  				continue

  			for m in messages_restore['Messages']:

  				# get user id
  				info_restore=json.loads(json.loads(m['Body'])['Message'])
  				user_id=info_restore['user_id']

  				# get all jobs of this user
  				try:
  					all_jobs=ann_table.query(IndexName='user_id_index', KeyConditionExpression=Key('user_id').eq(user_id))['Items']
  				except ClientError as e:
  					print(str(e))
  					continue

  				fail=0
  				for job in all_jobs:
  					if 'results_file_archive_id' in job:
  						# initialize restoration
  						# https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glacier.html#Glacier.Client.initiate_job
  						try:
	  						response_restore = glacier.initiate_job(
	  							vaultName=Config.AWS_GLACIER_VAULT,
	  							accountId='-',
	  							jobParameters={
		  							'ArchiveId': job['results_file_archive_id'],
		  							'SNSTopic': Config.AWS_SNS_JOB_RESTORE_COMPLETE_TOPIC,
		  							'Type': 'archive-retrieval',
		  							'Description': json.dumps({'file_key': job['s3_key_result_file'], 'user_email': info_restore['user_email']}),
		  							'Tier': 'Expedited'}
	  							)
	  						print("Expedited: "+response_restore['jobId'])
	  					except ClientError as e:
	  						if e.response['Error']['Code'] == 'InsufficientCapacityException':
	  							try:
	  								response_restore = glacier.initiate_job(
			  							vaultName=Config.AWS_GLACIER_VAULT,
			  							accountId='-',
			  							jobParameters={
				  							'ArchiveId': job['results_file_archive_id'],
				  							'SNSTopic': Config.AWS_SNS_JOB_RESTORE_COMPLETE_TOPIC,
				  							'Type': 'archive-retrieval',
				  							'Description': json.dumps({'file_key': job['s3_key_result_file'], 'user_email': info_restore['user_email']}),
				  							'Tier': 'Standard'}
				  							)
	  								print("Standard: "+response_restore['jobId'])
	  							except ClientError as e2:
	  								print(str(e2))
	  								fail=fail+1
	  						else:
	  							print(str(e))
	  							fail=fail+1

	  			if fail==0:
	  				try:
	  					sqs_client.delete_message(QueueUrl=qURL_restore, ReceiptHandle=m['ReceiptHandle'])
	  					print('FREE Message deleted!')
	  				except ClientError as e:
	  					print(str(e))