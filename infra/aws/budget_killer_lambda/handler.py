"""
Budget Killer Lambda — Emergency cost control for ai-gateway.

Triggered via SNS when AWS Budget exceeds the threshold.
Finds all resources tagged with project=ai-gateway and shuts them down.
"""

import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

APP_NAME = os.environ.get("APP_NAME", "ai-gateway")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
REGION = os.environ.get("AWS_REGION_", "eu-west-1")


def lambda_handler(event: dict, context: object) -> dict:
    """SNS-triggered handler that kills all project resources."""
    logger.info("🚨 Budget killer triggered! Event: %s", json.dumps(event))

    prefix = f"{APP_NAME}-{ENVIRONMENT}"
    killed: list[str] = []

    killed.extend(_kill_ecs(prefix))
    killed.extend(_kill_rds(prefix))

    summary = {
        "status": "resources_killed",
        "app_name": APP_NAME,
        "environment": ENVIRONMENT,
        "killed_count": len(killed),
        "killed_resources": killed,
    }
    logger.info("💀 Kill summary: %s", json.dumps(summary))
    return summary


def _kill_ecs(prefix: str) -> list[str]:
    """Scale all ECS services to 0 desired count."""
    killed = []
    ecs = boto3.client("ecs", region_name=REGION)
    try:
        clusters = ecs.list_clusters()["clusterArns"]
        for cluster_arn in clusters:
            if prefix not in cluster_arn:
                continue
            services = ecs.list_services(cluster=cluster_arn)["serviceArns"]
            for service_arn in services:
                ecs.update_service(cluster=cluster_arn, service=service_arn, desiredCount=0)
                killed.append(f"ecs:scaled-to-0:{service_arn}")
                logger.info("Scaled ECS service to 0: %s", service_arn)
    except Exception:
        logger.exception("Error killing ECS services")
    return killed


def _kill_rds(prefix: str) -> list[str]:
    """Stop RDS instances matching project prefix."""
    killed = []
    rds = boto3.client("rds", region_name=REGION)
    try:
        instances = rds.describe_db_instances()["DBInstances"]
        for db in instances:
            if prefix in db["DBInstanceIdentifier"]:
                rds.stop_db_instance(DBInstanceIdentifier=db["DBInstanceIdentifier"])
                killed.append(f"rds:stopped:{db['DBInstanceIdentifier']}")
                logger.info("Stopped RDS: %s", db["DBInstanceIdentifier"])
    except Exception:
        logger.exception("Error killing RDS instances")
    return killed
