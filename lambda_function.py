import json
import logging
import os
import traceback
from datetime import datetime
from typing import Literal

import boto3
from botocore.config import Config

TAG_KEY = os.environ.get('TAG_KEY', 'ScheduledStartStop')
TAG_VALUE = os.environ.get('TAG_VALUE', 'True')
DRY_RUN = os.environ.get('DRY_RUN', 'false').lower() == 'true'

logger = logging.getLogger()
logger.setLevel(logging.INFO)

BOTO_CONFIG = Config(retries={'max_attempts': 3, 'mode': 'adaptive'})

Action = Literal['start', 'stop']


def _get_tagged_instances(ec2_client, target_state: str) -> list[str]:
    paginator = ec2_client.get_paginator('describe_instances')
    instance_ids = []
    for page in paginator.paginate(
        Filters=[
            {'Name': 'instance-state-name', 'Values': [target_state]},
            {'Name': f'tag:{TAG_KEY}', 'Values': [TAG_VALUE]},
        ]
    ):
        for reservation in page['Reservations']:
            for instance in reservation['Instances']:
                instance_ids.append(instance['InstanceId'])
    return instance_ids


def manage_ec2_instances(action: Action, dry_run: bool = False) -> dict[str, list[str]]:
    target_state = 'stopped' if action == 'start' else 'running'
    start_time = datetime.now()
    results: dict[str, list[str]] = {}

    ec2_global = boto3.client('ec2', config=BOTO_CONFIG)
    regions = ec2_global.describe_regions(
        Filters=[{'Name': 'opt-in-status', 'Values': ['opt-in-not-required', 'opted-in']}]
    )['Regions']

    for region in regions:
        region_name = region['RegionName']
        try:
            ec2 = boto3.client('ec2', region_name=region_name, config=BOTO_CONFIG)
            instance_ids = _get_tagged_instances(ec2, target_state)

            if not instance_ids:
                continue

            logger.info(json.dumps({
                'region': region_name,
                'action': action,
                'dry_run': dry_run,
                'instances': instance_ids,
            }))

            if not dry_run:
                if action == 'start':
                    ec2.start_instances(InstanceIds=instance_ids)
                else:
                    ec2.stop_instances(InstanceIds=instance_ids, Force=False)

            results[region_name] = instance_ids

        except Exception:
            logger.error(json.dumps({
                'region': region_name,
                'action': action,
                'error': traceback.format_exc(),
            }))

    elapsed = round((datetime.now() - start_time).total_seconds(), 2)
    total = sum(len(ids) for ids in results.values())
    logger.info(json.dumps({'elapsed_seconds': elapsed, 'total_affected': total}))

    return results


def lambda_handler(event: dict, context) -> dict:
    action = str(event.get('action', '')).lower()
    if action not in ('start', 'stop'):
        raise ValueError(f"Invalid action: '{action}'. Expected 'start' or 'stop'.")

    dry_run = bool(event.get('dry_run', DRY_RUN))

    logger.info(json.dumps({'action': action, 'dry_run': dry_run}))

    affected = manage_ec2_instances(action, dry_run=dry_run)

    return {
        'statusCode': 200,
        'body': json.dumps({
            'action': action,
            'dry_run': dry_run,
            'affected': affected,
        }),
    }
