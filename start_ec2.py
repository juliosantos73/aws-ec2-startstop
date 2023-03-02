import boto3
import sys, traceback
from datetime import datetime
from time import sleep

def is_running(instance):
    is_running = False
    if instance['State']['Name'] == 'running':
        is_running = True
    return is_running

def start_ec2_instances():
    start_time = datetime.now()


def lambda_handler(event, context):
    print("Checking instances...")
    start_ec2_instances()

lambda_handler()